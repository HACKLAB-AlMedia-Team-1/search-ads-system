"""Plain-language wording of a finished report: the agent's fast model rewrites it, the numbers stay from the tools."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime

from rootsight.agent.llm import LLMClient, LLMUnavailable
from rootsight.agent.report import Report

logger = logging.getLogger(__name__)
NUMBER = re.compile(r"\d[\d,.]*")


def _numbers(text: str) -> set[str]:
    return {n.rstrip(".,").replace(",", "") for n in NUMBER.findall(text)}


def narrate(report: Report, llm: LLMClient, now: datetime) -> Report:
    """Ask the model for a shopper-friendly summary and next action; keep the code-built text if it is offline or invents numbers."""
    if not llm.available:
        return report
    facts = {"summary": report.summary, "cause": report.cause, "where": report.scope, "since": report.onset,
             "impact": report.impact, "failed_check": report.failed_check, "next_action": report.next_action}  # fmt: skip
    prompt = ("Rewrite this incident for a shop manager who is not an engineer. Reply with JSON only: "
              '{"summary": "<1-2 plain sentences: what shoppers experience, where, why, and what it costs>", '
              '"next_action": "<one sentence: the most likely fix>"}. Use only numbers that appear in the facts.\n'
              f"Facts: {json.dumps(facts, default=str)}")  # fmt: skip
    try:
        reply = llm.chat("fast", [{"role": "user", "content": prompt}], None, f"narrate-{report.case_id}", now)["content"]
        body = json.loads(reply[reply.index("{") : reply.rindex("}") + 1])
        summary, action = str(body["summary"]).strip(), str(body["next_action"]).strip()
    except (LLMUnavailable, ValueError, KeyError, TypeError) as exc:
        logger.warning("Plain-language rewrite skipped (%s)", exc)
        return report
    if not summary or not _numbers(summary + action) <= _numbers(json.dumps(facts, default=str)):
        logger.warning("Plain-language rewrite dropped: it used numbers that are not in the tool results")
        return report
    return report.model_copy(update={"summary": summary, "next_action": action or report.next_action})
