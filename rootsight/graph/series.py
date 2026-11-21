"""Compute a metric's values from the database for a time window and an optional segment."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

import pandas as pd

from rootsight.graph.graph import MetricSpec
from rootsight.store.db import Database

COLUMN_MAP = {"component_hourly": {"market": "scope"}}


def column(table: str, dim: str) -> str:
    """The real column behind a dimension name in a table (e.g. `market` is `scope` in component rows)."""
    return COLUMN_MAP.get(table, {}).get(dim, dim)


def _run(
    db: Database,
    spec: MetricSpec,
    start: datetime,
    end: datetime,
    segment: Mapping[str, str] | None,
    by: Sequence[str],
    hourly: bool,
) -> pd.DataFrame:
    expr, table, where = spec.parts()
    if unknown := [d for d in by if d not in spec.dims]:
        raise ValueError(f"{spec.name} cannot be split by {unknown}")
    conditions, params = ["ts >= ?", "ts < ?"], [start, end]
    if where:
        conditions.append(f"({where})")
    for dim, value in (segment or {}).items():
        if dim in spec.dims:
            conditions.append(f"{column(table, dim)} = ?")
            params.append(value)
    group = (["ts"] if hourly else []) + [column(table, d) for d in by]
    select = (["ts"] if hourly else []) + [f"{column(table, d)} AS {d}" for d in by] + [f"{expr} AS value"]
    sql = f"SELECT {', '.join(select)} FROM {table} WHERE {' AND '.join(conditions)}"
    if group:
        sql += f" GROUP BY {', '.join(group)} ORDER BY {', '.join(group)}"
    frame = db.df(sql, params)
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    return frame


def metric_series(
    db: Database,
    spec: MetricSpec,
    start: datetime,
    end: datetime,
    segment: Mapping[str, str] | None = None,
    by: Sequence[str] = (),
) -> pd.DataFrame:
    """Hourly values of a metric (columns: ts, the `by` dimensions, value) for `start <= ts < end`."""
    return _run(db, spec, start, end, segment, by, hourly=True)


def metric_total(
    db: Database,
    spec: MetricSpec,
    start: datetime,
    end: datetime,
    segment: Mapping[str, str] | None = None,
    by: Sequence[str] = (),
) -> pd.DataFrame:
    """The metric computed over the whole window (not per hour), optionally split by `by` dimensions."""
    return _run(db, spec, start, end, segment, by, hourly=False)
