"""The release / config / job event log: scenario entries plus harmless decoy events."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import numpy as np

from rootsight.sim.faults import Scenario

DECOYS = [
    ("release", "web-frontend", "3.4.1 rolled out 100%"),
    ("config", "email-templates", "spring banner copy updated"),
    ("deploy", "recommendation-service", "2.9.3 deployed"),
    ("job", "sitemap-refresh", "completed ok"),
    ("release", "ios-app", "7.8.2 rolled out 100% (bug fixes)"),
    ("config", "checkout-banner", "free-shipping text changed"),
    ("deploy", "image-cdn", "cache purge completed"),
    ("job", "email-digest", "completed ok"),
]


def decoy_events(day: date, seed: int) -> list[dict]:
    """3-5 harmless events for a day (same on every run), each at a seeded time."""
    rng = np.random.default_rng([seed, day.toordinal()])
    picks = rng.choice(len(DECOYS), size=int(rng.integers(3, 6)), replace=False)
    minutes = rng.integers(7 * 60, 22 * 60, len(picks))
    midnight = datetime(day.year, day.month, day.day)
    return [
        {"ts": midnight + timedelta(minutes=int(m)), "type": DECOYS[i][0], "component": DECOYS[i][1],
         "detail": DECOYS[i][2], "scope_json": "{}"}
        for i, m in zip(picks, minutes, strict=True)
    ]  # fmt: skip


def events_between(start: datetime, end: datetime, seed: int) -> list[dict]:
    """Decoy events with `start <= ts < end` (the range may span two days)."""
    days = {start.date(), (end - timedelta(seconds=1)).date()}
    return [e for d in sorted(days) for e in decoy_events(d, seed) if start <= e["ts"] < end]


def scenario_event_rows(scenario: Scenario) -> list[dict]:
    """The event-log rows a scenario leaves behind (release, config change, job ...)."""
    scope = json.dumps(scenario.scope)
    return [
        {
            "ts": e["ts"],
            "type": e["type"],
            "component": e["component"],
            "detail": e["detail"],
            "scope_json": scope,
        }
        for e in scenario.event_log
    ]


def calendar_rows(scenario: Scenario) -> list[dict]:
    """The planned-event (calendar) rows of a scenario, if it has any."""
    return [
        {
            "start_ts": c["start_ts"],
            "end_ts": c["end_ts"],
            "name": c["name"],
            "kind": c["kind"],
            "scope_json": json.dumps(c.get("scope", {})),
            "expected_effect_json": json.dumps(c.get("expected_effect", {})),
        }
        for c in scenario.calendar
    ]
