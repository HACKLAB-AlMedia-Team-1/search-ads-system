"""Write a monitoring scenario in plain words; the agent maps it onto a fault the simulator can produce, or says why not."""

from __future__ import annotations

import streamlit as st
from common import ROOT, page
from guide import custom_scenarios

from rootsight.sim.custom import COUNTRY, FAULTS, draft_scenario, save_scenario

rt, palette = page()
st.title("Add a scenario")
st.markdown(
    "Describe a failure the way a shop manager would: **what breaks**, **where**, and **what a shopper sees**. The agent reads it, "
    "picks the matching fault the simulator can really produce, and writes **what the numbers will do** (from the metric graph and "
    "the database) and **what the agent should do**. If the simulator cannot produce it yet, you get the reason instead."
)
with st.expander(f"Failures the simulator can produce ({len(FAULTS)})"):
    st.markdown("\n".join(f"- **{k.label}** - in {', '.join(COUNTRY[m] for m in k.markets)}"
                          + (f", {k.platform} only" if k.platform else "") for k in FAULTS.values()))  # fmt: skip
with st.form("add_scenario"):
    left, right = st.columns([1, 3])
    sid = left.text_input("Scenario id", placeholder="MY1")
    title = right.text_input("Title", placeholder="Spanish top sellers out of stock")
    what = st.text_area("What breaks", placeholder="The supplier delivery for the best sellers in Spain is late.", height=80)
    where = st.text_input("Where", placeholder="Spain")
    shop = st.text_area("What a shopper sees", placeholder="Products show 'Currently unavailable' and cannot be added to the cart.",
                        height=80)  # fmt: skip
    checked = st.form_submit_button("Let the agent check it", type="primary")

if checked:
    with rt.lock:
        draft = draft_scenario(rt.db, rt.pipeline.graph, rt.pipeline.llm, set(rt.scenarios), sid, title, what, where, shop, rt.now)
    if draft.possible:
        st.session_state["scenario_draft"] = draft
    else:
        st.session_state.pop("scenario_draft", None)
        for problem in draft.problems:
            st.error(problem)

draft = st.session_state.get("scenario_draft")
if draft:
    kind = FAULTS[draft.fault]
    with st.container(border=True):
        st.markdown(f"#### {draft.sid} · {draft.title}")
        st.markdown(
            f'<div class="kv"><i>Simulated as</i><span>{kind.label} (`{draft.fault}`)</span>'
            f"<i>Scope</i><span>{', '.join(f'{k} = {v}' for k, v in draft.scope.items())}</span>"
            f"<i>What the numbers will do</i><span>{draft.numbers}</span><i>What the agent should do</i><span>{draft.agent}</span></div>",
            unsafe_allow_html=True,
        )
        if st.button("Save the scenario", type="primary"):
            path = save_scenario(draft, ROOT / "scenarios")
            rt.add_scenario(path)
            custom_scenarios()
            st.session_state.pop("scenario_draft")
            st.success(f"Saved to scenarios/{path.name}. Open 'All scenarios' → 'Your scenarios' and press Simulate it.")
