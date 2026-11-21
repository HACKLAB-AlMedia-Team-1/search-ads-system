"""Control room: is everything normal, the key numbers against what is expected, alerts and the latest finding."""

from __future__ import annotations

import json

import streamlit as st
from common import controls, page
from widgets import band_chart, kpi_grid, report_card

BUSINESS = [
    ("Orders", "orders"),
    ("Revenue", "revenue"),
    ("Return on ad spend (6 h)", "roas"),
    ("Ad spend", "ad_spend"),
]
SEARCH = [("Search click rate", "search_ctr"), ("Zero-result searches", "zero_result_rate"), ("Result relevance", "relevance_at_10"),
          ("Top sellers in stock", "in_stock_rate_top")]  # fmt: skip
EXPERIENCE = [("Bounce rate", "bounce_rate"), ("Searches reworded", "refinement_rate"), ("Avg. clicked position", "avg_click_position"),
              ("Unavailable on click", "unavailable_on_click_rate")]  # fmt: skip
KIND = {"failure": ("bad", "problem"), "planned": ("info", "planned"), "data_delay": ("warn", "data delay")}

rt, palette = page()
st.title("Control room")
controls(rt, "room")
markets = ["All countries", *rt.pipeline.sim.engine.indexes]
market = st.segmented_control("Country", markets, default=markets[0], key="room_market") or markets[0]
segment = {} if market == markets[0] else {"market": market}
charts = dict(BUSINESS + SEARCH + EXPERIENCE)


@st.fragment(run_every=2)
def live() -> None:
    open_incidents = rt.db.df(
        "SELECT incident_id, report_json FROM incidents WHERE status = 'open' ORDER BY incident_id DESC"
    )
    if open_incidents.empty:
        st.markdown(
            '<div class="banner good"><span class="dot"></span><div><b>All normal</b><small>Every monitored metric is inside its expected range, or already explained.</small></div></div>',
            unsafe_allow_html=True,
        )
    else:
        first = json.loads(open_incidents["report_json"].iloc[0])["report"]
        st.markdown(
            f'<div class="banner bad"><span class="dot"></span><div><b>{len(open_incidents)} open incident(s)</b><small>{first["headline"]}</small></div></div>',
            unsafe_allow_html=True,
        )
    st.markdown("##### Money")
    kpi_grid(rt, BUSINESS, segment)
    st.markdown("##### Search and stock")
    kpi_grid(rt, SEARCH, segment)
    st.markdown("##### Shopper experience")
    kpi_grid(rt, EXPERIENCE, segment)
    left, right = st.columns([3, 2], gap="large")
    with left:
        choice = st.selectbox(
            "Chart (orange = actual, grey band = expected range)", list(charts), key="room_chart"
        )
        band_chart(
            rt,
            palette,
            charts[choice],
            segment if "market" in rt.pipeline.graph.metric(charts[choice]).dims else {},
        )
        st.markdown("##### Latest alerts")
        cases = rt.db.df(
            "SELECT ts, kind, status, headline FROM cases ORDER BY ts DESC, attention DESC LIMIT 6"
        )
        if cases.empty:
            st.caption("No alerts yet.")
        for r in cases.itertuples():
            cls, label = KIND[r.kind]
            st.markdown(
                f'<div class="card"><span class="badge {cls}">{label}</span> <small>{r.ts:%a %H:%M}</small><br>{r.headline}</div>',
                unsafe_allow_html=True,
            )
    with right:
        st.markdown("##### Latest finding")
        row = rt.db.df(
            "SELECT status, report_json FROM incidents ORDER BY (status = 'open') DESC, last_seen DESC LIMIT 1"
        )
        if row.empty:
            st.caption("No incident yet. Go to 'Shopper journey' and break something.")
        else:
            report_card(json.loads(row["report_json"].iloc[0])["report"], row["status"].iloc[0])


live()
