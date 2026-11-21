"""The guided demo: one shopper journey in Germany with three failures in a row, each found by the agent."""

from __future__ import annotations

import streamlit as st
from common import controls, page
from guide import JOURNEY
from widgets import kpi_grid, scenario_card

rt, palette = page()
st.title("One shopper, three failures")
st.markdown(
    "A shopper in Germany searches for **kopfhörer** and finds nothing (search is broken). Once fixed, the **sponsored product is missing** "
    "(the ad budget was gone by mid-morning). Then the product is **out of stock** (a supplier delivery never arrived). "
    "RootSight is told none of this. It has to notice each problem and trace it to its cause."
)
st.markdown(
    '<div class="steps"><div class="step"><div class="n">1</div><b>Start the clock</b><span>One simulated hour passes every few seconds.</span></div>'
    '<div class="step"><div class="n">2</div><b>Break something</b><span>Press "Break it" on a step below.</span></div>'
    '<div class="step"><div class="n">3</div><b>Look as a shopper</b><span>"See it in the store" opens the shop on the broken search.</span></div>'
    '<div class="step"><div class="n">4</div><b>Read the finding</b><span>Within 1-3 simulated hours the agent\'s report appears in the step.</span></div></div>',
    unsafe_allow_html=True,
)
controls(rt, "journey")


@st.fragment(run_every=2)
def live() -> None:
    st.caption("Germany, last full hour")
    kpi_grid(rt, [("Orders", "orders"), ("Zero-result searches", "zero_result_rate"), ("Ad spend", "ad_spend"),
                  ("Top sellers in stock", "in_stock_rate_top"), ("Add-to-cart rate", "add_to_cart_rate")], {"market": "DE"})  # fmt: skip
    for n, sid in enumerate(JOURNEY, start=1):
        scenario_card(rt, sid, step=n)


live()
