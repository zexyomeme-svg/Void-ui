"""
VOID-NUKE WEB - Vercel Free Tier Adaptive Serverless Adapter v6
Research from web search:

Vercel Free (Hobby) Limits 2025-2026:
- 100GB bandwidth, ~100K-1M function invocations, 6000 build minutes
- 10s function timeout default (can extend to 30s Hobby with maxDuration, 60s Pro with Fluid Compute)
- 50MB compressed, 250MB uncompressed (500MB for Python) function size
- No WebSockets, no persistent process, no background workers, stateless, no Celery
- Cold start 300-800ms for Python
- Python version auto-detected from .python-version, pyproject.toml, Pipfile.lock
  - If none, defaults to 3.12 (as seen in your error)
  - We now provide .python-version = 3.11.9 to force 3.11 (has builtin audioop)
- audioop-lts only works on Python >=3.13, so conditional requirement fixed:
  - requirements.txt: audioop-lts; python_version >= "3.13"
  - On 3.11/3.12: uses builtin audioop, no extra dependency

Render Free Limits:
- 512MB RAM, 0.1 CPU, 750 hours/month, persistent process, supports WebSockets
- PYTHON_VERSION 3.11.9 via env var
- Ideal for Discord bots that need persistent Gateway connection

This adapter:
- Detects VERCEL env var and adjusts behavior for serverless
- Provides /api/vercel-info with free tier details
- Handles audioop fix for both 3.11 and 3.13
- Sets maxDuration hints for Vercel
"""

import sys
import os

# Force Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Environment detection - adaptive for both Vercel and Render
IS_VERCEL = os.getenv("VERCEL") == "1" or os.getenv("VERCEL_ENV") is not None
IS_RENDER = os.getenv("RENDER") is not None or os.getenv("RENDER_SERVICE_ID") is not None

# Audioop fix - must be before discord import
# On Python 3.11/3.12 (Vercel 3.11, Render 3.11.9) builtin audioop exists
# On Python 3.13+ (local) needs audioop-lts shim
try:
    import audioop
    print(f"[VERCEL ADAPTER] audioop builtin OK, Python {sys.version.split()[0]}, IS_VERCEL={IS_VERCEL}, IS_RENDER={IS_RENDER}", flush=True)
except ModuleNotFoundError:
    try:
        import audioop_lts as audioop
        sys.modules['audioop'] = audioop
        print(f"[VERCEL ADAPTER] audioop-lts shim loaded, Python {sys.version.split()[0]}", flush=True)
    except ImportError as e:
        import types
        sys.modules['audioop'] = types.ModuleType("audioop")
        print(f"[VERCEL ADAPTER] audioop missing, voice disabled, error {e}", flush=True)

os.environ.setdefault("PYTHONUNBUFFERED", "1")
os.environ.setdefault("VERCEL", "1" if IS_VERCEL else "0")

# Import Flask app
try:
    from app import app as flask_app
    print(f"[VERCEL ADAPTER] Flask app imported OK, routes: {len(list(flask_app.url_map.iter_rules()))}", flush=True)
except Exception as e:
    print(f"[VERCEL ADAPTER] Failed to import app: {e}", flush=True)
    import traceback
    traceback.print_exc()
    # Fallback minimal app for debugging
    from flask import Flask, jsonify
    flask_app = Flask(__name__)
    @flask_app.route('/')
    def fallback():
        return jsonify({"error": f"Failed to import main app: {e}", "python": sys.version, "is_vercel": IS_VERCEL}), 500

app = flask_app

# Vercel maxDuration hint for Python - Vercel reads this from function config
# For Python, maxDuration set in vercel.json functions.api/index.py.maxDuration = 30
# This is the max allowed on Hobby free tier with Fluid Compute enabled

@app.route('/api/vercel-info')
def vercel_info():
    """Detailed Vercel free tier info + adaptive guidance"""
    return {
        "platform": "vercel" if IS_VERCEL else "render" if IS_RENDER else "local",
        "python_version": sys.version,
        "python_version_info": list(sys.version_info),
        "is_vercel": IS_VERCEL,
        "is_render": IS_RENDER,
        "adaptive_mode": "vercel_free_tier" if IS_VERCEL else "render_free_tier" if IS_RENDER else "local",
        "vercel_free_tier_limits": {
            "bandwidth": "100GB/month",
            "function_invocations": "~100K-1M/month (Hobby)",
            "build_minutes": "6000/month",
            "timeout_default": "10s Hobby (can set maxDuration 30s Hobby, 60s Pro with Fluid Compute)",
            "timeout_configured_in_vercel_json": "30s in vercel.json functions.api/index.py.maxDuration",
            "function_size_compressed": "50MB",
            "function_size_uncompressed": "250MB standard, 500MB Python",
            "memory": "1024MB configured in vercel.json (Hobby max)",
            "websockets": "No - not supported on Vercel",
            "persistent_process": "No - serverless, stateless, lambda dies after request",
            "background_workers": "No - no Celery, no Redis queues",
            "cold_start": "300-800ms for Python",
            "python_version_detection": ".python-version file now set to 3.11.9 to avoid 3.12 default issue",
            "audioop_issue_fixed": "requirements.txt now uses conditional marker: audioop-lts; python_version >= '3.13' - so on Python 3.11/3.12 (Vercel/Render) it uses builtin audioop, no extra dep"
        },
        "render_free_tier_limits": {
            "ram": "512MB",
            "cpu": "0.1 CPU",
            "hours": "750h/month",
            "persistent": "Yes - supports WebSockets, background workers",
            "timeout": "No timeout - persistent process",
            "python_version": "3.11.9 via PYTHON_VERSION env var",
            "ideal_for": "Discord bots that need persistent Gateway connection"
        },
        "why_your_build_failed_before": {
            "error_you_saw": "No Python version specified, using 3.12 + audioop-lts==0.2.1 depends on Python>=3.13, requirements unsatisfiable",
            "root_cause": "Vercel defaulted to Python 3.12 because no .python-version file, and requirements.txt had unconditional audioop-lts==0.2.1 which requires >=3.13, so uv resolver failed",
            "fix_applied": [
                "Created .python-version file with 3.11.9 to force Python 3.11 (has builtin audioop)",
                "Created runtime.txt with python-3.11.9 for Render compatibility",
                "Changed requirements.txt to conditional: audioop-lts; python_version >= '3.13' - only installs on 3.13+, not on 3.11/3.12",
                "Updated vercel.json to specify runtime python3.11, maxDuration 30s, memory 1024MB",
                "Added api/index.py with adaptive detection for VERCEL vs RENDER"
            ]
        },
        "what_works_on_vercel": [
            "UI / loads",
            "/health, /api/vercel-info",
            "Connect bot (connects but disconnects after request - stateless)",
            "/api/permissions after quick connect",
            "/api/test_send 1 message (quick <5s)",
            "Small actions: create_channels 5, spam count 2, server_info"
        ],
        "what_timeouts_on_vercel_free": [
            "nuke 30 channels (needs 30-60s) - will timeout after 10s default, 30s max Hobby",
            "auto_raid 20 channels (20s)",
            "ban_all 500 members (>10s)",
            "Fix: reduce quantities to 5 channels, 2 messages, or use Render"
        ],
        "recommendation": "For full functionality (all 39 commands perfected, persistent bot), deploy on Render Free Tier. Use Vercel only for UI demo or quick tests. Hybrid: UI on Vercel, bot logic on Render.",
        "deploy_buttons": {
            "vercel": "https://vercel.com/new/clone?repository-url=https://github.com/your-repo",
            "render": "https://render.com/deploy?repo=https://github.com/your-repo"
        }
    }

# For Vercel Python runtime, need to export app
# Vercel looks for 'app' variable
