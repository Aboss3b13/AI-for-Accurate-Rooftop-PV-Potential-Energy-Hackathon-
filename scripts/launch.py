"""One local process serves both FastAPI and the built React application."""

import os
import socket
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))


def open_when_ready(url):
    for _ in range(90):
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=1) as response:
                if response.status == 200:
                    webbrowser.open(url)
                    return
        except Exception:
            time.sleep(0.5)


if __name__ == "__main__":
    import uvicorn

    port = 8000
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/health", timeout=1
        ) as response:
            import json

            data = json.load(response)
            if data.get("app") == "SolarFit":
                webbrowser.open(f"http://127.0.0.1:{port}")
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
    uvicorn.run("backend.main:app", host="127.0.0.1", port=port, log_level="info")
