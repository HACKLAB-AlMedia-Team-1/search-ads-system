"""Simulator: faults stay local, ads follow (or break) their plan, late data is flagged and then repaired."""

from datetime import datetime

import pandas as pd
import pytest
from conftest import PROCESSED, SETTINGS

from rootsight.engine.search import SearchEngine
from rootsight.sim.faults import FaultRegistry, load_scenarios
from rootsight.sim.simulator import Simulator
from rootsight.sim.traffic import Traffic
from rootsight.sim.users import QueryPool
from rootsight.store.db import Database

SCENARIOS = load_scenarios(SETTINGS.data_raw_dir.parents[1] / "scenarios")
DAY = datetime(2026, 11, 10)  # a Tuesday


@pytest.fixture
def make_sim(sample):
    """Factory for independent (simulator, database) pairs built on the small sample."""
    products, queries, labels = sample
    profile = pd.read_parquet(PROCESSED / "traffic_profile.parquet")

    def make():
        db = Database(":memory:")
        engine = SearchEngine(products, FaultRegistry(), seed=SETTINGS.sim_seed)
        return Simulator(db, engine, QueryPool(queries, labels), Traffic(profile), SETTINGS.sim_seed), db

    return make


def totals(db, start, end, table="fact_hourly", by="market"):
    return db.df(f"SELECT {by}, sum(orders) AS orders, sum(searches) AS searches FROM {table} "
                 "WHERE ts >= ? AND ts < ? GROUP BY 1", [start, end]).set_index(by)  # fmt: skip


def test_scenarios_load():
    assert set(SCENARIOS) == {"S1", "S12", "S3", "AD1", "EV1", "DQ1", "S2", "S7", "S15", "INV1"}
    moved = SCENARIOS["S1"].shifted(datetime(2026, 12, 1, 9, 0))
    assert moved.start == datetime(2026, 12, 1, 9, 0) and moved.event_log[0]["ts"] == datetime(
        2026, 12, 1, 8, 55
    )


def test_s1_is_local_to_search_quality(make_sim):
    clean, clean_db = make_sim()
    broken, broken_db = make_sim()
    start, end = DAY.replace(hour=14), DAY.replace(hour=18)
    clean.run(start, end)
    broken.activate(SCENARIOS["S1"], at=start)
    broken.run(start, end)
    a = totals(clean_db, start, end)
    b = totals(broken_db, start, end)
    assert (b["searches"] / a["searches"]).between(0.9, 1.1).all()
    assert b["orders"].sum() <= 0.75 * a["orders"].sum()
    spend = [db.df("SELECT sum(spend_eur) AS s FROM ads_hourly").iloc[0, 0] for db in (clean_db, broken_db)]
    assert spend[1] == pytest.approx(spend[0], rel=0.1)
    assert broken_db.df("SELECT count(*) FROM events WHERE component = 'search-ranker'").iloc[0, 0] == 1


def test_ad1_exhausts_the_german_budget_early(make_sim):
    sim, db = make_sim()
    sim.activate(SCENARIOS["AD1"], at=DAY)
    sim.run(DAY, DAY.replace(hour=13))
    es = db.df("SELECT ts, spend_eur, paid_sessions FROM ads_hourly WHERE market = 'DE' ORDER BY ts")
    assert es["spend_eur"].sum() <= 250.0 + 1e-6
    assert es[es["ts"] < DAY.replace(hour=11)]["spend_eur"].sum() >= 249.0
    assert es[es["ts"] >= DAY.replace(hour=11)]["paid_sessions"].sum() == 0
    us = db.df("SELECT sum(spend_eur) AS s FROM ads_hourly WHERE market = 'US'").iloc[0, 0]
    assert us < 0.5 * 400.0


def test_ev1_doubles_paid_traffic_without_touching_search(make_sim):
    normal, normal_db = make_sim()
    push, push_db = make_sim()
    push.activate(SCENARIOS["EV1"], at=DAY)
    for sim in (normal, push):
        sim.run(DAY.replace(hour=6), DAY.replace(hour=12))
    spend = [db.df("SELECT sum(spend_eur) AS s FROM ads_hourly").iloc[0, 0] for db in (normal_db, push_db)]
    assert spend[1] == pytest.approx(2 * spend[0], rel=0.1)
    assert push_db.df("SELECT count(*) FROM calendar").iloc[0, 0] == 1


def test_dq1_late_search_events_are_flagged_then_repaired(make_sim):
    sim, db = make_sim()
    late = DAY.replace(hour=15)
    sim.activate(SCENARIOS["DQ1"], at=late)
    sim.run(late.replace(hour=14), late.replace(hour=19))
    arrivals = db.df("SELECT table_name, rows_received / rows_expected AS ratio, arrived_at FROM data_arrivals "
                     "WHERE ts = ? ORDER BY arrived_at", [late]).set_index(["table_name", "arrived_at"])  # fmt: skip
    ratios = arrivals["ratio"]
    assert ratios["search_events"].iloc[0] < 0.9 and ratios["search_events"].iloc[-1] == pytest.approx(1.0)
    assert ratios["orders"].iloc[0] == pytest.approx(1.0) and ratios["ads"].iloc[0] == pytest.approx(1.0)
    repaired = db.df("SELECT sum(searches) AS s FROM fact_hourly WHERE ts = ?", [late]).iloc[0, 0]
    assert repaired == pytest.approx(
        db.df("SELECT sum(sessions) AS s FROM fact_hourly WHERE ts = ?", [late]).iloc[0, 0]
    )


def test_same_seed_same_numbers(make_sim):
    first, first_db = make_sim()
    second, second_db = make_sim()
    for sim in (first, second):
        sim.run(DAY.replace(hour=8), DAY.replace(hour=11))
    query = "SELECT sum(orders) AS o, sum(revenue_eur) AS r, sum(searches_with_click) AS c FROM fact_hourly"
    pd.testing.assert_frame_equal(first_db.df(query), second_db.df(query))
