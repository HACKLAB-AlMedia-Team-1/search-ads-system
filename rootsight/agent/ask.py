"""Asking the agent: "why are orders down in Germany?" -> which number, is it unusual, and if so an investigation."""

from __future__ import annotations

import logging
import zlib
from dataclasses import dataclass, field
from datetime import datetime

from rootsight.agent.llm import LLMClient, LLMUnavailable
from rootsight.agent.report import Report, fmt
from rootsight.agent.watches import classify, find_segment, fit_segment, match_metric, where_words
from rootsight.graph.graph import MetricGraph
from rootsight.monitor.watcher import Z_ALARM, Anomaly, Case, Watcher
from rootsight.sim.clock import HOUR

logger = logging.getLogger(__name__)
MAX_RUN_HOURS = 12


@dataclass
class Answer:
    """The agent's answer to a question: the number it understood, how it stands now, and the report if it investigated."""

    question: str
    text: str
    metric: str | None = None
    segment: dict[str, str] = field(default_factory=dict)
    score: dict | None = None
    report: Report | None = None
    understood_by: str = "rules"  # rules | model


def understand(
    question: str, graph: MetricGraph, llm: LLMClient, now: datetime
) -> tuple[str | None, dict[str, str], str]:
    """(metric, segment, by): plain words first; the model only when the words name no metric."""
    metric, _ = match_metric(question, graph)
    if metric:
        return metric, fit_segment(graph, metric, find_segment(question)), "rules"
    if llm.available:
        try:
            choice = classify(llm, graph, question, now)
            if choice["kind"] == "metric":
                return choice["metric"], choice["segment"], "model"
        except LLMUnavailable as exc:
            logger.warning("The model could not read the question (%s)", exc)
    return None, find_segment(question), "rules"


def current_anomalies(
    watcher: Watcher, graph: MetricGraph, metric: str, segment: dict[str, str], hour: datetime
) -> list[Anomaly]:
    """The metric and everything upstream of it that is unusual (harmful direction) in this segment at this hour."""
    found = []
    for name in [metric, *sorted(graph.upstream_names(metric))]:
        seg = fit_segment(graph, name, segment)
        score = watcher.score_hour(name, seg, hour)
        if score is None or abs(score["z"]) < Z_ALARM or not watcher.is_bad(name, score["z"]):
            continue
        run = 1
        while run < MAX_RUN_HOURS:
            earlier = watcher.score_hour(name, seg, hour - HOUR * run)
            if earlier is None or abs(earlier["z"]) < Z_ALARM or (earlier["z"] > 0) != (score["z"] > 0):
                break
            run += 1
        weight = graph.metric(name).business_weight
        found.append(Anomaly(hour, name, seg, score["actual"], score["expected"], score["z"], abs(score["z"]) * weight, run,
                             score["planned"]))  # fmt: skip
    return sorted(found, key=lambda a: -a.attention)


def question_case(
    question: str, metric: str, segment: dict[str, str], anomalies: list[Anomaly], hour: datetime
) -> Case:
    """A case built from a question, so the investigator can work on it like on one the watcher raised."""
    onset = min((a.onset for a in anomalies), default=hour)
    return Case(f"Q{hour:%Y%m%d%H}-{zlib.crc32(question.encode()) % 10_000:04d}", hour, "question", f"Question: {question}", metric,
                segment, onset, max((a.attention for a in anomalies), default=0.0), anomalies, {"question": question})  # fmt: skip


def status_text(
    graph: MetricGraph, metric: str, segment: dict[str, str], score: dict | None, hour: datetime
) -> str:
    """One sentence on how the metric stands in the latest closed hour."""
    spec = graph.metric(metric)
    if score is None:
        return (f"{spec.description} (`{metric}`, {where_words(segment)}) cannot be judged for {hour:%H:00}: too few shoppers "
                "or late data in that hour.")  # fmt: skip
    return (f"{spec.description} (`{metric}`, {where_words(segment)}) at {hour:%H:00}: {fmt(score['actual'], spec.unit)} "
            f"against a normal {fmt(score['expected'], spec.unit)} ({score['z']:+.1f} standard deviations).")  # fmt: skip
