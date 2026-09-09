"""Reuse the existing SolarFit tunnel, or start the installed ngrok agent."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request
from dotenv import load_dotenv

DEFAULT_URL = "https://bernadette-nonfeeling-transparently.ngrok-free.dev"


def tunnel_url():
    try:
        with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=2) as response:
            tunnels = json.load(response).get("tunnels", [])
        for tunnel in tunnels:
            if tunnel.get("config", {}).get("addr", "").rstrip("/") in {
                "http://localhost:8000", "http://127.0.0.1:8000", "localhost:8000", "127.0.0.1:8000"}:
                if tunnel.get("public_url", "").startswith("https://"):
                    return tunnel["public_url"]
    except (OSError, ValueError):
        pass
    return None


def share():
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    existing = tunnel_url()
    if existing:
        return existing, None
    executable = shutil.which("ngrok")
    if not executable:
        raise RuntimeError("Install ngrok and configure its authtoken once, then run START_SOLARFIT_NGROK.bat again.")
    url = os.environ.get("SOLARFIT_PUBLIC_URL", DEFAULT_URL)
    cache = Path(".cache")
    cache.mkdir(exist_ok=True)
    log = cache / "ngrok-agent.log"
    with log.open("a", encoding="utf-8") as output:
        process = subprocess.Popen([executable, "http", "--url=" + url, "http://127.0.0.1:8000"],
            stdout=output, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    for _ in range(40):
        active = tunnel_url()
        if active:
            return active, process
        if process.poll() is not None:
            break
        time.sleep(.5)
    if process.poll() is None:
        process.terminate()
    raise RuntimeError("ngrok did not become ready. Check .cache/ngrok-agent.log and your ngrok account configuration.")
