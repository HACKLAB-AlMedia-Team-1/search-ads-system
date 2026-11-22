"""The investigation report: assembled in code from tool results, rendered as markdown."""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from rootsight.agent.evidence import SUPPORTED, Evidence
from rootsight.agent.tools import Z_ALARM, Toolbox
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
COUNTRY = {"DE": "Germany", "US": "the United States", "ES": "Spain", "JP": "Japan"}
PLAIN = {
    "search-language": "shoppers who search in another language get no results, because only the local language is searched",
    "search-analyzer": "searches no longer match products, because the language analyzer was swapped",
    "search-ranker": "search results no longer match what shoppers type, because the new ranker ignores the words",
    "ranking": "the best matches are pushed down the results, because a recency boost was switched on",
    "android-app": "Android shoppers get empty results, because the app sends an empty stock filter",
    "index-build": "many products cannot be found, because part of the search index is missing",
    "search-cache": "search shows old prices and stock, because results are cached for too long",
    "goods-receiving": "the top-selling products are out of stock, because a supplier delivery is overdue",
    "pacing-service": "the ad budget runs out early in the day, because the pacing service spends it too fast",
}


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
    summary: str = ""
    failed_check: dict = Field(default_factory=dict)


def fmt(value: float | None, unit: str) -> str:
    """A metric value written for people (shares as %, money in EUR)."""
    if value is None:
        return "no data"
    if unit == "share":
        return f"{value:.1%}"
    return f"€{value:,.2f}" if unit == "eur" else f"{value:,.1f}"


def where_text(scope: dict) -> str:
    """'Germany, android' style description of a segment."""
    return ", ".join(COUNTRY.get(v, v) for v in scope.values()) or "all traffic"


def plain_summary(report: Report) -> str:
    """One or two sentences a non-engineer understands, built only from numbers in the report."""
    imp = report.impact
    what = PLAIN.get(report.cause_component, f"something is wrong: {report.cause}")
    costs = []
    if round(imp.get("lost_orders") or 0):
        costs.append(f"about {imp['lost_orders']:,.0f} orders (€{imp.get('lost_revenue_eur') or 0:,.0f}) lost")
    if round(imp.get("ad_spend_over_plan_eur") or 0):
        costs.append(f"€{imp['ad_spend_over_plan_eur']:,.0f} of ads spent ahead of plan")
    cost = f" So far: {' and '.join(costs)}." if costs else ""
    return f"In {where_text(report.scope)}, {what}.{cost}"


def _step_with(tb: Toolbox, tool: str):
    return next((s for s in reversed(tb.trail) if s.tool == tool and s.sql), None)


def failed_check(tb: Toolbox, case: Case, component: str, metric: str) -> dict:
    """The database check that failed: the SQL, its tables, what was expected, what came back and why it fails."""
    po = _step_with(tb, "purchase_orders")
    late = [o for o in (po.result.get("orders", []) if po else []) if o["overdue"]]
    if component == "goods-receiving" and late:
        o = late[0]
        return {"sql": po.sql[0], "tables": ["purchase_orders"], "expected": "qty_received >= qty_ordered once the order is due",
                "got": f"{o['qty_received']:,} of {o['qty_ordered']:,} units received for {o['po_id']} (due {o['due']})",
                "why": "The delivery is past its due date and nothing arrived, so the top sellers have no stock."}  # fmt: skip
    pacing = _step_with(tb, "ad_pacing")
    if component == "pacing-service" and pacing and pacing.result.get("budget_eur"):
        r = pacing.result
        return {"sql": pacing.sql[0], "tables": ["ads_hourly"],
                "expected": f"spend_eur follows planned_spend_eur so the €{r['budget_eur']:,.0f} daily budget lasts until 24:00",
                "got": f"€{r['spent_eur']:,.0f} spent" + (f", budget used up at {r['budget_exhausted_at']}" if r["budget_exhausted_at"] else ""),
                "why": "Spend runs far ahead of the plan, so the ads stop for the rest of the day."}  # fmt: skip
    anomaly = next((a for a in case.anomalies if a.metric == metric), None) or next(
        (a for a in case.anomalies if a.metric == case.root_metric), None
    )
    if anomaly is None or metric not in tb.graph.specs:
        return {}
    spec = tb.graph.metric(anomaly.metric)
    step = next((s for s in reversed(tb.trail) if s.sql and anomaly.metric in json.dumps(s.args)), None)
    sql = step.sql[0] if step else ""
    return {"sql": sql, "tables": [spec.parts()[1].split()[0]],
            "expected": f"{anomaly.metric} close to {fmt(anomaly.expected, spec.unit)} (normal for this hour and day)",
            "got": f"{fmt(anomaly.actual, spec.unit)} in {where_text(anomaly.segment)}",
            "why": f"The value is {abs(anomaly.z):.1f} standard deviations {'above' if anomaly.z > 0 else 'below'} normal; "
                   f"the alarm fires beyond {Z_ALARM:.0f}."}  # fmt: skip


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
    report = Report(
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
                "sql": s.sql,
            }
            for s in tb.trail
        ],
        uncertain=uncertain,
        next_action=NEXT_ACTIONS.get(
            component, "Investigate the suspected component manually; no automatic remedy known."
        ),
        failed_check=failed_check(tb, case, component, summary["metric"]),
    )
    report.summary = plain_summary(report)
    return report


def render(report: Report) -> str:
    """Markdown version of a report."""
    imp = report.impact
    lines = [
        f"## {report.summary or report.headline}",
        f"_{report.headline}_",
        f"**Since:** {report.onset} | **Where:** {', '.join(f'{k}={v}' for k, v in report.scope.items()) or 'all traffic'} | **Status:** {report.status}",
        "",
        (
            f"**Impact so far ({imp['hours']} h):** {imp['lost_orders']} lost orders, EUR {imp['lost_revenue_eur']} lost revenue, "
            f"EUR {imp['wasted_ad_spend_eur']} of ad spend wasted, EUR {imp['ad_spend_over_plan_eur']} spent above plan."
        ),
        f"**Likely cause:** {report.cause}",
        f"**Possible next action:** {report.next_action}",
        *([(f"**Failed check:** {report.failed_check['why']} Expected {report.failed_check['expected']}, got "
            f"{report.failed_check['got']}. SQL: `{report.failed_check['sql']}`")] if report.failed_check else []),
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
