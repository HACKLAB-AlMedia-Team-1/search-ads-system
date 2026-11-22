"""Shared by every dashboard page: the live runtime (simulation thread + web shop), the sidebar and small UI helpers."""

from __future__ import annotations

import json
import logging
import shutil
import sys
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st
import theme
from shop_server import start_shop

from rootsight.config import load_settings
from rootsight.data.german import wrong_language
from rootsight.logging_setup import setup_logging
from rootsight.pipeline import Pipeline
from rootsight.sim.clock import HOUR
from rootsight.sim.faults import Fault, Scenario, load_scenarios
from rootsight.store.db import Database

logger = logging.getLogger(__name__)

BAND_SIGMAS = 3
SHOP_PORT = 8600
SHOP_URL = f"http://localhost:{SHOP_PORT}"
LANGUAGE_MARKETS = {"DE": "Germany", "US": "United States"}
SPEEDS = {"Slow": 6.0, "Normal": 3.0, "Fast": 1.0}
SIMULATE_SPEED = "Fast"
AD_CAMPAIGN = {"AD1": "CMP-DE"}


@dataclass
class LanguageRun:
    """Storefront observations and hourly orders for Step 1."""

    market: str
    counts: tuple[int, int] = (0, 0)
    last_search_empty: bool = False
    last_empty_hour: datetime | None = None
    first_failure: datetime | None = None
    orders: list[dict[str, datetime | float]] = field(default_factory=list)


class Runtime:
    """One shared pipeline for all browser sessions; a background thread advances the simulated clock."""

    def __init__(self) -> None:
        setup_logging()
        self.settings = load_settings()
        fresh_start(self.settings.duckdb_path)
        self.db = Database(self.settings.duckdb_path)
        self.pipeline = Pipeline.from_settings(self.settings, self.db)
        self.scenarios: dict[str, Scenario] = load_scenarios(ROOT / "scenarios")
        self.lock = threading.RLock()
        self.seconds_per_hour = self.settings.seconds_per_sim_hour
        self.running = False
        self.started: dict[str, datetime] = {}
        self._activations: dict[str, tuple[Scenario, Fault]] = {}
        self.shop_market = "DE"
        self.shop_revision = 0
        self.language_run: LanguageRun | None = None
        self._ad_run_start: dict[str, tuple[datetime, float]] = {}
        self._thread: threading.Thread | None = None
        self._wake = threading.Event()
        self._points: dict[tuple, dict | None] = {}
        self._latest: dict[tuple, dict | None] = {}
        self._wanted: set[tuple] = set()
        try:
            self.shop = start_shop(self, SHOP_PORT)
        except OSError:
            self.shop = None
            logger.warning("Port %d is in use; the web shop was not started", SHOP_PORT)

    @property
    def now(self) -> datetime:
        """The next simulated hour (everything before it is already in the database)."""
        return self.pipeline.now

    @property
    def busy(self) -> bool:
        """Is the simulation advancing right now?"""
        return self._thread is not None and self._thread.is_alive()

    def _work(self) -> None:
        """Background worker: queued hours run back to back; the running clock waits `seconds_per_hour` between hours."""
        while self.running:
            with self.lock:
                self.pipeline.step()
                self._score_wanted()
                self._record_hourly_orders()
            self._wake.wait(self.seconds_per_hour)
            self._wake.clear()

    def _ensure_worker(self) -> None:
        with self.lock:
            if not self.busy:
                self._thread = threading.Thread(target=self._work, daemon=True)
                self._thread.start()

    def start(self) -> None:
        """Run the simulation continuously in the background, one hour every `seconds_per_hour`."""
        self.running = True
        self._ensure_worker()

    def pause(self) -> None:
        """Stop the background simulation and wait for the hour in progress to finish."""
        self.running = False
        self._wake.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=60)

    def active(self) -> list[str]:
        """Ids of the scenarios whose fault is switched on right now."""
        active = [sid for sid, (_, fault) in self._activations.copy().items() if fault.matches(self.now, None, None)]
        if self.language_run is not None and "L1" not in active:
            active.append("L1")
        return active

    def journey_market(self) -> str:
        """Country of the first step, locked to Deliver to when the run starts."""
        run = self.language_run
        return run.market if run else self.shop_market

    def _activate(self, scenario: Scenario) -> None:
        scenario = scenario.shifted(self.now)
        self._activations[scenario.id] = (scenario, self.pipeline.sim.activate(scenario))
        self.pipeline.sim.engine.cache.clear()

    def record_shop_search(self, market: str, query: str, empty: bool) -> None:
        """Count a storefront search and start investigation on the first observed language failure."""
        run = self.language_run
        if run is None or run.market != market or not query:
            return
        if empty and wrong_language(query, market) and run.first_failure is None:
            self._activate(replace(self.scenarios["L1"].for_market(market), end=None))
            run.first_failure = self.now
        searches, misses = run.counts
        run.counts = (searches + 1, misses + int(empty))
        run.last_search_empty = empty
        if empty:
            run.last_empty_hour = self.now

    def add_scenario(self, path: Path) -> None:
        """Make a newly saved scenario file available to Simulate."""
        self.scenarios.update(load_scenarios(path.parent, path.name))

    def simulate(self, sid: str) -> bool:
        """Switch a scenario on and run the clock fast (one simulated hour per second), so the agent works live."""
        with self.lock:
            if sid in self.started:
                return False
            if sid == "L1":
                if self.shop_market not in LANGUAGE_MARKETS:
                    return False
                self.language_run = LanguageRun(self.shop_market)
            else:
                scenario = self.scenarios[sid]
                self._activate(scenario)
                if sid in AD_CAMPAIGN:
                    spent = self.pipeline.sim.pacer.spent(scenario.scope["market"], self.now.date())
                    self._ad_run_start[sid] = (self.now, spent)
            self.started[sid] = self.now
        self.seconds_per_hour = SPEEDS[SIMULATE_SPEED]
        self.start()
        return True

    def fix(self, sid: str | None = None) -> None:
        """End the selected simulation, keeping the clock and incident history."""
        with self.lock:
            if sid is not None and sid not in self.started:
                return
            ended = tuple(self.started) if sid is None else (sid,)
            for scenario_id in ended:
                if activation := self._activations.get(scenario_id):
                    self.pipeline.sim.end_scenario(*activation, self.now)
                    del self._activations[scenario_id]
                if scenario_id == "L1":
                    self.language_run = None
                self._ad_run_start.pop(scenario_id, None)
                self.started.pop(scenario_id, None)
            if ended:
                self.shop_revision += 1

    def _investigation_start(self, sid: str) -> datetime | None:
        if sid == "L1":
            run = self.language_run
            return run.first_failure if run else None
        return self.started.get(sid)

    def finding(self, sid: str) -> dict | None:
        """The agent's report for a scenario started from the UI: the incident that blames the scenario's component."""
        scenario, since = self.scenarios[sid], self._investigation_start(sid)
        if since is None or not scenario.event_log:
            return None
        market = self.journey_market() if sid == "L1" else ""
        detail = scenario.for_market(market).event_log[0]["detail"] if sid == "L1" else ""
        row = self.db.df(
            "SELECT incident_id, status, report_json FROM incidents WHERE cause_component = ? AND last_seen >= ? "
            "AND (? <> 'L1' OR json_extract_string(segment_json, '$.market') = ? "
            "OR (json_extract_string(segment_json, '$.market') IS NULL "
            "AND contains(json_extract_string(report_json, '$.report.cause'), ?))) "
            "ORDER BY last_seen DESC LIMIT 1",
            [scenario.event_log[0]["component"], since, sid, market, detail],
        )
        if row.empty:
            return None
        return {
            "incident_id": int(row["incident_id"].iloc[0]),
            "state": row["status"].iloc[0],
            **json.loads(row["report_json"].iloc[0])["report"],
        }

    def progress(self, sid: str) -> list[str]:
        """What the agent is doing for a started scenario, newest stage last: watching, anomaly, investigation."""
        since = self._investigation_start(sid)
        if since is None:
            return []
        hours = int((self.now - since) / HOUR)
        lines = [f"Hour {hours} since the fault started: the agent scores every metric each simulated hour."]
        market = self.journey_market() if sid == "L1" else self.scenarios[sid].scope.get("market", "all")
        anomaly = self.db.df(
            "SELECT case_id, ts, metric, segment_json, actual, expected, z FROM anomalies "
            "WHERE ts >= ? AND NOT planned AND (? = 'all' OR json_extract_string(segment_json, '$.market') = ?) "
            "AND (? <> 'L1' OR metric = 'zero_result_rate') ORDER BY attention DESC LIMIT 1",
            [since, market, market, sid],
        )
        if anomaly.empty:
            return [*lines, "No unusual numbers yet."]
        a = anomaly.iloc[0]
        where = ", ".join(json.loads(a["segment_json"]).values()) or "all traffic"
        name = self.pipeline.graph.metric(a["metric"]).description if a["metric"] in self.pipeline.graph.specs else a["metric"]
        lines.append(f"Anomaly at {a['ts']:%H:00}: {name} in {where} is {a['actual']:,.3g} against a normal "
                     f"{a['expected']:,.3g} ({a['z']:+.1f} standard deviations).")  # fmt: skip
        case_id = a["case_id"]
        steps = self.db.df(
            "SELECT step, tool, reasoning FROM investigations WHERE case_id = ? ORDER BY step", [case_id]
        )
        if steps.empty:
            return [*lines, f"Case {case_id} opened; the investigation is starting."]
        if (found := self.finding(sid)) is not None:
            done = f"{len(steps)} checks; finding confirmed as incident #{found['incident_id']} (see below)"
            return [*lines, f"Case {case_id} investigated with {done}."]
        last = steps.iloc[-1]
        latest = f"'{last['tool']}' ({last['reasoning'] or 'gathering evidence'})"
        return [*lines, f"Investigating case {case_id}: {len(steps)} checks so far, latest {latest}."]

    def _record_hourly_orders(self) -> None:
        run = self.language_run
        if run is None or not run.counts[0]:
            return
        hour, segment = self.now - HOUR, (("market", run.market),)
        key = ("orders", segment, hour)
        if key not in self._points:
            self._points[key] = self.pipeline.watcher.score_hour("orders", dict(segment), hour)
        if point := self._points[key]:
            if not run.orders:
                run.orders.append({"ts": hour, "expected": 0.0, "received": 0.0})
            blocked = run.last_search_empty or run.last_empty_hour == hour
            run.orders.append({
                "ts": self.now, "expected": point["expected"],
                "received": 0.0 if blocked else point["actual"],
            })

    def ads_chart(self, sid: str) -> pd.DataFrame:
        """Cumulative spend from this run, with a fresh daily budget at midnight."""
        now = self.now
        run_start = self._ad_run_start.get(sid)
        if run_start is None:
            return pd.DataFrame()
        since, opening_spend = run_start
        start = max(since, (now - HOUR).replace(hour=0))
        prior_spend = opening_spend if start == since else 0.0
        frame = self.db.df(
            "SELECT ts, budget_daily_eur, planned_spend_eur, spend_eur FROM ads_hourly WHERE campaign_id = ? "
            "AND ts >= ? AND ts < ? ORDER BY ts",
            [AD_CAMPAIGN[sid], start, now],
        )
        available = (frame["budget_daily_eur"] - prior_spend).clip(lower=0).round(2)
        market = self.scenarios[sid].scope["market"]
        sim = self.pipeline.sim
        opening_budget = (
            max(sim.pacer.budget(market, start, sim.faults) - prior_spend, 0.0)
            if available.empty else available.iloc[0]
        )
        origin = pd.DataFrame([{"ts": start, "budget": round(opening_budget, 2), "spend": 0.0, "planned": 0.0}])
        if frame.empty:
            return origin
        run = frame.assign(
            ts=frame["ts"] + HOUR,
            budget=available,
            spend=frame["spend_eur"].cumsum().round(2),
            planned=frame["planned_spend_eur"].cumsum().round(2).clip(upper=available),
        )
        return pd.concat([origin, run[origin.columns]], ignore_index=True)

    def notices(self, sid: str) -> list[str]:
        """Info cards (planned event, data delay) raised since an innocent scenario was started."""
        since = self.started.get(sid)
        if since is None:
            return []
        frame = self.db.df(
            "SELECT headline FROM cases WHERE kind IN ('planned', 'data_delay') AND ts >= ? ORDER BY ts LIMIT 3",
            [since],
        )
        return frame["headline"].tolist()

    def log_ux(
        self,
        event: str,
        market: str,
        platform: str,
        query: str = "",
        position: int | None = None,
        value: float = 0.0,
        session: str = "",
    ) -> None:
        """Record one real storefront interaction (search, click, add to cart, ...) for the UX panel."""
        row = {"ts": datetime.now(), "session_id": session, "market": market, "platform": platform, "event": event,
               "query": query, "position": position, "value": value}  # fmt: skip
        self.db.insert_df("ux_events", pd.DataFrame([row]))

    def point(self, metric: str, segment: dict, hour: datetime) -> dict | None:
        """Actual, expected, spread and z of a metric for a closed hour (cached per hour).

        The page never computes while the simulation is advancing (that made the screen wait and slowed the
        simulation down): the worker fills in the newest hour for every series a page has asked for, and until
        then the last known value is shown.
        """
        series = (metric, tuple(sorted(segment.items())))
        key = (*series, hour)
        self._wanted.add(series)
        if key not in self._points:
            if self.busy:
                return self._latest.get(series)
            with self.lock:
                self._points[key] = self.pipeline.watcher.score_hour(metric, segment, hour)
        self._latest[series] = self._points[key]
        return self._points[key]

    def forget_points(self) -> None:
        """Drop every cached score (after a metric's SQL changed)."""
        self._points.clear()
        self._latest.clear()

    def _score_wanted(self) -> None:
        """After an hour is simulated: score that hour for every series the pages show (called with the lock held)."""
        hour = self.now - HOUR
        for metric, segment in list(self._wanted):
            self._points[(metric, segment, hour)] = self.pipeline.watcher.score_hour(
                metric, dict(segment), hour
            )

    def _known(self, metric: str, segment: dict, hour: datetime) -> dict | None:
        """The value for exactly this hour, or None if it is not known yet (the chart adds it on a later refresh)."""
        self.point(metric, segment, hour)
        return self._points.get((metric, tuple(sorted(segment.items())), hour))

    def band(self, metric: str, segment: dict | None = None, hours: int = 36) -> pd.DataFrame:
        """Hourly actual with the expected band for the last `hours` closed hours."""
        rows = []
        for k in range(hours, 0, -1):
            hour = self.now - HOUR * k
            p = self._known(metric, segment or {}, hour)
            if p:
                rows.append({"ts": hour, "actual": p["actual"], "expected": p["expected"], "z": p["z"],
                             "low": p["expected"] - BAND_SIGMAS * p["spread"], "high": p["expected"] + BAND_SIGMAS * p["spread"]})  # fmt: skip
        return pd.DataFrame(rows)

    def shutdown(self) -> None:
        """Stop the simulation and the web shop and close the database (used by 'Reset demo')."""
        self.pause()
        if self.shop:
            self.shop.shutdown()
            self.shop.server_close()
        with self.lock:
            self.db.close()


@st.cache_resource(show_spinner="Starting RootSight (loading the search engine) ...")
def get_runtime() -> Runtime:
    """The single shared runtime (created on first use)."""
    return Runtime()


def fresh_start(path: Path) -> None:
    """Start from the 14 clean days of history: restore the backfill snapshot and drop leftovers of the last run.

    Faults live only in memory, so after a restart an old database would hold incidents whose fault no longer exists.
    """
    snapshot = path.with_suffix(".backfill.duckdb")
    if not snapshot.is_file():
        logger.warning("No snapshot %s; using the database as it is (run scripts/backfill.py)", snapshot.name)
        return
    path.with_name(path.name + ".wal").unlink(
        missing_ok=True
    )  # unfinished writes of a run that was stopped with Ctrl+C
    shutil.copy(snapshot, path)
    path.with_name("metrics_custom.yaml").unlink(missing_ok=True)


def reset_demo() -> None:
    """Throw away everything that happened in the demo and restore the 14 clean days of history."""
    get_runtime().shutdown()
    get_runtime.clear()  # the next page run builds a new Runtime, which starts fresh


def controls(rt: Runtime, key: str) -> None:
    """Start or pause the simulated clock and choose the speed."""
    run, speed = st.columns([1.3, 4.2], vertical_alignment="bottom")
    label = "⏸ Pause" if rt.running else "▶ Start the clock"
    run.button(
        label,
        key=f"{key}_run",
        type="primary",
        width="stretch",
        on_click=rt.pause if rt.running else rt.start,
    )
    current = min(SPEEDS, key=lambda name: abs(SPEEDS[name] - rt.seconds_per_hour))
    choice = speed.segmented_control(
        "Speed (one simulated hour)", list(SPEEDS), default=current, key=f"{key}_speed"
    )
    rt.seconds_per_hour = SPEEDS[choice or current]


@st.fragment(run_every=1)
def _status(rt: Runtime) -> None:
    active = rt.active()
    faults = "".join(f"<br>● {sid}: {rt.scenarios[sid].name}" for sid in active) or "<br>none"
    clock = "running" if rt.running else "advancing ..." if rt.busy else "paused"
    st.markdown(
        f'<div class="side-status"><span class="muted">Simulated time ({clock})</span><br><b>{rt.now:%a %d %b, %H:%M}</b>'
        f'<br><span class="muted">Active faults</span>{faults}</div>',
        unsafe_allow_html=True,
    )
    if rt.started:
        st.button("End all simulations", key="side_fix", width="stretch", on_click=rt.fix)


def page() -> tuple[Runtime, dict[str, str]]:
    """Common page setup: theme (dark-mode switch) and the sidebar status box. Returns (runtime, palette)."""
    # Streamlit forgets a widget's own state when you move to another page, so the choice is kept in a separate key.
    remembered = st.session_state.setdefault("dark_mode", st.query_params.get("theme") == "dark")
    with st.sidebar:
        st.session_state["dark_mode"] = st.toggle("Dark mode", value=remembered, key="dark_toggle")
        palette = theme.apply(st.session_state["dark_mode"])
        rt = get_runtime()
        _status(rt)
        st.link_button("🛒 Open the ShopLens store", SHOP_URL, width="stretch")
        with st.popover("Reset demo", width="stretch"):
            st.write(
                "Removes every incident and injected fault and goes back to the 14 clean days of history."
            )
            if st.button("Reset now", type="primary"):
                reset_demo()
                st.rerun()
    return rt, palette


def last_hour(rt: Runtime) -> datetime:
    """Start of the most recent closed hour."""
    return rt.now - timedelta(hours=1)
