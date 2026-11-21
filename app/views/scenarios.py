"""Catalogue of every scenario: what it is, how to see it, and a button to start it."""

from __future__ import annotations

import streamlit as st
from common import controls, page
from guide import FAILURES, INNOCENT
from widgets import scenario_card

rt, palette = page()
st.title("All scenarios")
st.caption(
    "Each card explains one situation in plain words. Start it, let the clock run, and compare what the agent reports with what it should find."
)
controls(rt, "scenarios")
failures, innocent = st.tabs(
    [f"Failures ({len(FAILURES)})", f"Innocent changes ({len(INNOCENT)}) - must NOT raise an incident"]
)


@st.fragment(run_every=2)
def cards(ids: tuple[str, ...]) -> None:
    for sid in ids:
        scenario_card(rt, sid)


with failures:
    cards(FAILURES)
with innocent:
    cards(INNOCENT)
