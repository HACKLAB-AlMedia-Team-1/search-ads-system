"""The always-on loop: simulate the next hour, score it (rules), let the model look at what rules cannot express,
investigate new failures (rules first, the model takes over), track incidents. Also: plan watches, answer questions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

from rootsight.agent.ask import Answer, current_anomalies, question_case, status_text, understand
from rootsight.agent.investigator import Investigator
from rootsight.agent.linkup import Linkup
from rootsight.agent.llm import LLMClient, LLMUnavailable
from rootsight.agent.tools import Toolbox
from rootsight.agent.watches import (
    PROBLEM,
    RULE,
    WAITING,
    Plan,
    Watch,
    WatchList,
    check_model_watch,
    plan_watch,
)
from rootsight.config import Settings
from rootsight.graph.graph import MetricGraph
from rootsight.graph.onboarding import OnboardingResult, edit_metric, onboard
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
        self.watches = WatchList(db)
        for watch in self.watches.all():  # rule watches survive a restart of the pipeline (not a demo reset)
            if watch.active and watch.kind == RULE and watch.metric in graph.specs:
                self.watcher.pin_segment(watch.metric, watch.segment)
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

    def add_metric(self, name: str, description: str, sql: str, plan: Plan | None = None) -> OnboardingResult:
        """Place a new metric in the graph (validated in code). It becomes a rule watch: scored from the next tick."""
        result = onboard(self.db, self.graph, name, description, sql, self.now, self.llm, self.custom_metrics)
        if result.added:
            self.watcher.pin(name)
            plan = plan or Plan(description or name, RULE, "Added as a new metric; the statistics score it every hour "
                                "(all traffic and every market).", name)  # fmt: skip
            self.watches.add(plan, self.now)
            if plan.segment:
                self.watcher.pin_segment(name, plan.segment)
        return result

    def edit_metric(self, name: str, description: str, sql: str) -> OnboardingResult:
        """Change an existing metric's description and SQL (saved to its YAML file); it is re-scored from the next tick."""
        result = edit_metric(self.db, self.graph, name, description, sql, self.now, self.custom_metrics)
        if result.added:
            self.watcher.forget_cache()
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
        events += self._model_watches(hour)
        events += self.incidents.close_stale(hour, self._measured)
        self.now = hour + HOUR
        return StepResult(hour, cases, events)

    # ---------- what the agent watches, and questions ----------

    def plan_watch(self, request: str) -> Plan:
        """How the agent would watch a request (rule if a metric can express it, else the model). Nothing starts yet."""
        return plan_watch(request, self.graph, self.llm, self.db, self.now)

    def add_watch(self, plan: Plan) -> tuple[Watch | None, list[str]]:
        """Start a planned watch. A model-written metric is placed in the graph first (validated like any new metric)."""
        if plan.new_metric:
            result = self.add_metric(plan.new_metric["name"], plan.new_metric["description"], plan.new_metric["sql"], plan)
            return (self.watches.all()[0], []) if result.added else (None, result.problems)
        watch = self.watches.add(plan, self.now)
        if watch.kind == RULE:
            self.watcher.pin_segment(watch.metric, watch.segment)
        return watch, []

    def watch_state(self, watch: Watch) -> str:
        """One line on how a watch stands now."""
        if not watch.active:
            return "stopped"
        if watch.kind == RULE:
            if watch.metric not in self.graph.specs:
                return "its metric was removed"
            hour = self.now - HOUR
            return status_text(self.graph, watch.metric, watch.segment, self.watcher.score_hour(watch.metric, watch.segment, hour), hour)
        if not self.llm.available:
            return WAITING
        if watch.last_check is None:
            return "the model looks at the next daytime hour"
        return f"{watch.last_check:%a %H:00}: {watch.last_verdict} - {watch.last_note}"

    def _model_watches(self, hour: datetime) -> list[IncidentEvent]:
        """Model watches that are due look at the data; a problem (checked in code) is investigated like any case."""
        if not self.llm.available:
            return []
        events = []
        for watch in self.watches.due(hour):
            try:
                verdict, note, case = check_model_watch(watch, self.toolbox, self.llm, hour)
            except LLMUnavailable as exc:
                verdict, note, case = "unclear", f"The model could not look ({exc}).", None
            self.watches.note(watch.watch_id, hour, verdict, note)
            if verdict == PROBLEM and case is not None:
                case.anomalies = current_anomalies(self.watcher, self.graph, case.root_metric, case.segment, hour)
                self.watcher.persist(hour, [case])
                events.append(self.incidents.process(case, self.investigator.run, self._impact))
        return events

    def ask(self, question: str, always: bool = False) -> Answer:
        """Answer 'why ...?' about the latest closed hour: find the number, score it, investigate it if it is unusual
        (or `always`). The investigation is the same as for any case: the rule recipe first, the model if the rules cannot confirm."""
        hour = self.now - HOUR
        metric, segment, by = understand(question, self.graph, self.llm, self.now)
        if metric is None:
            return Answer(question, "I could not tell which number you mean. Name one, e.g. orders, revenue, zero results, "
                          "ad spend, out of stock, relevance, and optionally a country or device.", understood_by=by)  # fmt: skip
        score = self.watcher.score_hour(metric, segment, hour)
        text = status_text(self.graph, metric, segment, score, hour)
        anomalies = current_anomalies(self.watcher, self.graph, metric, segment, hour)
        if not anomalies and not always:
            return Answer(question, text + " That is within its normal range, so there is nothing to investigate.", metric,
                          segment, score, understood_by=by)  # fmt: skip
        case = question_case(question, metric, segment, anomalies, hour)
        self.watcher.persist(hour, [case])
        report = self.investigator.run(case)
        return Answer(question, text, metric, segment, score, report, by)

    def _measured(self, metric: str, segment: dict[str, str], hour: datetime) -> bool:
        """Was there enough data in this hour to judge the metric? (A quiet night hour says nothing about a fault.)"""
        if metric not in self.graph.specs:
            return True
        dims = self.graph.metric(metric).dims
        return self.watcher.score_hour(metric, {k: v for k, v in segment.items() if k in dims}, hour) is not None

    def run_until(self, end: datetime) -> list[StepResult]:
        """Step until `now` reaches `end`."""
        results = []
        while self.now < end:
            results.append(self.step())
        return results
