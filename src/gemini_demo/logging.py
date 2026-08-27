"""Application logging."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

CHINA_TIMEZONE = timezone(timedelta(hours=8))
LOG_LINE_FORMAT = "[%(asctime)s +08:00] [%(levelname)s] [%(name)s] - %(message)s"


class ChinaTimeFormatter(logging.Formatter):
    """Format timestamps in UTC+08:00."""

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        """Return the record time in the configured fixed timezone."""
        timestamp = datetime.fromtimestamp(record.created, tz=CHINA_TIMEZONE)
        return timestamp.strftime(datefmt or "%Y-%m-%d %H:%M:%S")


def configure_logging(log_directory: Path, verbose: bool = False) -> logging.Logger:
    """Configure console and daily persistent log output."""
    log_directory.mkdir(parents=True, exist_ok=True)
    current_date = datetime.now(CHINA_TIMEZONE).strftime("%Y-%m-%d")
    formatter = ChinaTimeFormatter(LOG_LINE_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    daily_file = logging.FileHandler(
        log_directory / f"log_{current_date}.log", encoding="utf-8"
    )
    daily_file.setFormatter(formatter)

    logger = logging.getLogger("gemini_demo")
    logger.handlers.clear()
    logger.addHandler(console)
    logger.addHandler(daily_file)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.propagate = False
    return logger

