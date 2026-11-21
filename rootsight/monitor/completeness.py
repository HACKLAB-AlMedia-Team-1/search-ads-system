"""Data completeness: which source tables have fully arrived, and which metrics depend on them."""

from __future__ import annotations

import functools
from datetime import datetime

import sqlglot
from sqlglot import exp

from rootsight.graph.graph import MetricSpec
from rootsight.sim.arrivals import SEARCH_EVENT_COLUMNS
from rootsight.store.db import Database

COMPLETE_RATIO = 0.9
ORDER_COLUMNS = {"carts", "checkouts", "orders", "revenue_eur"}
ADS_TABLE = "ads_hourly"


def arrival_ratios(db: Database, hour: datetime, as_of: datetime) -> dict[str, float]:
    """rows_received / rows_expected per source table for `hour`, as known at `as_of` (latest record wins)."""
    frame = db.df(
        """SELECT table_name, arg_max(rows_received, arrived_at) AS received, arg_max(rows_expected, arrived_at) AS expected
           FROM data_arrivals WHERE ts = ? AND arrived_at <= ? GROUP BY table_name""",
        [hour, as_of],
    )
    return {r.table_name: (r.received / r.expected if r.expected else 1.0) for r in frame.itertuples()}


def incomplete_tables(db: Database, hour: datetime, as_of: datetime) -> dict[str, float]:
    """Source tables whose rows for `hour` are less than 90% complete, with their ratio."""
    return {t: r for t, r in arrival_ratios(db, hour, as_of).items() if r < COMPLETE_RATIO}


def source_tables(spec: MetricSpec) -> frozenset[str]:
    """The arrival tables (`search_events`, `orders`, `ads`) a metric's SQL reads from."""
    return _tables_of(spec.sql)


@functools.cache
def _tables_of(sql: str) -> frozenset[str]:
    parsed = sqlglot.parse_one(f"SELECT {sql}")
    names = {t.name for t in parsed.find_all(exp.Table)}
    columns = {c.name for c in parsed.find_all(exp.Column)}
    found = {"ads"} if ADS_TABLE in names else set()
    if "fact_hourly" in names:
        found |= ({"search_events"} if columns & set(SEARCH_EVENT_COLUMNS) else set()) | (
            {"orders"} if columns & ORDER_COLUMNS else set()
        )
    return frozenset(found)


def is_scorable(spec: MetricSpec, incomplete: dict[str, float]) -> bool:
    """A metric is only scored when none of its source tables is incomplete."""
    return not (source_tables(spec) & set(incomplete))
