"""Incidents: one per ongoing problem. Open -> ongoing -> resolved, re-notified only when it gets worse."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from rootsight.agent.report import Report, render
from rootsight.graph.graph import MetricGraph
from rootsight.monitor.watcher import Case
from rootsight.store.db import Database

RESOLVE_AFTER = timedelta(hours=3)
RENOTIFY_GROWTH = 0.5
REOPEN_WITHIN = timedelta(hours=24)
OPEN, RESOLVED = "open", "resolved"


@dataclass
class Incident:
    """An incident as kept in memory (the database row has the same data plus the report)."""

    incident_id: int
    fingerprint: str
    first_seen: datetime
    last_seen: datetime
    segment: dict[str, str]
    metrics: set[str]
    notified_impact: float
    cause: str = ""


@dataclass
class IncidentEvent:
    """What happened to an incident when a case was processed; `notify` says whether a person should be told."""

    kind: str  # opened | reopened | updated | ongoing | resolved
    incident_id: int
    case: Case | None = None
    report: Report | None = None
    impact: dict = field(default_factory=dict)

    @property
    def notify(self) -> bool:
        """Opened, worsened and resolved incidents are announced; silent continuation is not."""
        return self.kind != "ongoing"


def _money(impact: dict) -> float:
    return float(impact.get("lost_revenue_eur") or 0) + float(impact.get("wasted_ad_spend_eur") or 0)


class IncidentManager:
    """Matches cases to incidents so an ongoing fault is reported once, updated when worse, closed when over."""

    def __init__(self, db: Database, graph: MetricGraph):
        self.db, self.graph = db, graph
        self._open: dict[int, Incident] = {}
        for r in db.df("SELECT * FROM incidents WHERE status = 'open'").itertuples():
            meta = json.loads(r.report_json)
            self._open[int(r.incident_id)] = Incident(int(r.incident_id), r.fingerprint, r.first_seen.to_pydatetime(), r.last_seen.to_pydatetime(),
                                                      json.loads(r.segment_json), set(meta["metrics"]), meta["notified_impact"], r.cause_component or "")  # fmt: skip

    def _related(self, incident: Incident, case: Case) -> bool:
        if any(incident.segment[d] != case.segment[d] for d in incident.segment.keys() & case.segment.keys()):
            return False
        metrics = {a.metric for a in case.anomalies} | {case.root_metric}
        if not incident.cause:
            return any(self.graph.related(m, i) for m in metrics for i in incident.metrics)
        # same problem only if the incident's cause can explain the case's most upstream unusual metrics
        sources = [m for m in metrics if not (self.graph.upstream_names(m) & (metrics - {m}))] or list(
            metrics
        )
        return any(incident.cause in self.graph.linked_components(m) for m in sources)

    def process(
        self, case: Case, investigate: Callable[[Case], Report], impact_of: Callable[[Case, dict], dict]
    ) -> IncidentEvent:
        """Handle one failure case: open an incident (investigating it), or update the one it belongs to."""
        metrics = {a.metric for a in case.anomalies} | {case.root_metric}
        match = next((i for i in self._open.values() if self._related(i, case)), None)
        if match is None:
            report = investigate(case)
            fingerprint = f"{case.root_metric}|{json.dumps(report.scope, sort_keys=True)}|{report.cause_component or 'unknown'}"
            impact = report.impact
            earlier = self.db.df(
                "SELECT incident_id, first_seen, report_json FROM incidents WHERE status = 'resolved' AND cause_component = ? "
                "AND cause_component <> '' AND segment_json = ? AND resolved_at >= ? ORDER BY incident_id DESC LIMIT 1",
                [report.cause_component, json.dumps(report.scope), case.ts - REOPEN_WITHIN],
            )
            if not earlier.empty:  # the same cause in the same place again: one problem, not two
                incident_id, old = (
                    int(earlier["incident_id"].iloc[0]),
                    json.loads(earlier["report_json"].iloc[0]),
                )
                self.db.execute(
                    "UPDATE incidents SET status = 'open', resolved_at = NULL, last_seen = ? WHERE incident_id = ?",
                    [case.ts, incident_id],
                )
                first_seen = earlier["first_seen"].iloc[0].to_pydatetime()
                self._open[incident_id] = Incident(
                    incident_id,
                    fingerprint,
                    first_seen,
                    case.ts,
                    report.scope,
                    metrics | set(old["metrics"]),
                    old["notified_impact"],
                    report.cause_component,
                )
                return IncidentEvent("reopened", incident_id, case, None, impact)
            incident_id = int(self.db.df("SELECT nextval('incident_seq') AS n")["n"].iloc[0])
            self.db.execute(
                "INSERT INTO incidents VALUES (?, ?, 'open', ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [incident_id, fingerprint, case.onset, case.ts, case.root_metric, json.dumps(report.scope), report.cause_component, report.status,
                 impact["lost_orders"], impact["lost_revenue_eur"], impact["wasted_ad_spend_eur"], render(report),
                 json.dumps({"metrics": sorted(metrics), "notified_impact": _money(impact), "report": report.model_dump(mode="json")})],
            )  # fmt: skip
            self._open[incident_id] = Incident(
                incident_id,
                fingerprint,
                case.onset,
                case.ts,
                report.scope,
                metrics,
                _money(impact),
                report.cause_component,
            )
            return IncidentEvent("opened", incident_id, case, report, impact)
        match.last_seen, widened = case.ts, len(case.segment) < len(match.segment)
        match.metrics |= metrics
        impact = impact_of(case, match.segment)
        grew = _money(impact) > match.notified_impact * (1 + RENOTIFY_GROWTH)
        if grew or widened:
            match.notified_impact = _money(impact)
        self._save_progress(match, impact)
        return IncidentEvent(
            "updated" if grew or widened else "ongoing", match.incident_id, case, None, impact
        )

    def _save_progress(self, incident: Incident, impact: dict) -> None:
        old = json.loads(
            self.db.df("SELECT report_json FROM incidents WHERE incident_id = ?", [incident.incident_id])[
                "report_json"
            ].iloc[0]
        )
        meta = {**old, "metrics": sorted(incident.metrics), "notified_impact": incident.notified_impact}
        self.db.execute(
            "UPDATE incidents SET last_seen = ?, impact_orders = ?, impact_revenue_eur = ?, wasted_ad_spend_eur = ?, report_json = ? WHERE incident_id = ?",
            [
                incident.last_seen,
                impact["lost_orders"],
                impact["lost_revenue_eur"],
                impact["wasted_ad_spend_eur"],
                json.dumps(meta),
                incident.incident_id,
            ],
        )

    def close_stale(self, hour: datetime) -> list[IncidentEvent]:
        """Resolve incidents with no matching case for three hours."""
        events = []
        for incident in [i for i in self._open.values() if hour - i.last_seen >= RESOLVE_AFTER]:
            self.db.execute(
                "UPDATE incidents SET status = ?, resolved_at = ? WHERE incident_id = ?",
                [RESOLVED, incident.last_seen + timedelta(hours=1), incident.incident_id],
            )
            del self._open[incident.incident_id]
            events.append(IncidentEvent("resolved", incident.incident_id))
        return events
