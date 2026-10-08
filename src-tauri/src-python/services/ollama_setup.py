"""Installs Ollama (the local script writer) with Ollama's own PowerShell installer, after the user agreed in the app."""

import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict

import httpx

INSTALL_COMMAND = "irm https://ollama.com/install.ps1 | iex"
OLLAMA_URL = "http://127.0.0.1:11434"


def server_up() -> bool:
    try:
        return httpx.get(OLLAMA_URL, timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


def _start_server() -> None:
    exe = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama app.exe"
    if exe.exists():
        subprocess.Popen([str(exe)], creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))


def install_ollama(_payload: Dict[str, Any] = None) -> Dict[str, Any]:
    if os.name != "nt":
        return {"success": False, "error": "Install Ollama from https://ollama.com/download."}
    if not server_up():
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", INSTALL_COMMAND],
            capture_output=True, encoding="utf-8", errors="replace", timeout=1800,
        )
        if result.returncode != 0:
            return {"success": False, "error": f"Ollama's installer failed:\n{(result.stderr or result.stdout)[-600:]}"}
    _start_server()
    deadline = time.time() + 60
    while time.time() < deadline and not server_up():
        time.sleep(2)
    return {"success": True, "running": server_up()}
