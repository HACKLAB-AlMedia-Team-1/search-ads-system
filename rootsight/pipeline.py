"""The always-on loop: simulate the next hour, score it, investigate new failures, track incidents."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

from rootsight.agent.investigator import Investigator
from rootsight.agent.linkup import Linkup
from rootsight.agent.llm import LLMClient
from rootsight.agent.tools import Toolbox
from rootsight.config import Settings
from rootsight.graph.graph import MetricGraph
from rootsight.graph.onboarding import OnboardingResult, onboard
from rootsight.incidents.manager import IncidentEvent, IncidentManager
from rootsight.monitor.watcher import Case, Watcher
from rootsight.sim.clock import HOUR
from rootsight.sim.simulator import Simulator
from rootsight.store.db import Database


@dataclass
class StepResult:
    """Everything that happened in one simulated hour."""

    hour: datetime
    cases: list[Case] = field(default_factory=list)
    events: list[IncidentEvent] = field(default_factory=list)


class Pipeline:
    """Owns the simulator, watcher, investigator and incident manager and advances them hour by hour."""

    def __init__(
        self, settings: Settings, db: Database, sim: Simulator, graph: MetricGraph, custom_metrics: Path
    ):
        self.settings, self.db, self.sim, self.graph, self.custom_metrics = (
            settings,
            db,
            sim,
            graph,
            custom_metrics,
        )
        self.watcher = Watcher(db, graph)
        products = pd.read_parquet(
            settings.data_processed_dir / "products.parquet", columns=["market", "product_id", "title"]
        )
        titles = {(m, p): t for m, p, t in products.itertuples(index=False)}
        linkup = Linkup(settings, settings.data_processed_dir.parent / "cache" / "linkup")
        self.toolbox = Toolbox(db, graph, self.watcher, sim.funnel.pool, titles, linkup)
        self.llm = LLMClient(settings, db)
        self.investigator = Investigator(settings, self.toolbox, self.llm)
        self.incidents = IncidentManager(db, graph)
        last = db.df("SELECT max(ts) AS ts FROM fact_hourly")["ts"].iloc[0]
        self.now: datetime = settings.sim_start if pd.isna(last) else last.to_pydatetime() + HOUR
        self.sim.load_state(self.now)

    @classmethod
    def from_settings(cls, settings: Settings, db: Database, custom_metrics: Path | None = None) -> Pipeline:
        """Build everything from the processed data and the (backfilled) database.

        Metrics added at runtime are stored in `custom_metrics` (default `data/metrics_custom.yaml`) and reloaded from there.
        """
        custom = custom_metrics or settings.duckdb_path.parent / "metrics_custom.yaml"
        graph = MetricGraph.load(*([custom] if custom.is_file() else []))
        return cls(settings, db, Simulator.from_settings(settings, db), graph, custom)

    def add_metric(self, name: str, description: str, sql: str) -> OnboardingResult:
        """Place a new metric in the graph (validated in code); the watcher scores it from the next tick."""
        result = onboard(self.db, self.graph, name, description, sql, self.now, self.llm, self.custom_metrics)
        if result.added:
            self.watcher.pin(name)
        return result

    def _impact(self, case: Case, segment: dict[str, str]) -> dict:
        self.toolbox.start(case)
        return self.toolbox.estimate_impact(segment)

    def step(self) -> StepResult:
        """Simulate the next hour, score it, and handle the cases the watcher raised."""
        hour = self.now
        self.sim.tick(hour)
        cases = self.watcher.run_tick(hour)
        events = [
            self.incidents.process(c, self.investigator.run, self._impact)
            for c in cases
            if c.kind == "failure"
        ]
        events += self.incidents.close_stale(hour)
        self.now = hour + HOUR
        return StepResult(hour, cases, events)

    def run_until(self, end: datetime) -> list[StepResult]:
        """Step until `now` reaches `end`."""
        results = []
        while self.now < end:
            results.append(self.step())
        return results
