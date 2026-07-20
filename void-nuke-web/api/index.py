"""
VOID-NUKE WEB - Vercel Serverless Adapter
⚠️ IMPORTANT: Vercel is SERVERLESS (10s timeout on Hobby, 60s on Pro)
Discord bots need PERSISTENT WebSocket connection to Discord Gateway.
On Vercel, the bot will DISCONNECT after each request (stateless).

This adapter makes Flask UI work on Vercel for testing permissions, test_send, etc.
But for full nuke/spam that takes >10s, use Render (persistent) instead.

How it works on Vercel:
- Each /api/* request spawns a new Python lambda
- Bot connects, does action, then lambda dies (bot disconnects)
- For quick actions (server_info, test_send, create_channels 5) it works
- For long actions (nuke 30 channels) it will TIMEOUT after 10s

Recommended: Deploy UI on Vercel, bot logic on Render, or use Vercel only as demo.
"""

import sys
import os

# Add parent dir to path so we can import app.py, bot_manager.py
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Audioop fix for Python 3.11 (Vercel uses 3.11)
try:
    import audioop
except ModuleNotFoundError:
    try:
        import audioop_lts as audioop
        sys.modules['audioop'] = audioop
    except ImportError:
        import types
        sys.modules['audioop'] = types.ModuleType("audioop")

# Vercel sets PORT differently, but Flask app handles it
os.environ.setdefault("VERCEL", "1")
os.environ.setdefault("PYTHONUNBUFFERED", "1")

# Import Flask app from parent
from app import app as flask_app

# Vercel expects 'app' variable
app = flask_app

# Optional: Add Vercel-specific route for info
@flask_app.route('/api/vercel-info')
def vercel_info():
    return {
        "platform": "vercel",
        "warning": "Vercel is serverless - bot disconnects after each request. For persistent bot, use Render.",
        "note": "Quick actions (test_send, server_info, create 5 channels) work. Long actions (nuke 30) will timeout after 10s on Hobby plan.",
        "recommendation": "For full functionality, deploy on Render.com free tier (512MB, 0.1 CPU, persistent). Use Vercel only for UI demo.",
        "endpoints_that_work": ["/", "/health", "/api/status", "/api/permissions (after connect)", "/api/test_send (quick)", "/api/action with small quantities"],
        "endpoints_that_timeout": ["nuke with 30 channels (needs >10s)", "ban_all large servers", "auto_raid 20 channels"],
        "how_to_fix_timeout": "Reduce quantities: create 5 channels not 50, spam count 2 not 10, or upgrade Vercel Pro (60s) or use Render",
        "render_alternative": "https://github.com/v0id4real/Void-Nuke - Deploy to Render button in README"
    }

# Export for Vercel
# Vercel Python runtime looks for 'app' variable
