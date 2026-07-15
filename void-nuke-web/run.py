#!/usr/bin/env python3
"""
VOID-NUKE WEB - Unified Runner
Fixes audioop missing in Python 3.13 + installs deps + runs app
100% feature parity with https://github.com/v0id4real/Void-Nuke

Usage:
  python run.py              -> dev server http://0.0.0.0:10000
  python run.py --prod       -> gunicorn production (Render free tier)
  python run.py --install    -> force reinstall deps then run
  python run.py --fix        -> test audioop fix
"""

# --- Audioop fix MUST be first import ---
import sys
try:
    import audioop
except ModuleNotFoundError:
    try:
        import audioop_lts as _audioop_lts
        sys.modules['audioop'] = _audioop_lts
        print("[FIX] Python 3.13 detected - using audioop-lts shim")
    except ImportError:
        print("[INFO] audioop not found, will install audioop-lts...")
        # Will be installed later
        pass

import os
import subprocess
import argparse

def check_python():
    print(f"[INFO] Python {sys.version}")
    if sys.version_info < (3, 8):
        print("[ERR] Python 3.8+ required")
        sys.exit(1)
    if sys.version_info >= (3, 13):
        print("[WARN] Python 3.13 - audioop was removed, using shim. Recommended: Python 3.11 for Render")

def install_deps():
    print("[*] Installing dependencies with audioop-lts fix...")
    req = os.path.join(os.path.dirname(__file__), "requirements.txt")
    # Ensure audioop-lts in requirements
    try:
        with open(req, 'r') as f:
            content = f.read()
        if 'audioop' not in content.lower():
            print("[*] Adding audioop-lts to requirements.txt")
            with open(req, 'a') as f:
                f.write("\naudioop-lts==0.2.1\n")
    except:
        pass

    cmd = [sys.executable, "-m", "pip", "install", "--no-cache-dir", "-r", req]
    print(f"[*] Running: {' '.join(cmd)}")
    subprocess.check_call(cmd)
    
    # Double-check audioop fix
    try:
        import audioop
        print("[OK] audioop available")
    except ModuleNotFoundError:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--no-cache-dir", "audioop-lts==0.2.1"])
            print("[OK] audioop-lts installed")
        except Exception as e:
            print(f"[WARN] Could not install audioop-lts: {e}")

    print("[OK] All dependencies installed")

def test_audioop():
    print("[*] Testing audioop fix...")
    try:
        import audioop
        print(f"[OK] audioop module found: {audioop.__file__ if hasattr(audioop, '__file__') else 'shim'}")
        return True
    except ModuleNotFoundError as e:
        print(f"[ERR] audioop test failed: {e}")
        try:
            import audioop_lts
            sys.modules['audioop'] = audioop_lts
            print("[FIX] Applied audioop-lts shim")
            import audioop
            print("[OK] audioop now works via shim")
            return True
        except ImportError:
            print("[ERR] audioop-lts not installed, installing...")
            install_deps()
            return test_audioop()
    except Exception as e:
        print(f"[ERR] Unexpected: {e}")
        return False

def run_dev(port):
    os.environ["PYTHONUNBUFFERED"] = "1"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    print(f"""
╔════════════════════════════════════════════════╗
║  VOID-NUKE WEB v1.0.0 - FULL FEATURE SET     ║
║  Original: github.com/v0id4real/Void-Nuke    ║
║  Render Free Tier: 512MB / 0.1 CPU           ║
╠════════════════════════════════════════════════╣
║  Dev Server: http://0.0.0.0:{port:<5}                ║
║  Health:    http://0.0.0.0:{port}/health           ║
║  Docs:      All 39 commands implemented       ║
║  Fix:       audioop-lts shim for Py3.13      ║
╚════════════════════════════════════════════════╝
    """)
    # Verify imports before starting
    try:
        from app import app
        print("[OK] App imported successfully")
    except Exception as e:
        print(f"[ERR] Import failed: {e}")
        if "audioop" in str(e).lower():
            print("[*] Trying to fix audioop...")
            test_audioop()
            try:
                from app import app
                print("[OK] Fixed and imported")
            except Exception as e2:
                print(f"[FAIL] Still failing: {e2}")
                sys.exit(1)
        else:
            raise

    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)

def run_prod(port):
    print(f"""
╔════════════════════════════════════════════════╗
║  VOID-NUKE WEB - PRODUCTION / RENDER         ║
║  Gunicorn 1 worker + 2 threads = ~250MB RAM  ║
╠════════════════════════════════════════════════╣
║  Bind: 0.0.0.0:{port}                              ║
╚════════════════════════════════════════════════╝
    """)
    try:
        import gunicorn.app.wsgiapp as wsgi
        sys.argv = [
            "gunicorn",
            "app:app",
            "--workers", "1",
            "--threads", "2",
            "--timeout", "120",
            "--bind", f"0.0.0.0:{port}",
            "--worker-class", "gthread",
            "--log-level", "info",
            "--preload",
        ]
        wsgi.run()
    except ImportError:
        print("[WARN] gunicorn not found, fallback to dev server")
        run_dev(port)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VOID-NUKE WEB Runner - Full")
    parser.add_argument("--prod", action="store_true", help="Production gunicorn (Render)")
    parser.add_argument("--install", action="store_true", help="Force reinstall deps")
    parser.add_argument("--fix", action="store_true", help="Test/fix audioop only")
    parser.add_argument("--port", type=int, default=None, help="Port (default $PORT or 10000)")
    args = parser.parse_args()

    port = args.port or int(os.environ.get("PORT", "10000"))
    os.environ["PORT"] = str(port)

    check_python()

    if args.fix:
        test_audioop()
        sys.exit(0)

    if args.install:
        install_deps()
    else:
        # Auto-install if needed
        try:
            import flask, discord
            import audioop
        except ImportError as e:
            print(f"[*] Missing dep: {e}, auto-installing...")
            install_deps()
            test_audioop()

    # Clean pycache to save RAM
    try:
        import pathlib
        for p in pathlib.Path(".").rglob("__pycache__"):
            import shutil
            shutil.rmtree(p, ignore_errors=True)
    except:
        pass

    if args.prod:
        run_prod(port)
    else:
        run_dev(port)
