"""The Microsoft Visual C++ runtime that PyTorch, GPSBabel and the voice engines import (vcruntime140, msvcp140).

A clean Windows PC does not have it, and the failure shows up far from the cause: a "VCRUNTIME140.dll not found" dialog from gpsbabel.exe, or a voice
engine whose `import torch` fails with "DLL load failed". `vc_runtime_installed` lets the app say so before it runs anything."""

import os
import subprocess
from pathlib import Path

_RUNTIME_KEY = r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"
_DLL_FAILURE = ("dll load failed", "winerror 126", "winerror 127", "vcruntime140", "msvcp140", "the specified module could not be found")


def vc_runtime_installed() -> bool:
    if os.name != "nt":
        return True
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _RUNTIME_KEY) as key:
            return winreg.QueryValueEx(key, "Installed")[0] == 1
    except OSError:
        return False


def looks_like_missing_runtime(output: str) -> bool:
    text = output.lower()
    return any(marker in text for marker in _DLL_FAILURE)


def missing_runtime_message(what: str) -> str:
    """Said before anything big is downloaded: PyTorch cannot load without the runtime."""
    if vc_runtime_installed():
        return ""
    return f"{what} needs the Microsoft Visual C++ runtime, which this PC does not have. Install it from the prompt in Navivi or from Settings > Setup, then try again."


def import_failure(python: Path, code: str, what: str) -> str:
    """Why `python -c code` fails, in words the user can act on; empty when it works."""
    check = subprocess.run([str(python), "-c", code], capture_output=True, encoding="utf-8", errors="replace")
    if check.returncode == 0:
        return ""
    detail = (check.stderr or check.stdout).strip()[-500:]
    if looks_like_missing_runtime(detail) and not vc_runtime_installed():
        return f"{missing_runtime_message(what)}\n{detail}"
    return f"The packages installed, but {what} could not be imported:\n{detail}"
