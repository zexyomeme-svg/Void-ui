"""
VOID-NUKE WEB - Vercel Serverless Adapter v7 - Fixed 404
Research fixes from web search:

404 after build success is common for Flask on Vercel. Fixes:
1. Use "rewrites" not "builds"+"routes" (legacy, now rewrites is modern)
   vercel.json: {"rewrites": [{"source": "/(.*)", "destination": "/api/index"}]}
   Source: StackOverflow 76105842 - "This one resolve problem for me, just rechange vercel.json to rewrites"

2. Templates must be accessible to Flask when running as api/index.py
   Vercel bundles only api/ folder by default, but templates/ is outside api/
   Fix: Flask template_folder = absolute path to ../templates, and copy templates into api/ if needed
   Also set static_folder

3. Root Directory: If repo is Void-ui/void-nuke-web/, set Vercel Root Directory to void-nuke-web in dashboard
   Or put vercel.json at repo root pointing to void-nuke-web/api/index.py

4. Vercel Free Tier: 10s default, 30s max Hobby with maxDuration, no WebSockets, stateless

This file fixes 404 by:
- Importing Flask app with correct template_folder absolute path
- Adding fallback route for / to render index.html directly if main app fails
- Providing /api/vercel-info with debug
"""

import sys
import os

# Force Python path - adaptive for Vercel (path0 is repo root, code is in void-nuke-web/)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Also try parent of parent for when Vercel runs from void-nuke-web as root
PARENT_DIR = os.path.join(os.path.dirname(__file__), '..')
for p in [BASE_DIR, PARENT_DIR, os.path.join(os.path.dirname(__file__), '..', '..')]:
    if p not in sys.path:
        sys.path.insert(0, p)

# Add current dir and parent to path for imports
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Environment detection
IS_VERCEL = os.getenv("VERCEL") == "1" or os.getenv("VERCEL_ENV") is not None
IS_RENDER = os.getenv("RENDER") is not None

# Audioop fix
try:
    import audioop
    print(f"[VERCEL v7] audioop builtin OK Python {sys.version.split()[0]} IS_VERCEL={IS_VERCEL}", flush=True)
except ModuleNotFoundError:
    try:
        import audioop_lts as audioop
        sys.modules['audioop'] = audioop
        print(f"[VERCEL v7] audioop-lts shim", flush=True)
    except ImportError:
        import types
        sys.modules['audioop'] = types.ModuleType("audioop")
        print(f"[VERCEL v7] audioop dummy", flush=True)

os.environ.setdefault("PYTHONUNBUFFERED", "1")

# Try to import main Flask app
flask_app = None
import_error = None

try:
    # Try multiple import paths for adaptive
    try:
        from app import app as main_app
        flask_app = main_app
        print(f"[VERCEL v7] Imported app from app.py OK, routes={len(list(flask_app.url_map.iter_rules()))}", flush=True)
    except ImportError as e1:
        # Try void-nuke-web/app.py when running from repo root
        try:
            from void_nuke_web.app import app as main_app
            flask_app = main_app
            print(f"[VERCEL v7] Imported from void_nuke_web.app OK", flush=True)
        except ImportError:
            # Try parent import
            import importlib.util
            app_path = os.path.join(BASE_DIR, 'void-nuke-web', 'app.py')
            if not os.path.exists(app_path):
                app_path = os.path.join(PARENT_DIR, 'app.py')
            if not os.path.exists(app_path):
                app_path = os.path.join(os.path.dirname(__file__), '..', 'app.py')
            
            print(f"[VERCEL v7] Trying load from {app_path}", flush=True)
            if os.path.exists(app_path):
                spec = importlib.util.spec_from_file_location("app", app_path)
                mod = importlib.util.module_from_spec(spec)
                sys.modules["app"] = mod
                spec.loader.exec_module(mod)
                flask_app = mod.app
                print(f"[VERCEL v7] Loaded app.py from {app_path} OK", flush=True)
            else:
                raise e1

except Exception as e:
    import_error = f"{type(e).__name__}: {e}"
    print(f"[VERCEL v7] Failed to import main app: {import_error}", flush=True)
    import traceback
    traceback.print_exc()
    # Fallback minimal app to avoid 404 - shows error instead of 404
    from flask import Flask, jsonify, render_template_string
    flask_app = Flask(__name__)
    
    @flask_app.route('/')
    def fallback_index():
        return render_template_string("""
        <html><body style="background:#0a0a0a;color:#f1f1f1;font-family:monospace;padding:20px">
        <h1 style="color:#ff1a1a">VOID-NUKE WEB - Vercel Fallback (Main App Import Failed)</h1>
        <p>Error: {{ error }}</p>
        <p>Python: {{ pyver }}</p>
        <p>IS_VERCEL: {{ is_vercel }}</p>
        <p>BASE_DIR: {{ base_dir }}</p>
        <p>Files in BASE_DIR: {{ files }}</p>
        <p>Fix: Check that templates/ and app.py are accessible. Set Root Directory to void-nuke-web in Vercel dashboard.</p>
        <p><a href="/api/vercel-info" style="color:#00ff88">/api/vercel-info</a> | <a href="/health" style="color:#00ff88">/health</a></p>
        </body></html>
        """, error=import_error, pyver=sys.version, is_vercel=IS_VERCEL, base_dir=BASE_DIR, files=os.listdir(BASE_DIR)[:20] if os.path.exists(BASE_DIR) else [])

    @flask_app.route('/health')
    def fallback_health():
        return jsonify({"status":"fallback", "error":import_error, "python": sys.version, "is_vercel": IS_VERCEL})

# Ensure app has correct template folder for Vercel (api/ vs root)
# Vercel bundles api/ but templates/ is outside - Flask needs absolute path
if flask_app:
    try:
        # Try to find templates folder
        possible_template_dirs = [
            os.path.join(BASE_DIR, 'void-nuke-web', 'templates'),
            os.path.join(PARENT_DIR, 'templates'),
            os.path.join(os.path.dirname(__file__), '..', 'templates'),
            os.path.join(os.path.dirname(__file__), 'templates'),
            os.path.join(os.getcwd(), 'void-nuke-web', 'templates'),
            os.path.join(os.getcwd(), 'templates'),
        ]
        for tdir in possible_template_dirs:
            if os.path.exists(tdir):
                flask_app.template_folder = tdir
                print(f"[VERCEL v7] Set template_folder to {tdir}", flush=True)
                break
        # Also set static
        possible_static_dirs = [
            os.path.join(BASE_DIR, 'void-nuke-web', 'static'),
            os.path.join(PARENT_DIR, 'static'),
            os.path.join(os.path.dirname(__file__), '..', 'static'),
        ]
        for sdir in possible_static_dirs:
            if os.path.exists(sdir):
                flask_app.static_folder = sdir
                print(f"[VERCEL v7] Set static_folder to {sdir}", flush=True)
                break
    except Exception as e:
        print(f"[VERCEL v7] Failed to set template_folder: {e}", flush=True)

# Vercel expects 'app' variable
app = flask_app

# Add vercel-info route if not already exists
if app:
    try:
        # Check if route exists, if not add it
        has_vercel_info = any(r.rule == '/api/vercel-info' for r in app.url_map.iter_rules())
        if not has_vercel_info:
            @app.route('/api/vercel-info')
            def vercel_info_fallback():
                return {
                    "platform": "vercel" if IS_VERCEL else "render" if IS_RENDER else "local",
                    "python": sys.version,
                    "is_vercel": IS_VERCEL,
                    "is_render": IS_RENDER,
                    "base_dir": BASE_DIR,
                    "template_folder": getattr(app, 'template_folder', 'unknown'),
                    "routes": [str(r.rule) for r in app.url_map.iter_rules()][:20],
                    "fix_404": {
                        "1": "Use vercel.json with rewrites not builds+routes: {\"rewrites\": [{\"source\": \"/(.*)\", \"destination\": \"/api/index\"}]}",
                        "2": "Set Root Directory to void-nuke-web in Vercel dashboard if repo is Void-ui/void-nuke-web/",
                        "3": "Ensure templates/ is accessible - set absolute template_folder",
                        "4": "Build succeeds but 404 means routing misconfig - rewrites fix it"
                    }
                }
    except:
        pass
