"""Validate the metric graph against history: formulas hold, dimensions exist, causes co-move."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from rootsight.graph.graph import MetricGraph
from rootsight.graph.series import column, metric_series
from rootsight.store.db import Database

FORMULA_TOLERANCE = 0.01
CAUSAL_MIN_R = 0.3
MAX_LAG_HOURS = 2


@dataclass(frozen=True)
class Check:
    """Result of one validation check."""

    kind: str
    subject: str
    passed: bool
    detail: str
    value: float | None = None


def _combine(role_values: dict[str, list[pd.Series]]) -> pd.Series:
    if "addend" in role_values:
        return sum(role_values["addend"])
    if "numerator" in role_values:
        return role_values["numerator"][0] / role_values["denominator"][0].replace(0, np.nan)
    out = role_values["factor"][0]
    for series in role_values["factor"][1:]:
        out = out * series
    return out


def validate_formulas(graph: MetricGraph, db: Database, end: datetime, days: int = 7) -> list[Check]:
    """Recompute every formula target from its inputs; pass if the median relative error is below 1%."""
    start, checks = end - timedelta(days=days), []
    targets = {t for _, t, d in graph.graph.edges(data=True) if d["type"] == "formula"}
    for target in sorted(targets):
        inputs = graph.formula_inputs(target)
        specs = [graph.metric(target), *(graph.metric(i["metric"]) for i in inputs)]
        dims = [d for d in graph.metric(target).dims if all(d in s.dims for s in specs)]
        key = ["ts", *dims]
        actual = metric_series(db, specs[0], start, end, by=dims).set_index(key)["value"]
        roles: dict[str, list[pd.Series]] = {}
        for item in inputs:
            frame = metric_series(db, graph.metric(item["metric"]), start, end, by=dims)
            roles.setdefault(item["role"], []).append(frame.set_index(key)["value"].reindex(actual.index))
        error = ((_combine(roles) - actual).abs() / actual.abs().replace(0, np.nan)).dropna()
        median = float(error.median()) if len(error) else float("nan")
        checks.append(
            Check(
                "formula",
                target,
                bool(median < FORMULA_TOLERANCE),
                f"median error {median:.4%} on {len(error)} rows",
                median,
            )
        )
    return checks


def validate_dims(graph: MetricGraph, db: Database) -> list[Check]:
    """Every dimension a metric declares must exist as a column of its source table."""
    checks = []
    for spec in graph.specs.values():
        _, table, _ = spec.parts()
        have = set(db.df(f"SELECT * FROM {table} LIMIT 0").columns)
        missing = [d for d in spec.dims if column(table, d) not in have]
        checks.append(
            Check(
                "dims", spec.name, not missing, f"missing columns {missing}" if missing else "all dims exist"
            )
        )
    return checks


def check_causes(graph: MetricGraph, db: Database, end: datetime, days: int = 7) -> list[Check]:
    """Lagged correlation (0-2 h, cause leading) of each may_be_caused_by pair; for display only."""
    start, checks = end - timedelta(days=days), []
    cache: dict[str, pd.Series] = {}

    def series(name: str) -> pd.Series:
        if name not in cache:
            cache[name] = metric_series(db, graph.metric(name), start, end).set_index("ts")["value"]
        return cache[name]

    for cause, effect, d in graph.graph.edges(data=True):
        if d["type"] != "may_be_caused_by":
            continue
        a, b = series(cause), series(effect)
        best = max(
            ((a.shift(lag).corr(b), lag) for lag in range(MAX_LAG_HOURS + 1)),
            key=lambda p: abs(np.nan_to_num(p[0])),
        )
        r = float(np.nan_to_num(best[0]))
        checks.append(
            Check("causal", f"{cause}->{effect}", abs(r) >= CAUSAL_MIN_R, f"r={r:.2f} at lag {best[1]}h", r)
        )
    return checks
