"""One local process serves both FastAPI and the built React application."""

import os
import socket
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
import sys
import shutil
import subprocess

SHARE = "--ngrok" in sys.argv
TUNNEL_PROCESSES = []


def open_app(url):
    if SHARE:
        from scripts.ngrok_share import share
        try:
            url, process = share()
            if process:
                TUNNEL_PROCESSES.append(process)
            print("SolarFit public URL: " + url, flush=True)
        except RuntimeError as exc:
            print(str(exc), flush=True)
    if "--no-browser" not in sys.argv:
        webbrowser.open(url)

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))


def open_when_ready(url):
    for _ in range(90):
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=1) as response:
                if response.status == 200:
                    open_app(url)
                    return
        except Exception:
            time.sleep(0.5)


if __name__ == "__main__":
    import uvicorn

    frontend = ROOT / "frontend"
    built = frontend / "dist" / "index.html"
    inputs = list((frontend / "src").rglob("*")) + [frontend / "package-lock.json", frontend / "index.html"]
    if not built.exists() or any(p.is_file() and p.stat().st_mtime > built.stat().st_mtime for p in inputs):
        print("Building the updated SolarFit interface...")
        npm = shutil.which("npm.cmd") or shutil.which("npm")
        if not npm:
            print("Node.js is required to build this update. Run REBUILD_SOLARFIT.bat after installing Node.js.")
            sys.exit(1)
        if subprocess.run([npm, "run", "build"], cwd=frontend).returncode:
            sys.exit(1)

    port = 8000
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/health", timeout=1
        ) as response:
            import json

            data = json.load(response)
            if data.get("app") == "SolarFit":
                open_app(f"http://127.0.0.1:{port}")
                if TUNNEL_PROCESSES:
                    print("Keep this window open to share SolarFit. Ctrl+C stops this tunnel.")
                    try:
                        TUNNEL_PROCESSES[0].wait()
                    except KeyboardInterrupt:
                        TUNNEL_PROCESSES[0].terminate()
                sys.exit(0)
    except Exception:
        pass
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            print("Port 8000 is occupied. Close that app, then start SolarFit again.")
            sys.exit(1)
    threading.Thread(
        target=open_when_ready, args=(f"http://127.0.0.1:{port}",), daemon=True
    ).start()
    print(
        "SolarFit is starting at http://127.0.0.1:8000. Keep this window open. Ctrl+C stops it."
    )
    try:
        uvicorn.run("backend.main:app", host="127.0.0.1", port=port, log_level="info")
    finally:
        for process in TUNNEL_PROCESSES:
            if process.poll() is None:
                process.terminate()
