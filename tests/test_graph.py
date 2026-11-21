"""Metric graph: structure, queries and validation against the backfilled history."""

from datetime import datetime

import networkx as nx
import pytest

from rootsight.graph.graph import EDGE_TYPES, MetricGraph
from rootsight.graph.series import metric_series, metric_total
from rootsight.graph.validate import check_causes, validate_dims, validate_formulas

END = datetime(2026, 11, 21)


@pytest.fixture(scope="module")
def graph():
    return MetricGraph.load()


def test_structure(graph):
    assert len(graph.graph) >= 30
    assert {d["type"] for _, _, d in graph.graph.edges(data=True)} == set(EDGE_TYPES)
    assert nx.is_directed_acyclic_graph(graph.graph)


def test_upstream_of_orders_covers_funnel_search_and_ads(graph):
    upstream = {u["metric"] for u in graph.upstream("orders")}
    assert {
        "search_ctr",
        "add_to_cart_rate",
        "relevance_at_10",
        "zero_result_rate",
        "index_doc_count",
    } <= upstream
    assert {"paid_sessions", "paid_clicks", "pacing_ratio"} <= upstream


def test_neighbors(graph):
    near = graph.neighbors("search_ctr")
    assert {c["metric"] for c in near["causes"]} == {
        "zero_result_rate",
        "relevance_at_10",
        "first_exact_position",
    }
    assert near["causes"][0]["confidence"] == 0.8
    assert {"market", "platform", "source"} == {s["dimension"] for s in near["split_by"]}
    assert graph.contexts_for("pacing_ratio")[0]["components"] == ["pacing-service"]


def test_formulas_hold_on_history(graph, history_db):
    checks = validate_formulas(graph, history_db, END)
    assert {c.subject for c in checks} >= {
        "orders",
        "revenue",
        "sessions",
        "roas",
        "ad_spend",
        "conversion_rate",
    }
    assert all(c.passed for c in checks), [c for c in checks if not c.passed]


def test_dims_exist_and_causes_are_reported(graph, history_db):
    assert all(c.passed for c in validate_dims(graph, history_db))
    assert len(check_causes(graph, history_db, END)) >= 20


def test_series_and_totals(graph, history_db):
    day = (datetime(2026, 11, 19), datetime(2026, 11, 20))
    hourly = metric_series(history_db, graph.metric("orders"), *day, segment={"market": "ES"})
    total = metric_total(history_db, graph.metric("orders"), *day, segment={"market": "ES"})
    assert len(hourly) == 24 and hourly["value"].sum() == pytest.approx(total["value"].iloc[0])
    by_platform = metric_total(history_db, graph.metric("search_ctr"), *day, by=["platform"])
    assert set(by_platform["platform"]) == {"android", "ios", "web"}
    with pytest.raises(ValueError):
        metric_total(history_db, graph.metric("index_doc_count"), *day, by=["platform"])
