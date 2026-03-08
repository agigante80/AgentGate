"""
Centralised logging configuration for AgentGate.

Call configure_logging() once at startup (before any logger.* calls).
"""
import gzip
import logging
import logging.handlers
import os
import pathlib
import shutil
import sys

_FMT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%dT%H:%M:%S"

# Rotate daily, keep 14 compressed backups
_WHEN = "midnight"
_BACKUP_COUNT = 14
_LOG_FILENAME = "agentgate.log"


def _parse_level(level_str: str) -> int:
    """Return a logging level int; falls back to INFO for unrecognised values."""
    level = getattr(logging, level_str.upper(), None)
    if not isinstance(level, int):
        logging.getLogger(__name__).warning(
            "Unknown LOG_LEVEL %r — defaulting to INFO", level_str
        )
        return logging.INFO
    return level


def _gz_namer(default_name: str) -> str:
    """Append .gz to the rotated log filename."""
    return default_name + ".gz"


def _gz_rotator(source: str, dest: str) -> None:
    """Compress the rotated log file with gzip and remove the original."""
    with open(source, "rb") as f_in, gzip.open(dest, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    os.remove(source)


def configure_logging(log_level: str = "INFO", log_dir: str = "") -> None:
    """
    Configure the root logger.

    Args:
        log_level: One of DEBUG, INFO, WARNING, ERROR (case-insensitive). Default INFO.
        log_dir:   Directory path for rotating log files. Empty = stdout only.
    """
    level = _parse_level(log_level)
    formatter = logging.Formatter(_FMT, datefmt=_DATEFMT)

    root = logging.getLogger()
    root.setLevel(level)

    # Remove any handlers added by earlier basicConfig calls
    root.handlers.clear()

    # Always log to stdout
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    if log_dir:
        log_path = pathlib.Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.TimedRotatingFileHandler(
            filename=log_path / _LOG_FILENAME,
            when=_WHEN,
            interval=1,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.namer = _gz_namer
        file_handler.rotator = _gz_rotator
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
