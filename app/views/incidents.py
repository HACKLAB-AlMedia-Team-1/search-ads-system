"""Incidents: one row per problem, with its full evidence-based report."""

from __future__ import annotations

import json

import streamlit as st
from common import page
from widgets import report_card

from rootsight.agent.report import Report, render

COLUMNS = {
    "incident_id": "#",
    "status": "status",
    "cause_component": "cause",
    "first_seen": "since",
    "last_seen": "last seen",
    "evidence_status": "evidence",
    "impact_orders": "lost orders",
    "impact_revenue_eur": "lost revenue €",
    "wasted_ad_spend_eur": "wasted ad spend €",
}

rt, palette = page()
st.title("Incidents")
st.caption(
    "One incident per problem. An ongoing problem updates its incident instead of creating new ones; "
    "it closes when you press End Simulation, or by itself after three normal hours."
)
frame = rt.db.df(f"SELECT {', '.join(COLUMNS)}, report_json FROM incidents ORDER BY incident_id DESC")
if frame.empty:
    st.info("No incidents yet. Open 'Shopper journey', press 'Simulate it' on a step and wait a few seconds.")
    st.stop()
st.dataframe(frame[list(COLUMNS)].rename(columns=COLUMNS), width="stretch", hide_index=True)
labels = {
    int(r.incident_id): f"#{r.incident_id} - {r.cause_component or 'unknown cause'} ({r.status})"
    for r in frame.itertuples()
}
pick = st.selectbox("Report", list(labels), format_func=labels.get)
chosen = frame[frame["incident_id"] == pick].iloc[0]
report = json.loads(chosen["report_json"])["report"]
report_card(report, chosen["status"])
st.download_button(
    "Download this report (markdown)", render(Report(**report)), file_name=f"incident_{pick}.md"
)
