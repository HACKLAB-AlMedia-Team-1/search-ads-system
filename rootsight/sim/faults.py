"""Registry of active faults. The search engine and the simulator read it to switch behaviour."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

import yaml

RANKER_V2_IRRELEVANT = "ranker_v2_irrelevant"  # S1
REGIONAL_ANALYZER_ENGLISH = "regional_analyzer_english"  # S12
ANDROID_FILTER_NULL = "android_filter_null"  # S3
PARTIAL_INDEX = "partial_index"  # S2
RANKING_BOOST_RECENCY = "ranking_boost_recency"  # S7
CACHE_STALE = "cache_stale"  # S15
AD_PACING_RUNAWAY = "ad_pacing_runaway"  # AD1
CAMPAIGN_PUSH = "campaign_push"  # EV1 (planned, innocent)
SEARCH_EVENTS_LATE = "search_events_late"  # DQ1 (innocent)
SUPPLIER_DELIVERY_LATE = "supplier_delivery_late"  # INV1
FOREIGN_LANGUAGE_BLOCKED = "foreign_language_blocked"  # L1


@dataclass(frozen=True)
class Fault:
    """One fault switch, active from `start` until `end` (None = until stopped), limited to `scope`."""

    name: str
    start: datetime
    end: datetime | None = None
    scope: dict[str, str] = field(default_factory=dict)

    def matches(self, sim_time: datetime, market: str | None, platform: str | None) -> bool:
        """True when the fault is on at `sim_time` and the scope covers the market and platform."""
        if sim_time < self.start or (self.end is not None and sim_time >= self.end):
            return False
        for dim, value in (("market", market), ("platform", platform)):
            wanted = self.scope.get(dim, "all")
            if wanted != "all" and value is not None and wanted != value:
                return False
        return True


class FaultRegistry:
    """Holds the faults that are (or will be) active and answers `active(...)` queries."""

    def __init__(self) -> None:
        self._faults: list[Fault] = []

    def add(self, fault: Fault) -> None:
        """Register a fault."""
        self._faults.append(fault)

    def stop(self, name: str, at: datetime) -> None:
        """End every open fault with this name at `at`."""
        self._faults = [
            Fault(f.name, f.start, at, f.scope) if f.name == name and (f.end is None or f.end > at) else f
            for f in self._faults
        ]

    def clear(self) -> None:
        """Remove all faults."""
        self._faults.clear()

    def active(
        self, name: str, sim_time: datetime, market: str | None = None, platform: str | None = None
    ) -> bool:
        """Is fault `name` on at `sim_time` for this market and platform?"""
        return any(f.name == name and f.matches(sim_time, market, platform) for f in self._faults)

    def active_names(self, sim_time: datetime) -> list[str]:
        """Names of all faults on at `sim_time` in any scope (sorted, no duplicates)."""
        return sorted({f.name for f in self._faults if f.matches(sim_time, None, None)})


@dataclass(frozen=True)
class Scenario:
    """A scenario file: one fault, the event-log entries it leaves behind, and (for tests) the true cause."""

    id: str
    name: str
    fault: str
    start: datetime
    end: datetime | None
    scope: dict[str, str]
    event_log: tuple[dict, ...] = ()
    calendar: tuple[dict, ...] = ()
    expected_root_cause: str = ""

    def shifted(self, at: datetime) -> Scenario:
        """Copy of the scenario moved so that the fault starts at `at` (events and calendar move with it)."""
        delta = at - self.start

        def move(rows: tuple[dict, ...], keys: tuple[str, ...]) -> tuple[dict, ...]:
            return tuple({**r, **{k: r[k] + delta for k in keys if r.get(k)}} for r in rows)

        return replace(
            self,
            start=at,
            end=self.end + delta if self.end else None,
            event_log=move(self.event_log, ("ts",)),
            calendar=move(self.calendar, ("start_ts", "end_ts")),
        )

    def for_market(self, market: str) -> Scenario:
        """Copy of a one-market scenario moved to another market (scope and event text follow)."""
        old = self.scope.get("market", "")
        rename = lambda text: text.replace(f"[{old}]", f"[{market}]")
        return replace(
            self,
            scope={**self.scope, "market": market},
            event_log=tuple({**e, "detail": rename(e["detail"])} for e in self.event_log),
            expected_root_cause=rename(self.expected_root_cause),
        )

    def to_fault(self) -> Fault:
        """The fault switch this scenario turns on."""
        return Fault(self.fault, self.start, self.end, dict(self.scope))


def load_scenarios(directory: Path) -> dict[str, Scenario]:
    """Read every `*.yaml` scenario file in `directory`, keyed by scenario id."""
    out: dict[str, Scenario] = {}
    for path in sorted(directory.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        when = datetime.fromisoformat
        out[raw["id"]] = Scenario(
            id=raw["id"],
            name=raw["name"],
            fault=raw["fault"],
            start=when(raw["start"]),
            end=when(raw["end"]) if raw.get("end") else None,
            scope=dict(raw.get("scope") or {}),
            event_log=tuple({**e, "ts": when(e["ts"])} for e in raw.get("event_log", [])),
            calendar=tuple(
                {**c, "start_ts": when(c["start_ts"]), "end_ts": when(c["end_ts"])}
                for c in raw.get("calendar", [])
            ),
            expected_root_cause=raw.get("expected_root_cause", ""),
        )
    return out
