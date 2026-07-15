#!/usr/bin/env python3
"""
VOID-NUKE WEB v4 - Multi-threaded Unified Runner
- audioop fix
- Web UI with gthread (4 threads)
- CLI runner with multi-threading
- All 39 commands perfected

Usage:
  python run.py                          -> Web UI http://0.0.0.0:10000 (multi-threaded)
  python run.py --prod                   -> Prod gunicorn 1w/4threads (Render free tier 512MB)
  python run.py --cli --list             -> CLI list
  python run.py --cli --token TOKEN --guild ID --action nuke --confirm
  python run.py --threads 8              -> Custom thread count for executors
"""

# audioop fix MUST be first
import sys
try:
    import audioop
except ModuleNotFoundError:
    try:
        import audioop_lts as audioop
        sys.modules['audioop']=audioop
        print("[FIX] Python 3.13 - audioop -> audioop-lts shim", flush=True)
    except ImportError:
        print("[INFO] audioop missing - will install", flush=True)

import os, subprocess, argparse, threading
from concurrent.futures import ThreadPoolExecutor

def check_python():
    print(f"[INFO] Python {sys.version} | Threads {threading.active_count()}", flush=True)
    if sys.version_info < (3,8):
        print("[ERR] Python 3.8+ required"); sys.exit(1)
    if sys.version_info >= (3,13):
        print("[WARN] Python 3.13 - using shim, recommended 3.11 for Render", flush=True)

def install_deps():
    print("[*] Installing deps (multi-threaded optimized)...", flush=True)
    req=os.path.join(os.path.dirname(__file__),"requirements.txt")
    try:
        with open(req,'r') as f: content=f.read()
        if 'audioop' not in content.lower():
            with open(req,'a') as f: f.write("\naudioop-lts==0.2.1\n")
    except: pass
    cmd=[sys.executable,"-m","pip","install","--no-cache-dir","-r",req]
    print(f"[*] {' '.join(cmd)}", flush=True)
    subprocess.check_call(cmd)
    print("[OK] Deps installed", flush=True)

def test_audioop():
    print("[*] Testing audioop + threading...", flush=True)
    try:
        import audioop
        print(f"[OK] audioop: {getattr(audioop,'__file__','shim')}", flush=True)
        # Test threading
        def _t(): return True
        with ThreadPoolExecutor(max_workers=2) as ex:
            f=ex.submit(_t)
            print(f"[OK] ThreadPoolExecutor works: {f.result()}", flush=True)
        return True
    except ModuleNotFoundError:
        try:
            import audioop_lts as _a
            sys.modules['audioop']=_a
            print("[FIX] Applied shim", flush=True)
            return True
        except ImportError:
            install_deps()
            return test_audioop()

def run_web(port, prod=False, threads=4):
    os.environ["PYTHONUNBUFFERED"]="1"
    os.environ["PYTHONDONTWRITEBYTECODE"]="1"
    os.environ["PORT"]=str(port)
    os.environ["VOID_THREADS"]=str(threads)

    if prod:
        print(f"""
╔════════════════════════════════════════════════╗
║  VOID-NUKE WEB v4 - PROD MULTI-THREADED      ║
║  Gunicorn 1 worker / {threads} gthreads ~300MB      ║
║  + Command Executor 4 threads + Blocking 2   ║
║  All 39 cmds perfected + perms panel         ║
╠════════════════════════════════════════════════╣
║  Bind: 0.0.0.0:{port}  Threads: {threads}                ║
╚════════════════════════════════════════════════╝
""", flush=True)
        try:
            import gunicorn.app.wsgiapp as wsgi
            sys.argv=[
                "gunicorn","app:app",
                "--workers","1",
                "--threads",str(threads),
                "--timeout","120",
                "--bind",f"0.0.0.0:{port}",
                "--worker-class","gthread",
                "--log-level","info",
                "--preload",
            ]
            wsgi.run()
        except ImportError:
            print("[WARN] gunicorn missing, fallback dev", flush=True)
            run_web(port, prod=False, threads=threads)
    else:
        print(f"""
╔════════════════════════════════════════════════╗
║  VOID-NUKE WEB v4 - MULTI-THREADED FIXED     ║
║  Original: github.com/v0id4real/Void-Nuke    ║
║  Flask threaded + 4 cmd threads + 2 blocking ║
║  39 cmds + perms + execution fixed           ║
╠════════════════════════════════════════════════╣
║  Web UI:  http://0.0.0.0:{port:<5}  MT:{threads}          ║
║  Health:  /api/health → threads, tasks        ║
║  Per ms:  /api/permissions + /api/threads     ║
║  CLI:     python run.py --cli --list         ║
╚════════════════════════════════════════════════╝
""", flush=True)
        try:
            from app import app
            print(f"[OK] App imported | Main thread {threading.current_thread().name} | Executor {threads} threads", flush=True)
        except Exception as e:
            print(f"[ERR] Import failed {e}", flush=True)
            if "audioop" in str(e).lower():
                test_audioop()
                from app import app
        app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)

def extract_cli_args():
    if "--cli" not in sys.argv: return []
    idx=sys.argv.index("--cli")
    cli_args=sys.argv[idx+1:]
    if cli_args and cli_args[0]=="--": cli_args=cli_args[1:]
    return cli_args

def run_cli(remaining_args, threads=4):
    print(f"[*] CLI runner MT threads={threads} args={remaining_args}", flush=True)
    sys.argv=["command_runner.py"]+remaining_args
    # Pass threads via env
    os.environ["VOID_THREADS"]=str(threads)
    from command_runner import main as cli_main
    import asyncio
    asyncio.run(cli_main())

if __name__=="__main__":
    cli_mode="--cli" in sys.argv
    parser=argparse.ArgumentParser(description="VOID-NUKE WEB v4 Multi-threaded")
    parser.add_argument("--prod", action="store_true", help="Production gunicorn Render")
    parser.add_argument("--install", action="store_true", help="Force reinstall")
    parser.add_argument("--fix", action="store_true", help="Test audioop + threading")
    parser.add_argument("--port", type=int, default=None, help="Port default 10000")
    parser.add_argument("--cli", action="store_true", help="CLI mode, remaining args passed to CLI")
    parser.add_argument("--web", action="store_true", help="Force web")
    parser.add_argument("--threads", type=int, default=4, help="Thread count for executors (default 4, free tier safe 2-4)")

    if cli_mode:
        args,_=parser.parse_known_args()
        cli_extra=extract_cli_args()
    else:
        args=parser.parse_args()
        cli_extra=[]

    port=args.port or int(os.environ.get("PORT","10000"))
    threads=args.threads

    # Set thread env for bot_manager executors
    os.environ["VOID_THREADS"]=str(threads)

    check_python()

    if args.fix:
        test_audioop()
        # Test multi-threading
        print(f"[TEST] Main thread {threading.current_thread().name}")
        with ThreadPoolExecutor(max_workers=threads) as ex:
            futures=[ex.submit(lambda i=i: (threading.current_thread().name, i), i) for i in range(threads)]
            for f in futures:
                name,i=f.result()
                print(f"[TEST] Worker {name} task {i} OK")
        print("[OK] All MT tests passed")
        sys.exit(0)

    if args.install:
        install_deps()
    else:
        try:
            import flask, discord, audioop
        except ImportError as e:
            print(f"[*] Missing {e}, auto-install", flush=True)
            install_deps()
            test_audioop()

    try:
        import pathlib, shutil
        for p in pathlib.Path(".").rglob("__pycache__"):
            shutil.rmtree(p, ignore_errors=True)
    except: pass

    if cli_mode:
        run_cli(cli_extra, threads=threads)
    else:
        run_web(port, prod=args.prod, threads=threads)
