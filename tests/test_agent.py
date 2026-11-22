"""Investigator + incidents on the full pipeline (offline, rule-based): right cause, one incident, then resolved."""

from datetime import datetime, timedelta

import pytest
from conftest import SETTINGS

from rootsight.agent.evidence import SUPPORTED

pytestmark = pytest.mark.integration
H = timedelta(hours=1)
SLOTS = {  # each run takes up to 11 h (fault + 5 h cool-down); the clock only moves forward
    "S1": datetime(2026, 11, 21, 12),
    "AD1": datetime(2026, 11, 22, 0),
    "S12": datetime(2026, 11, 22, 12),
    "S3": datetime(2026, 11, 22, 20),
    "S2": datetime(2026, 11, 23, 10),
    "S7": datetime(2026, 11, 23, 18),
    "S15": datetime(2026, 11, 24, 8),
    "INV1": datetime(2026, 11, 24, 20),
    "L1": datetime(2026, 11, 25, 10),
}


def events_until(live, end):
    return [e for r in live.run_until(end) for e in r.events]


@pytest.mark.parametrize("scenario", list(SLOTS))
def test_scenario_is_traced_to_its_cause_and_reported_once(live, scenario):
    start, spec = SLOTS[scenario], live.scenarios[scenario]
    assert [e for e in events_until(live, start) if e.kind == "opened"] == []
    live.sim.activate(spec, at=start)
    hours = 6 if scenario == "S1" else 3
    events = events_until(live, start + hours * H)
    opened = [e for e in events if e.kind == "opened"]
    assert len(opened) == 1, [(e.kind, e.case.headline) for e in events]
    report = opened[0].report
    assert report.cause_component == spec.event_log[0]["component"]
    assert report.status == SUPPORTED and len(report.rejected) >= 2
    assert len(report.trail) <= SETTINGS.max_tool_calls
    live.sim.stop_all(start + hours * H)
    after = events_until(live, start + (hours + 5) * H)
    mine = opened[
        0
    ].incident_id  # an earlier incident may reopen meanwhile (e.g. the ad budget burned that morning)
    assert [e.kind for e in after if e.kind == "resolved" and e.incident_id == mine] == ["resolved"]
    assert not [e for e in after if e.kind == "opened"]


def test_planned_and_late_data_do_not_create_incidents(live):
    ev1, dq1 = datetime(2026, 11, 26, 0), datetime(2026, 11, 26, 14)
    live.run_until(ev1)
    live.sim.activate(live.scenarios["EV1"], at=ev1)
    assert [e for e in events_until(live, ev1 + 8 * H) if e.kind != "resolved"] == []
    live.sim.stop_all(ev1 + 8 * H)
    live.run_until(dq1)
    live.sim.activate(live.scenarios["DQ1"], at=dq1)
    assert events_until(live, dq1 + 5 * H) == []
