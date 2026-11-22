"""User-written monitoring scenarios: map a plain description onto a fault the simulator can produce, or explain why not."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from rootsight.agent.llm import LLMClient, LLMUnavailable
from rootsight.graph.graph import MetricGraph
from rootsight.graph.series import metric_total
from rootsight.sim import faults as fault_names
from rootsight.store.db import Database

logger = logging.getLogger(__name__)

ID = re.compile(r"^[A-Z][A-Z0-9_]{1,15}$")
MARKET_WORDS = {"DE": ("germany", "german store", "deutschland"), "US": ("united states", "usa", "u.s.", "america", "us store"),
                "ES": ("spain", "españa", "spanish store"), "JP": ("japan", "japanese store")}  # fmt: skip
OTHER_COUNTRIES = ("france", "italy", "uk", "united kingdom", "india", "china", "canada", "brazil", "netherlands", "poland")
COUNTRY = {"DE": "Germany", "US": "the United States", "ES": "Spain", "JP": "Japan"}
DURATION_HOURS = 12
START = datetime(2026, 11, 27, 9, 0)


@dataclass(frozen=True)
class FaultKind:
    """One failure the simulator really produces, with the trace it leaves for the agent."""

    label: str
    component: str
    event_type: str
    detail: str
    metric: str
    keywords: tuple[str, ...]
    markets: tuple[str, ...] = ("US", "DE", "ES", "JP")
    platform: str | None = None
    why_markets: str = ""


FAULTS: dict[str, FaultKind] = {
    fault_names.FOREIGN_LANGUAGE_BLOCKED: FaultKind(
        "Searches in the other language find nothing", "search-language", "config", "search-language[{market}] = local only",
        "zero_result_rate", ("other language", "foreign", "english search", "german search", "translat", "bilingual"), ("DE", "US"),
        why_markets="only the German and the US store accept searches in two languages"),
    fault_names.REGIONAL_ANALYZER_ENGLISH: FaultKind(
        "Local-language searches find nothing", "search-analyzer", "config", "search-analyzer[{market}] = english",
        "zero_result_rate", ("analyzer", "local language", "umlaut", "stemm", "no results", "nothing found", "zero result"),
        ("DE", "ES", "JP"), why_markets="the US store already reads search text with English rules"),
    fault_names.RANKER_V2_IRRELEVANT: FaultKind(
        "Search shows unrelated products", "search-ranker", "release", "v2.0.0 rolled out 100%", "relevance_at_10",
        ("unrelated", "irrelevant", "wrong product", "ranker", "relevance", "nothing to do with")),
    fault_names.RANKING_BOOST_RECENCY: FaultKind(
        "Best matches pushed down by the newest products", "ranking", "config", "ranking.boost_recency 0.0 -> 0.8",
        "first_exact_position", ("newest", "recent", "pushed down", "order of results", "sorted", "ranking")),
    fault_names.ANDROID_FILTER_NULL: FaultKind(
        "The Android app gets empty results", "android-app", "release", "5.2.0 rolled out 100%", "zero_result_rate",
        ("android", "mobile app", "app release"), platform="android", why_markets="only the Android app has the stock-filter bug"),
    fault_names.PARTIAL_INDEX: FaultKind(
        "Part of the catalogue cannot be found", "index-build", "job", "#812 status=partial (shards 0-1 missing)", "index_doc_count",
        ("index", "missing product", "cannot be found", "can't be found", "disappear", "shard")),
    fault_names.CACHE_STALE: FaultKind(
        "Search shows old prices and stock", "search-cache", "config", "search-cache.ttl 60s -> 86400s", "price_mismatch_rate",
        ("price", "stale", "cache", "outdated", "old price", "different price")),
    fault_names.AD_PACING_RUNAWAY: FaultKind(
        "The ad budget runs out early", "pacing-service", "deploy", "1.4.0 deployed (schedule handling changed)", "ad_spend",
        ("budget", "ad spend", "sponsored", "campaign", "pacing", "ads ")),
    fault_names.SUPPLIER_DELIVERY_LATE: FaultKind(
        "Top sellers out of stock", "goods-receiving", "job", "purchase order overdue: top-seller delivery not received",
        "in_stock_rate_top", ("out of stock", "unavailable", "delivery", "supplier", "sold out", "inventory", "purchase order")),
}  # fmt: skip


@dataclass
class Draft:
    """A scenario the user described, the fault it maps to (if any) and the agent-written expectations."""

    sid: str
    title: str
    what: str
    where: str
    shop: str
    fault: str | None = None
    scope: dict[str, str] = field(default_factory=dict)
    numbers: str = ""
    agent: str = ""
    problems: list[str] = field(default_factory=list)

    @property
    def possible(self) -> bool:
        """True when the simulator can really produce this scenario."""
        return self.fault is not None and not self.problems


def _scope(where: str, kind: FaultKind) -> tuple[dict[str, str], list[str]]:
    text = f" {where.lower()} "
    if other := [c for c in OTHER_COUNTRIES if c in text]:
        return {}, [f"The simulator only has stores in {', '.join(COUNTRY.values())}; '{other[0]}' is not one of them."]
    markets = [m for m, words in MARKET_WORDS.items() if any(w in text for w in words)]
    markets += [m for m in ("DE", "US", "ES", "JP") if re.search(rf"\b{m}\b", where) and m not in markets]
    if len(markets) > 1:
        return {}, ["Pick one country (or 'all markets'): a scenario breaks one market or all of them."]
    if not markets and len(kind.markets) < 4:
        markets = [kind.markets[0]]
    if markets and markets[0] not in kind.markets:
        return {}, [f"'{kind.label}' cannot be simulated in {COUNTRY[markets[0]]}: {kind.why_markets}."]
    for platform in ("ios", "web"):
        if kind.platform and platform in text:
            return {}, [f"'{kind.label}' cannot be simulated on {platform}: {kind.why_markets}."]
    scope = {"market": markets[0] if markets else "all"}
    if kind.platform:
        scope["platform"] = kind.platform
    return scope, []


def _classify_keywords(text: str) -> str | None:
    text = f" {text.lower()} "
    scores = {name: sum(k in text for k in kind.keywords) for name, kind in FAULTS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] else None


def _classify_llm(llm: LLMClient, draft: Draft, now: datetime) -> str | None:
    catalogue = {name: kind.label for name, kind in FAULTS.items()}
    prompt = ("A shop manager describes a failure to simulate. Pick the ONE simulator fault that produces it, or 'none' if no fault "
              f"matches. Faults: {json.dumps(catalogue)}. Reply with JSON only: {{\"fault\": \"<key or none>\"}}.\n"
              f"What breaks: {draft.what}\nWhere: {draft.where}\nWhat a shopper sees: {draft.shop}")  # fmt: skip
    reply = llm.chat("fast", [{"role": "user", "content": prompt}], None, f"scenario-{draft.sid}", now)["content"]
    try:
        choice = json.loads(reply[reply.index("{") : reply.rindex("}") + 1])["fault"]
    except (ValueError, KeyError, TypeError) as exc:
        raise LLMUnavailable("the model returned no usable fault") from exc
    return choice if choice in FAULTS else None


def _expectations(db: Database, graph: MetricGraph, kind: FaultKind, scope: dict, end: datetime) -> tuple[str, str]:
    """'What the numbers do' from the metric graph and the database, and 'what the agent should do' from the fault's trace."""
    spec, where = graph.metric(kind.metric), COUNTRY.get(scope.get("market", ""), "every market")
    segment = {k: v for k, v in scope.items() if v != "all" and k in spec.dims}
    frame = metric_total(db, spec, end - timedelta(days=1), end, segment)
    level = frame["value"].iloc[0] if not frame.empty else None
    shown = "no data" if level is None else f"{level:.1%}" if spec.unit == "share" else f"{level:,.1f}"
    move = {"up": "rises", "down": "falls"}.get(spec.bad_direction, "moves away from normal")
    near = graph.neighbors(kind.metric)
    downstream = [n["metric"] for key in ("formula_outputs", "funnel_next", "effects") for n in near[key]][:4]
    numbers = (f"{spec.description} (`{kind.metric}`, last 24 h: {shown} in {where}) {move}"
               + (f"; through the metric graph this moves {', '.join(f'`{m}`' for m in downstream)}" if downstream else "")
               + (". Other markets stay normal." if segment.get("market") else "."))  # fmt: skip
    detail = kind.detail.format(market=scope.get("market", "all"))
    agent = (f"Incident in {where} blaming `{kind.component}` ({detail}), found from the event log and confirmed by the "
             "4-point evidence checklist; other recent changes are ruled out.")  # fmt: skip
    return numbers, agent


def draft_scenario(
    db: Database, graph: MetricGraph, llm: LLMClient, existing: set[str], sid: str, title: str, what: str, where: str,
    shop: str, end: datetime,
) -> Draft:  # fmt: skip
    """Turn the user's description into a scenario draft; `problems` says in plain words why it cannot be simulated."""
    draft = Draft(sid.strip().upper(), title.strip(), what.strip(), where.strip(), shop.strip())
    if not ID.match(draft.sid):
        draft.problems.append("The id must be 2-16 capital letters, digits or underscores, starting with a letter (e.g. MY1).")
    elif draft.sid in existing:
        draft.problems.append(f"A scenario with the id {draft.sid} already exists.")
    if not (draft.title and draft.what and draft.shop):
        draft.problems.append("Fill in the title, what breaks and what a shopper sees.")
    if draft.problems:
        return draft
    try:
        draft.fault = _classify_llm(llm, draft, end) if llm.available else _classify_keywords(f"{what} {shop} {title}")
    except LLMUnavailable as exc:
        logger.warning("Scenario classification falls back to keywords (%s)", exc)
        draft.fault = _classify_keywords(f"{what} {shop} {title}")
    if draft.fault is None:
        labels = "; ".join(kind.label for kind in FAULTS.values())
        draft.problems.append("This cannot be simulated right now: the simulator can only produce these failures: "
                              f"{labels}. Nothing in your description matches one of them, so pressing Simulate would change nothing.")  # fmt: skip
        return draft
    kind = FAULTS[draft.fault]
    draft.scope, problems = _scope(draft.where, kind)
    draft.problems += problems
    if not draft.problems:
        draft.numbers, draft.agent = _expectations(db, graph, kind, draft.scope, end)
    return draft


def save_scenario(draft: Draft, directory: Path) -> Path:
    """Write the draft as `scenarios/<id>.yaml` (fault, scope, event-log trace and the plain-language guide)."""
    kind = FAULTS[draft.fault]
    market = draft.scope.get("market", "all")
    body = {
        "id": draft.sid, "name": draft.title, "fault": draft.fault, "start": START.isoformat(),
        "end": (START + timedelta(hours=DURATION_HOURS)).isoformat(), "scope": draft.scope,
        "event_log": [{"ts": (START - timedelta(minutes=5)).isoformat(), "type": kind.event_type, "component": kind.component,
                       "detail": kind.detail.format(market=market)}],
        "expected_root_cause": f"{kind.component} {kind.detail.format(market=market)}",
        "guide": {"title": draft.title, "what": draft.what, "where": draft.where or COUNTRY.get(market, "All markets"),
                  "shop": draft.shop, "metrics": draft.numbers, "agent": draft.agent},
    }  # fmt: skip
    path = directory / f"{draft.sid}.yaml"
    path.write_text(yaml.safe_dump(body, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def custom_guides(directory: Path) -> dict[str, dict[str, str]]:
    """Plain-language guides of the user-written scenarios in `directory`, keyed by scenario id."""
    out = {}
    for path in sorted(directory.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if raw.get("guide"):
            out[raw["id"]] = raw["guide"]
    return out
