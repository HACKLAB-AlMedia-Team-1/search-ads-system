"""The investigator: runs a case through the LLM agent (live/record/replay) or the rule-based policy."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from rootsight.agent import offline_policy
from rootsight.agent.llm import LLMClient, LLMUnavailable
from rootsight.agent.narrate import narrate
from rootsight.agent.report import Report, build_report
from rootsight.agent.tools import Step, Toolbox
from rootsight.config import Settings
from rootsight.monitor.watcher import Case

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (Path(__file__).with_name("prompts") / "investigator_system.md").read_text(encoding="utf-8")


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


class Investigator:
    """Investigates cases. With a model configured it lets the model pick tools; otherwise (or on failure) it follows rules."""

    def __init__(self, settings: Settings, toolbox: Toolbox, llm: LLMClient):
        self.settings, self.tb, self.llm = settings, toolbox, llm
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
        """Investigate one case and return its report."""
        self.tb.start(case)
        if self.llm.available:
            try:
                self._run_llm(case)
            except (LLMUnavailable, KeyError, TypeError, ValueError) as exc:  # also a malformed model reply
                logger.warning("Model unavailable (%s); using the rule-based investigator", exc)
                self.tb.start(case)
                offline_policy.investigate(self.tb, case)
        else:
            offline_policy.investigate(self.tb, case)
        return narrate(build_report(self.tb, case), self.llm, self.tb.end)

    def _run_llm(self, case: Case) -> None:
        brief = {"case_id": case.case_id, "hour": case.ts.isoformat(), "headline": case.headline, "root_metric": case.root_metric,
                 "segment": case.segment, "onset": case.onset.isoformat(),
                 "anomalies": [{"metric": a.metric, "segment": a.segment, "z": round(a.z, 1)} for a in case.anomalies[:8]]}  # fmt: skip
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(brief)},
        ]
        for turn in range(self.settings.max_tool_calls):
            if turn == self.settings.max_tool_calls - HYPOTHESIS_REMINDER and not self.tb.notes["hypotheses"]:
                # smaller models keep exploring; without a tested hypothesis there is no finding at all
                messages.append({"role": "user", "content": REMINDER})
            reply = self.llm.chat("agent", messages, TOOL_SCHEMAS, case.case_id, self.tb.end)
            messages.append(reply)
            if not reply.get("tool_calls"):
                break
            for call in reply["tool_calls"]:
                fn = call["function"]
                try:
                    args = json.loads(fn["arguments"] or "{}") if isinstance(fn["arguments"], str) else fn["arguments"]
                except ValueError:
                    args = None
                if fn["name"] not in TOOL_NAMES:  # small models invent tools; say so instead of running anything
                    result = {"error": f"unknown tool '{fn['name']}'; use one of {sorted(TOOL_NAMES)}"}
                elif not isinstance(args, dict):
                    result = {"error": "the arguments must be one JSON object"}
                else:
                    result = self.tb.call(fn["name"], args, (reply.get("content") or "").strip()[:200])
                messages.append(
                    {"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result, default=str)}
                )
                if fn["name"] == "finish":
                    return
        if not self.tb.notes["hypotheses"]:
            raise LLMUnavailable("the model did not test any hypothesis")
