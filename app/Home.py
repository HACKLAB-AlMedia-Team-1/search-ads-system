"""RootSight dashboard entry point: `streamlit run app/Home.py`. The pages live in `app/views/`."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

VIEWS = Path(__file__).parent / "views"

st.set_page_config(page_title="RootSight", page_icon=":material/visibility:", layout="wide")
st.navigation(
    {
        "Demo": [
            st.Page(VIEWS / "journey.py", title="Shopper journey", icon=":material/route:", default=True),
            st.Page(VIEWS / "scenarios.py", title="All scenarios", icon=":material/science:"),
        ],
        "Monitoring": [
            st.Page(VIEWS / "control_room.py", title="Control room", icon=":material/monitoring:"),
            st.Page(VIEWS / "incidents.py", title="Incidents", icon=":material/report:"),
            st.Page(VIEWS / "graph.py", title="Metric graph", icon=":material/hub:"),
            st.Page(VIEWS / "add_metric.py", title="Add or edit a metric", icon=":material/add_chart:"),
            st.Page(VIEWS / "add_scenario.py", title="Add a scenario", icon=":material/add_task:"),
        ],
    }
).run()
