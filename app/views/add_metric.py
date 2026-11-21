"""Add a metric by name, description and SQL; the system places it in the graph and validates it in code."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from common import page

EXAMPLES = {
    "no_click_search_rate": (
        "Share of searches without a click",
        "(SUM(searches) - SUM(searches_with_click)) / NULLIF(SUM(searches), 0) FROM fact_hourly",
    ),
    "wasted_spend_share": (
        "Share of ad spend on sessions whose search found nothing to click",
        (
            "SUM(spend_eur * idle) / NULLIF(SUM(spend_eur), 0) FROM (SELECT a.ts, a.market, a.campaign_id, a.spend_eur, "
            "1 - f.clicked / NULLIF(f.searches, 0) AS idle FROM ads_hourly a JOIN (SELECT ts, market, "
            "SUM(searches_with_click) AS clicked, SUM(searches) AS searches FROM fact_hourly WHERE source = 'paid' "
            "GROUP BY ts, market) f ON a.ts = f.ts AND a.market = f.market) AS paid_idle"
        ),
    ),
}
BLANK = "Write my own"

rt, palette = page()
st.title("Add a metric")
st.markdown(
    "Give only a **name**, a **description** and the **SQL**. You do not say where it belongs: the system reads the SQL, proposes the links "
    "to existing metrics, checks each link against 7 days of history, and starts monitoring the metric at the next hour."
)
example = st.segmented_control("Start from", [*EXAMPLES, BLANK], default=next(iter(EXAMPLES))) or BLANK
description, sql = EXAMPLES.get(example, ("", ""))
with st.form("add_metric"):
    name = st.text_input("Name (lowercase, underscores)", value="" if example == BLANK else example)
    description = st.text_input("Description", value=description)
    sql = st.text_area("SQL: an expression, then FROM a table", value=sql, height=150)
    submitted = st.form_submit_button("Place it in the graph", type="primary")

if submitted:
    with rt.lock:
        result = rt.pipeline.add_metric(name.strip(), description.strip(), sql.strip())
    for problem in result.problems:
        st.error(problem)
    if result.added:
        st.success(
            f"'{name}' is now in the graph (can be split by: {', '.join(result.spec.dims) or 'nothing'}) and will be scored from the next hour."
        )
        rows = [
            {
                "link": f"{p.source} → {p.target}",
                "meaning": "opposite of" if p.relation == "opposite" else "may be caused by",
                "check on history": "no data" if p.r is None else f"correlation {p.r:+.2f}",
                "verdict": "Needs a human look (weak evidence)" if p.status == "ambiguous" else "Validated",
                "confidence": p.confidence,
                "why proposed": p.reason,
            }
            for p in result.proposals
        ]
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        st.caption(
            f"Read from the SQL: tables {result.parsed['tables']}, columns {result.parsed['columns']}."
        )
