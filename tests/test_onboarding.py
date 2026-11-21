"""Onboarding: the two demo metrics are placed, validated in code, and survive a reload."""

from datetime import datetime

import pytest

from rootsight.graph.graph import MetricGraph
from rootsight.graph.onboarding import onboard

END = datetime(2026, 11, 21)
NO_CLICK = "(SUM(searches) - SUM(searches_with_click)) / NULLIF(SUM(searches), 0) FROM fact_hourly"
WASTED = (
    "SUM(spend_eur * idle) / NULLIF(SUM(spend_eur), 0) FROM (SELECT a.ts, a.market, a.campaign_id, a.spend_eur, "
    "1 - f.clicked / NULLIF(f.searches, 0) AS idle FROM ads_hourly a JOIN (SELECT ts, market, "
    "SUM(searches_with_click) AS clicked, SUM(searches) AS searches FROM fact_hourly WHERE source = 'paid' "
    "GROUP BY ts, market) f ON a.ts = f.ts AND a.market = f.market) AS paid_idle"
)


def test_no_click_rate_becomes_the_opposite_child_of_search_ctr(history_db, tmp_path):
    graph, custom = MetricGraph.load(), tmp_path / "custom.yaml"
    result = onboard(
        history_db,
        graph,
        "no_click_search_rate",
        "Searches without a click",
        NO_CLICK,
        END,
        custom_file=custom,
    )
    assert result.added and not result.problems
    edge = next(p for p in result.proposals if p.source == "search_ctr")
    assert edge.relation == "opposite" and edge.status == "validated" and edge.r < -0.6
    assert "no_click_search_rate" in {n["metric"] for n in graph.neighbors("search_ctr")["effects"]}
    assert "no_click_search_rate" in MetricGraph.load(custom).specs


def test_wasted_spend_share_links_ads_and_search_and_flags_the_weak_edge(history_db):
    graph = MetricGraph.load()
    result = onboard(
        history_db, graph, "wasted_spend_share", "Ad spend on sessions that found nothing", WASTED, END
    )
    assert result.added, result.problems
    sources = {(p.source, p.target) for p in result.proposals}
    assert {
        ("ad_spend", "wasted_spend_share"),
        ("search_ctr", "wasted_spend_share"),
        ("wasted_spend_share", "roas"),
    } <= sources
    assert any(p.status == "ambiguous" for p in result.proposals)
    assert set(graph.metric("wasted_spend_share").dims) == {"market", "campaign_id"}


@pytest.mark.parametrize(
    ("name", "sql"), [("Bad Name", NO_CLICK), ("broken_metric", "SUM(nothing) FROM fact_hourly")]
)
def test_bad_input_is_reported_not_added(history_db, name, sql):
    result = onboard(history_db, MetricGraph.load(), name, "x", sql, END)
    assert not result.added and result.problems
