"""Terminal demo: plays the whole story on a private copy of the backfilled history and narrates what the agent does."""

from __future__ import annotations

import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rootsight.agent.report import render
from rootsight.config import load_settings
from rootsight.graph.onboarding import OnboardingResult
from rootsight.logging_setup import setup_logging
from rootsight.pipeline import Pipeline
from rootsight.sim.faults import load_scenarios
from rootsight.store.db import Database

H = timedelta(hours=1)
NO_CLICK = "(SUM(searches) - SUM(searches_with_click)) / NULLIF(SUM(searches), 0) FROM fact_hourly"
WASTED = (
    "SUM(spend_eur * idle) / NULLIF(SUM(spend_eur), 0) FROM (SELECT a.ts, a.market, a.campaign_id, a.spend_eur, "
    "1 - f.clicked / NULLIF(f.searches, 0) AS idle FROM ads_hourly a JOIN (SELECT ts, market, SUM(searches_with_click) AS clicked, "
    "SUM(searches) AS searches FROM fact_hourly WHERE source = 'paid' GROUP BY ts, market) f ON a.ts = f.ts AND a.market = f.market) AS paid_idle"
)


def say(text: str) -> None:
    print(f"\n=== {text}")


def play(pipeline: Pipeline, end: datetime) -> None:
    """Run the pipeline to `end`, printing every notice the way a person would receive it."""
    for result in pipeline.run_until(end):
        for case in (c for c in result.cases if c.kind == "data_delay" or c.case_id.startswith("P")):
            print(f"[{result.hour:%a %H:%M}] INFO     {case.headline}")
        for event in result.events:
            if event.kind == "opened":
                print(f"[{result.hour:%a %H:%M}] ALERT    incident #{event.incident_id} opened\n")
                print(render(event.report))
            elif event.kind == "reopened":
                print(
                    f"[{result.hour:%a %H:%M}] REOPENED incident #{event.incident_id}: the same cause is back"
                )
            elif event.kind == "updated":
                print(
                    f"[{result.hour:%a %H:%M}] UPDATE   incident #{event.incident_id} got worse: {event.impact['lost_orders']} lost orders so far"
                )
            elif event.kind == "resolved":
                print(f"[{result.hour:%a %H:%M}] RESOLVED incident #{event.incident_id} (normal for 3 hours)")


def show(result: OnboardingResult) -> None:
    print(
        f"added={result.added} dims={list(result.spec.dims) if result.spec else []} problems={result.problems}"
    )
    for p in result.proposals:
        print(f"  {p.source} -> {p.target} [{p.type}{' / ' + p.relation if p.relation else ''}] r={p.r and round(p.r, 2)} "
              f"confidence={p.confidence} {p.status.upper()}: {p.reason}")  # fmt: skip


def main() -> int:
    """Copy the backfill snapshot to data/demo.duckdb and play the storyline."""
    setup_logging(level=40)
    settings = load_settings()
    snapshot = settings.duckdb_path.with_suffix(".backfill.duckdb")
    if not snapshot.is_file():
        print("Run scripts/backfill.py first.")
        return 1
    demo_db = settings.duckdb_path.with_name("demo.duckdb")
    shutil.copy(snapshot, demo_db)
    custom = demo_db.with_name("demo_metrics.yaml")
    custom.unlink(missing_ok=True)
    pipeline = Pipeline.from_settings(settings, Database(demo_db), custom)
    scenarios, day = (
        load_scenarios(Path(__file__).resolve().parents[1] / "scenarios"),
        pipeline.now.replace(hour=0),
    )

    def inject(sid: str, at: datetime, hours: int) -> None:
        play(pipeline, at)
        pipeline.sim.activate(scenarios[sid], at=at)
        play(pipeline, at + hours * H)
        pipeline.sim.stop_all(at + hours * H)

    say(
        "Day 1 - Black Friday: marketing doubles the ad budget for a new audience (planned). NOT an incident."
    )
    inject("EV1", day, 24)
    say("Day 2, 12:00 - shopper journey, step 1: a config change breaks search for German queries.")
    inject("S12", day + 36 * H, 3)
    say(
        "Day 3, midnight - step 2: a release makes the German ad campaign ignore its hourly limits; the budget is gone by mid-morning."
    )
    inject("AD1", day + 48 * H, 12)
    say(
        "Day 4, 09:00 - step 3: the supplier delivery for the top sellers never arrived; they are out of stock."
    )
    inject("INV1", day + 81 * H, 4)
    say("Add two new metrics: the system places them in the graph and validates the links in code.")
    show(pipeline.add_metric("no_click_search_rate", "Share of searches without a click", NO_CLICK))
    show(
        pipeline.add_metric("wasted_spend_share", "Ad spend on sessions that found nothing to click", WASTED)
    )
    say(
        "Day 4, 18:00 - a different branch of the graph: a search-ranker release returns unrelated products everywhere."
    )
    inject("S1", day + 90 * H, 3)
    play(pipeline, day + 102 * H)
    print("\nDemo finished. Everything above was found without being told which scenario was running.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
