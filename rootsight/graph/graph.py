"""The metric graph: metrics (nodes) and their relationships (typed edges), loaded from YAML."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx
import sqlglot
import yaml

DEFAULT_FILE = Path(__file__).with_name("metrics.yaml")
EDGE_TYPES = ("formula", "split_by", "funnel", "may_be_caused_by", "context")
CAUSAL_TYPES = ("formula", "funnel", "may_be_caused_by")


@dataclass(frozen=True)
class MetricSpec:
    """One metric: how to compute it, how to read it, and the edges declared on it."""

    name: str
    description: str
    sql: str
    kind: str
    unit: str
    dims: tuple[str, ...]
    business_weight: float
    bad_direction: str = "both"
    noise: str = "none"
    cv: float = 1.0
    min_spread: float = 0.0
    rel_floor: float = 0.05
    window_hours: int = 1
    edges: tuple[dict, ...] = field(default=(), compare=False)

    def parts(self) -> tuple[str, str, str]:
        """Split `"expr FROM source [WHERE cond]"` into (expression, source incl. joins, condition)."""
        select = sqlglot.parse_one(f"SELECT {self.sql}")
        where = select.args.get("where")
        bare = select.copy()
        bare.set("where", None)
        return (
            select.expressions[0].sql(),
            bare.sql().split(" FROM ", 1)[1],
            where.this.sql() if where else "",
        )


class MetricGraph:
    """All metrics plus a networkx MultiDiGraph. Edge u -> v always means "u composes, causes or affects v"."""

    def __init__(self, specs: dict[str, MetricSpec], contexts: dict[str, dict]):
        self.specs, self.contexts = specs, contexts
        self.platform_of = {
            c: plat for ctx in contexts.values() for c, plat in (ctx.get("platform_of") or {}).items()
        }
        self.graph = nx.MultiDiGraph()
        self._upstream_cache: dict[str, set[str]] = {}
        for spec in specs.values():
            self.graph.add_node(spec.name, kind="metric")
        for name, ctx in contexts.items():
            self.graph.add_node(name, kind="context", **ctx)
        for spec in specs.values():
            self._add_edges(spec)

    @classmethod
    def load(cls, *extra_files: Path) -> MetricGraph:
        """Load the built-in `metrics.yaml` plus any extra YAML files (e.g. user-added metrics)."""
        specs: dict[str, MetricSpec] = {}
        contexts: dict[str, dict] = {}
        for path in (DEFAULT_FILE, *extra_files):
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            contexts.update(raw.get("contexts") or {})
            for name, body in (raw.get("metrics") or {}).items():
                specs[name] = MetricSpec(
                    name=name,
                    description=body["description"],
                    sql=body["sql"],
                    kind=body["kind"],
                    unit=body["unit"],
                    dims=tuple(body.get("dims") or ()),
                    business_weight=float(body["business_weight"]),
                    bad_direction=body.get("bad_direction", "both"),
                    noise=body.get("noise", "none"),
                    cv=float(body.get("cv", 1.0)),
                    min_spread=float(body.get("min_spread", 0.0)),
                    rel_floor=float(body.get("rel_floor", 0.05)),
                    window_hours=int(body.get("window_hours", 1)),
                    edges=tuple(body.get("edges") or ()),
                )
        return cls(specs, contexts)

    def _add_edges(self, spec: MetricSpec) -> None:
        g = self.graph
        for dim in spec.dims:
            g.add_node(f"dim:{dim}", kind="dimension")
            g.add_edge(spec.name, f"dim:{dim}", type="split_by")
        for edge in spec.edges:
            kind = edge["type"]
            other = edge.get("to") or edge.get("from")
            if kind not in EDGE_TYPES or other not in g:
                raise ValueError(f"{spec.name}: bad edge {edge}")
            attrs = {k: v for k, v in edge.items() if k not in ("type", "to", "from")}
            source, target = (spec.name, other) if "to" in edge else (other, spec.name)
            g.add_edge(source, target, type=kind, **attrs)

    def add_metric(self, spec: MetricSpec) -> None:
        """Add (or replace) a metric and its edges."""
        self.specs[spec.name] = spec
        self._upstream_cache.clear()
        self.graph.add_node(spec.name, kind="metric")
        self._add_edges(spec)

    def metric(self, name: str) -> MetricSpec:
        """The spec of a metric (KeyError if unknown)."""
        return self.specs[name]

    def formula_inputs(self, name: str) -> list[dict]:
        """Metrics that exactly compose `name` (formula edges into it), each with its role."""
        return [
            {"metric": u, "role": d.get("role", "factor")}
            for u, _, d in self.graph.in_edges(name, data=True)
            if d["type"] == "formula"
        ]

    def neighbors(self, name: str) -> dict[str, list[dict]]:
        """Everything directly connected to a metric, grouped by relationship."""
        g = self.graph
        out: dict[str, list[dict]] = {k: [] for k in ("formula_inputs", "formula_outputs", "funnel_prev", "funnel_next",
                                                      "causes", "effects", "context", "split_by")}  # fmt: skip
        out["formula_inputs"] = self.formula_inputs(name)
        for _, v, d in g.out_edges(name, data=True):
            if d["type"] == "formula":
                out["formula_outputs"].append({"metric": v, "role": d.get("role", "factor")})
            elif d["type"] == "funnel":
                out["funnel_next"].append({"metric": v, "step": d.get("step")})
            elif d["type"] == "may_be_caused_by":
                out["effects"].append({"metric": v, "confidence": d.get("confidence")})
            elif d["type"] == "split_by":
                out["split_by"].append({"dimension": v.removeprefix("dim:")})
        for u, _, d in g.in_edges(name, data=True):
            if d["type"] == "funnel":
                out["funnel_prev"].append({"metric": u, "step": d.get("step")})
            elif d["type"] == "may_be_caused_by":
                out["causes"].append({"metric": u, "confidence": d.get("confidence")})
            elif d["type"] == "context":
                out["context"].append(
                    {"source": u, **{k: g.nodes[u].get(k) for k in ("components", "types", "note")}}
                )
        out["causes"].sort(key=lambda c: -(c["confidence"] or 0))
        return out

    def upstream(self, name: str) -> list[dict]:
        """Every metric that composes or may cause `name`, nearest first (breadth-first, no repeats)."""
        seen, order, frontier = {name}, [], [(name, 0)]
        while frontier:
            node, depth = frontier.pop(0)
            for u, _, d in self.graph.in_edges(node, data=True):
                if d["type"] in CAUSAL_TYPES and u not in seen:
                    seen.add(u)
                    order.append({"metric": u, "depth": depth + 1, "via": d["type"], "to": node})
                    frontier.append((u, depth + 1))
        return order

    def upstream_names(self, name: str) -> set[str]:
        """Names of all metrics upstream of `name` (cached)."""
        if name not in self._upstream_cache:
            self._upstream_cache[name] = {u["metric"] for u in self.upstream(name)}
        return self._upstream_cache[name]

    def linked_components(self, name: str) -> set[str]:
        """Event components (releases, configs, jobs) that can affect a metric or anything upstream of it."""
        return {
            c
            for n in (name, *self.upstream_names(name))
            for ctx in self.contexts_for(n)
            for c in ctx.get("components") or []
        }

    def related(self, a: str, b: str) -> bool:
        """Can one event family explain both metrics? True if equal, on one causal chain, or sharing an event component."""
        return (
            a == b
            or b in self.upstream_names(a)
            or a in self.upstream_names(b)
            or bool(self.linked_components(a) & self.linked_components(b))
        )

    def contexts_for(self, name: str) -> list[dict]:
        """Event sources (components / event types) that can affect a metric directly."""
        return self.neighbors(name)["context"]

    def to_tree(self, root: str, max_depth: int = 3, _depth: int = 0) -> dict:
        """Nested dict of `root` and the metrics upstream of it, for drawing in the UI."""
        node = {"metric": root, "children": []}
        if _depth < max_depth:
            for u, _, d in self.graph.in_edges(root, data=True):
                if d["type"] in CAUSAL_TYPES:
                    child = self.to_tree(u, max_depth, _depth + 1)
                    child["edge"] = d["type"]
                    node["children"].append(child)
        return node
