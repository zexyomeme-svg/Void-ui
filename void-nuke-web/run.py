#!/usr/bin/env python3
"""
VOID-NUKE WEB - Unified Runner
Optimized for Render Free Tier: 512MB RAM / 0.1 CPU

Usage:
  python run.py              -> dev server (localhost:10000)
  python run.py --prod       -> gunicorn production (Render style)
  python run.py --install    -> install deps then run

This is the ONLY file you need to run.
"""

import os
import sys
import subprocess
import argparse

def check_python():
    if sys.version_info < (3, 8):
        print("[ERR] Python 3.8+ required")
        sys.exit(1)

def install_deps():
    print("[*] Installing dependencies (optimized, no cache to save RAM)...")
    req = os.path.join(os.path.dirname(__file__), "requirements.txt")
    cmd = [sys.executable, "-m", "pip", "install", "--no-cache-dir", "-r", req]
    subprocess.check_call(cmd)
    print("[OK] Dependencies installed")

def run_dev():
    port = int(os.environ.get("PORT", "10000"))
    print(f"""
╔════════════════════════════════════════════════╗
║  VOID-NUKE WEB v1.0.0                         ║
║  Render Free Tier Optimized                  ║
║  512MB RAM / 0.1 CPU / 1 worker / 2 threads  ║
╠════════════════════════════════════════════════╣
║  Dev Server: http://0.0.0.0:{port:<5}                ║
║  Health:    http://0.0.0.0:{port}/health           ║
║  Mode:      Flask threaded (low RAM)            ║
╚════════════════════════════════════════════════╝
    """)
    # Import here to avoid overhead before banner
    os.environ["PYTHONUNBUFFERED"] = "1"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    from app import app
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)

def run_prod():
    port = os.environ.get("PORT", "10000")
    print(f"""
╔════════════════════════════════════════════════╗
║  VOID-NUKE WEB - PRODUCTION MODE             ║
║  Gunicorn 1 worker + 2 gthreads              ║
║  For Render Free Tier                        ║
╠════════════════════════════════════════════════╣
║  Command:                                    ║
║  gunicorn app:app --workers 1 --threads 2    ║
║  --bind 0.0.0.0:{port} --worker-class gthread      ║
╚════════════════════════════════════════════════╝
    """)
    # Use gunicorn programmatically if available
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
        print("[WARN] gunicorn not found, falling back to flask dev server")
        run_dev()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VOID-NUKE WEB Runner")
    parser.add_argument("--prod", action="store_true", help="Run production gunicorn (Render mode)")
    parser.add_argument("--install", action="store_true", help="Install requirements then run")
    parser.add_argument("--port", type=int, default=None, help="Port (default 10000 or $PORT)")
    args = parser.parse_args()

    if args.port:
        os.environ["PORT"] = str(args.port)

    check_python()

    if args.install:
        install_deps()

    # Auto-install if deps missing
    try:
        import flask, discord
    except ImportError:
        print("[*] Deps missing, auto-installing...")
        install_deps()

    # Clean pycache to save RAM on Render
    try:
        subprocess.call(["find", ".", "-type", "d", "-name", "__pycache__", "-exec", "rm", "-rf", "{}", "+"], stderr=subprocess.DEVNULL)
    except:
        pass

    if args.prod:
        run_prod()
    else:
        run_dev()
