"""
VOID-NUKE WEB v4 - Multi-threaded + Permissions + audioop fix
Free Tier: 512MB RAM / 0.1 CPU

Multi-threading:
- Flask gthread: 1 worker, 4 threads
- Bot thread: dedicated asyncio loop
- Command thread pool: 4 workers for concurrent commands
- API thread pool: 2 workers for blocking tasks
"""
import sys
try:
    import audioop
except ModuleNotFoundError:
    try:
        import audioop_lts as audioop
        sys.modules['audioop']=audioop
        print("[FIX] audioop-lts shim", flush=True)
    except ImportError:
        import types
        sys.modules['audioop']=types.ModuleType("audioop")

import os, threading, asyncio, gc, time
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import discord
from discord.ext import commands
from dotenv import load_dotenv

from bot_manager import manager, log_buffer, log_ok, log_err, log_info, log_warn, webhook_logger_check, REQUIRED_PERMISSIONS, REQUIRED_INTENTS, command_executor, blocking_executor

load_dotenv()
app = Flask(__name__)
CORS(app, resources={r"/api/*":{"origins":"*"}})
app.config['MAX_CONTENT_LENGTH']=1*1024*1024

# Multi-threading executors for Flask
flask_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="flask-api")

bot_loop=None
bot_thread_obj=None

def create_bot():
    intents=discord.Intents.none()
    intents.guilds=True; intents.members=True; intents.bans=True
    intents.emojis=True; intents.voice_states=True; intents.messages=True; intents.message_content=True
    bot=commands.Bot(command_prefix='!', intents=intents, max_messages=None, chunk_guilds_at_startup=False, member_cache_flags=discord.MemberCacheFlags.all())
    return bot

def run_bot(token, guild_id):
    global bot_loop
    bot_loop=asyncio.new_event_loop()
    asyncio.set_event_loop(bot_loop)
    bot=create_bot()
    manager.bot=bot; manager.guild_id=guild_id; manager.loop=bot_loop

    @bot.event
    async def on_ready():
        manager.connected=True
        g=bot.get_guild(int(guild_id)) if guild_id else None
        if g:
            try: await g.chunk()
            except: pass
            manager.guild_info={"name":g.name,"id":str(g.id),"members":g.member_count,"channels":len(g.channels),"roles":len(g.roles),"icon":str(g.icon.url) if g.icon else None}
            log_ok(f"[THREAD {threading.current_thread().name}] Connected to {g.name} ({g.member_count} members)")
            try:
                from bot_manager import BOT_PRESENCE
                from discord import Activity, ActivityType
                pt=getattr(ActivityType, BOT_PRESENCE["type"].lower(), ActivityType.playing)
                await bot.change_presence(activity=Activity(type=pt, name=BOT_PRESENCE["text"]))
            except: pass
        else:
            log_warn(f"Bot ready as {bot.user} but guild {guild_id} not found")
            log_info(f"Available guilds: {[f'{x.name} ({x.id})' for x in bot.guilds[:10]]}")

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

    try: bot_loop.run_until_complete(bot.start(token))
    except discord.LoginFailure: log_err("Invalid token"); manager.connected=False
    except Exception as e: log_err(f"Bot error: {e}"); manager.connected=False
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
    import threading
    return jsonify({
        "status":"ok",
        "bot_connected":manager.connected,
        "python":sys.version.split()[0],
        "audioop": "audioop" in sys.modules,
        "threads": threading.active_count(),
        "active_tasks": len(manager.active_tasks),
        "executor_workers": len(command_executor._threads) if hasattr(command_executor, '_threads') else 0,
    }),200

@app.route('/api/status')
def status_api():
    return jsonify({
        "connected":manager.connected,
        "guild":manager.guild_info,
        "guild_id":manager.guild_id,
        "bot_user":str(manager.bot.user) if manager.bot and manager.bot.user else None,
        "logs_count":len(log_buffer.logs),
        "python":sys.version.split()[0],
        "active_tasks": manager.active_tasks,
        "thread_count": threading.active_count(),
    })

@app.route('/api/permissions')
def permissions_api():
    check=manager.check_permissions()
    if "error" in check and not check.get("has_guild"):
        return jsonify(check),400
    guide={
        "steps":[
            "1. Go to https://discord.com/developers/applications → your bot → Bot tab",
            "2. Enable Privileged Gateway Intents: SERVER MEMBERS INTENT = ON, MESSAGE CONTENT INTENT = ON",
            "3. Save, then OAuth2 → URL Generator → Scopes: bot + applications.commands, Permissions: Administrator (8)",
            "4. Invite: https://discord.com/oauth2/authorize?client_id=YOUR_CLIENT_ID&permissions=8&scope=bot%20applications.commands",
            "5. In Server Settings → Roles, drag bot role ABOVE roles it manages",
        ],
        "required_intents_details":REQUIRED_INTENTS,
        "required_perms_details":REQUIRED_PERMISSIONS,
    }
    if check.get("has_guild"):
        g=manager.get_guild()
        if g:
            guide["diagnostics"]={
                "bot_top_role":check.get("top_role"),
                "bot_top_role_pos":check.get("top_role_pos"),
                "guild_roles_count":len(g.roles),
                "is_owner":str(g.owner_id)==check.get("bot_id"),
                "active_threads": threading.active_count(),
                "active_tasks": list(manager.active_tasks.keys()),
            }
    return jsonify({"permissions_check":check,"guide":guide})

# Multi-threaded logs endpoint - offload to executor for heavy logs
@app.route('/api/logs')
def get_logs():
    def _get():
        limit=min(int(request.args.get('limit',100)),500)
        return log_buffer.get_all()[-limit:]
    # Run in thread pool to not block Flask
    future=flask_executor.submit(_get)
    logs=future.result(timeout=2)
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
    log_info(f"[THREAD {threading.current_thread().name}] Connecting to guild {guild_id}...")
    manager.guild_id=guild_id
    bot_thread_obj=threading.Thread(target=run_bot, args=(token,guild_id), daemon=True, name="void-bot-main")
    bot_thread_obj.start()
    for _ in range(25):
        time.sleep(0.5)
        if manager.connected: break
    return jsonify({"ok":True,"connected":manager.connected,"message":"Bot starting","thread":threading.current_thread().name})

@app.route('/api/disconnect', methods=['POST'])
def disconnect():
    global bot_loop
    if manager.bot and bot_loop:
        try:
            future=asyncio.run_coroutine_threadsafe(manager.bot.close(), bot_loop)
            future.result(timeout=5)
            log_info("Bot disconnected by user")
        except Exception as e: log_err(f"Disconnect error: {e}")
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
    def _fetch():
        all_ch=[]
        vcs=[]
        tcs=[]
        for c in g.channels:
            # Check per-channel perms for bot
            can_send=False
            send_reason=""
            try:
                if g.me:
                    perms=c.permissions_for(g.me)
                    can_send=perms.send_messages and perms.view_channel
                    # Detail
                    if not perms.view_channel: send_reason="no view_channel"
                    elif not perms.send_messages: send_reason="no send_messages"
                    else: send_reason="ok"
            except: 
                can_send=False
                send_reason="perm check err"
            info={"name":c.name,"id":str(c.id),"type":str(c.type),"can_send":can_send,"send_reason":send_reason}
            all_ch.append(info)
            if isinstance(c,discord.VoiceChannel): vcs.append(info)
            if isinstance(c,discord.TextChannel): tcs.append(info)
        return {"all":all_ch,"voice":vcs,"text":tcs}
    future=flask_executor.submit(_fetch)
    return jsonify(future.result(timeout=3))

@app.route('/api/test_send', methods=['POST'])
def test_send():
    """Robust test send - guarantees message attempt with detailed diagnostics"""
    if not manager.connected or not manager.bot:
        return jsonify({"error":"Bot not connected"}),400
    data=request.get_json(silent=True) or {}
    channel_id=data.get("channel_id","").strip()
    content=data.get("content","VOID-NUKE ✅ Test message - Bot can send messages! 🚀").strip()
    use_everyone=data.get("everyone", False)
    
    g=manager.get_guild()
    if not g: return jsonify({"error":"Guild not found"}),400
    
    # Find channel
    chan=None
    if channel_id:
        try:
            chan=g.get_channel(int(channel_id))
        except: pass
        if not chan or not isinstance(chan, discord.TextChannel):
            return jsonify({"error":f"Channel {channel_id} not found or not text"}),400
    else:
        # First text channel where bot can send
        for c in g.channels:
            if isinstance(c, discord.TextChannel):
                try:
                    if g.me and c.permissions_for(g.me).send_messages:
                        chan=c
                        break
                except: continue
        if not chan:
            # Fallback first text
            for c in g.channels:
                if isinstance(c, discord.TextChannel):
                    chan=c
                    break
    
    if not chan:
        return jsonify({"error":"No text channels found"}),400
    
    # Check perms
    perm_info={}
    try:
        if g.me:
            perms=chan.permissions_for(g.me)
            perm_info={
                "view_channel": perms.view_channel,
                "send_messages": perms.send_messages,
                "embed_links": perms.embed_links,
                "mention_everyone": perms.mention_everyone,
                "attach_files": perms.attach_files,
            }
    except Exception as e:
        perm_info={"error":str(e)}
    
    # Try send via bot_loop
    async def _do_send():
        from bot_manager import safe_send, PUB
        test_content = content
        if use_everyone and "@everyone" not in test_content:
            test_content = f"@everyone {test_content}"
        # Try safe_send which has retries and stripping logic
        ok = await safe_send(chan, test_content, retry=3)
        return ok
    
    try:
        future=asyncio.run_coroutine_threadsafe(_do_send(), manager.loop)
        success=future.result(timeout=10)
        if success:
            log_ok(f"TEST SEND OK in #{chan.name}")
            return jsonify({"ok":True,"channel":chan.name,"channel_id":str(chan.id),"perms":perm_info,"message":"Test message sent! Check Discord"})
        else:
            log_err(f"TEST SEND FAILED in #{chan.name}")
            return jsonify({"ok":False,"channel":chan.name,"channel_id":str(chan.id),"perms":perm_info,"error":"Failed to send - check perms: send_messages, view_channel, mention_everyone if using @everyone"}),400
    except Exception as e:
        import traceback
        tb=traceback.format_exc()
        log_err(f"TEST SEND exception #{chan.name}: {e}")
        return jsonify({"ok":False,"channel":chan.name,"channel_id":str(chan.id),"perms":perm_info,"error":str(e),"traceback":tb[:800]}),500

@app.route('/api/action', methods=['POST'])
def do_action():
    """Multi-threaded action execution - fixed confirm handling"""
    if not manager.connected or not manager.bot:
        return jsonify({"error":"Bot not connected - connect first","need_connect":True}),400
    data=request.get_json(silent=True) or {}
    action=data.get("action")
    params=data.get("params", {}) or {}
    print(f"[API ACTION THREAD {threading.current_thread().name}] {action} {params}", flush=True)
    log_info(f"API /action {action} {params}")

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
        err=f"Unknown action '{action}' -> '{mapped}'"
        log_err(err)
        return jsonify({"error":err}),400

    confirm_raw=params.get("confirm",False)
    is_confirmed=False
    if isinstance(confirm_raw,bool): is_confirmed=confirm_raw
    elif isinstance(confirm_raw,str): is_confirmed=confirm_raw.lower() in ("true","1","yes","on")
    elif isinstance(confirm_raw,(int,float)): is_confirmed=bool(confirm_raw)

    destructive={"nuke","ban_all","kick_all","delete_channels","auto_raid"}
    if mapped in destructive and not is_confirmed:
        return jsonify({"error":f"Action '{mapped}' requires confirmation checkbox","need_confirm":True}),400

    cleaned_params={}
    for k,v in params.items():
        if v=="" or v is None: continue
        cleaned_params[k]=v
    cleaned_params["confirm"]=is_confirmed

    try:
        if manager.loop and manager.bot:
            # Multi-threaded execution: submit to command_executor, then run coroutine thread-safe
            def _run_in_thread():
                try:
                    coro=func(manager, cleaned_params)
                    future=asyncio.run_coroutine_threadsafe(coro, manager.loop)
                    # Don't block Flask thread, just start
                    log_info(f"[THREAD {threading.current_thread().name}] Started action: {mapped} {cleaned_params}")
                    # Try quick check for immediate error
                    try:
                        future.result(timeout=0.3)
                    except asyncio.TimeoutError:
                        pass
                    return True
                except Exception as e:
                    log_err(f"Thread run err {mapped}: {e}")
                    return False

            # Submit to thread pool (true multi-threading)
            command_executor.submit(_run_in_thread)

            return jsonify({"ok":True,"action":mapped,"message":f"Task {mapped} started in thread {threading.current_thread().name} - check logs","threaded":True})
        else:
            return jsonify({"error":"Bot loop not ready"}),500
    except Exception as e:
        import traceback
        tb=traceback.format_exc()
        print(tb, flush=True)
        log_err(f"Action {mapped} failed: {e}")
        return jsonify({"error":str(e),"traceback":tb[:1000]}),500

@app.route('/api/threads')
def threads_api():
    return jsonify({
        "active_threads": threading.active_count(),
        "threads": [t.name for t in threading.enumerate()],
        "active_tasks": manager.active_tasks,
        "command_executor_threads": len(command_executor._threads) if hasattr(command_executor, '_threads') else 0,
        "flask_executor_threads": len(flask_executor._threads) if hasattr(flask_executor, '_threads') else 0,
    })

if __name__=='__main__':
    port=int(os.environ.get('PORT',10000))
    app.run(host='0.0.0.0', port=port, threaded=True, debug=False)
