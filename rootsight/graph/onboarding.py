"""Add a new metric to the graph from just {name, description, sql}: parse, propose edges, validate in code, add."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import sqlglot
import yaml
from sqlglot import exp

from rootsight.agent.llm import LLMClient, LLMUnavailable
from rootsight.graph.graph import CAUSAL_TYPES, DEFAULT_FILE, MetricGraph, MetricSpec
from rootsight.graph.series import metric_series
from rootsight.store.db import Database

KNOWN_DIMS = ("market", "platform", "source", "campaign_id")
NAME = re.compile(r"^[a-z][a-z0-9_]{2,40}$")
SAME_SUBTREE = 0.5
MIN_R = 0.6
MAX_LAG = 2
VALIDATION_DAYS = 7
DEFAULT_WEIGHT = 0.5
SQL_TABLES = ("fact_hourly", "ads_hourly", "component_hourly")
SQL_NOTES = ("fact_hourly: shop funnel counts, one row per hour, market (US/DE/ES/JP), platform (web/android/ios) and source "
             "(organic/paid). ads_hourly: one row per hour and campaign, money in EUR. component_hourly: technical health "
             "values (columns component, scope, metric, value).")  # fmt: skip
SQL_EXAMPLES = ("search_ctr", "zero_result_rate", "ad_spend", "in_stock_rate_top")


@dataclass
class Proposal:
    """One proposed edge `source -> target` (source composes, causes or affects target)."""

    type: str
    source: str
    target: str
    confidence: float
    reason: str
    relation: str = ""
    r: float | None = None
    status: str = "proposed"  # proposed | validated | ambiguous


@dataclass
class OnboardingResult:
    """What onboarding did: the metric, parsed facts, every edge with its validation, and whether it was added."""

    spec: MetricSpec | None
    parsed: dict
    proposals: list[Proposal] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    added: bool = False


def parse_sql(sql: str) -> dict:
    """Tables, columns and aggregations a metric's SQL uses."""
    tree = sqlglot.parse_one(f"SELECT {sql}")
    return {
        "tables": sorted({t.name for t in tree.find_all(exp.Table)}),
        "columns": sorted({c.name for c in tree.find_all(exp.Column)}),
        "aggregations": sorted({type(a).__name__.upper() for a in tree.find_all(exp.AggFunc)}),
        "ratio": isinstance(tree.expressions[0], exp.Div),
    }


def _columns(spec: MetricSpec) -> set[str]:
    return set(parse_sql(spec.sql)["columns"])


def propose_heuristic(name: str, parsed: dict, graph: MetricGraph) -> list[Proposal]:
    """Edge proposals from shared columns: overlapping metrics share a subtree; mixed ads+search metrics link both worlds."""
    mine = set(parsed["columns"])
    scored = sorted(
        ((len(mine & _columns(s)) / len(mine | _columns(s)), s.name) for s in graph.specs.values()),
        reverse=True,
    )
    proposals: list[Proposal] = []
    top_score, top = scored[0]
    if top_score >= SAME_SUBTREE:
        opposite = mine == _columns(graph.metric(top)) and parsed["ratio"]
        proposals.append(Proposal("may_be_caused_by", top, name, 0.9 if opposite else 0.6,
                                  f"uses the same columns as {top}" + (" and looks like its complement" if opposite else ""),
                                  "opposite" if opposite else ""))  # fmt: skip
    if {"ads_hourly", "fact_hourly"} <= set(parsed["tables"]) or (
        "ads_hourly" in parsed["tables"]
        and any(c in mine for c in ("searches_with_click", "zero_result_searches", "idle"))
    ):
        proposals += [
            Proposal("may_be_caused_by", "ad_spend", name, 0.7, "reads ad spend"),
            Proposal(
                "may_be_caused_by",
                "search_ctr",
                name,
                0.6,
                "depends on what happens after the ad click (search)",
            ),
            Proposal(
                "may_be_caused_by",
                name,
                "roas",
                0.5,
                "money lost on idle ad clicks should lower the return on ad spend",
            ),
        ]
    unique = {(p.source, p.target): p for p in reversed(proposals) if p.source != p.target}
    return list(unique.values())[::-1]


def propose_with_llm(
    llm: LLMClient, name: str, description: str, parsed: dict, graph: MetricGraph, now: datetime
) -> list[Proposal]:
    """Ask the fast model for edges (JSON); anything unusable raises LLMUnavailable so the caller can use the heuristic."""
    catalogue = {m.name: m.description for m in graph.specs.values()}
    prompt = (f"New metric '{name}': {description}. SQL uses {json.dumps(parsed)}. Existing metrics: {json.dumps(catalogue)}. "
              'Reply with JSON only: [{"type": "may_be_caused_by", "source": <existing metric>, "target": <metric>, "confidence": 0-1, "reason": "..."}] '
              "where source influences target; the new metric may be either end.")  # fmt: skip
    reply = llm.chat("fast", [{"role": "user", "content": prompt}], None, f"onboard-{name}", now)["content"]
    try:
        items = json.loads(reply[reply.index("[") : reply.rindex("]") + 1])
        return [Proposal("may_be_caused_by", i["source"], i["target"], float(i["confidence"]), str(i["reason"]))
                for i in items if i["source"] in graph.specs | {name: 0} and i["target"] in graph.specs | {name: 0}]  # fmt: skip
    except (ValueError, KeyError, TypeError) as exc:
        raise LLMUnavailable("the model returned no usable edges") from exc


def draft_metric(llm: LLMClient, db: Database, graph: MetricGraph, wish: str, now: datetime) -> dict[str, str]:
    """Let the fast model write a metric (name and SQL) from a plain description. Rules cannot do this.

    The result is only a draft: `try_sql` runs it on history, and a person still places it with `onboard`.
    Raises LLMUnavailable when the model gives nothing usable.
    """
    columns = {t: [c for c in db.df(f"SELECT * FROM {t} LIMIT 0").columns if c != "ts"] for t in SQL_TABLES}
    examples = [f"{name}: {graph.metric(name).sql}" for name in SQL_EXAMPLES if name in graph.specs]
    prompt = ("Write ONE metric for a web shop's monitoring database (DuckDB). The SQL has a fixed short form: an aggregate "
              "expression, then FROM one table, then an optional WHERE. No SELECT keyword, no GROUP BY, no ORDER BY and no "
              "time filter: the system adds the hours, markets and devices itself. Guard every division with NULLIF(..., 0).\n"
              f"Tables and columns: {json.dumps(columns)}\n{SQL_NOTES}\nExisting metrics as examples:\n" + "\n".join(examples)
              + f"\nThe metric to write: {wish}\n"
              'Reply with JSON only: {"name": "<lowercase_with_underscores>", "sql": "<expression FROM table [WHERE ...]>"}')  # fmt: skip
    reply = llm.chat("fast", [{"role": "user", "content": prompt}], None, "draft-metric", now)["content"]
    try:
        body = json.loads(reply[reply.index("{") : reply.rindex("}") + 1])
        name = re.sub(r"[^a-z0-9_]+", "_", str(body["name"]).lower()).strip("_")[:40]
        sql = " ".join(str(body["sql"]).split()).rstrip(";")
    except (ValueError, KeyError, TypeError) as exc:
        raise LLMUnavailable("the model returned no usable SQL") from exc
    return {"name": name, "sql": sql[7:] if sql.lower().startswith("select ") else sql}


def try_sql(db: Database, sql: str, end: datetime) -> tuple[pd.DataFrame | None, str]:
    """Run a metric's SQL on the last 7 days: (hourly values, "") or (None, why it cannot be used)."""
    try:
        frame = metric_series(db, MetricSpec("draft", "", sql, "ratio", "", (), 0), end - timedelta(days=VALIDATION_DAYS), end)
    except Exception as exc:  # noqa: BLE001 - any parse/SQL error is told to the person instead of crashing
        return None, f"the SQL does not run on the history: {' '.join(str(exc).split())[:200]}"
    if frame["value"].notna().sum() < 24:
        return None, "the SQL returns almost no values over the last 7 days"
    return frame, ""


def _correlation(
    db: Database, graph: MetricGraph, spec: MetricSpec, p: Proposal, end: datetime
) -> float | None:
    start = end - timedelta(days=VALIDATION_DAYS)
    series = {
        n: metric_series(db, spec if n == spec.name else graph.metric(n), start, end).set_index("ts")["value"]
        for n in (p.source, p.target)
    }
    a, b = series[p.source], series[p.target]
    best = max((float(np.nan_to_num(a.shift(lag).corr(b))) for lag in range(MAX_LAG + 1)), key=abs)
    return None if np.isnan(best) else best


def onboard(
    db: Database, graph: MetricGraph, name: str, description: str, sql: str, end: datetime,
    llm: LLMClient | None = None, custom_file: Path | None = None, added_by: str = "user",
) -> OnboardingResult:  # fmt: skip
    """Parse, propose, validate and (if sound) add a metric. Edges that fail validation are kept but flagged ambiguous."""
    result = OnboardingResult(None, {})
    if not NAME.match(name) or name in graph.specs:
        result.problems.append(f"'{name}' must be a new lowercase name (letters, digits, underscore)")
        return result
    try:
        result.parsed = parse_sql(sql)
        columns = db.df(
            f"SELECT * FROM {MetricSpec(name, '', sql, 'ratio', '', (), 0).parts()[1]} LIMIT 0"
        ).columns
        dims = tuple(d for d in KNOWN_DIMS if d in columns)
        spec = MetricSpec(
            name,
            description,
            sql,
            "ratio" if result.parsed["ratio"] else "count",
            "value",
            dims,
            DEFAULT_WEIGHT,
        )
        test = metric_series(db, spec, end - timedelta(days=VALIDATION_DAYS), end)
        if result.parsed["ratio"] and test["value"].dropna().between(0, 1).all():
            spec = MetricSpec(**{**spec.__dict__, "unit": "share"})
    except Exception as exc:  # noqa: BLE001 - any parse/SQL error is shown to the user instead of crashing the UI
        result.problems.append(f"the SQL does not run on the history: {exc}")
        return result
    if test["value"].notna().sum() < 24:
        result.problems.append("the SQL returns almost no values over the last 7 days")
        return result
    try:
        proposals = (
            propose_with_llm(llm, name, description, result.parsed, graph, end)
            if llm and llm.available
            else None
        )
    except LLMUnavailable:
        proposals = None
    result.proposals = proposals or propose_heuristic(name, result.parsed, graph)
    for p in result.proposals:
        p.r = _correlation(db, graph, spec, p, end)
        p.status = "validated" if p.r is not None and abs(p.r) >= MIN_R else "ambiguous"
        if p.status == "ambiguous":
            p.confidence = round(p.confidence * 0.5, 2)
    result.spec = MetricSpec(**{**spec.__dict__, "edges": tuple({"type": p.type, "from": p.source, "confidence": p.confidence, **({"relation": p.relation} if p.relation else {})}
                                                                for p in result.proposals if p.target == name)})  # fmt: skip
    graph.add_metric(result.spec)
    for p in (p for p in result.proposals if p.source == name):
        graph.graph.add_edge(name, p.target, type=p.type, confidence=p.confidence)
    db.execute("INSERT INTO metric_registry VALUES (?, ?, ?, ?, ?)", [name, description, sql, end, added_by])
    if custom_file:
        _append_yaml(custom_file, result)
    result.added = True
    return result


def _append_yaml(path: Path, result: OnboardingResult) -> None:
    spec = result.spec
    outgoing = [
        {"type": p.type, "to": p.target, "confidence": p.confidence}
        for p in result.proposals
        if p.source == spec.name
    ]
    body = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}
    body = body or {"metrics": {}}
    body["metrics"][spec.name] = {
        "description": spec.description, "sql": spec.sql, "kind": spec.kind, "unit": spec.unit, "dims": list(spec.dims),
        "business_weight": spec.business_weight, "edges": [*spec.edges, *outgoing],
    }  # fmt: skip
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")


def edit_metric(
    db: Database, graph: MetricGraph, name: str, description: str, sql: str, end: datetime,
    custom_file: Path | None = None, builtin_file: Path = DEFAULT_FILE,
) -> OnboardingResult:  # fmt: skip
    """Change the description and SQL of an existing metric (built-in or added), re-check its links and save it to its YAML file."""
    result = OnboardingResult(None, {})
    if name not in graph.specs:
        result.problems.append(f"'{name}' is not a metric in the graph")
        return result
    try:
        result.parsed = parse_sql(sql)
        spec = replace(graph.metric(name), description=description, sql=sql)
        test = metric_series(db, spec, end - timedelta(days=VALIDATION_DAYS), end)
    except Exception as exc:  # noqa: BLE001 - any parse/SQL error is shown to the user instead of crashing the UI
        result.problems.append(f"the SQL does not run on the history: {exc}")
        return result
    if test["value"].notna().sum() < 24:
        result.problems.append("the SQL returns almost no values over the last 7 days")
        return result
    if missing := [d for d in spec.dims if d not in db.df(f"SELECT * FROM {spec.parts()[1]} LIMIT 0").columns]:
        result.problems.append(f"the new SQL's table has no column for the dimensions {missing} this metric is split by")
        return result
    graph.specs[name] = spec
    graph._upstream_cache.clear()
    g = graph.graph
    for source, target in [(u, v) for u, v, d in g.in_edges(name, data=True) if d["type"] in CAUSAL_TYPES] + [
        (u, v) for u, v, d in g.out_edges(name, data=True) if d["type"] in CAUSAL_TYPES
    ]:  # fmt: skip
        p = Proposal("may_be_caused_by", source, target, 1.0, "existing link")
        p.r = _correlation(db, graph, spec, p, end)
        p.status = "validated" if p.r is not None and abs(p.r) >= MIN_R else "ambiguous"
        result.proposals.append(p)
    db.execute("INSERT INTO metric_registry VALUES (?, ?, ?, ?, ?)", [name, description, sql, end, "edited"])
    if _in_yaml(builtin_file, name):
        _rewrite_builtin(builtin_file, name, description, sql)
    elif custom_file and _in_yaml(custom_file, name):
        body = yaml.safe_load(custom_file.read_text(encoding="utf-8"))
        body["metrics"][name].update({"description": description, "sql": sql})
        custom_file.write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")
    result.spec, result.added = spec, True
    return result


def _in_yaml(path: Path, name: str) -> bool:
    return path.is_file() and name in ((yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("metrics") or {})


def _rewrite_builtin(path: Path, name: str, description: str, sql: str) -> None:
    """Replace only the `description:` and `sql:` lines of one metric, so the file's comments and layout stay."""
    lines, inside = path.read_text(encoding="utf-8").splitlines(keepends=True), False
    for i, line in enumerate(lines):
        if re.match(r"^  \S", line):
            inside = line.strip() == f"{name}:"
        elif inside and line.startswith("    description:"):
            lines[i] = f"    description: {json.dumps(description, ensure_ascii=False)}\n"
        elif inside and line.startswith("    sql:"):
            lines[i] = f"    sql: {json.dumps(sql, ensure_ascii=False)}\n"
    text = "".join(lines)
    saved = yaml.safe_load(text)["metrics"][name]
    if (saved["description"], saved["sql"]) != (description, sql):
        raise ValueError(f"could not update {name} in {path.name}")
    path.write_text(text, encoding="utf-8")
