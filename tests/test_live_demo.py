"""Live demo: the real shopper is counted in the numbers, tool results read as sentences, top sellers per query,
incidents close only after measured normal hours, the ad budget on push days and new days, product pictures."""

import copy
import importlib
import json
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree

import numpy as np
import pandas as pd
import pytest

from rootsight.agent.evidence import SUPPORTED
from rootsight.agent.report import Report, step_summary
from rootsight.graph.graph import MetricGraph
from rootsight.incidents.manager import Incident, IncidentManager
from rootsight.monitor.watcher import Case
from rootsight.sim.ads import CAMPAIGNS, AdPacer
from rootsight.sim.faults import AD_PACING_RUNAWAY, CAMPAIGN_PUSH, Fault, FaultRegistry
from rootsight.sim.simulator import SHOPPER_COLUMNS, SHOPPER_MIN, SHOPPER_SHARE, SHOPPER_WEIGHT, Simulator
from rootsight.sim.users import QueryPool
from rootsight.store.db import Database

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))  # the shop's drawing code is not a package

T0 = datetime(2026, 11, 21, 10)  # a Saturday morning
H, DAY = timedelta(hours=1), timedelta(days=1)
INCIDENT, SEGMENT = 7, {"market": "DE"}
XML_NAMESPACES = ("http://www.w3.org/2000/svg", "http://www.w3.org/1999/xlink")


@pytest.fixture(scope="module")
def graph():
    return MetricGraph.load()


@pytest.fixture(scope="module")
def pictures():
    """`app/pictures.py`, imported here so that a broken import fails only the picture tests."""
    return importlib.import_module("pictures")


# ---------- the real shopper in the simulated numbers ----------


@pytest.fixture
def shop_sim():
    """A simulator that has only its shopper counter: counting the shopper needs no engine and no database."""
    sim = Simulator.__new__(Simulator)
    sim._shopper = Counter()
    return sim


def shop_hour(searches=400.0, market="DE", platform="web", source="organic"):
    """One hand-made hourly fact row: a tenth of the searches found nothing, every other number is above zero."""
    empty = searches / 10
    row = {"market": market, "platform": platform, "source": source, "sessions": searches, "searches": searches,
           "zero_result_searches": empty}  # fmt: skip
    row.update({column: (searches - empty) * (k + 1) / 20 for k, column in enumerate(SHOPPER_COLUMNS)})
    return row


def per_found_search(row, column):
    return row[column] / (row["searches"] - row["zero_result_searches"])


def search_at_the_shop(sim, found, market="DE", platform="web"):
    """What the web shop logs for one search of the real person: 'search', plus 'zero_result' when nothing came back."""
    sim.shopper_action("search", market, platform)
    if not found:
        sim.shopper_action("zero_result", market, platform)


def test_an_empty_search_means_a_crowd_of_this_hours_shoppers_found_nothing_too(shop_sim):
    facts = [shop_hour(), shop_hour(source="paid"), shop_hour(platform="android"), shop_hour(market="US")]
    before = copy.deepcopy(facts)
    search_at_the_shop(shop_sim, found=False)
    shop_sim._count_shopper(facts)
    row, was = facts[0], before[0]
    assert row["searches"] == was["searches"] and row["sessions"] == was["sessions"]  # no traffic spike
    assert row["zero_result_searches"] == pytest.approx(40 + 40)
    for column in SHOPPER_COLUMNS:  # fewer successful searchers: fewer clicks, carts and orders, at the same rates
        if column != "bounces":
            assert row[column] < was[column], column
            assert per_found_search(row, column) == pytest.approx(per_found_search(was, column)), column
    assert facts[1:] == before[1:]  # the paid row, the other platform and the other market are untouched


def test_a_search_that_found_products_means_a_crowd_that_would_have_found_nothing_found_products(shop_sim):
    facts = [shop_hour(), shop_hour(source="paid")]
    before = copy.deepcopy(facts)
    search_at_the_shop(shop_sim, found=True)
    shop_sim._count_shopper(facts)
    row, was = facts[0], before[0]
    assert row["searches"] == was["searches"] and row["sessions"] == was["sessions"]
    assert row["zero_result_searches"] == pytest.approx(0)  # all 40 empty searches of the hour are turned around
    for column in SHOPPER_COLUMNS:  # searches_with_click, orders, revenue_eur, ...
        if column != "bounces":
            assert row[column] > was[column], column
            assert per_found_search(row, column) == pytest.approx(per_found_search(was, column)), column
    assert row["revenue_eur"] / row["orders"] == pytest.approx(was["revenue_eur"] / was["orders"])
    assert facts[1] == before[1]


def test_a_good_and_an_empty_search_in_the_same_hour_cancel_out(shop_sim):
    facts = [shop_hour()]
    was = dict(facts[0])
    search_at_the_shop(shop_sim, found=True)
    search_at_the_shop(shop_sim, found=False)
    shop_sim._count_shopper(facts)
    assert facts[0] == pytest.approx(was)


@pytest.mark.parametrize(("searches", "crowd"), [(400, SHOPPER_SHARE * 400), (5000, SHOPPER_WEIGHT), (5, SHOPPER_MIN)])  # fmt: skip
def test_one_action_stands_for_a_tenth_of_the_hours_shoppers_at_least_1_and_at_most_100(shop_sim, searches, crowd):
    assert (SHOPPER_SHARE * 400, SHOPPER_WEIGHT, SHOPPER_MIN) == (pytest.approx(40), 100, 1)
    facts = [shop_hour(float(searches))]
    search_at_the_shop(shop_sim, found=False)
    shop_sim._count_shopper(facts)
    assert facts[0]["zero_result_searches"] - searches / 10 == pytest.approx(crowd)
    assert facts[0]["searches"] == searches


def test_a_checkout_adds_a_crowd_of_orders_each_worth_the_basket(shop_sim):
    facts = [shop_hour(), shop_hour(platform="ios")]
    before = copy.deepcopy(facts)
    shop_sim.shopper_action("checkout", "DE", "web", 25.0)
    shop_sim._count_shopper(facts)
    row, was = facts[0], before[0]
    assert row["orders"] == pytest.approx(was["orders"] + 40)
    assert row["checkouts"] == pytest.approx(was["checkouts"] + 40)
    assert row["revenue_eur"] == pytest.approx(was["revenue_eur"] + 40 * 25.0)
    assert row["searches"] == was["searches"] and row["sessions"] == was["sessions"]  # buying is not searching
    assert facts[1] == before[1]


def test_two_checkouts_add_up_their_baskets(shop_sim):
    facts = [shop_hour()]
    was = dict(facts[0])
    shop_sim.shopper_action("checkout", "DE", "web", 25.0)
    shop_sim.shopper_action("checkout", "DE", "web", 15.0)
    shop_sim._count_shopper(facts)
    assert facts[0]["orders"] == pytest.approx(was["orders"] + 2 * 40)
    assert facts[0]["revenue_eur"] == pytest.approx(was["revenue_eur"] + 40 * (25.0 + 15.0))


def test_cart_actions_add_carts_and_sold_out_errors(shop_sim):
    facts = [shop_hour()]
    was = dict(facts[0])
    shop_sim.shopper_action("add_to_cart", "DE", "web")
    shop_sim.shopper_action("add_to_cart", "DE", "web")
    shop_sim.shopper_action("cart_unavailable", "DE", "web")
    shop_sim._count_shopper(facts)
    assert facts[0]["carts"] == pytest.approx(was["carts"] + 2 * 40)
    assert facts[0]["cart_unavailable_errors"] == pytest.approx(was["cart_unavailable_errors"] + 40)
    assert facts[0]["orders"] == was["orders"] and facts[0]["searches"] == was["searches"]


def test_the_shoppers_actions_are_counted_in_one_hour_only(shop_sim):
    facts = [shop_hour()]
    search_at_the_shop(shop_sim, found=False)
    shop_sim.shopper_action("checkout", "DE", "web", 25.0)
    shop_sim._count_shopper(facts)
    assert facts != [shop_hour()]
    counted = copy.deepcopy(facts)
    shop_sim._count_shopper(facts)  # nothing is pending any more
    assert facts == counted
    next_hour = [shop_hour()]
    shop_sim._count_shopper(next_hour)
    assert next_hour == [shop_hour()]


# ---------- one sentence per tool result ----------


def is_plain_sentence(text):
    return bool(text) and text.endswith(".") and not set(text) & set('{}[]"')


def test_a_metric_result_is_told_in_the_metrics_own_unit(graph):
    hours = [{"hour": "21 08:00", "actual": 0.051, "expected": 0.05, "z": 0.2},
             {"hour": "21 09:00", "actual": 0.31, "expected": 0.052, "z": 9.4}]  # fmt: skip
    result = {"metric": "zero_result_rate", "segment": {"market": "DE"}, "hours": hours, "onset": "2026-11-21T09:00:00"}
    line = step_summary("get_metric", result, graph)
    assert graph.metric("zero_result_rate").unit == "share"
    assert is_plain_sentence(line) and line.startswith("zero_result_rate")
    assert "31.0%" in line and "5.2%" in line and "0.31" not in line  # the latest hour, as percentages
    assert "2026-11-21 09:00" in line  # since when it is unusual
    calm = step_summary("get_metric", {**result, "onset": None}, graph)
    assert is_plain_sentence(calm) and "31.0%" in calm and "2026" not in calm
    assert is_plain_sentence(step_summary("get_metric", {**result, "hours": [], "onset": None}, graph))


def test_a_drill_down_result_names_the_dimension_and_the_value_that_explains_most(graph):
    segments = [{"value": "android", "actual": 0.42, "expected": 0.05, "share_pct": 96.5, "z": 12.0},
                {"value": "ios", "actual": 0.06, "expected": 0.05, "share_pct": 3.5, "z": 0.8}]  # fmt: skip
    result = {"metric": "zero_result_rate", "dimension": "platform", "segments": segments}
    line = step_summary("drill_down", result, graph)
    assert is_plain_sentence(line) and line.startswith("platform = android")
    assert "96.5%" in line and "42.0%" in line and "5.0%" in line and "ios" not in line


def test_a_decompose_result_names_the_biggest_factor_or_says_there_is_nothing_to_split(graph):
    factors = [{"factor": "orders", "actual": 120.0, "expected": 300.0, "share_pct": 91.0},
               {"factor": "aov", "actual": 28.0, "expected": 30.0, "share_pct": 9.0}]  # fmt: skip
    line = step_summary("decompose", {"metric": "revenue", "factors": factors}, graph)
    assert is_plain_sentence(line) and line.startswith("orders") and "91%" in line and "120.0" in line and "300.0" in line
    assert is_plain_sentence(step_summary("decompose", {"metric": "orders", "formula": None}, graph))


def test_an_ad_pacing_result_says_the_budget_and_the_hour_it_ran_out(graph):
    result = {"campaign": "CMP-DE", "budget_eur": 250.0, "spent_eur": 250.0, "budget_exhausted_at": "11:00",
              "hours": [{"hour": "09:00", "planned": 10.4, "actual": 31.0}]}  # fmt: skip
    line = step_summary("ad_pacing", result, graph)
    assert is_plain_sentence(line) and "€250" in line and "11:00" in line
    on_plan = step_summary("ad_pacing", {**result, "spent_eur": 96.4, "budget_exhausted_at": None}, graph)
    assert is_plain_sentence(on_plan) and "€96.4" in on_plan and "€250" in on_plan and "ran out" not in on_plan


def test_a_purchase_order_result_names_the_overdue_order(graph):
    on_time = {"po_id": "PO-ES-111803", "created": "15 Nov 03:00", "due": "18 Nov 03:00", "qty_needed": 4000,
               "qty_ordered": 4800, "qty_received": 4800, "overdue": False}  # fmt: skip
    late = {**on_time, "po_id": "PO-ES-112109", "due": "21 Nov 09:00", "qty_received": 0, "overdue": True}
    line = step_summary("purchase_orders", {"market": "ES", "orders": [on_time, late]}, graph)
    assert is_plain_sentence(line) and "PO-ES-112109" in line and "overdue" in line
    assert "4,800" in line and "21 Nov 09:00" in line and "PO-ES-111803" not in line
    fine = step_summary("purchase_orders", {"market": "ES", "orders": [on_time]}, graph)
    assert is_plain_sentence(fine) and "PO-ES" not in fine and "on time" in fine


@pytest.mark.parametrize(
    ("tool", "result", "said"),
    [
        ("get_events", {"events": [{"event_id": 3, "ts": "21 08:55", "type": "release", "component": "search-ranker",
                                    "detail": "deployed v2"}]}, "search-ranker"),
        ("check_completeness", {"table": "search_events", "hours": [{"hour": "21 08:00", "ratio": 1.0},
                                                                    {"hour": "21 09:00", "ratio": 0.62}]}, "62%"),
        ("sample_searches", {"samples": [{"query": "usb kabel", "zero_result": True},
                                         {"query": "schuhe", "zero_result": False}]}, "1 of them"),
        ("calendar_lookup", {"entries": [{"name": "Black Friday push", "kind": "campaign", "effect": {}}]}, "Black Friday push"),
        ("calendar_lookup", {"entries": []}, "No planned event"),
        ("estimate_impact", {"hours": 2, "lost_orders": 12.4, "lost_revenue_eur": 340.0, "wasted_ad_spend_eur": 0.0,
                             "ad_spend_over_plan_eur": 0.0}, "12 lost orders"),
    ],
)  # fmt: skip
def test_other_tool_results_are_one_plain_sentence_too(graph, tool, result, said):
    line = step_summary(tool, result, graph)
    assert is_plain_sentence(line) and said in line


def test_a_failed_tool_call_is_reported_as_an_error_sentence(graph):
    line = step_summary("drill_down", {"error": "zero_result_rate cannot be split by colour"}, graph)
    assert line.startswith("The tool could not answer") and "cannot be split by colour" in line and "{" not in line
    assert "KeyError" in step_summary("get_metric", {"error": "KeyError: 'nope'"}, graph)


@pytest.mark.parametrize(
    ("tool", "result"),
    [
        ("no_such_tool", {"answer": 42}),
        ("finish", {"done": True}),
        ("get_metric", {}),
        ("get_metric", None),
        ("get_metric", {"metric": "zero_result_rate", "hours": [{"actual": "a lot", "expected": 0.05}]}),
        ("drill_down", {"metric": "zero_result_rate", "segments": [{"value": "android"}]}),
        ("ad_pacing", {"campaign": "CMP-DE", "hours": []}),
        ("purchase_orders", {"orders": [{}]}),
        ("component_health", {"health": "down"}),
    ],
)
def test_an_unknown_tool_or_a_malformed_result_gives_no_sentence_and_no_exception(graph, tool, result):
    assert step_summary(tool, result, graph) == ""


# ---------- top sellers per query ----------


@pytest.fixture
def tiny_pool():
    """Four US queries (searched 9, 7, 5 and 1 times) and one Spanish query, with a few labelled products."""
    queries = pd.DataFrame(
        {"market": ["US", "US", "US", "US", "ES"], "query_id": [1, 2, 3, 4, 5], "weight": [5.0, 9.0, 1.0, 7.0, 3.0],
         "query": ["usb cable", "red shoes", "desk lamp", "garden hose", "zapatillas"]}
    )  # fmt: skip
    labels = pd.DataFrame(
        [("US", 1, "P1", "E"), ("US", 1, "P2", "S"), ("US", 1, "P3", "E"), ("US", 2, "P3", "E"), ("US", 2, "P4", "I"),
         ("US", 3, "P5", "E"), ("US", 4, "P6", "C"), ("ES", 5, "P7", "E")],
        columns=["market", "query_id", "product_id", "esci_label"],
    )  # fmt: skip
    return QueryPool(queries, labels)


def test_top_queries_come_most_searched_first_each_with_its_exact_products(tiny_pool):
    top = tiny_pool.top_exact_by_query("US", 3)
    assert list(top) == ["red shoes", "garden hose", "usb cable"]  # 'desk lamp' is searched least and left out
    assert top == {"red shoes": ["P3"], "garden hose": [], "usb cable": ["P1", "P3"]}  # only label E counts
    assert list(tiny_pool.top_exact_by_query("US", 1)) == ["red shoes"]
    assert tiny_pool.top_exact_by_query("ES", 10) == {"zapatillas": ["P7"]}


@pytest.mark.parametrize(("market", "n", "expected"), [("US", 3, {"P1", "P3"}), ("US", 4, {"P1", "P3", "P5"}),
                                                       ("US", 1, {"P3"}), ("ES", 2, {"P7"})])  # fmt: skip
def test_top_sellers_are_exactly_the_exact_products_of_the_top_queries(tiny_pool, market, n, expected):
    by_query = tiny_pool.top_exact_by_query(market, n)
    assert tiny_pool.top_exact_products(market, n) == {p for products in by_query.values() for p in products}
    assert tiny_pool.top_exact_products(market, n) == expected


# ---------- incidents close after three measured normal hours ----------


def manager_with_open_incident(graph, last_seen=T0):
    """An incident manager on an empty database holding one open incident: zero results in Germany, last seen at `last_seen`."""
    db = Database(":memory:")
    manager = IncidentManager(db, graph)
    fingerprint = f"zero_result_rate|{json.dumps(SEGMENT)}|android-app"
    meta = {"metrics": ["zero_result_rate"], "notified_impact": 0.0}
    db.execute(
        "INSERT INTO incidents VALUES (?, ?, 'open', ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [INCIDENT, fingerprint, T0 - 2 * H, last_seen, "zero_result_rate", json.dumps(SEGMENT), "android-app", SUPPORTED,
         0.0, 0.0, 0.0, "", json.dumps(meta)],
    )  # fmt: skip
    manager._open[INCIDENT] = Incident(INCIDENT, fingerprint, T0 - 2 * H, last_seen, dict(SEGMENT), {"zero_result_rate"},
                                       0.0, "android-app")  # fmt: skip
    return manager, db


def stored(db, incident_id=INCIDENT):
    """(status, resolved_at) of an incident as written in the database."""
    frame = db.df("SELECT status, resolved_at FROM incidents WHERE incident_id = ?", [incident_id])
    resolved_at = frame["resolved_at"].iloc[0]
    return frame["status"].iloc[0], None if pd.isna(resolved_at) else pd.Timestamp(resolved_at).to_pydatetime()


def always_measured(metric, segment, hour):
    return True


def kinds(events):
    return [(e.kind, e.incident_id) for e in events]


def test_an_open_incident_is_resolved_at_the_third_normal_hour_without_a_matching_case(graph):
    manager, db = manager_with_open_incident(graph)
    assert manager.close_stale(T0, always_measured) == []  # the hour of the last matching case is not a quiet hour
    assert manager.close_stale(T0 + H, always_measured) == []
    assert manager.close_stale(T0 + 2 * H, always_measured) == []
    assert stored(db) == ("open", None)
    events = manager.close_stale(T0 + 3 * H, always_measured)
    assert kinds(events) == [("resolved", INCIDENT)] and events[0].notify
    assert stored(db) == ("resolved", T0 + H)  # it was over right after the last hour it was seen
    assert manager.close_stale(T0 + 4 * H, always_measured) == []  # and it is announced once


def test_night_hours_with_too_little_data_do_not_count_as_normal_hours(graph):
    manager, db = manager_with_open_incident(graph)
    night, asked = {T0 + H, T0 + 2 * H}, []

    def measured(metric, segment, hour):
        asked.append((metric, segment, hour))
        return hour not in night

    for k in (1, 2, 3, 4):  # two night hours that say nothing, then two normal hours
        assert manager.close_stale(T0 + k * H, measured) == []
        assert stored(db) == ("open", None)
    assert kinds(manager.close_stale(T0 + 5 * H, measured)) == [("resolved", INCIDENT)]  # the third measured hour
    assert stored(db)[0] == "resolved"
    assert asked == [("zero_result_rate", SEGMENT, T0 + k * H) for k in (1, 2, 3, 4, 5)]


def test_without_a_measured_check_every_hour_counts_as_normal(graph):
    manager, db = manager_with_open_incident(graph)
    assert manager.close_stale(T0 + H) == [] and manager.close_stale(T0 + 2 * H) == []
    assert stored(db) == ("open", None)
    assert kinds(manager.close_stale(T0 + 3 * H)) == [("resolved", INCIDENT)]
    assert stored(db) == ("resolved", T0 + H)


def test_a_matching_case_starts_the_count_of_normal_hours_again(graph):
    manager, db = manager_with_open_incident(graph)
    assert manager.close_stale(T0 + H, always_measured) == [] and manager.close_stale(T0 + 2 * H, always_measured) == []
    manager._open[INCIDENT].last_seen = T0 + 3 * H  # what `process` does when a case matches the incident in that hour
    for k in (3, 4, 5):
        assert manager.close_stale(T0 + k * H, always_measured) == []
    assert manager._open[INCIDENT].quiet_hours == 2 and stored(db) == ("open", None)
    assert kinds(manager.close_stale(T0 + 6 * H, always_measured)) == [("resolved", INCIDENT)]
    assert stored(db) == ("resolved", T0 + 4 * H)


def same_failure_again(manager, at):
    """Feed the manager a new failure case with the same cause in the same place as the hand-made incident."""
    impact = {"hours": 1, "lost_orders": 0.0, "lost_revenue_eur": 0.0, "wasted_ad_spend_eur": 0.0, "ad_spend_over_plan_eur": 0.0}
    report = Report(case_id="C2", headline="zero_result_rate above expected", onset=f"{at:%Y-%m-%dT%H:%M}", scope=dict(SEGMENT),
                    cause="Android release sends an empty stock filter", cause_component="android-app", status=SUPPORTED,
                    impact=impact, checklist=[], rejected=[], not_rejected=[], trail=[], uncertain=[],
                    next_action="Halt the rollout.")  # fmt: skip
    case = Case("C2", at, "failure", "zero_result_rate above expected", "zero_result_rate", dict(SEGMENT), at, 1.0)
    return manager.process(case, lambda _case: report, lambda _case, _segment: impact)


def test_the_same_cause_coming_back_within_a_day_reopens_the_resolved_incident(graph):
    manager, db = manager_with_open_incident(graph)
    assert [kinds(manager.close_stale(T0 + k * H)) for k in (1, 2, 3)] == [[], [], [("resolved", INCIDENT)]]
    event = same_failure_again(manager, T0 + 5 * H)
    assert (event.kind, event.incident_id) == ("reopened", INCIDENT)
    assert stored(db) == ("open", None) and db.df("SELECT count(*) AS n FROM incidents")["n"].iloc[0] == 1


def test_an_incident_fixed_by_a_person_still_closes_by_itself_but_the_cause_coming_back_is_a_new_incident(graph):
    manager, db = manager_with_open_incident(graph)
    manager.fixed(INCIDENT)
    assert stored(db) == ("open", None)  # fixing the cause does not close it; the numbers have to be normal first
    assert [kinds(manager.close_stale(T0 + k * H)) for k in (1, 2, 3)] == [[], [], [("resolved", INCIDENT)]]
    event = same_failure_again(manager, T0 + 5 * H)
    assert event.kind == "opened" and event.incident_id != INCIDENT and event.report is not None
    assert stored(db) == ("resolved", T0 + H) and stored(db, event.incident_id) == ("open", None)


# ---------- the ad budget on push days and new days ----------


def test_the_daily_ad_budget_is_doubled_on_a_campaign_push_day_in_that_market_only():
    pacer, faults, rng = AdPacer(), FaultRegistry(), np.random.default_rng(1)
    faults.add(Fault(CAMPAIGN_PUSH, T0, T0 + DAY, {"market": "DE"}))
    row = pacer.step(T0, "DE", 1 / 24, faults, rng)
    pacer.step(T0, "US", 1 / 24, faults, rng)
    assert pacer.budget("DE", T0) == row["budget_daily_eur"] == 2 * CAMPAIGNS["DE"][1]
    assert pacer.budget("US", T0) == CAMPAIGNS["US"][1]
    pacer.step(T0 + DAY, "DE", 1 / 24, faults, rng)  # the push is over the next day
    assert pacer.budget("DE", T0 + DAY) == CAMPAIGNS["DE"][1]


def test_a_campaign_that_used_up_its_budget_delivers_again_on_the_next_day():
    pacer, faults, rng = AdPacer(), FaultRegistry(), np.random.default_rng(1)
    day = datetime(2026, 11, 21)
    faults.add(Fault(AD_PACING_RUNAWAY, day, day + DAY, {"market": "DE"}))
    for k in range(12):
        pacer.step(day + k * H, "DE", 1 / 24, faults, rng)
    assert not pacer.delivering("DE", day + 23 * H)  # nothing is left for the rest of that day
    assert pacer.delivering("DE", day + DAY) and pacer.spent("DE", day + DAY) == 0.0
    pacer.step(day + DAY, "DE", 1 / 24, faults, rng)
    assert pacer.delivering("DE", day + DAY)
    assert 0 < pacer.spent("DE", day + DAY) < pacer.budget("DE", day + DAY) / 2


# ---------- product pictures ----------


def without_namespaces(svg):
    for url in XML_NAMESPACES:
        svg = svg.replace(url, "")
    return svg


def test_a_product_picture_is_a_self_contained_svg_and_the_same_every_time(pictures):
    args = ("Wireless Bluetooth Headphones, Over Ear", "Black", "Sony", "B000TEST01")
    svg = pictures.product_picture(*args)
    assert isinstance(svg, str) and svg.startswith("<svg")
    assert ElementTree.fromstring(svg).tag.endswith("svg")
    assert svg == pictures.product_picture(*args)
    assert "<image" not in svg and "http" not in without_namespaces(svg)  # nothing is downloaded


def test_a_black_and_a_white_product_of_the_same_type_get_different_pictures(pictures):
    black = pictures.product_picture("Cotton Crew T-Shirt", "Black", "Hanes", "B000TEST02")
    white = pictures.product_picture("Cotton Crew T-Shirt", "White", "Hanes", "B000TEST02")
    assert black != white


@pytest.mark.parametrize(
    ("title", "colour", "brand"),
    [
        ("Cotton Crew T-Shirt", "", ""),
        ("Zapatillas deportivas para hombre", "", ""),
        ("Zapatillas deportivas para hombre", "Negro", "Adidas"),
        ("ワイヤレスイヤホン", "", ""),
        ("ワイヤレスイヤホン", "ブラック", "ソニー"),
        ("", "", ""),
    ],
)
def test_a_picture_is_drawn_for_any_title_language_and_for_missing_colour_or_brand(pictures, title, colour, brand):
    svg = pictures.product_picture(title, colour, brand, "B000TEST03")
    assert svg.startswith("<svg") and ElementTree.fromstring(svg).tag.endswith("svg")
    assert "<image" not in svg and "http" not in without_namespaces(svg)


def test_a_picture_stays_valid_xml_when_the_title_or_brand_has_special_characters(pictures):
    svg = pictures.product_picture('Salt & Pepper Grinder Set <2 Pack>, 5" tall', "Black & White", "Black & Decker", "B000TEST04")
    assert svg.startswith("<svg") and ElementTree.fromstring(svg).tag.endswith("svg")


def test_the_picture_type_follows_the_product_noun_not_an_adjective_or_a_colour(pictures):
    jersey = pictures.kind_of("Hanes Men's Jersey Pant, Light Steel, XX-Large")[0]
    hiking = pictures.kind_of("Men's Summer Lightweight Breathable Casual Hiking Running Pants")[0]
    lamp = pictures.kind_of("LED Bedside Lamp")[0]
    assert jersey == hiking and jersey != lamp
