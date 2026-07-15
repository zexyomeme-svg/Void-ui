# VOID-NUKE WEB v4 — Multi-threaded Fixed

Web UI + CLI conversion of [v0id4real/Void-Nuke](https://github.com/v0id4real/Void-Nuke) — **All 39 original commands**, Render Free Tier optimized (512MB RAM / 0.1 CPU), **multi-threaded**.

> ⚠️ Educational use only — Use only on servers you own.

### What's Fixed vs Original CLI

**Bug Fixes:**
- `audioop doesn't exist` on Python 3.13 → shim `audioop-lts` in all files + pinned `PYTHON_VERSION 3.11.9` in render.yaml
- `Click RUN does nothing` → fixed confirm bool handling (`true/"on"/1`), added toast + debug panel + `/api/threads` + TEST EXECUTION button
- Missing commands → restored 7 missing: Fix Nicks, Impersonate, Ghost Ping, Webhook Logs, Reaction Spam, Voice Spam, Poll Spam

**Features Added:**
- ✅ **Permissions Panel** (`/api/permissions`) — shows ✅/❌ for Intents (Members, Message Content) + 14 Discord perms (Admin, Ban, Kick, Manage Ch, Roles, etc) + guide how to enable + invite URL with admin
- ✅ **Multi-threading** — Flask gthread 4 threads + Bot thread + Command Executor 4 threads + Blocking Executor 2 threads + Semaphore 5 + chunked gather 10 + GC
- ✅ **command_runner.py** — standalone CLI for all 39 cmds + `run.py --cli`
- ✅ **run.py** unified runner — `--fix`, `--prod`, `--cli`, `--threads`

### Deploy to Render Free

1. Push to GitHub
2. Render → New Web Service → Connect repo → auto detects `render.yaml`
   - Build: `pip install -r requirements.txt`
   - Start: `python run.py --prod`
   - Python 3.11.9, health `/health`
3. Open `.onrender.com`

Local:
```bash
pip install -r requirements.txt
python run.py --fix          # test audioop + MT
python run.py --port 10000 --threads 4   # web UI
python run.py --cli --list   # list 39 cmds
python run.py --cli --token TOKEN --guild ID --action server_info
python run.py --cli --token TOKEN --guild ID --action nuke --num_channels 30 --confirm --threads 4
```

### All 39 Commands (100% parity)

01 Nuke, 02 Auto Raid, 03 Ban All, 04 Kick All, 05 Mute All, 06 Unban All, 07 Del Channels, 08 Del Emojis, 09 Del Stickers, 10 Create Channels, 11 Create Roles, 12 Create Cats, 13 Rename Channels, 14 Rename Roles, 15 Edit Server, 16 Rename Members, 17 Fix Nicks, 18 Get Admin, 19 Impersonate, 20 Ghost Ping, 21 Strip Roles, 22 DM All, 23 DM Spam User, 24 Webhook Spam, 25 Server Info, 26 Clone Server, 27 Webhook Logs, 28 Lockdown, 29 Deafen VC, 30 Kick VC All, 31 Move All VC, 32 Invite Spam, 33 Spam, 34 Thread Spam, 35 Reaction Spam, 36 Voice Spam, 37 Spoiler Spam, 38 Poll Spam, 39 Event Spam

### Multi-threading Architecture

- **Flask**: `gunicorn --workers 1 --threads 4 --worker-class gthread` → ~250MB RAM fits 512MB
- **Bot**: dedicated thread `void-bot-main` asyncio loop
- **Command Executor**: ThreadPoolExecutor(4) — each `/api/action` runs in thread via `run_coroutine_threadsafe`
- **API Executor**: ThreadPoolExecutor(4) for blocking ops (channels, logs)
- **Blocking Executor**: ThreadPoolExecutor(2) for icon download, file IO (offloaded via `run_in_executor`)
- **API Limiter**: `Semaphore(5)` + chunk 10 + `sleep(0.2)` + `gc.collect()` = safe for 0.1 CPU

Endpoints:
- `/` UI with permissions panel, logs, debug
- `/health` → threads, tasks, audioop
- `/api/threads` → active threads list
- `/api/permissions` → ✅/❌ perms + guide
- `/api/action` → MT execution

### Structure
```
run.py              # unified runner v4 MT
app.py              # Flask MT + perms + threads API
bot_manager.py      # core MT + 39 cmds + perms check (54KB)
command_runner.py   # CLI MT runner
templates/index.html # permissions + execution fixed + toasts
requirements.txt    # discord.py 2.4 + audioop-lts
render.yaml         # Python 3.11.9, run.py --prod
```

**VOID-NUKE WEB v4** — t.me/v0idtool · discord.gg/voidv2 · github.com/v0id4real/Void-Nuke
