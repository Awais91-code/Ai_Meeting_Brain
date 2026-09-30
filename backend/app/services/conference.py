"""Start only this installation's fixed Compose project; never accept shell input."""
import os
import subprocess
import threading
import time
from pathlib import Path

import requests
from app.config import settings

_lock = threading.Lock()
_starting = False
_error = None
_cached = (0, None)


def _network_reconfigure_flag():
    return Path(settings.data_dir).resolve() / "network" / "jitsi-reconfigure.flag"


def configured():
    return bool(settings.jitsi_require_auth and len(settings.jitsi_app_secret) >= 32
                and settings.jitsi_domain.split(":")[0].lower() != "meet.jit.si")


def status():
    global _cached
    if not configured():
        return {"state": "unconfigured", "message": "Meeting service needs its one-time setup.", "managed": settings.managed_jitsi}
    if _network_reconfigure_flag().exists():
        return {
            "state": "offline",
            "message": "Laptop network changed. Meeting service will refresh automatically when the host starts the meeting.",
            "managed": settings.managed_jitsi,
        }
    if time.monotonic() - _cached[0] < 3:
        return _cached[1]
    try:
        response = requests.get(f"https://{settings.jitsi_domain}/config.js", timeout=3,
                                verify=settings.jitsi_ca_bundle or True, allow_redirects=False)
        response.raise_for_status()
        if response.status_code != 200 or "config" not in response.text:
            raise requests.RequestException()
        result = {"state": "ready", "message": "Meeting service is ready."}
    except requests.exceptions.SSLError:
        result = {"state": "certificate_error", "message": "Meeting HTTPS certificate needs the one-time local setup."}
    except (requests.RequestException, OSError):
        result = {"state": "starting" if _starting else "offline",
                  "message": "Starting meeting service…" if _starting else (_error or "Meeting service is offline. An administrator can start it here.")}
    result["managed"] = settings.managed_jitsi
    _cached = (time.monotonic(), result)
    return result


def _start():
    global _starting, _error, _cached
    try:
        project = Path(settings.data_dir).resolve() / "jitsi"
        command = ["docker", "compose", "--project-directory", str(project), "up", "-d"]
        if _network_reconfigure_flag().exists():
            command.append("--force-recreate")
        subprocess.run(command,
                       check=True, capture_output=True, timeout=90,
                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        _network_reconfigure_flag().unlink(missing_ok=True)
    except (OSError, subprocess.SubprocessError):
        # Docker's raw output can contain configuration; return only an actionable message.
        _error = "Open Docker Desktop, wait until its engine is running, then retry Start meeting."
    finally:
        with _lock:
            _starting = False
            _cached = (0, None)


def start():
    global _starting, _error, _cached
    with _lock:
        if not _starting:
            _starting = True
            _error = None
            _cached = (0, None)
            threading.Thread(target=_start, daemon=True, name="meeting-service-start").start()
    return {"state": "starting", "message": "Starting meeting service…"}
