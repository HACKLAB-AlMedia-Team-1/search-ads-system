"""Simulated time helpers: one tick is one simulated hour."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta

HOUR = timedelta(hours=1)


def day_type(ts: datetime) -> str:
    """`weekend` for Saturday and Sunday, else `weekday`."""
    return "weekend" if ts.weekday() >= 5 else "weekday"


def hours(start: datetime, end: datetime) -> Iterator[datetime]:
    """Every hour start from `start` (inclusive) to `end` (exclusive)."""
    ts = start
    while ts < end:
        yield ts
        ts += HOUR
