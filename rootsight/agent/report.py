"""The investigation report: assembled in code from tool results, rendered as markdown."""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from rootsight.agent.evidence import SUPPORTED, Evidence
from rootsight.agent.tools import Z_ALARM, Toolbox
from rootsight.graph.graph import MetricGraph
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


def cost_parts(impact: dict) -> list[str]:
    """Only the costs that apply (zeros are left out), each named in plain words."""
    parts = []
    if round(impact.get("lost_orders") or 0):
        parts.append(f"about {impact['lost_orders']:,.0f} lost orders (€{impact.get('lost_revenue_eur') or 0:,.0f} revenue)")
    if round(impact.get("wasted_ad_spend_eur") or 0):
        parts.append(f"€{impact['wasted_ad_spend_eur']:,.0f} of ad spend that brought fewer sales than usual")
    if round(impact.get("ad_spend_over_plan_eur") or 0):
        parts.append(f"€{impact['ad_spend_over_plan_eur']:,.0f} of ad budget spent faster than planned (the budget ends early)")
    return parts


def _n(value: float | None) -> str:
    return "no data" if value is None else f"{value:,.4g}"


def step_summary(tool: str, result: dict, graph: MetricGraph) -> str:
    """One plain line saying what a tool call found (shown to people instead of the raw answer)."""

    def shown(metric: str, value: float | None) -> str:
        return fmt(value, graph.metric(metric).unit) if metric in graph.specs else _n(value)

    try:
        if "error" in result:
            return f"The tool could not answer: {result['error']}"
        if tool == "get_metric":
            if not result["hours"]:
                return "No data for these hours."
            last, onset = result["hours"][-1], result.get("onset")
            since = f"; unusual since {onset[:16].replace('T', ' ')}" if onset else ""
            metric = result["metric"]
            return f"{metric} was {shown(metric, last['actual'])} in the latest hour against a normal {shown(metric, last['expected'])}{since}."
        if tool in ("decompose", "drill_down"):
            rows = result.get("factors") or result.get("segments")
            if not rows:
                return "The metric is measured directly; there is nothing to split."
            top = rows[0]
            what = top["factor"] if tool == "decompose" else f"{result['dimension']} = {top['value']}"
            metric = top["factor"] if tool == "decompose" else result["metric"]
            return (f"{what} explains {_n(top['share_pct'])}% of the change "
                    f"({shown(metric, top['actual'])} against a normal {shown(metric, top['expected'])}).")  # fmt: skip
        if tool == "get_events":
            events = result["events"]
            newest = f"; the newest is {events[0]['component']}: {events[0]['detail']}" if events else ""
            return f"{len(events)} release, config or job changes in the window{newest}."
        if tool == "check_completeness":
            worst = min((h["ratio"] for h in result["hours"] if h["ratio"] is not None), default=None)
            state = "has no arrival records" if worst is None else "arrived complete" if worst >= 0.99 else f"is only {worst:.0%} complete in the worst hour"
            return f"The data of {result['table']} {state}."
        if tool == "component_health":
            return "; ".join(f"{h['metric']} is {_n(h['now'])} (normal {_n(h['normal'])})" for h in result["health"][:3]) + "."
        if tool == "sample_searches":
            empty = sum(s["zero_result"] for s in result["samples"])
            return f"{len(result['samples'])} recent searches were looked at; {empty} of them found nothing."
        if tool == "judge_relevance":
            return f"{result['searches']} searches judged: {result['pattern']}."
        if tool == "ad_pacing":
            out = result["budget_exhausted_at"]
            return f"€{_n(result['spent_eur'])} of the €{_n(result['budget_eur'])} daily budget is spent" + (f"; it ran out at {out}." if out else ".")
        if tool == "purchase_orders":
            late = [o for o in result["orders"] if o["overdue"]]
            if not late:
                return "Every purchase order arrived on time."
            return f"{late[0]['po_id']} is overdue: nothing of the {late[0]['qty_ordered']:,} ordered units has arrived (due {late[0]['due']})."
        if tool == "calendar_lookup":
            names = ", ".join(e["name"] for e in result["entries"])
            return f"Planned for this time: {names}." if names else "No planned event covers this time."
        if tool == "record_hypothesis":
            passed = sum(c["passed"] for c in result["checks"])
            return f"{result['cause']}: {passed} of {len(result['checks'])} evidence checks passed."
        if tool == "estimate_impact":
            return f"Cost so far: {'; '.join(cost_parts(result)) or 'nothing measurable yet'}."
        if tool == "graph_neighbors":
            return f"Looked up what feeds into {result['metric']} and what it affects."
    except (KeyError, IndexError, TypeError, ValueError):
        pass
    return ""


def plain_summary(report: Report) -> str:
    """One or two sentences a non-engineer understands, built only from numbers in the report."""
    what = PLAIN.get(report.cause_component, f"something is wrong: {report.cause}")
    costs = cost_parts(report.impact)
    cost = f" So far: {' and '.join(costs)}." if costs else ""
    return f"In {where_text(report.scope)}, {what}.{cost}"


def _step_with(tb: Toolbox, tool: str):
    return next((s for s in reversed(tb.trail) if s.tool == tool and s.queries), None)


def failed_check(tb: Toolbox, case: Case, component: str, metric: str) -> dict:
    """The database check that failed: the query (name, SQL, first rows), what was expected, what came back and why it fails."""
    po = _step_with(tb, "purchase_orders")
    late = [o for o in (po.result.get("orders", []) if po else []) if o["overdue"]]
    if component == "goods-receiving" and late:
        o = late[0]
        return {"query": po.queries[0], "sql": po.sql[0], "tables": ["purchase_orders"],
                "expected": "qty_received >= qty_ordered once the order is due",
                "got": f"{o['qty_received']:,} of {o['qty_ordered']:,} units received for {o['po_id']} (due {o['due']})",
                "why": "The delivery is past its due date and nothing arrived, so the top sellers have no stock."}  # fmt: skip
    pacing = _step_with(tb, "ad_pacing")
    if component == "pacing-service" and pacing and pacing.result.get("budget_eur"):
        r = pacing.result
        return {"query": pacing.queries[0], "sql": pacing.sql[0], "tables": ["ads_hourly"],
                "expected": f"spend_eur follows planned_spend_eur so the €{r['budget_eur']:,.0f} daily budget lasts until 24:00",
                "got": f"€{r['spent_eur']:,.0f} spent" + (f", budget used up at {r['budget_exhausted_at']}" if r["budget_exhausted_at"] else ""),
                "why": "Spend runs far ahead of the plan, so the ads stop for the rest of the day."}  # fmt: skip
    anomaly = next((a for a in case.anomalies if a.metric == metric), None) or next(
        (a for a in case.anomalies if a.metric == case.root_metric), None
    )
    if anomaly is None or metric not in tb.graph.specs:
        return {}
    spec = tb.graph.metric(anomaly.metric)
    step = next((s for s in reversed(tb.trail) if s.queries and anomaly.metric in json.dumps(s.args)), None)
    query = step.queries[0] if step else {}
    return {"query": query, "sql": query.get("sql", ""), "tables": [spec.parts()[1].split()[0]],
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
                "why": s.reasoning,
                "summary": step_summary(s.tool, s.result, tb.graph),
                "queries": s.queries,
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
        f"**Cost so far ({imp['hours']} h):** {'; '.join(cost_parts(imp)) or 'no measurable cost yet'}.",
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
