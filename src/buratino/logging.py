"""Logging setup."""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger


def configure_logging(level: str = "INFO", *, log_file: Path | None = None) -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        level=level,
        colorize=True,
        format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | {message}",
    )
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            log_file,
            level=level,
            colorize=False,
            mode="w",
            format="{time:HH:mm:ss} | {level:<8} | {message}",
        )
