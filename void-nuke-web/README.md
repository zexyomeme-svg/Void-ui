# VOID-NUKE WEB v5 — Multi-threaded + Send Messages Fixed

Web UI + CLI conversion of [v0id4real/Void-Nuke](https://github.com/v0id4real/Void-Nuke) — **All 39 original commands**, Render Free Tier optimized (512MB / 0.1 CPU), **multi-threaded**, **send guaranteed**.

> ⚠️ Educational use only — Use only on servers you own.

### v5 Fix: It won't send messages → FIXED

**Root causes fixed:**
- `@everyone` mention without `MENTION_EVERYONE` perm → `Forbidden`
- Embed image URL expired → HTTP 400
- No retry on rate-limit 429
- No per-channel perm check
- No fallback when send fails

**New `safe_send()` in bot_manager.py:**
```python
async def safe_send(channel, content, retry=3):
  attempts = [
    full content with @everyone,
    stripped @everyone (everyone),
    short 500 chars,
    simple "VOID-NUKE ✅ test"
  ]
  # Retries with:
  # - Forbidden → try stripped version
  # - 429 rate-limit → await retry_after + 0.5s
  # - Check perms: view_channel, send_messages, embed_links, mention_everyone
  # - Logs detailed: OK ID:msg, ERR reason
```

- All spam commands (`spam`, `spoiler_spam`, `webhook_spam`, `nuke`, `auto_raid`, `thread_spam`, etc.) now use `safe_send()` + `_send_embed()` with fallback
- `_send_embed()` now tries without image if image fails, without @everyone if forbidden, fallback to plain text via `safe_send()`
- `/api/channels` now returns `can_send` + `send_reason` per channel
- New endpoint `/api/test_send` → test if bot can actually send with diagnostics: VIEW_CHANNEL, SEND_MESSAGES, EMBED_LINKS, MENTION_EVERYONE
- UI new card **📤 Test Send Messages** → select channel (or auto), enter content, test @everyone, see detailed result + perms
- Permissions expanded: Added critical for send: `embed_links`, `attach_files`, `mention_everyone`, `read_message_history`, `add_reactions`, `create_public_threads`, `manage_events`, `view_channel` (total 21 now)

**Other fixes from v4:**
- audioop fix for Python 3.13 (audioop-lts shim) + PYTHON_VERSION 3.11.9
- RUN click does nothing → fixed confirm bool handling, toast, debug, /api/threads, TEST button
- Permissions panel with per-channel check
- Multi-threading: gthread 4 + bot thread + command executor 4 + blocking executor 2 + Semaphore 5 + chunk 10 + GC

### Deploy

Push to GitHub → Render → New Web Service → auto `render.yaml` → Python 3.11.9 → `python run.py --prod` → Health `/health`

Local:
```bash
pip install -r requirements.txt
python run.py --fix               # test audioop + MT
python run.py --threads 4         # web UI http://0.0.0.0:10000
python run.py --cli --list        # 39 cmds
# Test send
python run.py --cli --token TOKEN --guild ID --action server_info
curl -X POST http://localhost:10000/api/test_send -H "Content-Type: application/json" -d '{"content":"hi"}'
```

### All 39 Commands — Now with guaranteed send

01 Nuke (safe_send webhook spam), 02 Auto Raid, 03 Ban All, 04 Kick All, 05 Mute All, 06 Unban All, 07 Del Channels, 08 Del Emojis, 09 Del Stickers, 10 Create Channels, 11 Create Roles, 12 Create Cats, 13 Rename Channels, 14 Rename Roles, 15 Edit Server (blocking IO offloaded), 16 Rename Members, 17 Fix Nicks, 18 Get Admin, 19 Impersonate, 20 Ghost Ping, 21 Strip Roles, 22 DM All (safe_send), 23 DM Spam User (safe_send + retry), 24 Webhook Spam (safe_send + cleanup), 25 Server Info, 26 Clone Server (file IO offloaded), 27 Webhook Logs, 28 Lockdown, 29 Deafen VC, 30 Kick VC All, 31 Move All VC, 32 Invite Spam, 33 Spam (safe_send guaranteed), 34 Thread Spam, 35 Reaction Spam, 36 Voice Spam, 37 Spoiler Spam (safe_send), 38 Poll Spam, 39 Event Spam

### Architecture v5

- Flask: 1 worker / 4 gthreads ~250MB
- Bot: 1 thread asyncio
- Command Executor: 4 threads — each action `run_coroutine_threadsafe` in thread
- Blocking: 2 threads — icon download, file IO via `run_in_executor`
- Semaphore 5, chunk 10, sleep 0.2-0.5 anti rate-limit
- Endpoints: `/`, `/health`, `/api/threads`, `/api/permissions`, `/api/channels` (with can_send), `/api/test_send` (NEW), `/api/action` (MT + safe_send)

**If messages still don't send:**
1. Connect bot → check Permissions card → need SEND_MESSAGES ✅ VIEW_CHANNEL ✅ EMBED_LINKS ✅
2. If using @everyone → need MENTION_EVERYONE ✅ or uncheck @everyone (safe_send auto-strips on retry)
3. Check per-channel list: ✅ can send vs ❌ NO SEND reason
4. Use 📤 Test Send panel → select channel → SEND → see detailed perms + error
5. Re-invite with Admin: `https://discord.com/oauth2/authorize?client_id=ID&permissions=8&scope=bot`

### Files
```
run.py v5              # MT + threads arg + CLI
app.py v5              # MT + test_send + per-channel perm check
bot_manager.py v5      # 61KB MT + safe_send() 4 retries + all 39 perfected + 21 perms
command_runner.py v4   # CLI MT
templates/index.html v5 # test send card + critical perms + per-channel + safe_send logs
requirements.txt       # discord.py 2.4 + audioop-lts
render.yaml            # Python 3.11.9 + run.py --prod
```

VOID-NUKE WEB v5 — t.me/v0idtool · discord.gg/voidv2
