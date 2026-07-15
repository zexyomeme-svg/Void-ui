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
    """
    Robust test send v6 - with detailed diagnostics for raid-by-void case
    Where perms true but send fails with empty error
    """
    if not manager.connected or not manager.bot:
        return jsonify({"ok":False,"error":"Bot not connected","perms":{}}),400
    data=request.get_json(silent=True) or {}
    channel_id=data.get("channel_id","").strip()
    content=data.get("content","VOID-NUKE ✅ Test message - Bot can send messages! 🚀").strip()
    use_everyone=data.get("everyone", False)
    
    g=manager.get_guild()
    if not g: return jsonify({"ok":False,"error":"Guild not found"}),400
    
    # Find channel - try fresh fetch
    chan=None
    if channel_id:
        try:
            # Try cache first
            chan=g.get_channel(int(channel_id))
            if not chan:
                # Try API fetch (blocking but ok for test)
                log_info(f"Channel {channel_id} not in cache, trying fetch...")
        except Exception as fetch_err:
            log_warn(f"Channel fetch err {fetch_err}")

        if not chan:
            try:
                chan=g.get_channel(int(channel_id))
            except: pass

        if not chan:
            return jsonify({"ok":False,"error":f"Channel {channel_id} not found in cache - try /api/channels to list IDs","perms":{}}),400
        # Allow threads too? But require TextChannel for simple test
        if not isinstance(chan, (discord.TextChannel, discord.Thread, discord.ForumChannel)):
            # Check if VoiceChannel with text? In new Discord, voice has text chat
            if not hasattr(chan, 'send'):
                return jsonify({"ok":False,"error":f"Channel {channel_id} type {type(chan)} does not support send() - is it category?","channel":getattr(chan,'name','?'),"channel_id":channel_id,"perms":{}}),400
    else:
        # Auto-find first writable text channel
        for c in g.channels:
            if isinstance(c, discord.TextChannel):
                try:
                    if g.me and c.permissions_for(g.me).send_messages and c.permissions_for(g.me).view_channel:
                        chan=c
                        break
                except: continue
        if not chan:
            for c in g.channels:
                if isinstance(c, discord.TextChannel):
                    chan=c
                    break
    
    if not chan:
        return jsonify({"ok":False,"error":"No text channels found in guild"}),400
    
    # Detailed perms + channel diagnostics
    perm_info={}
    chan_info={}
    try:
        chan_info={
            "name": getattr(chan,'name','?'),
            "id": str(getattr(chan,'id','?')),
            "type": str(type(chan)),
            "is_text": isinstance(chan, discord.TextChannel),
            "is_thread": isinstance(chan, discord.Thread),
            "is_voice": isinstance(chan, discord.VoiceChannel),
            "guild_id": str(getattr(chan.guild,'id','?')) if hasattr(chan,'guild') else '?',
        }
        if g.me:
            perms=chan.permissions_for(g.me)
            perm_info={
                "view_channel": perms.view_channel,
                "send_messages": perms.send_messages,
                "embed_links": perms.embed_links,
                "mention_everyone": perms.mention_everyone,
                "attach_files": perms.attach_files,
                "read_message_history": getattr(perms, 'read_message_history', False),
                "manage_messages": getattr(perms, 'manage_messages', False),
            }
            # Additional checks
            perm_info["is_archived"] = getattr(chan, 'archived', False) if hasattr(chan, 'archived') else False
            perm_info["is_locked"] = getattr(chan, 'locked', False) if hasattr(chan, 'locked') else False
    except Exception as e:
        perm_info={"error":f"perm check exception: {e}", "traceback": __import__('traceback').format_exc()[:500]}

    # Build test content
    test_content = content
    if use_everyone and "@everyone" not in test_content:
        test_content = f"@everyone {test_content}"

    # Try send via bot_loop with detailed version
    async def _do_send_detailed():
        from bot_manager import safe_send_detailed
        ok, details = await safe_send_detailed(chan, test_content, retry=4)
        return ok, details

    try:
        future=asyncio.run_coroutine_threadsafe(_do_send_detailed(), manager.loop)
        success, details = future.result(timeout=15)
        if success:
            log_ok(f"TEST SEND OK in #{chan_info.get('name','?')} ID {chan_info.get('id')}")
            return jsonify({
                "ok":True,
                "channel":chan_info.get('name'),
                "channel_id":chan_info.get('id'),
                "chan_info":chan_info,
                "perms":perm_info,
                "details":details,
                "message":"✅ Test message sent! Check Discord channel - if you don't see it, check channel muted or hidden"
            })
        else:
            # Return detailed error - this fixes user's empty error issue
            err_msg = details.get("error") or "Unknown error - all retries failed"
            attempts = details.get("attempts", [])
            # Build user-friendly fix suggestion
            fix = []
            if not perm_info.get("view_channel"): fix.append("Need VIEW_CHANNEL")
            if not perm_info.get("send_messages"): fix.append("Need SEND_MESSAGES")
            if not perm_info.get("embed_links"): fix.append("Embed links missing but not critical")
            if use_everyone and not perm_info.get("mention_everyone"): fix.append("Disable @everyone checkbox - need MENTION_EVERYONE")
            if chan_info.get("is_archived"): fix.append("Channel is ARCHIVED - unarchive in Discord")
            if chan_info.get("is_locked"): fix.append("Thread is LOCKED - unlock")
            if not is_text and not chan_info.get("is_thread"):
                fix.append(f"Channel type {chan_info.get('type')} may not support text - try a TextChannel")

            # If perms all true but still fails, suggest common Discord issues
            if perm_info.get("view_channel") and perm_info.get("send_messages"):
                fix.append("Perms true but still fails? Check: 1) Channel not deleted? 2) Bot not timed out? 3) Slowmode? 4) Automod blocked? 5) Try without @everyone and shorter content")
                fix.append("Also try: Server Settings → Safety → Disable Automod for test, or try different channel")

            log_err(f"TEST SEND FAILED #{chan_info.get('name')} err={err_msg[:200]} attempts={len(attempts)}")
            return jsonify({
                "ok":False,
                "channel":chan_info.get('name'),
                "channel_id":chan_info.get('id'),
                "chan_info":chan_info,
                "perms":perm_info,
                "error": err_msg,
                "details": details,
                "attempts": attempts,
                "fix_suggestions": fix,
                "debug": f"If error empty, Discord returned empty Forbidden - usually means channel is archived thread, or bot is missing SEND_MESSAGES in thread parent, or content blocked by automod. Try simple content 'hello' in different channel."
            }),400

    except Exception as e:
        import traceback
        tb=traceback.format_exc()
        log_err(f"TEST SEND exception #{chan_info.get('name','?')}: {e} {tb[:800]}")
        return jsonify({
            "ok":False,
            "channel":chan_info.get('name','?'),
            "channel_id":chan_info.get('id','?'),
            "chan_info":chan_info,
            "perms":perm_info,
            "error": f"{type(e).__name__}: {str(e) or repr(e)}",
            "traceback": tb[:1200],
            "fix_suggestions": ["Check bot is still in guild", "Re-invite with Administrator", "Try different channel ID from /api/channels"]
        }),500

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
