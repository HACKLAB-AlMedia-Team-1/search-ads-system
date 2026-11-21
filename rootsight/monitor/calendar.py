"""Planned events (campaigns etc.): adjust what is expected and tag the metrics they explain."""

from __future__ import annotations

import json
from datetime import datetime

from rootsight.graph.graph import MetricGraph
from rootsight.store.db import Database

EXPLAINING_EDGES = ("formula", "may_be_caused_by")
SCOPE_DIMS = ("market", "platform")


def entries_at(db: Database, ts: datetime) -> list[dict]:
    """All calendar entries covering `ts`, with their scope and expected effect decoded."""
    rows = db.df("SELECT * FROM calendar WHERE start_ts <= ? AND end_ts > ?", [ts, ts])
    return [
        {
            "name": r.name,
            "kind": r.kind,
            "scope": json.loads(r.scope_json),
            "effect": json.loads(r.expected_effect_json),
        }
        for r in rows.itertuples()
    ]


def entries_for(entries: list[dict], segment: dict[str, str]) -> list[dict]:
    """The entries whose scope includes the segment (a dimension the segment does not fix always matches)."""
    return [
        e
        for e in entries
        if all(
            e["scope"].get(d, "all") in ("all", segment.get(d)) or segment.get(d) is None for d in SCOPE_DIMS
        )
    ]


def expected_factor(entries: list[dict], metric: str) -> float:
    """Multiplier that planned events apply to the expected value of a metric (1.0 = none)."""
    factor = 1.0
    for entry in entries:
        factor *= float(entry["effect"].get(metric, 1.0))
    return factor


def explained_metrics(entries: list[dict], graph: MetricGraph) -> set[str]:
    """Metrics whose change a planned event explains: the metrics it names and what they feed into."""
    explained: set[str] = set()
    for entry in entries:
        for metric in entry["effect"]:
            explained.add(metric)
            stack = [metric]
            while stack:
                for _, v, d in graph.graph.out_edges(stack.pop(), data=True):
                    if d["type"] in EXPLAINING_EDGES and v not in explained:
                        explained.add(v)
                        stack.append(v)
    return explained
