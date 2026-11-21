"""In-memory search-result cache with a TTL in simulated minutes and hit-rate / age statistics."""

from __future__ import annotations

from datetime import datetime
from typing import Any

NORMAL_TTL_MIN = 1.0
STALE_TTL_MIN = 24 * 60.0


class SearchCache:
    """Stores results by key. Entries expire lazily: an old entry is only ignored, not removed."""

    def __init__(self) -> None:
        self._entries: dict[Any, tuple[datetime, Any]] = {}
        self._hits = self._lookups = 0
        self._age_sum = 0.0

    def get(self, key: Any, now: datetime, ttl_minutes: float) -> tuple[Any, float] | None:
        """Return (value, age in minutes) if a fresh-enough entry exists, else None."""
        self._lookups += 1
        entry = self._entries.get(key)
        if entry is None:
            return None
        age = (now - entry[0]).total_seconds() / 60
        if age > ttl_minutes:
            return None
        self._hits += 1
        self._age_sum += age
        return entry[1], age

    def put(self, key: Any, value: Any, now: datetime) -> None:
        """Store `value` for `key` as of `now`."""
        self._entries[key] = (now, value)

    def clear(self) -> None:
        """Drop all entries and reset the statistics."""
        self._entries.clear()
        self.pop_window_stats()

    def pop_window_stats(self) -> dict[str, float]:
        """Hit rate and mean served-result age since the last call; resets the counters."""
        stats = {
            "cache_hit_rate": self._hits / self._lookups if self._lookups else 0.0,
            "cache_result_age_min": self._age_sum / self._hits if self._hits else 0.0,
        }
        self._hits = self._lookups = 0
        self._age_sum = 0.0
        return stats
