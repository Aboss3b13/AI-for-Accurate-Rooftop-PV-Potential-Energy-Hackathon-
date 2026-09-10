"""Free port 8000 from a previous SolarFit before starting a new one.

Reloading the browser cannot replace a running backend, so a stale server used
to end the launch with an instruction to go and close a window. It can simply be
closed here instead.

Only a confirmed SolarFit is ever stopped. Whatever else happens to be holding
the port belongs to someone else, and the launcher still steps aside for it.
"""

import json
import os
import platform
import re
import signal
import socket
import subprocess
import time
import urllib.request

WINDOWS = platform.system() == "Windows"
LISTENING = re.compile(r"^\s*TCP\s+\S+:(\d+)\s+\S+\s+LISTENING\s+(\d+)\s*$", re.M)
STOP_TIMEOUT_S = 12.0


def running_app(port: int, timeout: float = 1.5) -> dict | None:
    """Whatever answers /api/health on this port, if anything does."""
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/health", timeout=timeout
        ) as response:
            return json.load(response)
    except Exception:
        return None


def parse_windows_listeners(output: str, port: int) -> list[int]:
    """Process ids listening on this port, from `netstat -ano` output."""
    return sorted({int(pid) for listening, pid in LISTENING.findall(output)
                   if int(listening) == port})


def parse_posix_listeners(output: str) -> list[int]:
    """Process ids from `lsof -t` output."""
    pids = []
    for line in output.split():
        if line.strip().isdigit():
            pids.append(int(line))
    return sorted(set(pids))


def listeners(port: int) -> list[int]:
    """Which processes hold this port open."""
    try:
        if WINDOWS:
            result = subprocess.run(["netstat", "-ano", "-p", "TCP"],
                                    capture_output=True, text=True, timeout=15)
            return parse_windows_listeners(result.stdout, port)
        result = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True, text=True, timeout=15)
        return parse_posix_listeners(result.stdout)
    except (OSError, subprocess.SubprocessError):
        return []


def stop(pid: int) -> None:
    """Ask a process to end, then insist."""
    try:
        if WINDOWS:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, timeout=15)
            return
        os.kill(pid, signal.SIGTERM)
    except (OSError, subprocess.SubprocessError, ProcessLookupError):
        return


def force(pid: int) -> None:
    if WINDOWS:
        return
    try:
        os.kill(pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        return


def is_free(port: int) -> bool:
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        try:
            probe.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def wait_until_free(port: int, timeout: float = STOP_TIMEOUT_S) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_free(port):
            return True
        time.sleep(0.25)
    return is_free(port)


def replace_previous(port: int, app_name: str = "SolarFit", log=print) -> bool:
    """Close a previous instance of our own app so this one can take the port.

    Returns True when the port is ready to bind. False means something is still
    holding it, and the caller should say so rather than start anyway.
    """
    running = running_app(port)
    if running is None:
        return is_free(port)
    if running.get("app") != app_name:
        log(f"Port {port} is held by another application. Close it, then start "
            f"{app_name} again.")
        return False

    held = listeners(port)
    if not held:
        log(f"An older {app_name} is running on port {port} but its process "
            "could not be identified. Close its window, then start again.")
        return False

    log(f"Closing the previous {app_name} backend (process "
        + ", ".join(str(p) for p in held) + ")...")
    for pid in held:
        stop(pid)
    if wait_until_free(port, STOP_TIMEOUT_S / 2):
        return True
    for pid in held:
        force(pid)
    if wait_until_free(port):
        return True
    log(f"The previous {app_name} on port {port} did not close. Close its "
        "window, then start again.")
    return False
