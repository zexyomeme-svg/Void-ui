# Deploying VOID-NUKE WEB to Vercel

⚠️ **Vercel is SERVERLESS — Not ideal for Discord bots that need persistent WebSocket**

## TL;DR

- **Vercel Hobby**: 10s function timeout, 512MB RAM, stateless — bot disconnects after each request
- **Render Free**: 512MB RAM, 0.1 CPU, **persistent** process — bot stays connected ✅ **RECOMMENDED**
- **Use Vercel for**: Quick UI demo, test_send, server_info, small actions (create 5 channels)
- **Use Render for**: Full nuke, auto_raid, ban_all large servers, persistent bot

## How to Deploy to Vercel (if you still want to)

### Option 1: Vercel Dashboard (Easiest)

1. Push this repo to GitHub
2. Go to https://vercel.com → Add New → Project → Import your GitHub repo
3. Vercel auto-detects `vercel.json`
4. Settings:
   - Framework Preset: Other
   - Root Directory: `./`
   - Build Command: (leave empty, Vercel uses `vercel.json`)
   - Install Command: `pip install -r requirements.txt`
5. Environment Variables:
   - `PYTHON_VERSION` = `3.11.9`
   - `PYTHONUNBUFFERED` = `1`
6. Deploy → you get `https://your-project.vercel.app`

### Option 2: Vercel CLI

```bash
npm i -g vercel
cd void-nuke-web
vercel --prod
# Follow prompts
```

### Files Added for Vercel

- `vercel.json` — tells Vercel to use `@vercel/python` runtime with `api/index.py`
- `api/index.py` — serverless adapter that imports Flask app from `app.py`
- `.vercelignore` — ignore cache

### What Works on Vercel vs What Timeouts

✅ **Works (quick, <10s):**
- `/` UI loads
- `/health` + `/api/vercel-info`
- Connect bot (`/api/connect`) — connects but disconnects after request (need reconnect each action)
- `/api/permissions` — after connect, shows perms (if bot still in memory)
- `/api/test_send` — test send 1 message (quick)
- `/api/action` with small qty: create_channels 5, spam count 2, server_info, clone_server

❌ **Will Timeout (10s Hobby limit):**
- Nuke 30 channels + 30 roles + webhook spam (needs 30-60s)
- Auto Raid 20 channels (needs 20s)
- Ban All 500+ members (needs >10s)
- Any action with large quantities

**Fix for timeout:**
- Reduce quantities: in UI, use 5 channels not 50, 2 messages not 10
- Or upgrade Vercel Pro (60s timeout) — still not persistent, but longer
- Or **use Render for bot + Vercel for UI** (see hybrid)

### Hybrid: Vercel UI + Render Bot (Best of Both)

1. Deploy full app to Render (persistent bot) → you get `https://void-nuke-web.onrender.com`
2. Deploy UI to Vercel → `https://void-nuke-web.vercel.app`
3. In Vercel UI, the bot will still need to connect, but you can have 2 UIs

Better yet, just use Render for everything — it's free tier 750h/month, 512MB, supports persistent WebSocket.

### Vercel Env Vars to Set

```
PYTHON_VERSION=3.11.9
PYTHONUNBUFFERED=1
PYTHONDONTWRITEBYTECODE=1
```

No need for PORT — Vercel handles it.

### Troubleshooting Vercel

**Error: `audioop` missing**
- We already handle with `audioop-lts` shim in `api/index.py` + `requirements.txt`
- Vercel uses Python 3.11 (has audioop), so less issue than Python 3.13

**Error: Function timeout 10s**
- Normal on Hobby — reduce quantities or use Render
- Check Vercel logs: `vercel logs your-deployment`

**Bot disconnects after each action**
- Normal — serverless is stateless, each request is new lambda
- You need to click CONNECT before each action on Vercel (annoying, but serverless limitation)
- On Render, bot stays connected once

**`/api/action` returns 500**
- Check Vercel Function Logs
- Might be Discord rate limit or missing perms — same as Render, check `/api/permissions`

### Recommendation

**For this project (Discord nuke bot that needs persistent gateway connection):**
- **Use Render.com** — we optimized for Render Free Tier (512MB, 0.1 CPU, gthread)
- **vercel.json is provided for demo/testing only**

If you really want Vercel, use it for frontend static + keep bot on Render, or accept reconnect + timeout limits.

### Deploy Button

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https://github.com/your-repo/void-nuke-web)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/your-repo/void-nuke-web)

---

**VOID-NUKE WEB v6** — Vercel adapter included, but Render recommended for full functionality.
