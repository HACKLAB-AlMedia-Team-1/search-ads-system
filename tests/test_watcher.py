"""Watcher on the full pipeline: faults are found fast, innocent changes are not failures."""

from datetime import datetime, timedelta

import pytest

pytestmark = pytest.mark.integration
H = timedelta(hours=1)


def run_until(live, end):
    """Step the pipeline and return every case the watcher raised on the way."""
    return [c for r in live.run_until(end) for c in r.cases]


def failures(cases):
    return [c for c in cases if c.kind == "failure"]


def inject(live, scenario_id, start):
    """Run clean up to `start`, then switch the scenario on there."""
    clean = run_until(live, start)
    live.sim.activate(live.scenarios[scenario_id], at=start)
    return clean


def metrics(cases):
    return {a.metric for c in failures(cases) for a in c.anomalies}


def test_clean_hours_raise_no_failure_case(live):
    assert failures(run_until(live, datetime(2026, 11, 21, 12))) == []


@pytest.mark.parametrize(
    ("scenario", "start", "expected"),
    [
        ("S1", datetime(2026, 11, 21, 12), {"orders", "search_ctr", "relevance_at_10", "ndcg_at_10"}),
        (
            "S12",
            datetime(2026, 11, 21, 16),
            {"search_ctr", "relevance_at_10", "ndcg_at_10", "zero_result_rate"},
        ),
        ("S3", datetime(2026, 11, 21, 20), {"search_ctr", "zero_result_rate", "orders"}),
        ("AD1", datetime(2026, 11, 22, 0), {"ad_spend", "pacing_ratio", "paid_clicks"}),
    ],
)
def test_fault_is_found_within_two_hours(live, scenario, start, expected):
    assert failures(inject(live, scenario, start)) == []
    cases = run_until(live, start + 2 * H)
    assert metrics(cases) & expected, [c.headline for c in cases]
    live.sim.stop_all(start + 2 * H)
    run_until(live, start + 4 * H)


def test_planned_campaign_is_not_a_failure(live):
    start = datetime(2026, 11, 22, 4)
    inject(live, "EV1", start)
    cases = run_until(live, start + 8 * H)
    assert failures(cases) == [], [c.headline for c in failures(cases)]
    assert any(c.kind == "planned" for c in cases)
    live.sim.stop_all(start + 8 * H)


def test_late_data_is_a_notice_not_a_business_case(live):
    start = datetime(2026, 11, 22, 14)
    run_until(live, start)
    live.sim.activate(live.scenarios["DQ1"], at=start)
    cases = run_until(live, start + 5 * H)
    assert [c.root_metric for c in cases if c.kind == "data_delay"] == ["search_events"]
    assert failures(cases) == []
    status = live.db.df("SELECT status FROM cases WHERE kind = 'data_delay'")["status"].iloc[0]
    assert status == "resolved"
