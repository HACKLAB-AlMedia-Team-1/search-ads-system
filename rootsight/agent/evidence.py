"""The 4-point evidence checklist (size, location, timing, alternatives), computed in code."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING

from rootsight.graph.series import metric_total
from rootsight.monitor.completeness import source_tables
from rootsight.sim.clock import HOUR

if TYPE_CHECKING:
    from rootsight.agent.tools import Toolbox

SIZE_MIN_SHARE = 0.70
LOCATION_Z, SIBLING_Z = 3.0, 3.0
TIMING_MAX = timedelta(hours=2)
MIN_REJECTED = 2
PAID_SHARE_TOLERANCE = 0.05
PRICE_SHARE_MAX = 30.0
PLATFORMS = ("android", "ios", "web")
LOOKBACK = timedelta(hours=3)
SUPPORTED, LIKELY, HYPOTHESIS = "SUPPORTED", "LIKELY", "HYPOTHESIS"


@dataclass
class Hypothesis:
    """'Event `event_id` (cause) changed `metric` in `segment`'."""

    cause: str
    metric: str
    segment: dict[str, str] = field(default_factory=dict)
    event_id: int | None = None


@dataclass
class Evidence:
    """The checklist result: four pass/fail checks plus the alternatives that were tested."""

    hypothesis: Hypothesis
    checks: list[dict]
    alternatives: list[dict]

    @property
    def status(self) -> str:
        """SUPPORTED if all four checks pass, LIKELY if three do, otherwise HYPOTHESIS."""
        passed = sum(c["passed"] for c in self.checks)
        return (
            SUPPORTED
            if passed == len(self.checks)
            else LIKELY
            if passed == len(self.checks) - 1
            else HYPOTHESIS
        )

    def summary(self) -> dict:
        """Small JSON view for the agent and the report."""
        return {
            "status": self.status,
            "cause": self.hypothesis.cause,
            "metric": self.hypothesis.metric,
            "segment": self.hypothesis.segment,
            "checks": self.checks,
            "rejected": [a for a in self.alternatives if a["rejected"]],
            "not_rejected": [a for a in self.alternatives if not a["rejected"]],
        }


def _check(name: str, passed: bool, detail: str) -> dict:
    return {"name": name, "passed": bool(passed), "detail": detail}


def _size_and_location(tb: Toolbox, h: Hypothesis, start, end) -> tuple[dict, dict]:
    hours = max(int((end - start) / HOUR), 1)
    share, worst_sibling = 1.0, 0.0
    for dim, value in h.segment.items():
        rows = tb.drill_down(h.metric, dim, {}, hours).get("segments", [])
        mine = next((r for r in rows if r["value"] == value), None)
        share *= abs(mine["share_pct"]) / 100 if mine else 0.0
        worst_sibling = max(
            [worst_sibling] + [abs(r["z"]) for r in rows if r["value"] != value and r["z"] is not None]
        )
    score = tb.watcher.score_hour(h.metric, h.segment, end - HOUR)
    z = score["z"] if score else 0.0
    where = ", ".join(f"{k}={v}" for k, v in h.segment.items()) or "all traffic"
    return (
        _check(
            "Size",
            share >= SIZE_MIN_SHARE,
            f"{where} explains {share:.0%} of the deviation (needs {SIZE_MIN_SHARE:.0%})",
        ),
        _check(
            "Location",
            abs(z) >= LOCATION_Z and worst_sibling <= SIBLING_Z,
            f"z={z:.1f} in {where}; most unusual sibling segment z={worst_sibling:.1f} (needs |z|>={LOCATION_Z:g} and siblings within {SIBLING_Z:g})",
        ),
    )


def _timing(tb: Toolbox, h: Hypothesis, onset) -> dict:
    row = (
        tb.db.df("SELECT ts FROM events WHERE event_id = ?", [h.event_id]) if h.event_id is not None else None
    )
    if row is None or row.empty or onset is None:
        return _check("Timing", False, "no event or no clear onset to compare")
    delta = onset - row["ts"].iloc[0].to_pydatetime()
    return _check(
        "Timing",
        timedelta(0) <= delta <= TIMING_MAX,
        f"change starts {delta.total_seconds() / 60:.0f} min after the event (needs 0-120)",
    )


def _alternatives(tb: Toolbox, h: Hypothesis, onset, start, end) -> list[dict]:
    alternatives = []
    spec = tb.graph.metric(h.metric)
    worst = min(
        [
            r["ratio"]
            for t in source_tables(spec)
            for r in tb.check_completeness(t, 6)["hours"]
            if r["ratio"] is not None
        ]
        or [1.0]
    )
    alternatives.append(
        {
            "name": "late or missing data",
            "rejected": worst >= 0.9,
            "reason": f"lowest completeness of the source tables is {worst:.0%}",
        }
    )
    planned = tb.calendar_lookup(scope=h.segment)["entries"]
    alternatives.append(
        {
            "name": "planned event",
            "rejected": not planned,
            "reason": "no calendar entry covers this time and scope"
            if not planned
            else f"calendar: {planned[0]['name']}",
        }
    )
    if "ads" in source_tables(spec):
        probes = [
            tb.watcher.score_hour(m, {k: v for k, v in h.segment.items() if k == "market"}, end - HOUR)
            for m in ("search_ctr", "zero_result_rate")
        ]
        calm = all(p is None or abs(p["z"]) < LOCATION_Z for p in probes)
        alternatives.append(
            {
                "name": "search or site problem",
                "rejected": calm,
                "reason": "search CTR and zero-result rate are normal in that market"
                if calm
                else "search metrics are also unusual",
            }
        )
    else:
        mix = _traffic_mix(tb, start, end)
        alternatives.append({"name": "traffic mix shift", "rejected": mix[0], "reason": mix[1]})
    linked = tb.graph.linked_components(h.metric)
    own = next((e for e in tb.get_events(8)["events"] if e["event_id"] == h.event_id), None)
    for e in tb.get_events(8)["events"]:
        if e["event_id"] == h.event_id or (own and e["component"] == own["component"]):
            continue
        if onset is not None and not (onset - LOOKBACK <= _event_time(tb, e) <= onset + HOUR):
            continue
        rejected, reason = _rival_verdict(tb, h, e, linked)
        alternatives.append(
            {
                "name": f"{e['type']} {e['component']} ({e['detail'][:40]})",
                "rejected": rejected,
                "reason": reason,
            }
        )
    return alternatives + _look_alikes(tb, h, own["component"] if own else "", end)


def _look_alikes(tb: Toolbox, h: Hypothesis, component: str, end) -> list[dict]:
    """Named look-alike causes of the metric's domain (search, ads, inventory), each tested against the data."""
    out: list[dict] = []
    table = tb.graph.metric(h.metric).parts()[1]
    market = {k: v for k, v in h.segment.items() if k == "market"}
    if table == "fact_hourly":
        if component != "index-build":
            index = tb.watcher.score_hour("index_doc_count", market, end - HOUR)
            ok = index is None or abs(index["z"]) < LOCATION_Z
            reason = (
                "the search index has its normal size" if ok else "the search index is smaller than normal"
            )
            out.append({"name": "indexing failure", "rejected": ok, "reason": reason})
        if "platform" not in h.segment:
            scores = {
                p: tb.watcher.score_hour(h.metric, {**h.segment, "platform": p}, end - HOUR)
                for p in PLATFORMS
            }
            hit = [p for p, s in scores.items() if s and abs(s["z"]) >= LOCATION_Z]
            reason = (
                f"only {hit[0]} is affected"
                if len(hit) == 1
                else f"{len(hit)} of {len(PLATFORMS)} platforms are affected; an app release would hit exactly one"
            )
            out.append({"name": "mobile app release", "rejected": len(hit) != 1, "reason": reason})
    elif table == "ads_hourly":
        shares = {f["factor"]: f["share_pct"] for f in tb.decompose("ad_spend", h.segment).get("factors", [])}
        price = abs(shares.get("cpc", 0.0))
        reason = f"cost per click explains {price:.0f}% of the spend change; impressions explain {shares.get('impressions', 0.0):.0f}%"
        out.append({"name": "cost-per-click spike", "rejected": price < PRICE_SHARE_MAX, "reason": reason})
        traffic = tb.watcher.score_hour("organic_sessions", market, end - HOUR)
        calm = traffic is None or abs(traffic["z"]) < LOCATION_Z
        out.append(
            {
                "name": "site traffic spike",
                "rejected": calm,
                "reason": "organic site traffic is normal" if calm else "site traffic is unusual too",
            }
        )
    if component == "goods-receiving" and market:
        orders = tb.purchase_orders(market["market"])["orders"]
        if not orders:
            return [
                *out,
                {
                    "name": "automatic reordering failure",
                    "rejected": False,
                    "reason": "no purchase order was found",
                },
            ]
        po = orders[0]
        out.append(
            {
                "name": "automatic reordering failure",
                "rejected": True,
                "reason": f"purchase order {po['po_id']} was created on {po['created']}",
            }
        )
        reason = f"{po['qty_ordered']:,} units were ordered for a need of {po['qty_needed']:,}; {po['qty_received']:,} received, due {po['due']}"
        out.append(
            {"name": "under-ordering", "rejected": po["qty_ordered"] >= po["qty_needed"], "reason": reason}
        )
    return out


def _rival_verdict(tb: Toolbox, h: Hypothesis, event: dict, linked: set[str]) -> tuple[bool, str]:
    """Can this other event explain the change? Rejected if unconnected in the graph or its platform does not fit."""
    component = event["component"]
    if component not in linked:
        return True, f"{component} is not connected to {h.metric} in the metric graph"
    platform = tb.graph.platform_of.get(component)
    if platform is None:
        return False, "connected to the metric and close in time"
    if h.segment.get("platform", platform) != platform:
        return (
            True,
            f"{component} only changes {platform} traffic, but the change is on {h.segment['platform']}",
        )
    others = [p for p in PLATFORMS if p != platform]
    hit = [
        p
        for p in others
        if (s := tb.watcher.score_hour(h.metric, {**h.segment, "platform": p}, tb.end - HOUR))
        and abs(s["z"]) >= LOCATION_Z
    ]
    if hit:
        return (
            True,
            f"{component} only changes {platform} traffic, but {', '.join(hit)} traffic is hit as well",
        )
    return False, "connected to the metric and close in time"


def _event_time(tb: Toolbox, event: dict):
    return (
        tb.db.df("SELECT ts FROM events WHERE event_id = ?", [event["event_id"]])["ts"]
        .iloc[0]
        .to_pydatetime()
    )


def _traffic_mix(tb: Toolbox, start, end) -> tuple[bool, str]:
    paid, sessions = tb.graph.metric("paid_sessions"), tb.graph.metric("sessions")
    a_paid, a_all = (float(metric_total(tb.db, s, start, end)["value"].iloc[0]) for s in (paid, sessions))
    e_paid, e_all = tb.expected_total(paid, {}, start, end), tb.expected_total(sessions, {}, start, end)
    if not (e_paid and e_all and a_all):
        return True, "not enough history to compare the traffic mix"
    now, normal = a_paid / a_all, e_paid / e_all
    return abs(
        now - normal
    ) < PAID_SHARE_TOLERANCE, f"paid share of sessions {now:.0%} versus {normal:.0%} expected"


def check(tb: Toolbox, h: Hypothesis) -> Evidence:
    """Run the 4-point checklist for a hypothesis against the data."""
    onset = tb.onset(h.metric, h.segment)
    start, end = (onset or tb.window()[0]), tb.end
    size, location = _size_and_location(tb, h, start, end)
    timing = _timing(tb, h, onset)
    alternatives = _alternatives(tb, h, onset, start, end)
    rejected = sum(a["rejected"] for a in alternatives)
    alt = _check(
        "Alternatives",
        rejected >= MIN_REJECTED and rejected == len(alternatives),
        f"{rejected} of {len(alternatives)} other explanations rejected (needs {MIN_REJECTED}+ and none open)",
    )
    return Evidence(h, [size, location, timing, alt], alternatives)
