#!/usr/bin/env python3
"""
BitForensics native desktop app.
Starts the API in-process and opens a real OS window (not a browser tab).
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if (ROOT / "backend").is_dir():
    APP_ROOT = ROOT
elif (ROOT / "app" / "backend").is_dir():
    APP_ROOT = ROOT / "app"
else:
    cand = ROOT.parent / "Resources" / "app"
    APP_ROOT = cand if (cand / "backend").is_dir() else ROOT

VENV = APP_ROOT / ".venv"
REQ = APP_ROOT / "requirements.txt"
PORT = int(os.environ.get("PORT", "8765"))  # dedicated desktop port
HOST = "127.0.0.1"
URL = f"http://{HOST}:{PORT}"


def _venv_python() -> Path:
    if sys.platform == "win32":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def _ensure_deps() -> None:
    """Install into venv if needed; re-exec under venv python for a clean env."""
    os.chdir(APP_ROOT)
    sys.path.insert(0, str(APP_ROOT))
    py = _venv_python()
    marker = VENV / ".desktop-ok"
    need = not py.exists() or not marker.exists()

    if need:
        if not py.exists():
            print("Creating app environment (first launch)…")
            subprocess.check_call([sys.executable, "-m", "venv", str(VENV)], cwd=str(APP_ROOT))
            py = _venv_python()
        print("Installing packages (internet once)…")
        subprocess.check_call([str(py), "-m", "pip", "install", "--upgrade", "pip"], cwd=str(APP_ROOT))
        subprocess.check_call([str(py), "-m", "pip", "install", "-r", str(REQ)], cwd=str(APP_ROOT))
        # desktop UI dependency
        subprocess.check_call([str(py), "-m", "pip", "install", "pywebview>=5.0"], cwd=str(APP_ROOT))
        marker.write_text("ok\n", encoding="utf-8")

    # Re-exec inside venv so imports resolve
    if Path(sys.executable).resolve() != py.resolve():
        os.execv(str(py), [str(py), str(Path(__file__).resolve()), *sys.argv[1:]])


def _port_open() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=0.3):
            return True
    except OSError:
        return False


def _start_server() -> None:
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=HOST,
        port=PORT,
        reload=False,
        log_level="warning",
    )


def _wait_ready(timeout: float = 45.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_open():
            return True
        time.sleep(0.2)
    return False


def main() -> int:
    os.environ["PORT"] = str(PORT)
    os.environ["BITFORENSICS_RELOAD"] = "0"
    _ensure_deps()

    # After re-exec we are in venv
    os.chdir(APP_ROOT)
    sys.path.insert(0, str(APP_ROOT))

    if not _port_open():
        t = threading.Thread(target=_start_server, name="bitforensics-api", daemon=True)
        t.start()
        if not _wait_ready():
            _fail("Could not start BitForensics server.")
            return 1

    try:
        import webview
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pywebview>=5.0"])
        import webview

    window = webview.create_window(
        title="BitForensics",
        url=URL,
        width=1440,
        height=900,
        min_size=(1024, 680),
        confirm_close=False,
        background_color="#0f1419",
    )
    webview.start()
    return 0


def _fail(msg: str) -> None:
    print(msg)
    if sys.platform == "darwin":
        try:
            subprocess.run(
                ["osascript", "-e", f'display dialog "{msg}" buttons {{"OK"}} default button 1 with title "BitForensics"'],
                check=False,
            )
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
