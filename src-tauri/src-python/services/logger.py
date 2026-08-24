"""
Logger.py (Refactored)
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


def setup_logger(name: str) -> logging.Logger:
    """
    Configures and returns a standardized logger instance.

    [PARAMETERS]
        name: str
            The name of the logger, typically the module name.
    """

    # 1. Create a logger with the specified name
    logger = logging.getLogger(name)

    # Only add handlers if they haven't been added yet to avoid duplicate logs
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )

        # File handler (saves logs to disk)
        file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        # Stream handler (sends logs to stderr so Tauri/CLI can catch them)
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    # 2. Return the configured logger instance
    return logger
