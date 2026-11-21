"""Logging setup."""

from __future__ import annotations

import logging


def setup_logging(level: int | str = logging.INFO) -> None:
    """Configure the root logger with a plain-English timestamped format."""
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
