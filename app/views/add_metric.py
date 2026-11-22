"""Add a metric by name, description and SQL; the system places it in the graph and validates it in code."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from common import page

from rootsight.agent.llm import LLMUnavailable
from rootsight.graph.onboarding import draft_metric, try_sql

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


def metric_fields(tab: str, button: str, existing: bool) -> tuple[str, str, str, bool]:
    """The one template both tabs use: name, description, SQL, button. Only the name differs: typed (add) or picked (edit)."""
    description = sql = ""
    if existing:
        name = st.selectbox("Name", sorted(rt.pipeline.graph.specs), key=f"{tab}_name")
        description, sql = rt.pipeline.graph.metric(name).description, rt.pipeline.graph.metric(name).sql
    else:
        name = st.text_input("Name", key=f"{tab}_name", placeholder="lowercase_with_underscores")
    suffix = name if existing else "new"
    d_key, s_key = f"{tab}_desc_{suffix}", f"{tab}_sql_{suffix}"
    st.session_state.setdefault(d_key, description)  # keys, so a model-written draft can fill the fields
    st.session_state.setdefault(s_key, sql)
    with st.form(f"{tab}_{suffix}"):
        description = st.text_input("Description", key=d_key, placeholder="What the metric measures, in one line")
        sql = st.text_area("SQL: an expression, then FROM a table", key=s_key, height=150,
                           placeholder="SUM(orders) / NULLIF(SUM(sessions), 0) FROM fact_hourly")  # fmt: skip
        pressed = st.form_submit_button(button, type="primary")
    return name.strip(), description.strip(), sql.strip(), pressed


with add_tab:
    st.markdown(
        "Give only a **name**, a **description** and the **SQL**. You do not say where it belongs: the system reads the SQL, proposes "
        "the links to existing metrics, checks each link against 7 days of history, and starts monitoring the metric at the next hour."
    )
    llm = rt.pipeline.llm
    with st.expander("Or describe it in words and let the model write the SQL"):
        if not llm.available:
            st.caption("Needs a language model (`LLM_MODE=live` and a model in `.env`, see `docs/MODEL_COMPARISON.md`). "
                       "The rule-based agent cannot write SQL.")  # fmt: skip
        wish = st.text_input("What should the metric measure?", key="metric_wish",
                             placeholder="Share of carts that do not become an order")  # fmt: skip
        if st.button("Write the SQL", disabled=not (llm.available and wish.strip())):
            try:
                draft = draft_metric(llm, rt.db, rt.pipeline.graph, wish.strip(), rt.now)
            except LLMUnavailable as exc:
                st.error(f"The model could not write it: {exc}")
            else:
                frame, problem = try_sql(rt.db, draft["sql"], rt.now)
                st.session_state.update({"add_metric_name": draft["name"], "add_metric_desc_new": wish.strip(),
                                         "add_metric_sql_new": draft["sql"]})  # fmt: skip
                st.session_state["metric_draft_note"] = problem or (
                    f"The model's SQL runs on the last 7 days ({len(frame)} hourly values). Read it below, then place it in the graph.")
        if note := st.session_state.get("metric_draft_note"):
            st.info(note)
    name, description, sql, submitted = metric_fields("add_metric", "Place it in the graph", existing=False)
    if submitted:
        with rt.lock:
            result = rt.pipeline.add_metric(name, description, sql)
        for problem in result.problems:
            st.error(problem)
        if result.added:
            st.success(
                f"'{name}' is now in the graph (can be split by: {', '.join(result.spec.dims) or 'nothing'}) and will be scored from the next hour."
            )
            links_table(result)

with edit_tab:
    st.markdown(
        "Pick any metric, built-in or added. Change its **description** or **SQL**; the SQL is tested on 7 days of history, "
        "its links are re-checked, and the change is written to the metric's YAML file (`rootsight/graph/metrics.yaml` for built-in ones)."
    )
    chosen, new_description, new_sql, saved = metric_fields("edit_metric", "Save the change", existing=True)
    if saved:
        with rt.lock:
            edited = rt.pipeline.edit_metric(chosen, new_description, new_sql)
            rt.forget_points()
        for problem in edited.problems:
            st.error(problem)
        if edited.added:
            st.success(f"'{chosen}' is saved and will be scored with the new SQL from the next hour.")
            if edited.proposals:
                links_table(edited)
