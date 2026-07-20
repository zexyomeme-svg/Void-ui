"""
Root api/index.py for Vercel deployment when Root Directory = repo root (Void-ui)
This file re-exports the actual app from void-nuke-web/api/index.py and void-nuke-web/app.py
Fixes 404 NOT_FOUND when repo has subfolder void-nuke-web/

Research fixes:
- Vercel expects api/index.py at root of project (or Root Directory)
- If code is in void-nuke-web/api/index.py but Root Directory is ., then /api/index doesn't exist at root -> 404
- Solution: Create api/index.py at root that imports from void-nuke-web/
- Also need rewrites: {"source": "/(.*)", "destination": "/api/index"} (modern) not builds+routes (legacy)
- Templates must be in api/templates for Vercel bundling
"""

import sys
import os

# Add void-nuke-web to path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOID_DIR = os.path.join(ROOT, 'void-nuke-web')
if VOID_DIR not in sys.path:
    sys.path.insert(0, VOID_DIR)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Also add void-nuke-web/api to path
API_DIR = os.path.join(VOID_DIR, 'api')
if API_DIR not in sys.path:
    sys.path.insert(0, API_DIR)

# Force templates folder to be found (copy already exists in api/templates, but also try void-nuke-web/templates)
print(f"[ROOT API] ROOT={ROOT} VOID_DIR={VOID_DIR} API_DIR={API_DIR} cwd={os.getcwd()}", flush=True)

# Audioop fix
try:
    import audioop
except ModuleNotFoundError:
    try:
        import audioop_lts as audioop
        sys.modules['audioop'] = audioop
        print("[ROOT API] audioop-lts shim", flush=True)
    except ImportError:
        import types
        sys.modules['audioop'] = types.ModuleType("audioop")

# Try to import main app from void-nuke-web
flask_app = None
import_error = None

try:
    # Import the adaptive Vercel adapter from void-nuke-web/api/index.py
    # It already handles template_folder, audioop, etc.
    import importlib.util
    # Load void-nuke-web/api/index.py as module
    vw_api_path = os.path.join(VOID_DIR, 'api', 'index.py')
    if os.path.exists(vw_api_path):
        spec = importlib.util.spec_from_file_location("void_api_index", vw_api_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["void_api_index"] = mod
        spec.loader.exec_module(mod)
        flask_app = mod.app
        print(f"[ROOT API] Loaded from {vw_api_path} OK", flush=True)
    else:
        # Fallback: try void-nuke-web/app.py directly
        app_path = os.path.join(VOID_DIR, 'app.py')
        spec = importlib.util.spec_from_file_location("app", app_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["app"] = mod
        spec.loader.exec_module(mod)
        flask_app = mod.app
        print(f"[ROOT API] Loaded from {app_path} OK", flush=True)

except Exception as e:
    import_error = f"{type(e).__name__}: {e}"
    print(f"[ROOT API] Failed to import main app: {import_error}", flush=True)
    import traceback
    traceback.print_exc()
    # Fallback minimal app to avoid 404 - shows error page
    from flask import Flask, jsonify, render_template_string
    flask_app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__), 'templates'))
    
    @flask_app.route('/')
    def fallback_root():
        return render_template_string("""
        <html><body style="background:#0a0a0a;color:#f1f1f1;font-family:monospace;padding:20px">
        <h1 style="color:#ff1a1a">VOID-NUKE WEB - Root API Fallback</h1>
        <p>Main app import failed: {{ error }}</p>
        <p>This is fallback from /api/index.py at repo root. Actual code is in void-nuke-web/</p>
        <p><b>Fix:</b> Set Root Directory to <code>void-nuke-web</code> in Vercel dashboard → Settings → General → Root Directory</p>
        <p>Then vercel.json inside void-nuke-web will be used with correct api/index.py</p>
        <p><a href="/api/vercel-info" style="color:#00ff88">/api/vercel-info</a></p>
        </body></html>
        """, error=import_error)
    
    @flask_app.route('/api/vercel-info')
    def vercel_info_root():
        return jsonify({
            "platform": "vercel-root-fallback",
            "error": import_error,
            "fix": "Set Root Directory to void-nuke-web in Vercel dashboard, or ensure void-nuke-web/api/index.py exists",
            "cwd": os.getcwd(),
            "root": ROOT,
            "void_dir_exists": os.path.exists(VOID_DIR),
            "api_index_exists": os.path.exists(os.path.join(VOID_DIR, 'api', 'index.py')),
            "files_in_root": os.listdir(ROOT)[:20] if os.path.exists(ROOT) else []
        })

# Vercel expects 'app' variable
app = flask_app
