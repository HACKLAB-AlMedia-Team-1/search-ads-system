"""The watcher: once per tick, score metrics against what is normal and group anomalies into cases."""

from __future__ import annotations

import itertools
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

import pandas as pd

from rootsight.data.loaders import MARKETS
from rootsight.graph.graph import MetricGraph, MetricSpec
from rootsight.graph.series import metric_series, metric_total
from rootsight.monitor import calendar, completeness
from rootsight.monitor.baseline import compute_baseline, denominator_spec, robust_z
from rootsight.sim.clock import HOUR
from rootsight.store.db import Database

logger = logging.getLogger(__name__)

TOP_KPIS = ("orders", "revenue", "search_ctr", "roas", "ad_spend", "pacing_ratio", "zero_result_rate")
COMPONENT_KPIS = ("index_doc_count", "cache_hit_rate", "cache_result_age_min", "in_stock_rate_top")
QUALITY_KPIS = ("relevance_at_10", "ndcg_at_10", "first_exact_position")
DIM_VALUES = {
    "market": tuple(MARKETS),
    "platform": ("android", "ios", "web"),
    "source": ("organic", "paid"),
}
BATCH_SIZE = 40
MIN_VOLUME = 60
Z_ALARM, Z_SINGLE_HOUR = 3.0, 5.0
PERSISTENCE_BONUS = 0.5
HISTORY_DAYS = 14
REFRESH_HOURS = 3
MAX_CASES_PER_TICK = 2
CUBES = {"fact_hourly": ("market", "platform", "source"), "ads_hourly": ("market",)}
ALL = "*"


@dataclass
class Anomaly:
    """One metric in one segment that is clearly away from its expected value."""

    ts: datetime
    metric: str
    segment: dict[str, str]
    actual: float
    expected: float
    z: float
    attention: float
    n_consecutive: int
    planned: bool

    @property
    def onset(self) -> datetime:
        """First hour of the current run of unusual values."""
        return self.ts - HOUR * (self.n_consecutive - 1)


@dataclass
class Case:
    """A group of related anomalies (or a data-delay notice) that deserves attention."""

    case_id: str
    ts: datetime
    kind: str  # failure | planned | data_delay
    headline: str
    root_metric: str
    segment: dict[str, str]
    onset: datetime
    attention: float
    anomalies: list[Anomaly] = field(default_factory=list)
    detail: dict = field(default_factory=dict)


class TableHistory:
    """Hourly values of every plain metric of one table, for every segment, kept in memory.

    One `GROUP BY ts, CUBE(dims)` query per simulated hour refreshes all of them, instead of one query per
    metric and segment. The latest hours are re-read each time in case late data was repaired.
    """

    def __init__(self, db: Database, table: str, dims: tuple[str, ...]):
        self.db, self.table, self.dims = db, table, dims
        self.aliases: dict[str, str] = {}
        self.loaded: datetime | None = None
        self._frame = pd.DataFrame()
        self._groups: dict[tuple, pd.DataFrame] = {}

    def refresh(self, exprs: dict[str, str], hour: datetime) -> None:
        """Make sure the hours up to and including `hour` are loaded for the metrics in `exprs` (sql -> expression)."""
        end = hour + HOUR
        known = set(exprs) <= set(self.aliases)
        if known and self.loaded is not None and self.loaded >= end:
            return
        full = self.loaded is None or not known
        if full:
            self.aliases = {sql: f"c{i}" for i, sql in enumerate(exprs)}
            self._select = ", ".join(f"{expr} AS {self.aliases[sql]}" for sql, expr in exprs.items())
        start = hour - timedelta(days=HISTORY_DAYS + 2) if full else self.loaded - HOUR * REFRESH_HOURS
        dims = ", ".join(self.dims)
        fresh = self.db.df(
            f"SELECT ts, {dims}, {self._select} FROM {self.table} WHERE ts >= ? AND ts < ? "
            f"GROUP BY ts, CUBE ({dims}) ORDER BY ts",
            [start, end],
        )
        fresh[list(self.dims)] = fresh[list(self.dims)].fillna(ALL)
        self._frame = (
            fresh if full else pd.concat([self._frame[self._frame["ts"] < start], fresh], ignore_index=True)
        )
        grouped = self._frame.groupby(list(self.dims), sort=False)
        self._groups = {k if isinstance(k, tuple) else (k,): g for k, g in grouped}
        self.loaded = end

    def series(self, sql: str, segment: dict[str, str]) -> pd.DataFrame:
        """Hourly values (columns ts, value) of one metric in one segment."""
        group = self._groups.get(tuple(segment.get(d, ALL) for d in self.dims))
        if group is None:
            return pd.DataFrame(
                {"ts": pd.Series(dtype="datetime64[us]"), "value": pd.Series(dtype="float64")}
            )
        return pd.DataFrame(
            {
                "ts": group["ts"].to_numpy(),
                "value": pd.to_numeric(group[self.aliases[sql]], errors="coerce").to_numpy(),
            }
        )


def _key(metric: str, segment: dict[str, str]) -> tuple[str, tuple]:
    return metric, tuple(sorted(segment.items()))


def _compatible(a: dict[str, str], b: dict[str, str]) -> bool:
    return all(a[d] == b[d] for d in a.keys() & b.keys())


class Watcher:
    """Scores the top KPIs every tick, a rotating batch of other segments, and anything unusual last tick."""

    def __init__(self, db: Database, graph: MetricGraph, batch_size: int = BATCH_SIZE):
        self.db, self.graph, self.batch_size = db, graph, batch_size
        self._universe = self._build_universe()
        self._pinned: list[tuple[str, dict[str, str]]] = []
        self._cursor = 0
        self._cache: dict[tuple, tuple[pd.DataFrame, datetime]] = {}
        self._streak: dict[tuple, int] = {}
        self._watch: set[tuple] = set()
        self._open_delays: dict[tuple[str, datetime], str] = {}
        self._announced: set[str] = set()
        self._volume_specs: dict[str, MetricSpec | None] = {}
        self._totals: dict[tuple, float | None] = {}
        self._hour_context: dict[datetime, tuple] = {}
        self._tables = {table: TableHistory(db, table, dims) for table, dims in CUBES.items()}
        self._plain: tuple[int, dict[str, dict[str, str]]] = (-1, {})

    def _build_universe(self) -> list[tuple[str, dict[str, str]]]:
        universe = []
        for spec in self.graph.specs.values():
            if spec.name == "rows_completeness":
                continue
            dims = [d for d in spec.dims if d in DIM_VALUES]
            for size in range(min(len(dims), 2) + 1):
                for combo in itertools.combinations(dims, size):
                    for values in itertools.product(*(DIM_VALUES[d] for d in combo)):
                        universe.append((spec.name, dict(zip(combo, values, strict=True))))
        return universe

    def pin(self, metric: str) -> None:
        """Start scoring a newly added metric (all traffic and every market) on every tick."""
        self._universe = self._build_universe()
        self._pinned += [
            (metric, {}),
            *(
                (metric, {"market": m})
                for m in DIM_VALUES["market"]
                if "market" in self.graph.metric(metric).dims
            ),
        ]

    def _targets(self) -> list[tuple[str, dict[str, str]]]:
        targets = {
            _key(m, s): (m, s)
            for m in (*TOP_KPIS, *COMPONENT_KPIS, *QUALITY_KPIS)
            for s in [{}, *({"market": v} for v in DIM_VALUES["market"])]
        }
        for metric, segment in self._pinned:
            targets.setdefault(_key(metric, segment), (metric, segment))
        for _ in range(self.batch_size):
            metric, segment = self._universe[self._cursor % len(self._universe)]
            targets.setdefault(_key(metric, segment), (metric, segment))
            self._cursor += 1
        for metric, seg in self._watch:
            targets.setdefault((metric, seg), (metric, dict(seg)))
        return list(targets.values())

    def _series(self, spec: MetricSpec, segment: dict[str, str], hour: datetime) -> pd.DataFrame:
        """Hourly history up to and including `hour`, cached; the latest hours are re-read in case they were repaired."""
        _, table, where = spec.parts()
        if (
            not where
            and table in CUBES
            and not any(d in spec.dims and d not in CUBES[table] for d in segment)
        ):
            self._tables[table].refresh(self._plain_exprs()[table], hour)
            return self._tables[table].series(spec.sql, segment)
        key = _key(spec.name, segment)
        end = hour + HOUR
        if key in self._cache and self._cache[key][1] >= end:
            return self._cache[key][0]
        if key in self._cache:
            frame, loaded = self._cache[key]
            start = max(loaded - timedelta(hours=REFRESH_HOURS), hour - timedelta(days=HISTORY_DAYS))
            fresh = metric_series(self.db, spec, start, end, segment)
            frame = pd.concat([frame[frame["ts"] < start], fresh], ignore_index=True)
        else:
            frame = metric_series(self.db, spec, hour - timedelta(days=HISTORY_DAYS), end, segment)
        self._cache[key] = (frame, end)
        return frame

    def _plain_exprs(self) -> dict[str, dict[str, str]]:
        """Per table: sql -> expression of every metric (and its volume) that is a plain aggregate of that table."""
        if self._plain[0] != len(self.graph.specs):
            found: dict[str, dict[str, str]] = {table: {} for table in CUBES}
            for spec in self.graph.specs.values():
                for s in (spec, self._volume_spec(spec)):
                    if s is not None:
                        expr, table, where = s.parts()
                        if not where and table in CUBES:
                            found[table][s.sql] = expr
            self._plain = (len(self.graph.specs), found)
        return self._plain[1]

    def total(
        self, spec: MetricSpec, segment: dict[str, str], start: datetime, end: datetime
    ) -> float | None:
        """The metric over a whole window (cached: past windows never change)."""
        key = (spec.name, tuple(sorted(segment.items())), start, end)
        if key not in self._totals:
            value = metric_total(self.db, spec, start, end, segment)["value"].iloc[0]
            self._totals[key] = None if pd.isna(value) else float(value)
        return self._totals[key]

    def _volume_spec(self, spec: MetricSpec) -> MetricSpec | None:
        if spec.name not in self._volume_specs:
            self._volume_specs[spec.name] = denominator_spec(spec)
        return self._volume_specs[spec.name]

    def _observe(self, spec: MetricSpec, segment: dict[str, str], hour: datetime):
        """(actual, history, volume) for the hour; metrics with a window use rolling windows ending at the hour."""
        den = self._volume_spec(spec)
        if spec.window_hours == 1:
            history = self._series(spec, segment, hour)
            row = history[history["ts"] == hour]["value"]
            volume = None
            if den is not None:
                frame = self._series(den, segment, hour)
                volume = float(frame[frame["ts"] == hour]["value"].sum())
            return (None if row.empty or pd.isna(row.iloc[0]) else float(row.iloc[0])), history, volume
        span = HOUR * spec.window_hours
        rows = []
        for days in range(HISTORY_DAYS + 1):
            end = hour + HOUR - timedelta(days=days)
            rows.append({"ts": end - HOUR, "value": self.total(spec, segment, end - span, end)})
        history = pd.DataFrame(rows)
        actual = history["value"].iloc[0]
        volume = self.total(den, segment, hour + HOUR - span, hour + HOUR) if den is not None else None
        return (None if pd.isna(actual) else float(actual)), history.iloc[1:], volume

    def _score(
        self, metric: str, segment: dict[str, str], hour: datetime, incomplete, entries, explained
    ) -> dict | None:
        spec = self.graph.metric(metric)
        if not completeness.is_scorable(spec, incomplete):
            return None
        actual, history, volume = self._observe(spec, segment, hour)
        if actual is None or (volume is not None and volume < MIN_VOLUME):
            return None
        baseline = compute_baseline(history, hour, spec, volume)
        if baseline is None:
            return None
        here = calendar.entries_for(entries, segment)
        factor = calendar.expected_factor(here, metric)
        expected, spread = baseline.expected * factor, baseline.spread * factor
        return {"actual": actual, "expected": expected, "spread": spread, "z": robust_z(actual, expected, spread),
                "planned": bool(here) and metric in explained}  # fmt: skip

    def score_hour(self, metric: str, segment: dict[str, str], hour: datetime) -> dict | None:
        """Actual, expected and z of one metric in one segment for one closed hour (None if it cannot be scored)."""
        if (
            hour not in self._hour_context
        ):  # calendar and completeness of a closed hour do not change: look them up once
            entries = calendar.entries_at(self.db, hour)
            incomplete = completeness.incomplete_tables(self.db, hour, hour + HOUR)
            self._hour_context[hour] = (incomplete, entries, calendar.explained_metrics(entries, self.graph))
        return self._score(metric, segment, hour, *self._hour_context[hour])

    def _is_bad(self, metric: str, z: float) -> bool:
        """Is a move in the direction of z harmful for this metric (e.g. orders up is not a failure)?"""
        direction = self.graph.metric(metric).bad_direction
        return direction == "both" or (direction == "down") == (z < 0)

    def run_tick(self, hour: datetime) -> list[Case]:
        """Score the hour that just closed; returns new failure/planned cases and data-delay notices."""
        incomplete = completeness.incomplete_tables(self.db, hour, hour + HOUR)
        entries = calendar.entries_at(self.db, hour)
        explained = calendar.explained_metrics(entries, self.graph)
        anomalies = []
        for metric, segment in self._targets():
            key = _key(metric, segment)
            scored = self._score(metric, segment, hour, incomplete, entries, explained)
            if scored is None:
                continue
            hot = abs(scored["z"]) >= Z_ALARM and self._is_bad(metric, scored["z"])
            self._streak[key] = self._streak.get(key, 0) + 1 if hot else 0
            if hot:
                self._watch.add(key)
            else:
                self._watch.discard(key)
            if (abs(scored["z"]) >= Z_SINGLE_HOUR and self._is_bad(metric, scored["z"])) or self._streak[
                key
            ] >= 2:
                weight = self.graph.metric(metric).business_weight
                attention = abs(scored["z"]) * weight * (1 + PERSISTENCE_BONUS * self._streak[key])
                anomalies.append(Anomaly(hour, metric, segment, n_consecutive=self._streak[key], attention=attention,
                                         **{k: scored[k] for k in ("actual", "expected", "z", "planned")}))  # fmt: skip
        cases = self._group(hour, [a for a in anomalies if not a.planned], "failure")
        cases += self._group(hour, [a for a in anomalies if a.planned], "planned")
        cases.sort(key=lambda c: -c.attention)
        failures = [c for c in cases if c.kind == "failure"][:MAX_CASES_PER_TICK]
        result = (
            failures
            + [c for c in cases if c.kind == "planned"]
            + self._planned_notices(hour, entries)
            + self._delay_notices(hour, incomplete)
        )
        self._persist(hour, result)
        return result

    def _group(self, hour: datetime, anomalies: list[Anomaly], kind: str) -> list[Case]:
        """Merge anomalies that sit on one causal chain (one is upstream of the other) in compatible segments."""
        parent = list(range(len(anomalies)))

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i, j in itertools.combinations(range(len(anomalies)), 2):
            a, b = anomalies[i], anomalies[j]
            if self.graph.related(a.metric, b.metric) and _compatible(a.segment, b.segment):
                parent[find(i)] = find(j)
        groups: dict[int, list[Anomaly]] = {}
        for i, anomaly in enumerate(anomalies):
            groups.setdefault(find(i), []).append(anomaly)
        cases = []
        for n, members in enumerate(sorted(groups.values(), key=lambda g: -max(a.attention for a in g))):
            top = max(members, key=lambda a: a.attention)
            direction = "above" if top.z > 0 else "below"
            pct = abs(top.actual - top.expected) / abs(top.expected) * 100 if top.expected else None
            size = f"{pct:.0f}%" if pct is not None else "far"
            where = ", ".join(f"{k}={v}" for k, v in top.segment.items()) or "all traffic"
            label = "Planned change" if kind == "planned" else "Unusual change"
            cases.append(Case(
                case_id=f"C{hour:%Y%m%d%H}-{kind[0]}{n + 1}", ts=hour, kind=kind,
                headline=f"{label}: {top.metric} is {size} {direction} expected ({where})",
                root_metric=top.metric, segment=top.segment, onset=min(a.onset for a in members),
                attention=max(a.attention for a in members),
                anomalies=sorted(members, key=lambda a: -a.attention),
            ))  # fmt: skip
        return cases

    def _planned_notices(self, hour: datetime, entries: list[dict]) -> list[Case]:
        """An info card the first time a calendar entry is seen active, so people know a change is expected."""
        notices = []
        for entry in entries:
            if entry["name"] not in self._announced:
                self._announced.add(entry["name"])
                effects = ", ".join(f"{m} x{f:g}" for m, f in entry["effect"].items())
                notices.append(Case(case_id=f"P{hour:%Y%m%d%H}-{entry['name']}", ts=hour, kind="planned",
                                    headline=f"Planned event active: {entry['name']} (expected: {effects})",
                                    root_metric=next(iter(entry["effect"]), entry["name"]), segment={}, onset=hour, attention=0.0,
                                    detail={"entry": entry["name"], "effect": entry["effect"]}))  # fmt: skip
        return notices

    def _delay_notices(self, hour: datetime, incomplete: dict[str, float]) -> list[Case]:
        """Open a notice for each newly incomplete table; close notices whose rows have arrived."""
        now = hour + HOUR
        for (table, late_hour), case_id in list(self._open_delays.items()):
            if table not in completeness.incomplete_tables(self.db, late_hour, now):
                self.db.execute("UPDATE cases SET status = 'resolved' WHERE case_id = ?", [case_id])
                del self._open_delays[(table, late_hour)]
        notices = []
        for table, ratio in incomplete.items():
            if (table, hour) not in self._open_delays:
                case = Case(
                    case_id=f"D{hour:%Y%m%d%H}-{table}", ts=hour, kind="data_delay",
                    headline=f"Data delay: {table} for {hour:%H:%M} is only {ratio:.0%} complete",
                    root_metric=table, segment={}, onset=hour, attention=0.0, detail={"table": table, "ratio": ratio},
                )  # fmt: skip
                self._open_delays[(table, hour)] = case.case_id
                notices.append(case)
        return notices

    def _persist(self, hour: datetime, cases: list[Case]) -> None:
        anomaly_rows, case_rows = [], []
        for case in cases:
            case_rows.append({"case_id": case.case_id, "ts": case.ts, "kind": case.kind, "status": "open",
                              "headline": case.headline, "root_metric": case.root_metric,
                              "segment_json": json.dumps(case.segment), "onset_ts": case.onset,
                              "attention": case.attention, "detail_json": json.dumps(case.detail)})  # fmt: skip
            for a in case.anomalies:
                row = {k: v for k, v in asdict(a).items() if k != "segment"}
                anomaly_rows.append({**row, "segment_json": json.dumps(a.segment), "case_id": case.case_id})
        self.db.insert_df("cases", pd.DataFrame(case_rows))
        self.db.insert_df("anomalies", pd.DataFrame(anomaly_rows))
        if cases:
            logger.info("%s: %d case(s): %s", hour, len(cases), "; ".join(c.headline for c in cases))
