"""
Central log file for all attack activity.

Every attack — one-shot or persistent — writes through this logger so
investigators have a single chronological record of what happened.
"""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "attacks.log"

_configured = False


def get_attack_logger(name: str) -> logging.Logger:
    """
    Return a logger that writes to logs/attacks.log (rotating) and stdout.
    Idempotent — safe to call from anywhere.
    """
    global _configured

    logger = logging.getLogger(name)

    if not _configured:
        LOG_DIR.mkdir(parents=True, exist_ok=True)

        fmt = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        file_handler = RotatingFileHandler(
            LOG_FILE, maxBytes=2_000_000, backupCount=5
        )
        file_handler.setFormatter(fmt)

        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(fmt)

        root = logging.getLogger("attack")
        root.setLevel(logging.INFO)
        root.addHandler(file_handler)
        root.addHandler(stream_handler)
        root.propagate = False

        _configured = True

    return logger


def read_log_tail(n: int = 100) -> list:
    """Return the last n lines of the attack log (for API / debugging)."""
    if not LOG_FILE.exists():
        return []
    with LOG_FILE.open() as f:
        lines = f.readlines()
    return [line.rstrip("\n") for line in lines[-n:]]