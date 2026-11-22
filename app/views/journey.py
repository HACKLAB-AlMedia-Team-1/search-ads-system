"""The guided demo: one shopper journey with three failures in a row, each found by the agent."""

from __future__ import annotations

import streamlit as st
from common import LANGUAGE_MARKETS, controls, page
from guide import GUIDE, JOURNEY
from widgets import kpi_grid, scenario_card

rt, palette = page()
st.title("One shopper, three failures")
st.markdown(
    "Step 1 happens in the country you choose in the store (**Deliver to**: Germany or United States): searches in the other "
    "language suddenly find nothing. Steps 2 and 3 happen in Germany: the **sponsored product is missing** "
    "(the ad budget was gone by mid-morning). Then the product is **out of stock** (a supplier delivery never arrived). "
    "RootSight is told none of this. It has to notice each problem and trace it to its cause."
)
st.markdown(
    '<div class="steps"><div class="step"><div class="n">1</div><b>Start the clock</b><span>One simulated hour passes every few seconds.</span></div>'
    '<div class="step"><div class="n">2</div><b>Simulate a failure</b><span>Press "Simulate it" on a step below; the clock starts at one hour per second.</span></div>'
    '<div class="step"><div class="n">3</div><b>Look as a shopper</b><span>"See it in the store" opens the shop on the broken search.</span></div>'
    '<div class="step"><div class="n">4</div><b>Read the finding</b><span>The agent\'s report appears in the step after it has enough evidence.</span></div></div>',
    unsafe_allow_html=True,
)
controls(rt, "journey")
ALL_STEPS = "All steps"
steps = {f"Step {n} · {GUIDE[sid]['title']}": (n, sid) for n, sid in enumerate(JOURNEY, start=1)}


@st.fragment(run_every=1)
def live() -> None:
    market = rt.journey_market()
    run = rt.language_run
    country = LANGUAGE_MARKETS.get(market, {"ES": "Spain", "JP": "Japan"}.get(market, market))
    st.caption(f"{country} ({'locked for Step 1' if run else 'follows the store’s Deliver to'}), last full hour")
    kpi_grid(rt, [("Orders", "orders"), ("Zero-result searches", "zero_result_rate"), ("Ad spend", "ad_spend"),
                  ("Top sellers in stock", "in_stock_rate_top"), ("Add-to-cart rate", "add_to_cart_rate")],
             {"market": market}, shop_searches=run.counts if run else None)  # fmt: skip
    chosen = st.selectbox("Demo step", [ALL_STEPS, *steps], key="journey_step")
    for n, sid in steps.values() if chosen == ALL_STEPS else [steps[chosen]]:
        scenario_card(rt, sid, step=n, palette=palette)


live()
