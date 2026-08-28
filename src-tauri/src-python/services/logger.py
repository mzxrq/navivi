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

# Define a clean log directory in your project
LOG_DIR = Path("./logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "app.log"


import logging
import sys
from pathlib import Path


def setup_logger(name: str):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)  # Keeps capturing info internally

    # Prevent adding duplicate handlers if setup is called multiple times
    if not logger.handlers:
        # 1. File Handler (Keeps saving everything to logs/app.log)
        log_dir = Path("logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / "app.log", encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        file_formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

        # 2. Console / Stream Handler (HIDDEN from terminal unless it's a WARNING or ERROR)
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(logging.ERROR)
        console_formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

    return logger
