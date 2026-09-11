"""
Logging Service (logger.py)
---------------------------------------------------------------------------
This module provides a standardized logging setup for the application, ensuring
that logs are consistently formatted and directed
---------------------------------------------------------------------------
"""

import sys
import logging
from pathlib import Path

# [I/O] Log file path
LOG_FILE =  "app.log"


import logging
import sys
from pathlib import Path

# [Utility] Setup a logger with both file and console handlers
def setup_logger(name: str):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        # Resolved against THIS file's own location, not the process's CWD —
        # a relative "services/logger" path here used to write app.log
        # wherever the process happened to be launched from (the Tauri
        # sidecar never sets a working directory, and every entry point
        # relies on relative "src-python/main.py" args, so CWD is whatever
        # directory Tauri itself started in). That scattered app.log copies
        # across src-tauri/, the repo root, and even nested cwd's like
        # services/model/ — none of them the one actually being checked at
        # src-python/services/logger/app.log, which sat empty/stale while
        # logging silently landed elsewhere.
        log_dir = Path(__file__).resolve().parent
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / "app.log", encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        file_formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

        # [NOTE] [Core] Console only surfaces ERROR+ (stderr feeds Tauri's error stream/stdout JSON parsing),
        # while the file handler above keeps the full INFO+ history.
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(logging.ERROR)
        console_formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

    return logger