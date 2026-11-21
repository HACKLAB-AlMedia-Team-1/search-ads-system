"""The investigator's tools: deterministic, read-only (except notes) and returning small JSON."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from rootsight.agent.evidence import Hypothesis, check
from rootsight.agent.linkup import Linkup
from rootsight.data.loaders import MARKETS
from rootsight.engine.analyzers import analyze
from rootsight.graph.graph import MetricGraph, MetricSpec
from rootsight.graph.series import metric_total
from rootsight.monitor import calendar, completeness
from rootsight.monitor.baseline import DAYS, denominator_spec
from rootsight.monitor.watcher import Case, Watcher
from rootsight.sim.clock import HOUR
from rootsight.sim.users import QueryPool
from rootsight.store.db import Database

MAX_ROWS = 10
MAX_ONSET_HOURS = 12
Z_ALARM = 3.0
IMPACT_Z = 2.0
LOG_CAP = 20.0


def num(x: float | None, digits: int = 4) -> float | None:
    """Round to a few significant digits so tool results stay small."""
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else float(f"{x:.{digits}g}")


@dataclass
class Step:
    """One tool call in the investigation trail."""

    n: int
    tool: str
    args: dict
    result: dict
    reasoning: str = ""


@dataclass
class Toolbox:
    """All tools, bound to one case (its time window ends at the end of the case's hour)."""

    db: Database
    graph: MetricGraph
    watcher: Watcher
    pool: QueryPool
    titles: Mapping[tuple[str, str], str]
    linkup: Linkup
    on_step: Callable[[Step], None] | None = None
    case: Case | None = None
    end: datetime = field(default_factory=datetime.now)
    trail: list[Step] = field(default_factory=list)
    notes: dict = field(default_factory=dict)

    def start(self, case: Case) -> None:
        """Bind the toolbox to a case and clear the previous investigation."""
        self.case, self.end, self.trail, self.notes = case, case.ts + HOUR, [], {"hypotheses": []}

    def call(self, name: str, args: dict, reasoning: str = "") -> dict:
        """Run a tool by name; errors become `{"error": ...}` so one bad call never stops an investigation."""
        try:
            result = getattr(self, name)(**args)
        except (KeyError, ValueError, TypeError) as exc:
            result = {"error": f"{type(exc).__name__}: {exc}"}
        step = Step(len(self.trail) + 1, name, args, result, reasoning)
        self.trail.append(step)
        if self.on_step:
            self.on_step(step)
        return result

    def _spec(self, name: str) -> MetricSpec:
        return self.graph.metric(name)

    def expected_total(self, spec: MetricSpec, segment: dict, start: datetime, end: datetime) -> float | None:
        """Median of the same window on up to 7 earlier comparable days (same day type)."""
        weekend, values = start.weekday() >= 5, []
        for days in range(1, 15):
            s = start - timedelta(days=days)
            if (s.weekday() >= 5) == weekend and (
                v := self.watcher.total(spec, segment, s, s + (end - start))
            ) is not None:
                values.append(v)
        return float(np.median(values[:DAYS])) if len(values) >= 3 else None

    def onset(self, metric: str, segment: dict) -> datetime | None:
        """Start of the unbroken run of unusual hours (same direction) that ends at the latest hour."""
        run, sign = None, None
        for k in range(1, MAX_ONSET_HOURS + 1):
            hour = self.end - HOUR * k
            score = self.watcher.score_hour(metric, segment, hour)
            if score is None or abs(score["z"]) < Z_ALARM or (sign is not None and (score["z"] > 0) != sign):
                break
            sign, run = score["z"] > 0, hour
        return run

    def window(self, hours: int | None = None) -> tuple[datetime, datetime]:
        """The analysis window: from the case onset (or `hours` back) to the end of the case hour."""
        start = self.end - HOUR * hours if hours else min(self.case.onset, self.end - HOUR)
        return max(start, self.end - HOUR * MAX_ONSET_HOURS), self.end

    # ---------- observation ----------

    def get_metric(self, name: str, segment: dict | None = None, hours: int = 6) -> dict:
        """Actual, expected and z for each of the last hours, plus the onset of the current run."""
        segment = segment or {}
        rows = []
        for k in range(min(hours, MAX_ONSET_HOURS), 0, -1):
            hour = self.end - HOUR * k
            s = self.watcher.score_hour(name, segment, hour)
            if s:
                rows.append(
                    {
                        "hour": f"{hour:%d %H:00}",
                        "actual": num(s["actual"]),
                        "expected": num(s["expected"]),
                        "z": num(s["z"], 3),
                    }
                )
        onset = self.onset(name, segment)
        return {
            "metric": name,
            "segment": segment,
            "hours": rows,
            "onset": onset.isoformat() if onset else None,
        }

    def decompose(self, metric: str, segment: dict | None = None, window: int | None = None) -> dict:
        """Share (in %, sums to 100) of each formula factor in the change of `metric` versus expected."""
        segment, (start, end) = segment or {}, self.window(window)
        inputs = self.graph.formula_inputs(metric)
        if not inputs:
            return {"metric": metric, "formula": None}
        rows = []
        for item in inputs:
            spec = self._spec(item["metric"])
            actual = metric_total(self.db, spec, start, end, segment)["value"].iloc[0]
            expected = self.expected_total(spec, segment, start, end)
            rows.append(
                {
                    "factor": item["metric"],
                    "role": item["role"],
                    "actual": float(actual),
                    "expected": expected,
                }
            )
        additive = any(r["role"] == "addend" for r in rows)
        for r in rows:
            a, e = r["actual"], r["expected"]
            if a is None or e is None or math.isnan(a):
                r["change"] = 0.0
            elif additive:
                r["change"] = a - e
            else:
                log = math.log(max(a, 1e-9) / max(e, 1e-9))
                r["change"] = max(-LOG_CAP, min(LOG_CAP, -log if r["role"] == "denominator" else log))
        total = sum(r["change"] for r in rows)
        return {
            "metric": metric,
            "factors": sorted(
                ({"factor": r["factor"], "actual": num(r["actual"]), "expected": num(r["expected"]),
                  "share_pct": num(100 * r["change"] / total, 3) if total else 0.0} for r in rows),
                key=lambda r: -abs(r["share_pct"]),
            ),
        }  # fmt: skip

    def drill_down(
        self, metric: str, dimension: str, segment: dict | None = None, window: int | None = None
    ) -> dict:
        """Values of `dimension` ranked by their share of the metric's total deviation, each with its latest z."""
        segment, (start, end) = segment or {}, self.window(window)
        spec = self._spec(metric)
        if dimension not in spec.dims:
            return {"error": f"{metric} cannot be split by {dimension}; use one of {list(spec.dims)}"}
        den = denominator_spec(spec)
        actual = metric_total(self.db, spec, start, end, segment, by=[dimension])
        rows = []
        for value, a in zip(actual[dimension], actual["value"], strict=True):
            part = {**segment, dimension: value}
            expected = self.expected_total(spec, part, start, end)
            volume = self.expected_total(den, part, start, end) if den else 1.0
            z = self.watcher.score_hour(metric, part, end - HOUR)
            rows.append(
                {
                    "value": value,
                    "actual": a,
                    "expected": expected,
                    "volume": volume or 0.0,
                    "z": z and z["z"],
                }
            )
        total_volume = sum(r["volume"] for r in rows) or 1.0
        for r in rows:
            r["contribution"] = (
                0.0
                if r["expected"] is None or math.isnan(r["actual"])
                else r["volume"] / total_volume * (r["actual"] - r["expected"])
            )
        total = sum(r["contribution"] for r in rows)
        ranked = sorted(rows, key=lambda r: -abs(r["contribution"]))[:MAX_ROWS]
        return {
            "metric": metric,
            "dimension": dimension,
            "segments": [
                {"value": r["value"], "actual": num(r["actual"]), "expected": num(r["expected"]),
                 "share_pct": num(100 * r["contribution"] / total, 3) if total else 0.0, "z": num(r["z"], 3)}
                for r in ranked
            ],
        }  # fmt: skip

    def graph_neighbors(self, metric: str) -> dict:
        """What composes, may cause or is affected by a metric, with edge types and confidence."""
        near = self.graph.neighbors(metric)
        return {"metric": metric, **{k: v[:MAX_ROWS] for k, v in near.items() if v}}

    def get_events(self, hours_back: int = 6, component: str | None = None) -> dict:
        """Releases, configs, jobs and calendar entries in the last hours (decoys included), newest first."""
        sql = "SELECT event_id, ts, type, component, detail FROM events WHERE ts <= ? AND ts > ?"
        params: list = [self.end, self.end - HOUR * hours_back]
        if component:
            sql, params = sql + " AND component = ?", [*params, component]
        frame = self.db.df(sql + f" ORDER BY ts DESC LIMIT {MAX_ROWS + 5}", params)
        return {"events": [{"event_id": int(r.event_id), "ts": f"{r.ts:%d %H:%M}", "type": r.type, "component": r.component,
                            "detail": r.detail} for r in frame.itertuples()]}  # fmt: skip

    def check_completeness(self, table: str, hours: int = 6) -> dict:
        """rows_received / rows_expected per hour for `search_events`, `orders` or `ads`, as known now."""
        rows = []
        for k in range(min(hours, MAX_ONSET_HOURS), 0, -1):
            hour = self.end - HOUR * k
            ratio = completeness.arrival_ratios(self.db, hour, self.end).get(table)
            rows.append({"hour": f"{hour:%d %H:00}", "ratio": num(ratio, 3)})
        return {"table": table, "hours": rows}

    def component_health(self, component: str) -> dict:
        """Latest value of every health metric of a component next to its normal value (median of 7 days)."""
        hour = self.end - HOUR
        frame = self.db.df(
            "SELECT ts, scope, metric, value FROM component_hourly WHERE component = ? AND ts <= ? AND ts > ?",
            [component, hour, hour - timedelta(days=14)],
        )
        rows = []
        for (scope, metric), group in frame.groupby(["scope", "metric"]):
            now = group[group["ts"] == hour]["value"]
            past = group[(group["ts"] < hour) & (group["ts"].dt.hour == hour.hour)]["value"].tail(7)
            if len(now):
                rows.append({"scope": scope, "metric": metric, "now": num(float(now.iloc[0])),
                             "normal": num(float(past.median())) if len(past) else None})  # fmt: skip
        return {"component": component, "health": rows[:MAX_ROWS]}

    def sample_searches(self, market: str, platform: str, n: int = 5) -> dict:
        """Recent real searches (query, filters, zero-result flag, top titles) for a market and platform."""
        frame = self.db.df(
            "SELECT ts, query, filters_json, result_ids_json, zero_result, source FROM search_samples "
            "WHERE market = ? AND platform = ? AND ts <= ? ORDER BY ts DESC LIMIT ?",
            [market, platform, self.end, min(n, MAX_ROWS)],
        )
        samples = []
        for r in frame.itertuples():
            ids = json.loads(r.result_ids_json)
            samples.append({"market": market, "query": r.query, "filters": json.loads(r.filters_json), "zero_result": bool(r.zero_result),
                            "top_titles": [self.titles.get((market, p), "?")[:60] for p in ids[:3]], "ids": ids[:3]})  # fmt: skip
        return {"samples": samples}

    def judge_relevance(self, samples: list[dict]) -> dict:
        """Rate result titles against the query by word overlap, cross-checked with ESCI labels."""
        lang = {market: code for market, (_, code) in MARKETS.items()}
        rated = unrelated = agree = checked = 0
        for s in samples:
            q = set(analyze(s["query"], lang.get(s.get("market", "US"), "en")))
            labels = self.pool.labels.get(
                (s.get("market"), self.pool.query_ids.get((s.get("market"), s["query"]))), {}
            )
            for title, pid in zip(s.get("top_titles", []), s.get("ids", []), strict=False):
                overlap = len(q & set(analyze(title, lang.get(s.get("market", "US"), "en")))) / max(len(q), 1)
                rated, unrelated = rated + 1, unrelated + (overlap == 0)
                if pid in labels:
                    checked, agree = checked + 1, agree + ((overlap >= 0.3) == (labels[pid] in ("E", "S")))
        empty = sum(s["zero_result"] for s in samples)
        pattern = ("results are empty" if empty > len(samples) / 2 else
                   "results share no word with the query" if rated and unrelated / rated > 0.5 else "results look related to the queries")  # fmt: skip
        return {"searches": len(samples), "empty": empty, "rated": rated,
                "unrelated_share": num(unrelated / rated, 2) if rated else None,
                "label_agreement": num(agree / checked, 2) if checked else None, "pattern": pattern}  # fmt: skip

    def ad_pacing(self, campaign: str, day: str | None = None) -> dict:
        """Planned versus actual spend of a campaign for a day, and the hour its budget ran out."""
        day_start = datetime.fromisoformat(day) if day else self.end.replace(hour=0, minute=0)
        frame = self.db.df(
            "SELECT ts, budget_daily_eur, planned_spend_eur, spend_eur FROM ads_hourly "
            "WHERE campaign_id = ? AND ts >= ? AND ts < ? AND ts < ? ORDER BY ts",
            [campaign, day_start, day_start + timedelta(days=1), self.end],
        )
        if frame.empty:
            return {"campaign": campaign, "hours": []}
        budget = float(frame["budget_daily_eur"].iloc[0])
        cumulative = frame["spend_eur"].cumsum()
        spent_out = frame[cumulative >= 0.99 * budget]
        worst = (
            frame.assign(gap=(frame["spend_eur"] - frame["planned_spend_eur"]).abs())
            .nlargest(MAX_ROWS, "gap")
            .sort_values("ts")
        )
        return {
            "campaign": campaign, "budget_eur": num(budget), "spent_eur": num(float(cumulative.iloc[-1])),
            "budget_exhausted_at": f"{spent_out['ts'].iloc[0]:%H:00}" if len(spent_out) else None,
            "hours": [{"hour": f"{r.ts:%H:00}", "planned": num(r.planned_spend_eur), "actual": num(r.spend_eur)} for r in worst.itertuples()],
        }  # fmt: skip

    def purchase_orders(self, market: str) -> dict:
        """Latest purchase orders for a market's top sellers: units needed, ordered and received, and the due date."""
        frame = self.db.df(
            "SELECT * FROM purchase_orders WHERE market = ? AND due_at <= ? ORDER BY due_at DESC LIMIT 3",
            [market, self.end],
        )
        orders = []
        for r in frame.itertuples():
            overdue = bool(pd.isna(r.received_at) or r.received_at > self.end)
            orders.append({"po_id": r.po_id, "created": f"{r.created_at:%d %b %H:%M}", "due": f"{r.due_at:%d %b %H:%M}",
                           "qty_needed": int(r.qty_needed), "qty_ordered": int(r.qty_ordered),
                           "qty_received": 0 if overdue else int(r.qty_received), "overdue": overdue})  # fmt: skip
        return {"market": market, "orders": orders}

    def calendar_lookup(self, ts: str | None = None, scope: dict | None = None) -> dict:
        """Planned events (campaigns etc.) covering a time and scope."""
        when = datetime.fromisoformat(ts) if ts else self.end - HOUR
        entries = calendar.entries_for(calendar.entries_at(self.db, when), scope or {})
        return {"entries": [{"name": e["name"], "kind": e["kind"], "effect": e["effect"]} for e in entries]}

    def web_check(self, question: str) -> dict:
        """Ask the web for outside context (skipped when Linkup is off)."""
        return self.linkup.web_check(question)

    # ---------- judgement and impact ----------

    def record_hypothesis(
        self, cause: str, metric: str, segment: dict | None = None, event_id: int | None = None
    ) -> dict:
        """Test 'event E caused the change in `metric` in `segment`' with the 4-point evidence checklist (in code)."""
        result = check(self, Hypothesis(cause, metric, segment or {}, event_id))
        self.notes["hypotheses"].append(result)
        return result.summary()

    def estimate_impact(self, segment: dict | None = None) -> dict:
        """Lost orders and revenue (EUR), wasted ad spend (EUR) and budget spent outside the plan since onset.

        Counted inside the affected market/platform (default: the segment of the latest hypothesis).
        """
        start, end = self.window()
        if segment is None:
            segment = self.notes["hypotheses"][-1].hypothesis.segment if self.notes["hypotheses"] else {}
        shop = {k: v for k, v in segment.items() if k in ("market", "platform")}
        ads = {k: v for k, v in segment.items() if k == "market"}
        hours, lost = [start + HOUR * k for k in range(int((end - start) / HOUR))], 0.0
        for hour in hours:
            s = self.watcher.score_hour("orders", shop, hour)
            lost += s["expected"] - s["actual"] if s and s["z"] <= -IMPACT_Z else 0.0
        expected_aov = self.expected_total(self._spec("aov"), shop, start, end) or 0.0
        spend = metric_total(self.db, self._spec("ad_spend"), start, end, ads)["value"].iloc[0]
        actual_roas = metric_total(self.db, self._spec("roas"), start, end, ads)["value"].iloc[0]
        expected_roas = self.expected_total(self._spec("roas"), ads, start, end) or 0.0
        wasted = (
            0.0
            if pd.isna(spend) or pd.isna(actual_roas) or not expected_roas
            else float(spend) * max(0.0, 1 - float(actual_roas) / expected_roas)
        )
        sql = "SELECT sum(greatest(spend_eur - planned_spend_eur, 0)) AS over FROM ads_hourly WHERE ts >= ? AND ts < ?"
        over = self.db.df(sql + (" AND market = ?" if ads else ""), [start, end, *ads.values()])["over"].iloc[
            0
        ]
        result = {"hours": len(hours), "lost_orders": num(lost), "lost_revenue_eur": num(lost * expected_aov),
                  "wasted_ad_spend_eur": num(wasted), "ad_spend_over_plan_eur": num(0.0 if pd.isna(over) else float(over))}  # fmt: skip
        self.notes["impact"] = result
        return result

    def finish(self, summary: str = "") -> dict:
        """End the investigation; the report is assembled in code from the recorded results."""
        self.notes["summary"] = summary
        return {"done": True}
