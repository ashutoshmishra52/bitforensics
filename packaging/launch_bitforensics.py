#!/usr/bin/env python3
"""
BitForensics desktop launcher.
- Creates venv on first run if missing
- Starts FastAPI (no reload)
- Opens the browser to http://localhost:8000
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if (ROOT / "backend").is_dir():
    APP_ROOT = ROOT
elif (ROOT / "app" / "backend").is_dir():
    APP_ROOT = ROOT / "app"
else:
    # Inside .app: Contents/MacOS/… → Resources/app
    cand = ROOT.parent / "Resources" / "app"
    APP_ROOT = cand if (cand / "backend").is_dir() else ROOT

VENV = APP_ROOT / ".venv"
REQ = APP_ROOT / "requirements.txt"
PORT = int(os.environ.get("PORT", "8000"))
HOST = os.environ.get("HOST", "127.0.0.1")
URL = f"http://{HOST}:{PORT}"


def _py() -> Path:
    if sys.platform == "win32":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def _ensure_venv() -> Path:
    py = _py()
    if py.exists():
        return py
    print("First launch: creating virtual environment…")
    subprocess.check_call([sys.executable, "-m", "venv", str(VENV)], cwd=str(APP_ROOT))
    py = _py()
    print("Installing Python packages (needs internet once)…")
    subprocess.check_call([str(py), "-m", "pip", "install", "--upgrade", "pip"], cwd=str(APP_ROOT))
    subprocess.check_call([str(py), "-m", "pip", "install", "-r", str(REQ)], cwd=str(APP_ROOT))
    print("Setup complete.")
    return py


def _port_open() -> bool:
    import socket
    try:
        with socket.create_connection((HOST if HOST != "0.0.0.0" else "127.0.0.1", PORT), timeout=0.4):
            return True
    except OSError:
        return False


def main() -> int:
    os.chdir(APP_ROOT)
    os.environ["PORT"] = str(PORT)
    os.environ["BITFORENSICS_RELOAD"] = "0"
    sys.path.insert(0, str(APP_ROOT))

    if _port_open():
        print(f"Already running at {URL}")
        webbrowser.open(URL)
        return 0

    py = _ensure_venv()
    env = os.environ.copy()
    env["PORT"] = str(PORT)
    env["BITFORENSICS_RELOAD"] = "0"

    log_dir = APP_ROOT / "data"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "launcher.log"
    log_f = open(log_path, "a", encoding="utf-8")
    log_f.write(f"\n--- launch {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
    log_f.flush()

    proc = subprocess.Popen(
        [str(py), str(APP_ROOT / "run.py")],
        cwd=str(APP_ROOT),
        env=env,
        stdout=log_f,
        stderr=subprocess.STDOUT,
    )

    for _ in range(60):
        if proc.poll() is not None:
            print(f"Server exited early. See {log_path}")
            return 1
        if _port_open():
            break
        time.sleep(0.35)
    else:
        print(f"Timed out waiting for server. See {log_path}")
        return 1

    print(f"BitForensics ready → {URL}")
    webbrowser.open(URL)

    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
