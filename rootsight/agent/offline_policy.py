"""The rule-based investigator: walks the metric graph with the same tools the LLM agent gets."""

from __future__ import annotations

from rootsight.agent.evidence import SUPPORTED
from rootsight.agent.tools import Toolbox
from rootsight.monitor.watcher import Case

CONCENTRATED = 0.70
EVENT_WINDOW_HOURS, WIDE_WINDOW_HOURS = 6, 36
MAX_CANDIDATES = 2
PREFERRED_DIMS = ("market", "platform")


def _first_cause_metric(tb: Toolbox, case: Case) -> str:
    """The anomalous metric with no other anomalous metric upstream of it: the symptom's likely source."""
    metrics = {a.metric for a in case.anomalies} | {case.root_metric}
    sources = [m for m in metrics if not (tb.graph.upstream_names(m) & (metrics - {m}))]
    best = {a.metric: a.attention for a in case.anomalies}
    return max(sources or [case.root_metric], key=lambda m: best.get(m, 0.0))


def _localise(tb: Toolbox, metric: str) -> dict[str, str]:
    """Drill down by market and platform; keep a value that holds >=70% of the deviation."""
    segment: dict[str, str] = {}
    for dim in (d for d in PREFERRED_DIMS if d in tb.graph.metric(metric).dims):
        top = (
            tb.call(
                "drill_down",
                {"metric": metric, "dimension": dim, "segment": segment},
                f"is the change concentrated in one {dim}?",
            ).get("segments")
            or [None]
        )[0]
        if (
            top
            and abs(top["share_pct"]) >= 100 * CONCENTRATED
            and top["z"] is not None
            and abs(top["z"]) >= 3
        ):
            segment[dim] = top["value"]
    return segment


def _candidate_events(tb: Toolbox, metric: str, onset, hours_back: int) -> list[dict]:
    """Events in the last `hours_back` hours whose component feeds the metric or something upstream, nearest before onset first."""
    linked = tb.graph.linked_components(metric)
    events = tb.call(
        "get_events",
        {"hours_back": hours_back},
        "which releases or config changes happened just before?",
    )["events"]
    cands = [e for e in events if e["component"] in linked and e["type"] != "calendar"]
    stamp = {
        e["event_id"]: tb.db.df("SELECT ts FROM events WHERE event_id = ?", [e["event_id"]])["ts"]
        .iloc[0]
        .to_pydatetime()
        for e in cands
    }
    return sorted(cands, key=lambda e: abs((onset - stamp[e["event_id"]]).total_seconds()) if onset else 0)


def investigate(tb: Toolbox, case: Case) -> None:
    """Run the fixed investigation recipe; results are kept in `tb.notes` and `tb.trail`."""
    source = _first_cause_metric(tb, case)
    first = tb.call(
        "get_metric",
        {"name": source, "segment": {}, "hours": 6},
        f"{source} looks like the earliest anomalous metric upstream",
    )
    onset = tb.onset(source, {})
    tb.call("decompose", {"metric": case.root_metric}, f"which factor of {case.root_metric} moved?")
    segment = _localise(tb, source)
    candidates = _candidate_events(tb, source, onset, EVENT_WINDOW_HOURS) or _candidate_events(
        tb, source, onset, WIDE_WINDOW_HOURS
    )
    spec = tb.graph.metric(source)
    if candidates:
        tb.call(
            "component_health",
            {"component": candidates[0]["component"]},
            "is the suspected component unhealthy?",
        )
    if candidates and candidates[0]["component"] == "goods-receiving" and "market" in segment:
        tb.call(
            "purchase_orders",
            {"market": segment["market"]},
            "was enough ordered, and did the delivery arrive?",
        )
    if spec.parts()[1] == "ads_hourly":
        tb.call(
            "decompose", {"metric": "ad_spend", "segment": segment}, "is it impressions, click rate or price?"
        )
    if spec.parts()[1] == "fact_hourly":
        market = segment.get("market", "US")
        samples = tb.call(
            "sample_searches",
            {"market": market, "platform": segment.get("platform", "web"), "n": 5},
            "what do real searches look like?",
        )
        tb.call(
            "judge_relevance",
            {"samples": samples.get("samples", [])},
            "are the results related to the queries?",
        )
    for event in candidates[:MAX_CANDIDATES] or [None]:
        args = {"cause": f"{event['type']} {event['component']}: {event['detail']}" if event else "no recent change found",
                "metric": source, "segment": segment, "event_id": event["event_id"] if event else None}  # fmt: skip
        if tb.call("record_hypothesis", args, "check the evidence").get("status") == SUPPORTED:
            break
    tb.call("estimate_impact", {}, "how much did this cost?")
    tb.call(
        "finish",
        {"summary": f"first cause candidate: {source}; onset {first.get('onset')}"},
        "enough evidence",
    )
