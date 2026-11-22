"""Add a metric by name, description and SQL; the system places it in the graph and validates it in code."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from common import page

rt, palette = page()
st.title("Add or edit a metric")
add_tab, edit_tab = st.tabs(["Add a metric", "Edit a metric"])


def links_table(result) -> None:
    """Every link of the metric with its check against 7 days of history."""
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
    st.caption(f"Read from the SQL: tables {result.parsed['tables']}, columns {result.parsed['columns']}.")


with edit_tab:
    st.markdown(
        "Pick any metric, built-in or added. Change its **description** or **SQL**; the SQL is tested on 7 days of history, "
        "its links are re-checked, and the change is written to the metric's YAML file (`rootsight/graph/metrics.yaml` for built-in ones)."
    )
    chosen = st.selectbox("Metric", sorted(rt.pipeline.graph.specs), key="edit_metric_name")
    current = rt.pipeline.graph.metric(chosen)
    with st.form(f"edit_metric_{chosen}"):
        new_description = st.text_input("Description", value=current.description)
        new_sql = st.text_area("SQL: an expression, then FROM a table", value=current.sql, height=150)
        saved = st.form_submit_button("Save the change", type="primary")
    if saved:
        with rt.lock:
            edited = rt.pipeline.edit_metric(chosen, new_description.strip(), new_sql.strip())
            rt.forget_points()
        for problem in edited.problems:
            st.error(problem)
        if edited.added:
            st.success(f"'{chosen}' is saved and will be scored with the new SQL from the next hour.")
            if edited.proposals:
                links_table(edited)

with add_tab:
    st.markdown(
        "Give only a **name**, a **description** and the **SQL**. You do not say where it belongs: the system reads the SQL, proposes "
        "the links to existing metrics, checks each link against 7 days of history, and starts monitoring the metric at the next hour."
    )
    with st.form("add_metric"):
        name = st.text_input("Name (lowercase, underscores)")
        description = st.text_input("Description")
        sql = st.text_area("SQL: an expression, then FROM a table", height=150)
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
            links_table(result)
