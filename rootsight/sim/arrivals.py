"""Data arrival: which tables arrive complete, and the DQ1 case where search events arrive late."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from rootsight.sim import faults as fault_names
from rootsight.sim.faults import FaultRegistry

LATE_FRACTION = 0.35
DELAY_HOURS = 2
SEARCH_EVENT_COLUMNS = [
    "sessions", "searches", "zero_result_searches", "results_total", "searches_with_click", "clicks_top3",
    "sum_relevance10", "sum_ndcg10", "sum_first_exact_pos", "latency_ms_sum", "cart_unavailable_errors",
    "price_mismatch_clicks", "sum_click_position", "refinements", "bounces",
]  # fmt: skip


def search_events_fraction(faults: FaultRegistry, ts: datetime) -> float:
    """Share of this hour's search-event rows that has arrived when the hour closes (1.0 = complete)."""
    return LATE_FRACTION if faults.active(fault_names.SEARCH_EVENTS_LATE, ts) else 1.0


def degrade(facts: pd.DataFrame, fraction: float) -> pd.DataFrame:
    """Facts as first seen: only `fraction` of the search-event columns has arrived."""
    out = facts.copy()
    out[SEARCH_EVENT_COLUMNS] = out[SEARCH_EVENT_COLUMNS] * fraction
    return out


def arrival_records(ts: datetime, facts: pd.DataFrame, n_campaigns: int, fraction: float) -> list[dict]:
    """`data_arrivals` rows for the hour `ts`; a late hour gets a partial row now and the full row later."""
    expected = {"search_events": float(facts["searches"].sum()), "orders": float(facts["carts"].sum()),
                "ads": float(n_campaigns)}  # fmt: skip
    closed = ts + timedelta(hours=1)
    rows = [
        {"ts": ts, "table_name": name, "rows_expected": exp,
         "rows_received": exp * (fraction if name == "search_events" else 1.0), "arrived_at": closed}
        for name, exp in expected.items()
    ]  # fmt: skip
    if fraction < 1.0:
        rows.append({"ts": ts, "table_name": "search_events", "rows_expected": expected["search_events"],
                     "rows_received": expected["search_events"], "arrived_at": closed + timedelta(hours=DELAY_HOURS)})  # fmt: skip
    return rows
