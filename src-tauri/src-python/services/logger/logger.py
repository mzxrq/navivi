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
        log_dir = Path("services/logger")
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / "app.log", encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        file_formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(logging.ERROR)
        console_formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

    return logger