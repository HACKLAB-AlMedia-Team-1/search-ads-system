"""The investigator: the rule recipe first; when it cannot confirm a cause and a model is configured, the model takes over."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path

from rootsight.agent import offline_policy
from rootsight.agent.evidence import SUPPORTED
from rootsight.agent.llm import LLMClient, LLMUnavailable
from rootsight.agent.narrate import narrate
from rootsight.agent.report import Report, best_hypothesis, build_report
from rootsight.agent.tools import Step, Toolbox
from rootsight.config import Settings
from rootsight.monitor.watcher import Case

logger = logging.getLogger(__name__)

PROMPTS = Path(__file__).with_name("prompts")
SYSTEM_PROMPT = (PROMPTS / "investigator_system.md").read_text(encoding="utf-8")
TAKEOVER_PROMPT = (PROMPTS / "takeover.md").read_text(encoding="utf-8")


TYPES = {"segment": "object", "scope": "object", "samples": "array", "hours": "integer", "window": "integer", "n": "integer",
         "event_id": "integer", "hours_back": "integer"}  # fmt: skip


def _tool(tool: str, description: str, required: tuple[str, ...] = (), **params: str) -> dict:
    properties = {p: {"type": TYPES.get(p, "string"), "description": d} for p, d in params.items()}
    return {"type": "function", "function": {"name": tool, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": list(required)}}}  # fmt: skip


TOOL_SCHEMAS = [
    _tool(
        "get_metric",
        "Actual, expected and z of a metric for the last hours, plus onset.",
        ("name",),
        name="metric name",
        segment="e.g. {market: ES}",
        hours="hours back",
    ),
    _tool(
        "decompose",
        "Share of each formula factor in the metric's change.",
        ("metric",),
        metric="metric name",
        segment="segment",
        window="hours",
    ),
    _tool(
        "drill_down",
        "Rank values of a dimension by share of the deviation.",
        ("metric", "dimension"),
        metric="metric name",
        dimension="market|platform|source|campaign_id",
        segment="segment",
        window="hours",
    ),
    _tool(
        "graph_neighbors",
        "Parents, children, causes and event sources of a metric.",
        ("metric",),
        metric="metric name",
    ),
    _tool(
        "get_events",
        "Releases, configs, jobs in the last hours (includes harmless decoys).",
        hours_back="hours",
        component="optional component",
    ),
    _tool(
        "check_completeness",
        "rows received/expected per hour for search_events, orders or ads.",
        ("table",),
        table="table",
        hours="hours",
    ),
    _tool(
        "component_health",
        "Health metrics of a component next to normal values.",
        ("component",),
        component="index|search-ranker|ranking|search-cache",
    ),
    _tool(
        "sample_searches",
        "Recent real searches with top titles.",
        ("market", "platform"),
        market="US|ES|JP",
        platform="android|ios|web",
        n="how many",
    ),
    _tool(
        "judge_relevance",
        "Rate sampled results against their queries.",
        ("samples",),
        samples="the list returned by sample_searches",
    ),
    _tool(
        "ad_pacing",
        "Planned vs actual spend of a campaign for a day.",
        ("campaign",),
        campaign="CMP-US|CMP-ES|CMP-JP",
        day="ISO date",
    ),
    _tool(
        "purchase_orders",
        "Purchase orders of a market's top sellers: needed, ordered, received, due.",
        ("market",),
        market="US|ES|JP|DE",
    ),
    _tool("calendar_lookup", "Planned events covering a time and scope.", ts="ISO time", scope="segment"),
    _tool("web_check", "Ask the web for outside context.", ("question",), question="question"),
    _tool(
        "record_hypothesis",
        "Run the 4-point evidence checklist for a cause.",
        ("cause", "metric"),
        cause="short text",
        metric="metric name",
        segment="segment",
        event_id="event id from get_events",
    ),
    _tool("estimate_impact", "Lost orders and revenue, wasted ad spend."),
    _tool("finish", "End the investigation.", summary="one sentence"),
]


HYPOTHESIS_REMINDER = 4  # tool calls before the limit at which a model without a tested hypothesis is reminded
REMINDER = ("You have few tool calls left and have not tested a cause yet. Call record_hypothesis now for the most likely "
            "cause (cause, metric, segment, and the event_id from get_events), then estimate_impact, then finish.")  # fmt: skip
TOOL_NAMES = frozenset(t["function"]["name"] for t in TOOL_SCHEMAS)
HYPOTHESIS_TOOL = next(t for t in TOOL_SCHEMAS if t["function"]["name"] == "record_hypothesis")
LAST_CHANCE = "No tool calls are left except this one: call record_hypothesis for the most likely cause you found."
RULES, TAKEN_OVER, MODEL = "rules", "rules, then the model", "model"
MODEL_TRIED = "rules; the model found nothing better"  # the model took over but its causes were not stronger


def _arguments(raw: object) -> dict | None:
    try:
        args = json.loads(raw or "{}") if isinstance(raw, str) else raw
    except ValueError:
        return None
    return args if isinstance(args, dict) else None


def tool_loop(llm: LLMClient, tb: Toolbox, messages: list[dict], schemas: list[dict], case_id: str, max_calls: int,
              stop: str, reminder: tuple[str, Callable[[], bool]] | None = None) -> None:  # fmt: skip
    """Let the model call tools until it calls `stop`, stops calling tools, or has used `max_calls` turns.

    `reminder` = (text, needed): the text is added once, `HYPOTHESIS_REMINDER` turns before the limit, if `needed()` is true.
    Unknown tools and bad arguments are answered with an error instead of being run (small models invent tools).
    """
    names = frozenset(t["function"]["name"] for t in schemas)
    for turn in range(max_calls):
        if reminder and turn == max_calls - HYPOTHESIS_REMINDER and reminder[1]():
            messages.append({"role": "user", "content": reminder[0]})
        reply = llm.chat("agent", messages, schemas, case_id, tb.end)
        messages.append(reply)
        if not reply.get("tool_calls"):
            return
        for call in reply["tool_calls"]:
            fn, args = call["function"], _arguments(call["function"].get("arguments"))
            if fn["name"] not in names:
                result = {"error": f"unknown tool '{fn['name']}'; use one of {sorted(names)}"}
            elif args is None:
                result = {"error": "the arguments must be one JSON object"}
            else:
                result = tb.call(fn["name"], args, (reply.get("content") or "").strip()[:200])
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result, default=str)})
            if fn["name"] == stop:
                return


class Investigator:
    """Investigates cases: the rule recipe first; the model takes over only when the rules cannot confirm a cause.

    `rules_first=False` keeps the older order (the model first, the rules if it fails); only the model comparison uses it.
    """

    def __init__(self, settings: Settings, toolbox: Toolbox, llm: LLMClient, rules_first: bool = True):
        self.settings, self.tb, self.llm, self.rules_first = settings, toolbox, llm, rules_first
        self.tb.on_step = self._store_step

    def _store_step(self, step: Step) -> None:
        self.tb.db.execute(
            "INSERT INTO investigations VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                self.tb.case.case_id,
                step.n,
                self.tb.end,
                step.tool,
                json.dumps(step.args, default=str),
                json.dumps(step.result, default=str)[:4000],
                step.reasoning,
            ],
        )

    def run(self, case: Case) -> Report:
        """Investigate one case and return its report (`report.method` says who found the cause)."""
        method = self._rules_then_model(case) if self.rules_first else self._model_then_rules(case)
        report = build_report(self.tb, case)
        report.method = method
        return narrate(report, self.llm, self.tb.end)

    def _rules_then_model(self, case: Case) -> str:
        self.tb.start(case)
        offline_policy.investigate(self.tb, case)
        if self._confirmed() or not self.llm.available:
            return RULES
        tried = [{"cause": e.hypothesis.cause, "status": e.status, "failed_checks": [c["name"] for c in e.checks if not c["passed"]]}
                 for e in self.tb.notes["hypotheses"]]  # fmt: skip
        before, steps = len(self.tb.notes["hypotheses"]), len(self.tb.trail)
        try:
            self._run_llm(case, {"rules_tried": tried})
        except (LLMUnavailable, KeyError, TypeError, ValueError) as exc:  # also a malformed model reply
            logger.warning("The model could not take over (%s); keeping the rule recipe's result", exc)
        if len(self.tb.trail) == steps:
            return RULES
        best = best_hypothesis(self.tb.notes["hypotheses"])
        if best not in self.tb.notes["hypotheses"][before:]:
            return MODEL_TRIED
        self.tb.call("estimate_impact", {"segment": best.hypothesis.segment}, "cost for the best-supported cause")
        return TAKEN_OVER

    def _model_then_rules(self, case: Case) -> str:
        self.tb.start(case)
        if self.llm.available:
            try:
                self._run_llm(case)
                return MODEL
            except (LLMUnavailable, KeyError, TypeError, ValueError) as exc:
                logger.warning("Model unavailable (%s); using the rule-based investigator", exc)
                self.tb.start(case)
        offline_policy.investigate(self.tb, case)
        return RULES

    def _confirmed(self) -> bool:
        return any(e.status == SUPPORTED for e in self.tb.notes["hypotheses"])

    def _run_llm(self, case: Case, takeover: dict | None = None) -> None:
        """The model drives the tools. With `takeover` it continues after the rule recipe and is told what the rules tried."""
        brief = {"case_id": case.case_id, "hour": case.ts.isoformat(), "headline": case.headline, "root_metric": case.root_metric,
                 "segment": case.segment, "onset": case.onset.isoformat(),
                 "anomalies": [{"metric": a.metric, "segment": a.segment, "z": round(a.z, 1)} for a in case.anomalies[:8]],
                 **(takeover or {})}  # fmt: skip
        system = SYSTEM_PROMPT + ("\n\n" + TAKEOVER_PROMPT if takeover else "")
        messages = [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(brief, default=str)}]
        before = len(self.tb.notes["hypotheses"])
        tool_loop(self.llm, self.tb, messages, TOOL_SCHEMAS, case.case_id, self.settings.max_tool_calls, "finish",
                  (REMINDER, lambda: len(self.tb.notes["hypotheses"]) == before))  # fmt: skip
        if len(self.tb.notes["hypotheses"]) == before:  # one last turn in which testing a cause is the only choice
            messages.append({"role": "user", "content": LAST_CHANCE})
            tool_loop(self.llm, self.tb, messages, [HYPOTHESIS_TOOL], case.case_id, 1, "record_hypothesis")
        if len(self.tb.notes["hypotheses"]) == before:
            raise LLMUnavailable("the model did not test any hypothesis")
