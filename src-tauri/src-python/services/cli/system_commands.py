"""Facts about this PC the UI needs to judge things like whether a local model fits in memory (main.py system_info)."""

import os
from typing import Any, Dict


def system_info() -> Dict[str, Any]:
    import psutil

    memory = psutil.virtual_memory()
    return {
        "success": True,
        "ram_total_gb": round(memory.total / 2**30, 1),
        "ram_available_gb": round(memory.available / 2**30, 1),
        "cpu_threads": os.cpu_count() or 0,
    }
