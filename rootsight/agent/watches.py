"""The agent's watch list: what a person asked it to keep an eye on, and how it watches each one.

Rules first. A request becomes a *rule watch* when a metric can express it: the statistical watcher then scores that
metric in that segment every hour, like every other metric (fast, no model). A model may help find or write the metric
(its SQL is run on history and shown to the person first). When no metric can express the request (it needs reading or
judging, e.g. "do the German results look English?"), it becomes a *model watch*: every few hours the model looks with
the same read-only tools and gives a verdict, which code checks before it counts.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from rootsight.agent.investigator import TOOL_SCHEMAS, _tool, tool_loop
from rootsight.agent.llm import LLMClient, LLMUnavailable
from rootsight.agent.narrate import numbers_in
from rootsight.agent.tools import Toolbox
from rootsight.graph.graph import MetricGraph
from rootsight.graph.onboarding import draft_metric, try_sql
from rootsight.monitor.watcher import DIM_VALUES, Case
from rootsight.store.db import Database

logger = logging.getLogger(__name__)

RULE, MODEL = "rule", "model"
MODEL_EVERY_HOURS = 6  # a model watch looks again after this many simulated hours
QUIET_HOURS = range(1, 7)  # night: too few shoppers to judge anything, model watches are not checked
MODEL_TOOL_CALLS = 8
OK, PROBLEM, UNCLEAR, WAITING = "ok", "problem", "unclear", "waiting for a model"
WATCH_PROMPT = (Path(__file__).with_name("prompts") / "model_watch.md").read_text(encoding="utf-8")

MARKET_WORDS = {"DE": ("germany", "german", "deutschland"), "US": ("united states", "usa", "u.s.", "america", "american"),
                "ES": ("spain", "spanish", "españa"), "JP": ("japan", "japanese")}  # fmt: skip
PLATFORM_WORDS = {
    "android": ("android",),
    "ios": ("ios", "iphone", "ipad"),
    "web": ("web", "desktop", "browser", "website"),
}
# Plain phrases -> metric. Checked before the metric names; the longest phrase found wins.
PHRASES = {
    "zero_result_rate": ("no result", "zero result", "nothing found", "find nothing", "finds nothing", "found nothing", "empty result"),
    "in_stock_rate_top": ("out of stock", "sold out", "in stock", "top seller", "best seller", "stock"),
    "unavailable_on_click_rate": ("unavailable",),
    "ad_spend": ("ad spend", "ad budget", "advertising spend", "budget", "ad cost"),
    "pacing_ratio": ("pacing",),
    "roas": ("roas", "return on ad"),
    "relevance_at_10": ("relevance", "relevant", "unrelated", "irrelevant"),
    "first_exact_position": ("best match", "exact match", "pushed down"),
    "search_ctr": ("search click", "click rate", "clicks on search", "ctr"),
    "price_mismatch_rate": ("wrong price", "old price", "price mismatch", "outdated price"),
    "index_doc_count": ("search index", "searchable product", "index"),
    "cache_hit_rate": ("cache",),
    "search_latency_p95": ("slow search", "latency", "search speed"),
    "orders": ("orders", "sales"),
    "revenue": ("revenue", "turnover", "income"),
    "conversion_rate": ("conversion",),
    "cpc": ("cost per click",),
    "sessions": ("traffic", "visitors", "sessions"),
    "add_to_cart_rate": ("add to cart", "added to cart", "adds to cart"),
    "bounce_rate": ("bounce",),
    "refinement_rate": ("reword", "refine", "search again"),
}  # fmt: skip
READ_ONLY_TOOLS = ("get_metric", "decompose", "drill_down", "graph_neighbors", "get_events", "check_completeness",
                   "component_health", "sample_searches", "judge_relevance", "ad_pacing", "purchase_orders", "calendar_lookup")  # fmt: skip
VERDICT_TOOL = _tool(
    "verdict",
    "End this check. status ok or problem; for a problem name the existing metric that shows it best and its segment.",
    ("status", "reason"),
    status="ok|problem",
    reason="one sentence, numbers only from tool results",
    metric="existing metric name (for a problem)",
    segment="e.g. {market: DE}",
)
WATCH_SCHEMAS = [t for t in TOOL_SCHEMAS if t["function"]["name"] in READ_ONLY_TOOLS] + [VERDICT_TOOL]


@dataclass
class Watch:
    """One thing a person asked the agent to watch."""

    watch_id: str
    created: datetime
    request: str
    kind: str  # rule | model
    metric: str | None
    segment: dict[str, str]
    every_hours: int
    reason: str
    active: bool = True
    last_check: datetime | None = None
    last_verdict: str = ""
    last_note: str = ""


@dataclass
class Plan:
    """How the agent proposes to watch a request, shown to the person before the watch starts."""

    request: str
    kind: str  # rule | model
    reason: str
    metric: str | None = None
    segment: dict[str, str] = field(default_factory=dict)
    every_hours: int = 1
    new_metric: dict[str, str] = field(
        default_factory=dict
    )  # model-written {name, description, sql}, checked on history
    by: str = "rules"  # rules | model: who chose how to watch


def find_segment(text: str) -> dict[str, str]:
    """Market and device named in plain words ('in Germany on Android' -> {market: DE, platform: android})."""
    low = f" {text.lower()} "
    segment = {}
    markets = [
        m for m, words in MARKET_WORDS.items() if any(re.search(rf"\b{re.escape(w)}\b", low) for w in words)
    ]
    markets += [m for m in MARKET_WORDS if re.search(rf"\b{m}\b", text) and m not in markets]
    if len(markets) == 1:
        segment["market"] = markets[0]
    platforms = [p for p, words in PLATFORM_WORDS.items() if any(re.search(rf"\b{w}\b", low) for w in words)]
    if len(platforms) == 1:
        segment["platform"] = platforms[0]
    return segment


def match_metric(text: str, graph: MetricGraph) -> tuple[str | None, str]:
    """The metric plain words name, by the longest matching phrase or metric name; (None, '') if none fits."""
    low = " " + re.sub(r"[^a-z0-9 ]+", " ", text.lower().replace("_", " ")) + " "
    found = [(phrase, metric) for metric, phrases in PHRASES.items() if metric in graph.specs for phrase in phrases
             if f" {phrase}" in low]  # fmt: skip
    found += [(name.replace("_", " "), name) for name in graph.specs if f" {name.replace('_', ' ')} " in low]
    if not found:
        return None, ""
    phrase, metric = max(found, key=lambda f: len(f[0]))
    return metric, phrase


def fit_segment(graph: MetricGraph, metric: str, segment: dict) -> dict[str, str]:
    """Keep only the parts of a segment the metric can be split by, with values that exist."""
    dims = graph.metric(metric).dims
    return {k: str(v) for k, v in (segment or {}).items() if k in dims and str(v) in DIM_VALUES.get(k, ())}


def where_words(segment: dict[str, str]) -> str:
    """'market = DE, platform = android' or 'all traffic'."""
    return ", ".join(f"{k} = {v}" for k, v in segment.items()) or "all traffic"


def classify(llm: LLMClient, graph: MetricGraph, text: str, now: datetime) -> dict:
    """Ask the fast model how a request can be watched; the answer is validated in code.

    Returns {kind: metric, metric, segment} | {kind: new_metric} | {kind: judgement, why}. Raises LLMUnavailable.
    """
    catalogue = {name: spec.description for name, spec in graph.specs.items()}
    prompt = ("A web shop's monitoring agent was asked to watch something. Decide how. If ONE existing metric (optionally in "
              "one market and/or device) measures it, reply {\"kind\": \"metric\", \"metric\": <name>, \"market\": <DE|US|ES|JP|null>, "
              "\"platform\": <android|ios|web|null>}. If no existing metric fits but a new number per hour computed from the "
              "shop's tables (searches, clicks, carts, orders, ads, stock) would, reply {\"kind\": \"new_metric\"}. If it needs "
              "reading or judging (e.g. what results show, which language they are in), reply {\"kind\": \"judgement\", \"why\": "
              f"\"<one sentence>\"}}. JSON only.\nMetrics: {json.dumps(catalogue)}\nRequest: {text}")  # fmt: skip
    reply = llm.chat("fast", [{"role": "user", "content": prompt}], None, "plan-watch", now)["content"]
    try:
        body = json.loads(reply[reply.index("{") : reply.rindex("}") + 1])
        kind = body["kind"]
    except (ValueError, KeyError, TypeError) as exc:
        raise LLMUnavailable("the model gave no usable plan") from exc
    if kind == "metric" and body.get("metric") in graph.specs:
        segment = {k: body[k] for k in ("market", "platform") if body.get(k)}
        return {
            "kind": "metric",
            "metric": body["metric"],
            "segment": fit_segment(graph, body["metric"], segment),
        }
    if kind == "new_metric":
        return {"kind": "new_metric"}
    return {"kind": "judgement", "why": str(body.get("why") or "no metric measures it")[:300]}


def plan_watch(request: str, graph: MetricGraph, llm: LLMClient, db: Database, now: datetime) -> Plan:
    """Rules first: plain words that name a metric become a rule watch. Otherwise the model decides between an existing
    metric, a new metric (it writes the SQL, which is run on history and shown), or watching it itself."""
    request = " ".join(request.split())
    metric, phrase = match_metric(request, graph)
    if metric:
        segment = fit_segment(graph, metric, find_segment(request))
        return Plan(request, RULE, f"Your words '{phrase}' name the metric `{metric}` ({graph.metric(metric).description}). "
                    "The statistics score it every hour against its normal value; no model is needed.", metric, segment)  # fmt: skip
    if not llm.available:
        return Plan(request, MODEL, "No metric matches these words, so a rule cannot watch it and the model has to. No model "
                    "is switched on (LLM_MODE=offline): the watch is saved and waits for one.", every_hours=MODEL_EVERY_HOURS)  # fmt: skip
    try:
        choice = classify(llm, graph, request, now)
        if choice["kind"] == "metric":
            return Plan(request, RULE, f"The model picked the metric `{choice['metric']}` "
                        f"({graph.metric(choice['metric']).description}); from now on the statistics score it every hour.",
                        choice["metric"], choice["segment"], by="model")  # fmt: skip
        if choice["kind"] == "new_metric":
            draft = draft_metric(llm, db, graph, request, now)
            frame, problem = try_sql(db, draft["sql"], now)
            if not problem and draft["name"] not in graph.specs:
                segment = find_segment(request)
                return Plan(request, RULE, f"No metric fits, so the model wrote one. Its SQL runs on the last 7 days ({len(frame)} "
                            "hourly values). Read it: SQL can run and still be wrong. Once added, the statistics score it every hour.",
                            draft["name"], segment, new_metric={**draft, "description": request}, by="model")  # fmt: skip
            why = problem or f"a metric called {draft['name']} already exists"
            return Plan(request, MODEL, f"The model tried to write a metric for this, but it cannot be used ({why}). "
                        "The model will watch it itself instead.", every_hours=MODEL_EVERY_HOURS, by="model")  # fmt: skip
        return Plan(request, MODEL, f"No metric can express this ({choice['why']}), so the model watches it itself every "
                    f"{MODEL_EVERY_HOURS} hours with the read-only tools.", every_hours=MODEL_EVERY_HOURS, by="model")  # fmt: skip
    except LLMUnavailable as exc:
        logger.warning("Watch planning by the model failed (%s)", exc)
        return Plan(request, MODEL, f"No metric matches these words and the model could not plan it ({exc}). "
                    "The model will watch it itself.", every_hours=MODEL_EVERY_HOURS)  # fmt: skip


def as_rule(plan: Plan, graph: MetricGraph) -> Plan | None:
    """A model watch the person wants as a rule anyway? Only possible when the words name a metric."""
    metric, _ = match_metric(plan.request, graph)
    return None if metric is None else Plan(plan.request, RULE, "Watched by the statistics, as you chose.", metric,
                                            fit_segment(graph, metric, find_segment(plan.request)))  # fmt: skip


def as_model(plan: Plan) -> Plan:
    """The person prefers the model to watch it, even though a rule could."""
    return Plan(
        plan.request,
        MODEL,
        "Watched by the model, as you chose.",
        plan.metric,
        plan.segment,
        MODEL_EVERY_HOURS,
        by=plan.by,
    )


class WatchList:
    """The watches, kept in the `watches` table (so 'Reset demo' clears them with the rest of the demo)."""

    def __init__(self, db: Database):
        self.db = db

    def all(self) -> list[Watch]:
        """Every watch, newest first."""
        rows = self.db.df("SELECT * FROM watches ORDER BY created DESC, watch_id DESC")
        return [Watch(r.watch_id, r.created.to_pydatetime(), r.request, r.kind, r.metric or None, json.loads(r.segment_json),
                      int(r.every_hours), r.reason, bool(r.active), None if r.last_check is None or str(r.last_check) == "NaT"
                      else r.last_check.to_pydatetime(), r.last_verdict or "", r.last_note or "") for r in rows.itertuples()]  # fmt: skip

    def add(self, plan: Plan, now: datetime) -> Watch:
        """Store a planned watch as active (W1, W2, ...)."""
        n = int(self.db.df("SELECT count(*) AS n FROM watches")["n"].iloc[0]) + 1
        watch = Watch(
            f"W{n}", now, plan.request, plan.kind, plan.metric, plan.segment, plan.every_hours, plan.reason
        )
        self.db.execute("INSERT INTO watches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, '', '')",
                        [watch.watch_id, now, watch.request, watch.kind, watch.metric or "", json.dumps(watch.segment),
                         watch.every_hours, watch.reason, True])  # fmt: skip
        return watch

    def stop(self, watch_id: str) -> None:
        """Stop a watch (it stays in the list as stopped)."""
        self.db.execute("UPDATE watches SET active = false WHERE watch_id = ?", [watch_id])

    def due(self, hour: datetime) -> list[Watch]:
        """Active model watches whose next look is due at this hour (never at night)."""
        if hour.hour in QUIET_HOURS:
            return []
        return [w for w in self.all() if w.active and w.kind == MODEL
                and (w.last_check is None or hour - w.last_check >= timedelta(hours=w.every_hours))]  # fmt: skip

    def note(self, watch_id: str, hour: datetime, verdict: str, text: str) -> None:
        """Remember the latest look of a model watch."""
        self.db.execute("UPDATE watches SET last_check = ?, last_verdict = ?, last_note = ? WHERE watch_id = ?",
                        [hour, verdict, text, watch_id])  # fmt: skip


def check_model_watch(
    watch: Watch, tb: Toolbox, llm: LLMClient, hour: datetime
) -> tuple[str, str, Case | None]:
    """One look by the model: (verdict, note, case to investigate or None). The verdict is checked in code:
    a problem must name an existing metric, the segment must exist, and the note may only use numbers from tool results."""
    probe = Case(f"M{hour:%Y%m%d%H}-{watch.watch_id}", hour, "watch", watch.request, watch.metric or "orders", watch.segment,
                 hour, 0.0, detail={"watch": watch.watch_id})  # fmt: skip
    tb.start(probe)
    brief = {"request": watch.request, "hour": hour.isoformat(), "metric_hint": watch.metric, "segment_hint": watch.segment,
             "previous_look": watch.last_note or None,
             "metrics": {n: s.description for n, s in tb.graph.specs.items()}}  # fmt: skip
    messages = [
        {"role": "system", "content": WATCH_PROMPT},
        {"role": "user", "content": json.dumps(brief, default=str)},
    ]
    tool_loop(llm, tb, messages, WATCH_SCHEMAS, probe.case_id, MODEL_TOOL_CALLS, "verdict",
              ("You have few tool calls left. Call verdict now.", lambda: "verdict" not in tb.notes))  # fmt: skip
    if "verdict" not in tb.notes:  # one last turn in which the verdict is the only choice
        messages.append(
            {
                "role": "user",
                "content": "No tool calls are left except this one: call verdict now (ok or problem).",
            }
        )
        tool_loop(llm, tb, messages, [VERDICT_TOOL], probe.case_id, 1, "verdict")
    said = tb.notes.get("verdict")
    if said is None:
        return UNCLEAR, "The model looked but gave no verdict.", None
    seen = numbers_in(json.dumps([s.result for s in tb.trail], default=str) + json.dumps(brief, default=str))
    reason = str(said.get("reason") or "").strip()
    if not reason or not numbers_in(reason) <= seen:
        reason = "(The model's wording was dropped: it used numbers that are not in the tool results.)"
    status = str(said.get("status") or "").lower()
    if status == OK:
        return OK, reason, None
    if status != PROBLEM:
        return UNCLEAR, f"The model answered '{status}', not ok or problem.", None
    metric = said.get("metric") or watch.metric
    if metric not in tb.graph.specs:
        return (
            UNCLEAR,
            f"The model saw a problem but named no known metric ('{metric}'), so nothing was raised. {reason}",
            None,
        )
    segment = fit_segment(
        tb.graph, metric, said.get("segment") if isinstance(said.get("segment"), dict) else watch.segment
    )
    case = Case(f"M{hour:%Y%m%d%H}-{watch.watch_id}-p", hour, "failure", f"Model watch {watch.watch_id}: {reason}", metric,
                segment, hour, 1.0, detail={"watch": watch.watch_id, "request": watch.request})  # fmt: skip
    return PROBLEM, reason, case
