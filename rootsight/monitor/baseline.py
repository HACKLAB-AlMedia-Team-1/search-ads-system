"""What is normal: the median of the same hour on recent comparable days, with a robust spread."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

import numpy as np
import pandas as pd
import sqlglot
from sqlglot import exp

from rootsight.graph.graph import MetricSpec
from rootsight.sim.clock import day_type

DAYS = 7
MIN_SAMPLES = 3
MAD_TO_SIGMA = 1.4826
STD_WEIGHT = 0.5
MONEY_UNIT = 100.0
RARE_EVENTS = 2.0
TINY = 1e-9


@dataclass(frozen=True)
class Baseline:
    """Expected value and spread for one metric, segment and hour; `n` is the number of days used."""

    expected: float
    spread: float
    n: int


def denominator_spec(spec: MetricSpec) -> MetricSpec | None:
    """For a ratio metric `A / NULLIF(B, 0)`: a spec that computes B (its volume), else None."""
    node = sqlglot.parse_one(f"SELECT {spec.sql}").expressions[0]
    if not (isinstance(node, exp.Div) and isinstance(node.expression, exp.Nullif)):
        return None
    _, table, where = spec.parts()
    sql = f"{node.expression.this.sql()} FROM {table}" + (f" WHERE {where}" if where else "")
    return replace(spec, name=f"{spec.name}#volume", sql=sql)


def spread_floor(spec: MetricSpec, median: float, mean: float, volume: float | None) -> float:
    """Smallest spread we accept: the sampling noise to expect at this volume (binomial, Poisson, ...)."""
    level = max(abs(median), abs(mean))
    floor = max(spec.rel_floor * level, spec.min_spread)
    if volume:
        if spec.unit == "share":
            p = min(max(median, mean, RARE_EVENTS / volume, 0.01), 0.99)
            floor = max(floor, float(np.sqrt(p * (1 - p) / volume)))
        else:
            floor = max(floor, spec.cv * level / float(np.sqrt(volume)))
    if spec.noise == "poisson":
        floor = max(floor, float(np.sqrt(level)), 1.0)
    elif spec.noise == "money":
        floor = max(floor, float(np.sqrt(level * MONEY_UNIT)), MONEY_UNIT)
    return max(floor, TINY)


def compute_baseline(
    history: pd.DataFrame, hour: datetime, spec: MetricSpec, volume: float | None = None
) -> Baseline | None:
    """Baseline for `hour` from `history` (columns ts, value): same hour, same day type, last 7 such days."""
    past = history[(history["ts"] < hour) & (history["ts"].dt.hour == hour.hour)]
    past = past[past["ts"].dt.day_of_week.map(lambda d: d >= 5) == (day_type(hour) == "weekend")]
    values = past.sort_values("ts")["value"].dropna().tail(DAYS).to_numpy()
    if len(values) < MIN_SAMPLES:
        return None
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    floor = spread_floor(spec, median, float(np.mean(values)), volume)
    return Baseline(median, max(MAD_TO_SIGMA * mad, STD_WEIGHT * float(np.std(values)), floor), len(values))


def robust_z(actual: float, expected: float, spread: float) -> float:
    """How many spreads `actual` is away from `expected`."""
    return (actual - expected) / spread
