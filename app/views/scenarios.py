"""Catalogue of every scenario: what it is, how to see it, and a button to start it."""

from __future__ import annotations

import streamlit as st
from common import controls, page
from guide import FAILURES, INNOCENT, custom_scenarios
from widgets import scenario_card

rt, palette = page()
st.title("All scenarios")
st.caption(
    "Each card explains one situation in plain words. Start it, let the clock run, and compare what the agent reports with what it should find."
)
controls(rt, "scenarios")
CUSTOM = tuple(sid for sid in custom_scenarios() if sid in rt.scenarios)
failures, innocent, yours = st.tabs(
    [f"Failures ({len(FAILURES)})", f"Innocent changes ({len(INNOCENT)}) - must NOT raise an incident", f"Your scenarios ({len(CUSTOM)})"]
)


@st.fragment(run_every=1)
def cards(ids: tuple[str, ...]) -> None:
    for sid in ids:
        scenario_card(rt, sid, palette=palette)


with failures:
    cards(FAILURES)
with innocent:
    cards(INNOCENT)
with yours:
    if CUSTOM:
        cards(CUSTOM)
    else:
        st.info("No scenarios of your own yet. Write one on the 'Add a scenario' page.")
