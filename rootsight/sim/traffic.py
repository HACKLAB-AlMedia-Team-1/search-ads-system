"""Organic traffic volume per market and hour, from the traffic profile with seeded noise."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from rootsight.sim.clock import day_type

DAILY_SESSIONS = {"US": 6000, "ES": 3000, "JP": 3000, "DE": 3000}
PLATFORM_SHARE = {"android": 0.45, "ios": 0.30, "web": 0.25}
NOISE = 0.05


class Traffic:
    """Hourly organic sessions: daily volume x hour weight x weekend multiplier x noise (+-5%)."""

    def __init__(self, profile: pd.DataFrame):
        self._rows = profile.set_index(["day_type", "hour"])

    def weight(self, ts: datetime) -> float:
        """Share of a day's traffic that falls into this hour (sums to 1 over a day)."""
        return float(self._rows.loc[(day_type(ts), ts.hour), "weight"])

    def organic_sessions(self, ts: datetime, market: str, rng: np.random.Generator) -> int:
        """Organic sessions of a market in the hour starting at `ts`."""
        row = self._rows.loc[(day_type(ts), ts.hour)]
        noise = rng.uniform(1 - NOISE, 1 + NOISE)
        return round(DAILY_SESSIONS[market] * row["weight"] * row["day_multiplier"] * noise)


def split_platforms(n: int, rng: np.random.Generator) -> dict[str, int]:
    """Split `n` sessions over android / ios / web."""
    counts = rng.multinomial(n, list(PLATFORM_SHARE.values()))
    return dict(zip(PLATFORM_SHARE, (int(c) for c in counts), strict=True))
