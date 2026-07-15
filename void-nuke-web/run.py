#!/usr/bin/env python3
"""
VOID-NUKE WEB - Unified Runner + CLI
Fixed audioop for Python 3.13, all 39 commands, permissions area.

Usage:
  python run.py                          -> Web UI http://0.0.0.0:10000
  python run.py --prod                   -> Prod gunicorn (Render free tier)
  python run.py --cli --help             -> CLI runner help (direct commands)
  python run.py --cli --token ... --guild ... --action server_info
  python run.py --cli --token ... --guild ... --action ban_all --confirm
  python run.py --port 5000              -> Custom port
  python run.py --fix                    -> Test audioop fix
  python run.py --install                -> Force reinstall deps
"""

# Audioop fix MUST be first
import sys
try:
    import audioop
except ModuleNotFoundError:
    try:
        import audioop_lts as audioop
        sys.modules['audioop'] = audioop
        print("[FIX] Python 3.13 - audioop -> audioop-lts shim", flush=True)
    except ImportError:
        print("[INFO] audioop missing - will install audioop-lts...", flush=True)

import os
import subprocess
import argparse

def check_python():
    print(f"[INFO] Python {sys.version}", flush=True)
    if sys.version_info < (3, 8):
        print("[ERR] Python 3.8+ required")
        sys.exit(1)
    if sys.version_info >= (3, 13):
        print("[WARN] Python 3.13 detected - using audioop-lts shim. Recommended 3.11 for Render", flush=True)

def install_deps():
    print("[*] Installing deps with audioop fix...", flush=True)
    req = os.path.join(os.path.dirname(__file__), "requirements.txt")
    try:
        with open(req, 'r') as f:
            content = f.read()
        if 'audioop' not in content.lower():
            with open(req, 'a') as f:
                f.write("\naudioop-lts==0.2.1\n")
    except:
        pass
    cmd = [sys.executable, "-m", "pip", "install", "--no-cache-dir", "-r", req]
    print(f"[*] {' '.join(cmd)}", flush=True)
    subprocess.check_call(cmd)
    print("[OK] Deps installed", flush=True)

def test_audioop():
    print("[*] Testing audioop...", flush=True)
    try:
        import audioop
        print(f"[OK] audioop: {getattr(audioop,'__file__','builtin/shim')}", flush=True)
        return True
    except ModuleNotFoundError:
        try:
            import audioop_lts as _a
            sys.modules['audioop'] = _a
            print("[FIX] Applied shim, now OK", flush=True)
            return True
        except ImportError:
            print("[ERR] audioop-lts missing, installing...", flush=True)
            install_deps()
            return test_audioop()

def run_web(port, prod=False):
    os.environ["PYTHONUNBUFFERED"] = "1"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ["PORT"] = str(port)

    if prod:
        print(f"""
╔════════════════════════════════════════════════╗
║  VOID-NUKE WEB - PROD / RENDER FREE TIER     ║
║  1 worker / 2 threads ~250MB RAM             ║
║  All 39 commands + permissions panel         ║
╠════════════════════════════════════════════════╣
║  Bind: 0.0.0.0:{port}                              ║
║  Health: /health  •  Logs: /api/logs           ║
║  Perms: /api/permissions                      ║
╚════════════════════════════════════════════════╝
""", flush=True)
        try:
            import gunicorn.app.wsgiapp as wsgi
            sys.argv = [
                "gunicorn", "app:app",
                "--workers", "1", "--threads", "2",
                "--timeout", "120",
                "--bind", f"0.0.0.0:{port}",
                "--worker-class", "gthread",
                "--log-level", "info",
                "--preload",
            ]
            wsgi.run()
        except ImportError:
            print("[WARN] gunicorn not found, fallback dev", flush=True)
            run_web(port, prod=False)
    else:
        print(f"""
╔════════════════════════════════════════════════╗
║  VOID-NUKE WEB v1.0.0 - FIXED + FULL SET     ║
║  Original: github.com/v0id4real/Void-Nuke    ║
║  512MB / 0.1 CPU / Permissions Panel / 39cmd ║
╠════════════════════════════════════════════════╣
║  Web UI:  http://0.0.0.0:{port:<5}                ║
║  Health:  http://0.0.0.0:{port}/health           ║
║  API:     /api/action, /api/permissions       ║
║  CLI:     python run.py --cli --help         ║
╚════════════════════════════════════════════════╝
""", flush=True)
        try:
            from app import app
            print("[OK] App imported, starting Flask...", flush=True)
        except Exception as e:
            print(f"[ERR] Import failed: {e}", flush=True)
            if "audioop" in str(e).lower():
                test_audioop()
                from app import app
        app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)

def run_cli(remaining_args):
    print("[*] Launching CLI command runner (all 39 cmds)...", flush=True)
    # Pass through to command_runner.py
    import command_runner
    # Simulate argv for command_runner
    sys.argv = ["command_runner.py"] + remaining_args
    import asyncio
    # Need to run main
    try:
        # command_runner already has asyncio.run(main) in __main__, we import and run manually
        from command_runner import main as cli_main
        asyncio.run(cli_main())
    except Exception as e:
        print(f"[ERR] CLI failed: {e}", flush=True)
        import traceback
        traceback.print_exc()

def extract_cli_args():
    """Extract args after --cli flag manually to avoid argparse confusion"""
    if "--cli" not in sys.argv:
        return []
    idx = sys.argv.index("--cli")
    cli_args = sys.argv[idx+1:]
    # Remove leading -- if present
    if cli_args and cli_args[0] == "--":
        cli_args = cli_args[1:]
    return cli_args

if __name__ == "__main__":
    # Manual CLI extraction before argparse to allow --list etc after --cli
    cli_mode = "--cli" in sys.argv
    cli_extra = extract_cli_args() if cli_mode else []

    parser = argparse.ArgumentParser(description="VOID-NUKE WEB Runner - Web UI + CLI + Fixed")
    parser.add_argument("--prod", action="store_true", help="Production gunicorn (Render)")
    parser.add_argument("--install", action="store_true", help="Force reinstall deps")
    parser.add_argument("--fix", action="store_true", help="Test audioop fix only")
    parser.add_argument("--port", type=int, default=None, help="Port (default $PORT or 10000)")
    parser.add_argument("--cli", action="store_true", help="Run CLI command runner instead of web UI - all args after --cli passed to CLI")
    parser.add_argument("--web", action="store_true", help="Force web mode (default)")

    # If CLI mode, parse only known web args, ignore rest
    if cli_mode:
        args, _ = parser.parse_known_args()
    else:
        args = parser.parse_args()

    port = args.port or int(os.environ.get("PORT", "10000"))

    check_python()

    if args.fix:
        test_audioop()
        sys.exit(0)

    if args.install:
        install_deps()
    else:
        try:
            import flask, discord
            import audioop
        except ImportError as e:
            print(f"[*] Missing {e}, auto-installing...", flush=True)
            install_deps()
            test_audioop()

    # Clean pycache
    try:
        import pathlib, shutil
        for p in pathlib.Path(".").rglob("__pycache__"):
            shutil.rmtree(p, ignore_errors=True)
    except:
        pass

    if cli_mode:
        run_cli(cli_extra)
    else:
        run_web(port, prod=args.prod)
