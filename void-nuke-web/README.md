# VOID-NUKE WEB — Render Optimized (512MB / 0.1 CPU Free Tier)

Web UI conversion of [v0id4real/Void-Nuke](https://github.com/v0id4real/Void-Nuke) for Render deployment.

> ⚠️ **Educational use only** — Use only on Discord servers you own or with explicit written permission. Respect Discord ToS.

### ✨ What changed vs original CLI?

- **CLI → Web UI**: Single-page dark/red UI, no terminal needed
- **Render ready**: `render.yaml`, `Procfile`, `Dockerfile`, `/health` check
- **Optimized for Free Tier**:
  - `gunicorn --workers 1 --threads 2 --worker-class gthread` (~200-300MB RAM)
  - `discord.py` with `max_messages=None`, minimal intents, `chunk_guilds_at_startup=False`
  - `asyncio.Semaphore(3)` + chunked gather (10 ops) + 0.25s sleep + `gc.collect()`
  - Max 30 channels/roles by default (original 50) to avoid OOM
  - Single bot thread + Flask in main thread
  - No Rich, colorama, heavy libs — only Flask + discord.py

### 🚀 Deploy to Render (Free)

**Option 1: One-click**
1. Fork this repo to your GitHub
2. Go to https://dashboard.render.com → New → Web Service → Connect your fork
3. Render auto-detects `render.yaml` (Free plan, Oregon)
4. Build: `pip install -r requirements.txt`
5. Start: `gunicorn app:app --workers 1 --threads 2 --timeout 120 --bind 0.0.0.0:$PORT --worker-class gthread`
6. Deploy, then open your `.onrender.com` URL

**Option 2: Manual**
- Env: `Python 3.11`
- Port: `10000`
- Health check: `/health`

### 💻 Local Run

```bash
pip install -r requirements.txt
python app.py
# open http://localhost:10000
```

### 🧠 Usage

1. Enter Bot Token + Server ID (Guild ID) → CONNECT
2. Wait for green CONNECTED + Server Info card
3. Pick category (Nuke, Mod, Channels etc)
4. Click RUN → fill params → confirm destructive if needed → EXECUTE
5. Watch Live Logs (polls /api/logs every 1.5s)

### 🔧 All 39 Commands Mapped

| ID | UI Name | Notes |
|---|---|---|
| 01 | Nuke | 30 ch/roles default, webhook spam 3x |
| 02 | Auto Raid | 20 ch/roles |
| 03-06 | Ban/Kick/Mute/Unban | Semaphore 3, chunked |
| 07-14 | Channel/Role management | |
| ... | Spam / DM / VC | Limited to 2-5 msgs per action for free tier |
| 25 | Server Info | Returns JSON in logs |
| etc | | |

**Free Tier Tips:**
- Don't run >50 channels/roles at once
- Use 10-20 quantity for safety
- Wait between destructive actions (rate limits)
- Logs are in-memory (500 max) — clear often

### 📁 Structure

```
/app.py           # Flask + bot thread launcher
/bot_manager.py   # Optimized command core (Semaphore)
/templates/index.html # Full SPA UI (no build step)
/requirements.txt # minimal deps
/render.yaml      # Render free spec
/Procfile         # gunicorn 1 worker
/Dockerfile       # optional, preload, 512MB friendly
```

### ⚖️ License

MIT — same as original. Educational only.

**VOID-NUKE WEB v1.0.0** — t.me/v0idtool · discord.gg/voidv2
