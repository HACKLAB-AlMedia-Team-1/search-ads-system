"""The agent: ask it why something happened, tell it what to watch, see its watch list, or add a metric by SQL."""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st
from common import last_hour, page
from widgets import FOUND_BY, report_card

from rootsight.agent.ask import status_text
from rootsight.agent.llm import LLMUnavailable
from rootsight.agent.watches import MODEL, RULE, as_model, as_rule, where_words
from rootsight.graph.onboarding import draft_metric, try_sql

HOW = {RULE: ("good", "Rule"), MODEL: ("warn", "Model")}

rt, palette = page()
llm = rt.pipeline.llm
st.title("Agent")
st.markdown(
    "One agent watches the whole shop. **Rules first**: every metric is scored every hour by statistics, and the cause of a "
    "failure is found by a fixed recipe with an evidence checklist. **The model only where rules cannot**: it watches "
    "what no metric can express, and takes over an investigation the recipe could not confirm. Code checks everything "
    "a model says (numbers, metrics, SQL) before it counts."
)
model_line = (f"Model: **{rt.settings.llm_model_agent}** via `{rt.settings.llm_base_url}` (`LLM_MODE={llm.mode}`)" if llm.available
              else "Model: **off** (`LLM_MODE=offline`). Rules do all the work; model watches wait for a model.")  # fmt: skip
st.caption(model_line)
ask_tab, watch_tab, list_tab, metric_tab = st.tabs(
    ["Ask why", "Watch something", "Watch list", "Add or edit a metric (SQL)"]
)

with ask_tab:
    with st.form("ask"):
        question = st.text_input("Your question", placeholder="Why do searches find nothing in Germany?")
        always = st.checkbox("Investigate even if the number looks normal")
        asked = st.form_submit_button("Ask the agent", type="primary")
    if asked and question.strip():
        with (
            st.spinner("The agent is looking..."),
            rt.lock,
        ):  # the clock waits so the investigation sees one fixed hour
            st.session_state["answer"] = rt.pipeline.ask(question.strip(), always)
    if answer := st.session_state.get("answer"):
        st.info(answer.text)
        st.caption(f"Question read by {'plain-word rules' if answer.understood_by == 'rules' else 'the model'}."
                   + (f" Cause found by {FOUND_BY.get(answer.report.method, answer.report.method)}." if answer.report else ""))  # fmt: skip
        if answer.report:
            report_card(answer.report.model_dump(mode="json"))

with watch_tab:
    st.markdown(
        "Say in plain words what to keep an eye on. If a metric can measure it, the agent makes it a **rule** (scored every "
        "hour). If not, the **model** looks at it itself every few hours. You see the plan before anything starts."
    )
    with st.form("watch"):
        wish = st.text_input("What should the agent watch?", placeholder="Zero results in Germany on Android")
        planned = st.form_submit_button("Plan it", type="primary")
    if planned and wish.strip():
        with st.spinner("The agent is planning..."):  # read-only, so the clock keeps running
            st.session_state["watch_plan"] = rt.pipeline.plan_watch(wish.strip())
    if plan := st.session_state.get("watch_plan"):
        cls, label = HOW[plan.kind]
        target = (f"`{plan.metric}` in {where_words(plan.segment)}, scored every hour" if plan.kind == RULE
                  else f"the model looks every {plan.every_hours} simulated hours")  # fmt: skip
        st.markdown(
            f'<div class="card"><span class="badge {cls}">{label}</span><br><b>{html.escape(plan.request)}</b>'
            f'<div class="kv"><i>How</i><span>{html.escape(target)}</span><i>Why</i><span>{html.escape(plan.reason)}</span>'
            f"<i>Planned by</i><span>{'plain-word rules' if plan.by == 'rules' else 'the model'}</span></div></div>",
            unsafe_allow_html=True,
        )
        if plan.new_metric:
            st.markdown(
                f"New metric **{plan.new_metric['name']}**, written by the model. Read the SQL before you start it:"
            )
            st.code(plan.new_metric["sql"], language="sql")
        left, right = st.columns(2)
        if left.button("Start watching", type="primary"):
            with rt.lock:
                watch, problems = rt.pipeline.add_watch(plan)
            for problem in problems:
                st.error(problem)
            if watch:
                st.session_state.pop("watch_plan")
                st.success(f"{watch.watch_id} started. See 'Watch list'.")
        other = as_model(plan) if plan.kind == RULE else as_rule(plan, rt.pipeline.graph)
        if other and right.button(
            "Let the model watch it instead" if plan.kind == RULE else "Use a rule instead"
        ):
            st.session_state["watch_plan"] = other
            st.rerun()


@st.fragment(run_every=2)
def watch_list() -> None:
    """Every watch and how it stands right now (rule watches: latest score; model watches: latest look)."""
    watches = rt.pipeline.watches.all()
    if not watches:
        st.info(
            "Nothing asked yet. The agent still scores every metric of the graph every hour; add a watch in 'Watch something'."
        )
        return
    hour = last_hour(rt)
    for w in watches:
        cls, label = HOW[w.kind]
        if not w.active:
            state = "stopped"
        elif w.kind == RULE and w.metric in rt.pipeline.graph.specs:
            state = status_text(
                rt.pipeline.graph, w.metric, w.segment, rt.point(w.metric, w.segment, hour), hour
            )
        else:
            state = rt.pipeline.watch_state(w)
        how = (
            f"`{w.metric}` in {where_words(w.segment)}, every hour"
            if w.kind == RULE
            else f"model, every {w.every_hours} h"
        )
        with st.container(border=True):
            st.markdown(f'<span class="badge {cls}">{label}</span> <b>{w.watch_id}</b> · {html.escape(w.request)}<br>'
                        f'<small>{html.escape(how)} · since {w.created:%a %H:00}</small><br>{html.escape(state)}',
                        unsafe_allow_html=True)  # fmt: skip
            if w.active and st.button("Stop", key=f"stop_{w.watch_id}"):
                rt.pipeline.watches.stop(w.watch_id)
                st.rerun()


with list_tab:
    watch_list()


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
    """The one template both forms use: name, description, SQL, button. Only the name differs: typed (add) or picked (edit)."""
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
        description = st.text_input(
            "Description", key=d_key, placeholder="What the metric measures, in one line"
        )
        sql = st.text_area("SQL: an expression, then FROM a table", key=s_key, height=150,
                           placeholder="SUM(orders) / NULLIF(SUM(sessions), 0) FROM fact_hourly")  # fmt: skip
        pressed = st.form_submit_button(button, type="primary")
    return name.strip(), description.strip(), sql.strip(), pressed


with metric_tab:
    st.markdown(
        "For people who write SQL. Give a **name**, a **description** and the **SQL**: the system reads the SQL, proposes the "
        "links to existing metrics, checks each link against 7 days of history, and the metric becomes a rule watch from the "
        "next hour. Or edit any metric, built-in or added."
    )
    mode = st.segmented_control(
        "Metric", ["Add a metric", "Edit a metric"], default="Add a metric", key="metric_mode"
    )
    if mode != "Edit a metric":
        with st.expander("Or describe it in words and let the model write the SQL"):
            if not llm.available:
                st.caption("Needs a language model (`LLM_MODE=live` and a model in `.env`, see `docs/MODEL_COMPARISON.md`). "
                           "The rule-based agent cannot write SQL.")  # fmt: skip
            words = st.text_input("What should the metric measure?", key="metric_wish",
                                  placeholder="Share of carts that do not become an order")  # fmt: skip
            if st.button("Write the SQL", disabled=not (llm.available and words.strip())):
                try:
                    draft = draft_metric(llm, rt.db, rt.pipeline.graph, words.strip(), rt.now)
                except LLMUnavailable as exc:
                    st.error(f"The model could not write it: {exc}")
                else:
                    frame, problem = try_sql(rt.db, draft["sql"], rt.now)
                    st.session_state.update({"add_metric_name": draft["name"], "add_metric_desc_new": words.strip(),
                                             "add_metric_sql_new": draft["sql"]})  # fmt: skip
                    st.session_state["metric_draft_note"] = problem or (
                        f"The model's SQL runs on the last 7 days ({len(frame)} hourly values). Read it below, then place it in the graph."
                    )
            if note := st.session_state.get("metric_draft_note"):
                st.info(note)
        name, description, sql, submitted = metric_fields(
            "add_metric", "Place it in the graph", existing=False
        )
        if submitted:
            with rt.lock:
                result = rt.pipeline.add_metric(name, description, sql)
            for problem in result.problems:
                st.error(problem)
            if result.added:
                st.success(f"'{name}' is now in the graph (can be split by: {', '.join(result.spec.dims) or 'nothing'}) and is "
                           "on the watch list; it is scored from the next hour.")  # fmt: skip
                links_table(result)
    else:
        chosen, new_description, new_sql, saved = metric_fields(
            "edit_metric", "Save the change", existing=True
        )
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
