"""
Centralised logging utility.

All modules should use:
    from utils.logger import get_logger
    logger = get_logger(__name__)

Logs are written to both stdout and a global log.log file.
"""

import logging
import sys
from pathlib import Path
from typing import Optional

from config import settings

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Ensure logs directory exists
_LOGS_DIR = Path(__file__).parent.parent / "logs"
_LOGS_DIR.mkdir(exist_ok=True)
_LOG_FILE = _LOGS_DIR / "log.log"


def _build_stream_handler() -> logging.StreamHandler:
    """Create a stream handler for stdout logging."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    return handler


def _build_file_handler() -> logging.FileHandler:
    """Create a file handler for persistent logging to log.log."""
    handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    return handler


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    Return a logger that writes to both stdout and logs/log.log.

    Standard context fields supported via extra={...} on every log call:
        request_id, audit_id, task_id, service, worker_id, phase

    Usage:
        logger = get_logger(__name__)
        logger.info("msg", extra={"audit_id": "...", "phase": "discovery"})
    """
    logger = logging.getLogger(name or "pattern_proof")
    if not logger.handlers:
        logger.addHandler(_build_stream_handler())
        logger.addHandler(_build_file_handler())
    logger.setLevel(getattr(logging, settings.log_level.upper(), logging.DEBUG))
    logger.propagate = False
    return logger