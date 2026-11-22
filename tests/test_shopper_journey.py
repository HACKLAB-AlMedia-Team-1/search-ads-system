"""Exercise the dashboard runtime and the live ShopLens HTTP API on a private database."""

import json
import shutil
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd
import pytest
from conftest import SETTINGS
from streamlit.testing.v1 import AppTest

from rootsight.sim.clock import HOUR

APP = Path(__file__).resolve().parents[1] / "app"


@pytest.fixture
def dashboard(tmp_path, monkeypatch):
    snapshot = SETTINGS.duckdb_path.with_suffix(".backfill.duckdb")
    if not snapshot.is_file():
        pytest.skip("run scripts/backfill.py first")
    path = tmp_path / "shopper.duckdb"
    shutil.copyfile(snapshot, path)
    monkeypatch.syspath_prepend(str(APP))
    import common

    settings = replace(SETTINGS, duckdb_path=path, llm_mode="offline", linkup_mode="offline")
    monkeypatch.setattr(common, "load_settings", lambda: settings)
    monkeypatch.setattr(common, "SHOP_PORT", 0)
    runtime = common.Runtime()
    try:
        # Keep the clock state real while closing hours explicitly for repeatable tests.
        monkeypatch.setattr(runtime, "_ensure_worker", lambda: None)
        monkeypatch.setattr(common, "get_runtime", lambda: runtime)
        yield runtime
    finally:
        runtime.shutdown()


def shop_call(rt, path, **query):
    port = rt.shop.server_address[1]
    with urlopen(f"http://127.0.0.1:{port}/api/{path}?{urlencode(query)}", timeout=20) as response:
        return json.load(response)


def add_to_cart(rt, item):
    port = rt.shop.server_address[1]
    body = {"market": "DE", "doc": item["doc"], "price": item["price"]}
    request = Request(
        f"http://127.0.0.1:{port}/api/cart", json.dumps(body).encode(), {"Content-Type": "application/json"}
    )
    with urlopen(request, timeout=20) as response:
        return json.load(response)


def close_hour(rt):
    result = rt.pipeline.step()
    rt._record_hourly_orders()
    return result


def select_ui(page):
    screen = AppTest.from_file(str(APP / "views" / f"{page}.py"), default_timeout=120).run()
    assert not screen.exception
    return screen


@pytest.mark.integration
def test_storefront_searches_drive_step_one_and_ending_preserves_monitoring(dashboard):
    rt = dashboard
    shop_call(rt, "home", market="ES")
    assert not rt.simulate("L1")
    assert select_ui("journey").button(key="go_L1_1").disabled
    shop_call(rt, "home", market="DE")
    assert rt.simulate("L1")
    assert rt.running and rt.journey_market() == "DE"
    assert not shop_call(rt, "search", market="DE", q="headphones", observe=0)["items"]
    assert shop_call(rt, "search", market="US", q="kopfhörer")["items"]
    assert rt.journey_market() == "DE"
    close_hour(rt)
    assert rt.language_run.counts == (0, 0)
    assert not rt.language_run.orders and not rt.progress("L1")
    assert rt.db.df("SELECT * FROM events WHERE component = 'search-language'").empty

    assert not shop_call(rt, "search", market="DE", q="headphones")["items"]
    assert rt.language_run.counts == (1, 1)
    assert rt.language_run.first_failure == rt.now
    close_hour(rt)
    blocked = rt.language_run.orders[-1]
    assert blocked["expected"] > 0 and blocked["received"] == 0
    assert rt.progress("L1")
    assert shop_call(rt, "search", market="DE", q="kopfhörer")["items"]
    assert rt.language_run.counts == (2, 1)
    close_hour(rt)
    recovered = rt.language_run.orders[-1]
    hourly_orders = rt.point("orders", {"market": "DE"}, rt.now - HOUR)
    assert recovered["received"] == hourly_orders["actual"] > 0
    assert recovered["expected"] == hourly_orders["expected"] > 0

    journey = select_ui("journey")
    assert any("50.0%" in tile.value and "1 of 2 shop searches" in tile.value for tile in journey.markdown)
    assert journey.button(key="fix_L1_1").label == "End simulation"
    assert len(journey.get("plotly_chart")) == 1
    traces = json.loads(journey.get("plotly_chart")[0].proto.spec)["data"]
    assert [trace["name"] for trace in traces] == ["Total expected orders", "Total received orders"]
    assert not any(b.label in {"+1 hour", "+6 hours"} for b in journey.button)

    # A local-language search with no matches counts, without creating another fault event.
    assert not shop_call(rt, "search", market="DE", q="zzzxxyyqq")["items"]
    assert rt.language_run.counts == (3, 2)
    close_hour(rt)
    assert rt.language_run.orders[-1]["received"] == 0
    incident_count = len(rt.db.df("SELECT incident_id FROM incidents"))
    assert rt.finding("L1") is not None
    revision = shop_call(rt, "state")["revision"]
    cleared = journey.button(key="fix_L1_1").click().run()
    assert rt.running and rt.language_run is None
    assert rt.finding("L1") is None and not rt.progress("L1")
    assert len(rt.db.df("SELECT incident_id FROM incidents")) == incident_count
    assert shop_call(rt, "state")["revision"] == revision + 1
    assert shop_call(rt, "search", market="DE", q="headphones")["items"]
    assert not cleared.exception
    assert not cleared.get("plotly_chart")
    assert cleared.button(key="go_L1_1").label == "Simulate it"

    shop_call(rt, "home", market="US")
    assert rt.simulate("L1")
    assert not shop_call(rt, "search", market="US", q="kopfhörer")["items"]
    assert shop_call(rt, "search", market="US", q="headphones")["items"]
    assert rt.language_run.counts == (2, 1)
    rt.fix("L1")
    assert shop_call(rt, "search", market="US", q="kopfhörer")["items"]


@pytest.mark.integration
def test_ending_one_scenario_restores_its_storefront_state(dashboard):
    rt = dashboard
    assert rt.simulate("AD1") and rt.simulate("INV1")
    sim = rt.pipeline.sim
    sim._supply(rt.now)
    # Exhaust the campaign deterministically, without advancing the other scenario.
    rng = np.random.default_rng(42)
    for _ in range(10):
        sim.pacer.step(rt.now, "DE", 0.05, sim.faults, rng)
    broken = shop_call(rt, "search", market="DE", q="kopfhörer")
    assert broken["sponsored"] is None
    best_sellers = [item for item in broken["items"] if item["best_seller"]]
    assert best_sellers and all(item["stock"] == 0 for item in best_sellers)
    assert not add_to_cart(rt, best_sellers[0])["ok"]

    rt.fix("AD1")
    ads_recovered = shop_call(rt, "search", market="DE", q="kopfhörer")
    assert ads_recovered["sponsored"] is not None
    assert "AD1" not in rt.active() and "INV1" in rt.active()
    assert all(item["stock"] == 0 for item in ads_recovered["items"] if item["best_seller"])
    rt.fix("INV1")
    stock_recovered = shop_call(rt, "search", market="DE", q="kopfhörer")
    restocked = [item for item in stock_recovered["items"] if item["best_seller"]]
    assert restocked and all(item["stock"] > 0 for item in restocked)
    assert add_to_cart(rt, restocked[0])["ok"]
    assert not rt.started and rt.running

    for page in ("scenarios", "control_room"):
        screen = select_ui(page)
        assert not any(b.label in {"+1 hour", "+6 hours"} for b in screen.button)
    metric = select_ui("add_metric")
    assert not any(control.label == "Start from" for control in metric.get("segmented_control"))
    assert [tab.label for tab in metric.tabs] == ["Add a metric", "Edit a metric"]
    assert all(field.value == "" for field in metric.tabs[0].get("text_input"))
    assert metric.tabs[0].get("text_area")[0].value == ""


@pytest.mark.integration
def test_ad_budget_chart_restarts_at_zero_and_respects_remaining_budget(dashboard):
    rt = dashboard
    sim = rt.pipeline.sim
    rng = np.random.default_rng(42)
    first_start = rt.now

    def close_ad_hours(count):
        rows = []
        for _ in range(count):
            rows.append(sim.pacer.step(rt.now, "DE", 0.06, sim.faults, rng))
            rt.pipeline.now += HOUR
        rt.db.insert_df("ads_hourly", pd.DataFrame(rows))

    assert rt.simulate("AD1")
    close_ad_hours(11)
    assert rt.ads_chart("AD1")["spend"].iloc[-1] == 250.0
    rt.fix("AD1")
    assert rt.ads_chart("AD1").empty
    close_ad_hours(1)

    restart = rt.now
    available = round(250.0 - sim.pacer.spent("DE", restart.date()), 2)
    assert 0 < available < 250.0
    assert rt.simulate("AD1")
    opening = rt.ads_chart("AD1")
    assert opening.to_dict("records") == [{"ts": restart, "budget": available, "spend": 0.0, "planned": 0.0}]
    chart = select_ui("journey").get("plotly_chart")[0]
    assert [trace["name"] for trace in json.loads(chart.proto.spec)["data"]] == [
        "available budget", "expected spend", "actual spend",
    ]

    close_ad_hours(11)
    rerun = rt.ads_chart("AD1")
    assert rerun["ts"].iloc[0] == restart
    assert rerun["spend"].iloc[-1] == available
    assert (rerun["spend"] <= rerun["budget"]).all()
    assert (rerun["planned"] <= rerun["budget"]).all()
    assert shop_call(rt, "search", market="DE", q="kopfhörer")["sponsored"] is None
    history = rt.db.df(
        "SELECT sum(spend_eur) AS total FROM ads_hourly WHERE campaign_id = 'CMP-DE' AND ts >= ?",
        [first_start],
    )
    assert history["total"].iloc[0] > 250.0

    close_ad_hours(1)
    midnight = rt.now
    close_ad_hours(1)
    next_day = rt.ads_chart("AD1")
    assert next_day["ts"].iloc[0] == midnight
    assert next_day["budget"].iloc[0] == 250.0
    assert next_day["spend"].iloc[0] == 0.0
