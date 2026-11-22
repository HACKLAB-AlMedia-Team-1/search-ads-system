"""The investigation report: assembled in code from tool results, rendered as markdown."""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from rootsight.agent.evidence import SUPPORTED, Evidence
from rootsight.agent.tools import Toolbox
from rootsight.monitor.watcher import Case

NEXT_ACTIONS = {
    "search-ranker": "Roll back search-ranker to the previous version, then review why v2 ignores text relevance.",
    "ranking": "Revert the ranking.boost_recency change and re-test result order on a sample of queries.",
    "search-analyzer": "Restore the language-specific analyzer for the affected market and re-index if needed.",
    "search-language": "Turn the 'local language only' setting off again so shoppers can search in other languages.",
    "android-app": "Halt the Android rollout and hotfix the null stock filter; the API should also reject a null filter.",
    "index-build": "Re-run the index build (shards were missing) and alert on index document count.",
    "search-cache": "Reset the cache TTL to its previous value and flush stale entries.",
    "goods-receiving": "Chase the supplier for the overdue delivery and mark the affected top sellers as back-ordered.",
    "pacing-service": "Roll back pacing-service and cap the hourly spend until the schedule logic is fixed.",
}
TRAIL_RESULT_CHARS = 180


class Report(BaseModel):
    """Everything a person needs: what broke, where, since when, why (with evidence) and what it costs."""

    case_id: str
    headline: str
    onset: str
    scope: dict[str, str]
    cause: str
    cause_component: str
    status: str
    impact: dict
    checklist: list[dict]
    rejected: list[dict]
    not_rejected: list[dict]
    trail: list[dict]
    uncertain: list[str]
    next_action: str
    sources: list[str] = Field(default_factory=list)


def _best(hypotheses: list[Evidence]) -> Evidence | None:
    return max(
        hypotheses, key=lambda e: (e.status == SUPPORTED, sum(c["passed"] for c in e.checks)), default=None
    )


def build_report(tb: Toolbox, case: Case) -> Report:
    """Turn the toolbox state of a finished investigation into a `Report`."""
    if "impact" not in tb.notes:
        tb.call("estimate_impact", {})
    best = _best(tb.notes["hypotheses"])
    summary = best.summary() if best else {"status": "HYPOTHESIS", "cause": "no cause found", "checks": [], "rejected": [], "not_rejected": [], "segment": {}, "metric": case.root_metric}  # fmt: skip
    event = (
        tb.db.df("SELECT component FROM events WHERE event_id = ?", [best.hypothesis.event_id])
        if best and best.hypothesis.event_id is not None
        else None
    )
    component = event["component"].iloc[0] if event is not None and not event.empty else ""
    impact = tb.notes["impact"]
    business = max(case.anomalies, key=lambda a: tb.graph.metric(a.metric).business_weight, default=None)
    effect = (f"{business.metric} {abs(business.actual - business.expected) / abs(business.expected):.0%} "
              f"{'above' if business.z > 0 else 'below'} expected") if business and business.expected else case.headline  # fmt: skip
    uncertain = [f"{c['name']}: {c['detail']}" for c in summary["checks"] if not c["passed"]]
    uncertain += [f"Not ruled out: {a['name']} ({a['reason']})" for a in summary["not_rejected"]]
    if tb.linkup.mode != "live":
        uncertain.append("No outside (web) context was checked.")
    return Report(
        case_id=case.case_id,
        headline=f"{effect} - {summary['cause']}",
        onset=case.onset.isoformat(timespec="minutes"),
        scope=summary["segment"],
        cause=summary["cause"],
        cause_component=component,
        status=summary["status"],
        impact=impact,
        checklist=summary["checks"],
        rejected=summary["rejected"],
        not_rejected=summary["not_rejected"],
        trail=[
            {
                "n": s.n,
                "tool": s.tool,
                "args": json.dumps(s.args)[:80],
                "result": json.dumps(s.result)[:TRAIL_RESULT_CHARS],
                "why": s.reasoning,
            }
            for s in tb.trail
        ],
        uncertain=uncertain,
        next_action=NEXT_ACTIONS.get(
            component, "Investigate the suspected component manually; no automatic remedy known."
        ),
    )


def render(report: Report) -> str:
    """Markdown version of a report."""
    imp = report.impact
    lines = [
        f"## {report.headline}",
        f"**Since:** {report.onset} | **Where:** {', '.join(f'{k}={v}' for k, v in report.scope.items()) or 'all traffic'} | **Status:** {report.status}",
        "",
        (
            f"**Impact so far ({imp['hours']} h):** {imp['lost_orders']} lost orders, EUR {imp['lost_revenue_eur']} lost revenue, "
            f"EUR {imp['wasted_ad_spend_eur']} of ad spend wasted, EUR {imp['ad_spend_over_plan_eur']} spent above plan."
        ),
        f"**Likely cause:** {report.cause}",
        f"**Suggested next action:** {report.next_action}",
        "",
        "### Evidence checklist",
        "| Check | Result | Detail |",
        "|---|---|---|",
        *(f"| {c['name']} | {'PASS' if c['passed'] else 'FAIL'} | {c['detail']} |" for c in report.checklist),
        "",
        "### Alternatives rejected",
        *(f"- {a['name']}: {a['reason']}" for a in report.rejected),
        "",
        "### Still uncertain",
        *(f"- {u}" for u in report.uncertain),
        "",
        "### Investigation trail",
        *(f"{s['n']}. `{s['tool']}` {s['why']}" for s in report.trail),
    ]
    return "\n".join(lines)
