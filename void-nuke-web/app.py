"""
VOID-NUKE WEB - Render Optimized
Free Tier: 512 MB RAM, 0.1 CPU, 750h/mo

Architecture:
- Flask (lightweight) + gunicorn 1 worker, 2-4 threads
- discord.py bot runs in separate thread with its own asyncio loop
- Semaphore(3) for all Discord API calls
- No message cache, minimal intents, GC after batches
- Health check for Render
"""

import os
import threading
import asyncio
import gc
import time
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import discord
from discord.ext import commands
from dotenv import load_dotenv

from bot_manager import manager, log_buffer, log_ok, log_err, log_info, log_warn

load_dotenv()

app = Flask(__name__)
CORS(app)
app.config['MAX_CONTENT_LENGTH'] = 1 * 1024 * 1024  # 1MB max

# --- Bot Thread ---
bot_loop = None
bot_thread_obj = None

def create_bot():
    # Optimized intents: only what we need
    intents = discord.Intents.none()
    intents.guilds = True
    intents.members = True
    intents.bans = True
    intents.emojis = True
    intents.voice_states = True
    intents.messages = True
    intents.message_content = True

    bot = commands.Bot(
        command_prefix='!',
        intents=intents,
        max_messages=None,  # disable cache to save RAM
        chunk_guilds_at_startup=False,
        member_cache_flags=discord.MemberCacheFlags.all(),
    )
    return bot

def run_bot(token, guild_id):
    global bot_loop
    bot_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(bot_loop)

    bot = create_bot()
    manager.bot = bot
    manager.guild_id = guild_id
    manager.loop = bot_loop

    @bot.event
    async def on_ready():
        manager.connected = True
        g = bot.get_guild(int(guild_id)) if guild_id else None
        if g:
            # Try chunk for member list but don't block
            try:
                await bot_loop.create_task(g.chunk())
            except:
                pass
            manager.guild_info = {
                "name": g.name,
                "id": str(g.id),
                "members": g.member_count,
                "channels": len(g.channels),
                "roles": len(g.roles),
                "icon": str(g.icon.url) if g.icon else None,
            }
            log_ok(f"Connected to {g.name} ({g.member_count} members)")
        else:
            log_warn(f"Bot ready as {bot.user} but guild {guild_id} not found")
            # list guilds
            guilds = [f"{x.name} ({x.id})" for x in bot.guilds]
            log_info(f"Available guilds: {', '.join(guilds[:10])}")

    @bot.event
    async def on_disconnect():
        manager.connected = False
        log_warn("Bot disconnected")

    try:
        bot_loop.run_until_complete(bot.start(token))
    except discord.LoginFailure:
        log_err("Invalid token")
        manager.connected = False
    except Exception as e:
        log_err(f"Bot error: {e}")
        manager.connected = False
    finally:
        try:
            bot_loop.run_until_complete(bot.close())
        except:
            pass
        bot_loop.close()
        gc.collect()

# --- Routes ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/health')
def health():
    return jsonify({"status": "ok", "bot_connected": manager.connected}), 200

@app.route('/api/status')
def status():
    return jsonify({
        "connected": manager.connected,
        "guild": manager.guild_info,
        "guild_id": manager.guild_id,
        "bot_user": str(manager.bot.user) if manager.bot and manager.bot.user else None,
        "logs_count": len(log_buffer.logs)
    })

@app.route('/api/logs')
def get_logs():
    # Return last N logs
    limit = min(int(request.args.get('limit', 100)), 500)
    logs = log_buffer.get_all()[-limit:]
    return jsonify(logs)

@app.route('/api/logs/clear', methods=['POST'])
def clear_logs():
    log_buffer.clear()
    return jsonify({"ok": True})

@app.route('/api/connect', methods=['POST'])
def connect():
    global bot_thread_obj, bot_loop
    data = request.get_json() or {}
    token = data.get('token', '').strip()
    guild_id = data.get('guild_id', '').strip()

    if not token or not guild_id:
        return jsonify({"error": "Token and Server ID required"}), 400

    # Stop existing bot if running
    if manager.bot and manager.connected:
        try:
            if bot_loop:
                asyncio.run_coroutine_threadsafe(manager.bot.close(), bot_loop)
        except:
            pass
        time.sleep(1)

    # Validate guild_id numeric
    if not guild_id.isdigit():
        return jsonify({"error": "Server ID must be numeric"}), 400

    log_info(f"Connecting to guild {guild_id}...")
    manager.guild_id = guild_id

    # Start bot in thread
    bot_thread_obj = threading.Thread(target=run_bot, args=(token, guild_id), daemon=True)
    bot_thread_obj.start()

    # Wait a bit for connection
    for _ in range(20):
        time.sleep(0.5)
        if manager.connected:
            break

    return jsonify({
        "ok": True,
        "connected": manager.connected,
        "message": "Bot starting, check logs"
    })

@app.route('/api/disconnect', methods=['POST'])
def disconnect():
    global bot_loop
    if manager.bot and bot_loop:
        try:
            future = asyncio.run_coroutine_threadsafe(manager.bot.close(), bot_loop)
            future.result(timeout=5)
            log_info("Bot disconnected by user")
        except Exception as e:
            log_err(f"Disconnect error: {e}")
    manager.connected = False
    manager.guild_info = {}
    gc.collect()
    return jsonify({"ok": True})

@app.route('/api/guilds')
def guilds():
    if not manager.bot or not manager.connected:
        return jsonify({"error": "Bot not connected"}), 400
    try:
        guild_list = [{"name": g.name, "id": str(g.id), "members": g.member_count} for g in manager.bot.guilds]
        return jsonify(guild_list)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/channels')
def channels():
    g = manager.get_guild()
    if not g:
        return jsonify({"error": "Guild not found or bot not connected"}), 400
    chans = [{"name": c.name, "id": str(c.id), "type": str(c.type)} for c in g.channels]
    vcs = [{"name": c.name, "id": str(c.id)} for c in g.channels if isinstance(c, discord.VoiceChannel)]
    return jsonify({"all": chans, "voice": vcs, "text": [c for c in chans if "text" in c["type"].lower()]})

@app.route('/api/action', methods=['POST'])
def do_action():
    if not manager.connected or not manager.bot:
        return jsonify({"error": "Bot not connected"}), 400
    data = request.get_json() or {}
    action = data.get("action")
    params = data.get("params", {})

    if not action:
        return jsonify({"error": "No action"}), 400

    # Map UI ids to bot_manager actions
    action_map = {
        # original 01-39 mapping to new names
        "01": "nuke", "nuke": "nuke",
        "02": "auto_raid",
        "03": "ban_all",
        "04": "kick_all",
        "05": "mute_all",
        "06": "unban_all",
        "07": "del_channels",
        "08": "del_emojis",
        "09": "del_stickers",
        "10": "create_channels",
        "11": "create_roles",
        "12": "create_cats",
        "13": "rename_channels",
        "14": "rename_roles",
        "15": "edit_server",
        "16": "rename_members",
        "17": "deafen_all", # fix nicks mapped? keep original categories below
        "18": "get_admin",
        "19": "dm_spam_user", # impersonate replaced
        "20": "deafen_all", # ghost ping -> using deafen for safety? we'll map to log
        "21": "strip_roles",
        "22": "dm_all",
        "23": "dm_spam_user",
        "24": "webhook_spam",
        "25": "server_info",
        "26": "clone_server",
        "27": "server_info", # webhook logs
        "28": "lockdown",
        "29": "deafen_all",
        "30": "disconnect_all",
        "31": "mass_move",
        "32": "invite_spam",
        "33": "spam",
        "34": "thread_spam",
        "35": "server_info", # reaction spam light
        "36": "deafen_all", # voice spam -> minimal
        "37": "spoiler_spam",
        "38": "server_info", # poll spam not critical
        "39": "event_spam",
        # direct names
        "auto_raid": "auto_raid",
        "ban_all": "ban_all",
        "kick_all": "kick_all",
        "mute_all": "mute_all",
        "unban_all": "unban_all",
        "del_channels": "del_channels",
        "del_emojis": "del_emojis",
        "del_stickers": "del_stickers",
        "create_channels": "create_channels",
        "create_roles": "create_roles",
        "create_cats": "create_cats",
        "rename_channels": "rename_channels",
        "rename_roles": "rename_roles",
        "edit_server": "edit_server",
        "rename_members": "rename_members",
        "strip_roles": "strip_roles",
        "spam": "spam",
        "webhook_spam": "webhook_spam",
        "dm_all": "dm_all",
        "dm_spam_user": "dm_spam_user",
        "server_info": "server_info",
        "lockdown": "lockdown",
        "mass_move": "mass_move",
        "deafen_all": "deafen_all",
        "disconnect_all": "disconnect_all",
        "thread_spam": "thread_spam",
        "invite_spam": "invite_spam",
        "get_admin": "get_admin",
        "spoiler_spam": "spoiler_spam",
        "event_spam": "event_spam",
        "clone_server": "clone_server",
    }

    mapped = action_map.get(action, action)
    func = manager.ACTIONS.get(mapped)

    if not func:
        return jsonify({"error": f"Unknown action {action}"}), 400

    # For safety, require confirmation for destructive
    destructive = {"nuke", "ban_all", "kick_all", "del_channels", "auto_raid"}
    if mapped in destructive and not params.get("confirm"):
        return jsonify({"error": "This action requires confirmation", "need_confirm": True}), 400

    # Run in bot loop
    try:
        if manager.loop and manager.bot:
            # create task
            coro = func(manager, params)
            future = asyncio.run_coroutine_threadsafe(coro, manager.loop)
            # Don't wait, return immediately for UI responsiveness (free tier CPU)
            log_info(f"Started action: {mapped} with {params}")
            return jsonify({"ok": True, "action": mapped, "message": "Task started, check logs"})
        else:
            return jsonify({"error": "Bot loop not ready"}), 500
    except Exception as e:
        log_err(f"Action {mapped} failed: {e}")
        return jsonify({"error": str(e)}), 500

# Gunicorn entrypoint
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))  # Render default 10000
    # Optimized for low RAM: threaded, not multiple workers
    app.run(host='0.0.0.0', port=port, threaded=True, debug=False)
