"""Shared by every dashboard page: the live runtime (simulation thread + web shop), the sidebar and small UI helpers."""

from __future__ import annotations

import json
import logging
import shutil
import sys
import threading
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st
import theme
from shop_server import start_shop

from rootsight.config import load_settings
from rootsight.logging_setup import setup_logging
from rootsight.pipeline import Pipeline
from rootsight.sim.clock import HOUR
from rootsight.sim.faults import Scenario, load_scenarios
from rootsight.store.db import Database

logger = logging.getLogger(__name__)

BAND_SIGMAS = 3
SHOP_PORT = 8600
SHOP_URL = f"http://localhost:{SHOP_PORT}"
FOLLOWS_STORE = ("L1",)  # scenarios that break the country chosen in the store
LANGUAGE_MARKETS = {"DE": "Germany", "US": "United States"}
SPEEDS = {"Slow": 3.0, "Normal": 2.0, "Fast": 1.0}  # real seconds per simulated hour
DEFAULT_SPEED = "Normal"
FAILING_LANGUAGE = {"DE": "English", "US": "German"}  # L1: the language that finds nothing in each country
AD_CAMPAIGN = {"AD1": "CMP-DE"}
NEVER = timedelta(days=3650)  # a simulation started from the UI runs until 'End Simulation', never by itself
NIGHT_HOURS, MORNING_HOUR = range(1, 7), 7  # 01:00-06:59 simulated time is passed without waiting
CHART_LEAD_HOURS, CHART_HOURS = 6, 72  # the step 1 chart: hours shown before Simulate, and at most in total
ONE_OFF = ("DQ1",)  # one late hour by definition: the delay keeps its length, the simulation still runs until it is ended
STORE_EVENTS = {"search": "Your searches", "zero_result": "Found nothing", "no_sponsored": "No sponsored product",
                "cart_unavailable": "Could not add to cart", "add_to_cart": "Added to cart", "checkout": "Orders placed"}  # fmt: skip


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
        self.seconds_per_hour = SPEEDS[DEFAULT_SPEED]
        self.running = False
        self.started: dict[str, datetime] = {}
        self.ended: dict[str, datetime] = {}
        self.wall: dict[str, tuple[datetime, datetime | None]] = {}  # real time of Simulate / End, for the store activity
        self.changes = 0  # counts Simulate / End presses; an open store tab reloads when it changes
        self.shop_market = "DE"
        self.broken_market: dict[str, str] = {}
        self._thread: threading.Thread | None = None
        self._wake = threading.Event()
        self._points: dict[tuple, dict | None] = {}
        self._latest: dict[tuple, dict | None] = {}
        self._wanted: set[tuple] = set()
        self._history: dict[tuple, int] = {}
        self._normal_found: dict[str, dict[int, float]] = {}
        try:
            self.shop = start_shop(self, SHOP_PORT)
        except OSError:
            self.shop = None
            logger.warning("Port %d is in use; the web shop was not started", SHOP_PORT)
        self.start()  # monitoring is live from the moment the dashboard loads

    @property
    def now(self) -> datetime:
        """The next simulated hour (everything before it is already in the database)."""
        return self.pipeline.now

    @property
    def busy(self) -> bool:
        """Is the simulation advancing right now (the clock is running)?"""
        return self._thread is not None and self._thread.is_alive()

    def _work(self) -> None:
        """Background worker: simulates one hour, then waits `seconds_per_hour`, until the clock is stopped."""
        while self.running:
            with self.lock:
                if not self.running:  # stopped while this thread waited for the lock: no extra hour
                    break
                self.pipeline.step()
                self._score_wanted()
            if self.now.hour not in NIGHT_HOURS:  # nights have too few shoppers to judge anything: pass them quickly
                self._wake.wait(self.seconds_per_hour)
            self._wake.clear()

    def start(self) -> None:
        """Run the simulation continuously in the background, one hour every `seconds_per_hour`."""
        with self.lock:
            self.running = True
            if not self.busy:
                self._wake.clear()
                self._thread = threading.Thread(target=self._work, daemon=True)
                self._thread.start()

    def pause(self) -> None:
        """Stop the background simulation and wait for the hour in progress to finish."""
        self.running = False
        self._wake.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=60)

    def active(self) -> list[str]:
        """Ids of the scenarios whose simulation is running: started with 'Simulate it' and not ended yet."""
        return [sid for sid in self.started if sid not in self.ended]

    def journey_market(self) -> str:
        """Country of the journey's first step: where L1 is broken, else the store's 'Deliver to' (US or DE)."""
        if "L1" in self.active() and "L1" in self.broken_market:
            return self.broken_market["L1"]
        return self.shop_market if self.shop_market in LANGUAGE_MARKETS else "DE"

    def inject(self, sid: str) -> None:
        """Switch a scenario on from the next simulated hour (L1 in the country chosen in the store); it never ends by itself."""
        with self.lock:
            scenario = self.scenarios[sid]
            if sid in FOLLOWS_STORE:
                self.broken_market[sid] = self.journey_market()
                scenario = scenario.for_market(self.broken_market[sid])
            # at night there are too few shoppers to notice anything: the failure then starts with the morning
            start = self.now.replace(hour=MORNING_HOUR) if self.now.hour in NIGHT_HOURS else self.now
            scenario = scenario.shifted(start)
            if sid not in ONE_OFF:
                calendar = tuple({**c, "end_ts": c["start_ts"] + NEVER} for c in scenario.calendar)
                scenario = replace(scenario, end=None, calendar=calendar)
            self.pipeline.sim.restore(self.now)  # every simulation starts from a normal shop (ad budget on plan)
            self.pipeline.sim.activate(scenario)
            self.pipeline.sim.engine.cache.clear()  # no result cached before the change may be served after it
            self.started[sid] = start
            self.ended.pop(sid, None)
            self.wall[sid] = (datetime.now(), None)
            self.changes += 1

    def add_scenario(self, path: Path) -> None:
        """Make a newly saved scenario file available to Simulate."""
        self.scenarios.update(load_scenarios(path.parent, path.name))

    def simulate(self, sid: str) -> None:
        """Switch a scenario on in the live stream; it stays on until 'End Simulation' is pressed."""
        self.inject(sid)
        self.start()

    def end_simulation(self, sid: str | None = None) -> None:
        """End one running scenario (or all): the fault is switched off and the store is back to normal at once.

        Monitoring keeps running, so the agent sees the numbers recover and closes the incident itself.
        """
        with self.lock:
            for one in [sid] if sid else self.active():
                self._end(one)

    def _end(self, sid: str) -> None:
        scenario, sim = self.scenarios[sid], self.pipeline.sim
        sim.faults.stop(scenario.fault, self.now)
        if scenario.calendar:
            self.db.execute(
                "UPDATE calendar SET end_ts = ? WHERE start_ts <= ? AND end_ts > ?", [self.now, self.now, self.now]
            )
        sim.restore(self.now)  # late deliveries arrive, the ad budget is back on plan
        sim.engine.cache.clear()
        if found := self.finding(sid):
            self.pipeline.incidents.fixed(found["incident_id"])  # simulated again later, it is a new incident
        self.ended[sid] = self.now
        if sid in self.wall:
            self.wall[sid] = (self.wall[sid][0], datetime.now())
        self.changes += 1

    def store_version(self, market: str) -> str:
        """Changes whenever the store would look different (Simulate / End pressed, ad budget used up, delivery late)."""
        sim = self.pipeline.sim
        faults = len(sim.faults.active_names(self.now))  # a failure pressed at night switches on with the morning
        return f"{self.changes}.{faults}.{int(sim.pacer.delivering(market, self.now))}.{int(market in sim.late_supply)}"

    def store_activity(self, sid: str) -> dict[str, int]:
        """What the person at the store did since Simulate was pressed (until End): searches, empty results, cart, orders."""
        if sid not in self.wall:
            return {}
        start, end = self.wall[sid]
        market = self.broken_market.get(sid) or self.scenarios[sid].scope.get("market", "all")
        frame = self.db.df(
            "SELECT event, count(*) AS n FROM ux_events WHERE ts >= ? AND ts <= ? AND (? = 'all' OR market = ?) GROUP BY event",
            [start, end or datetime.now(), market, market],
        )
        counts = dict(zip(frame["event"], frame["n"], strict=True))
        return {label: int(counts.get(event, 0)) for event, label in STORE_EVENTS.items()}

    def finding(self, sid: str) -> dict | None:
        """The agent's report for a scenario started from the UI: the incident that blames the scenario's component."""
        scenario, since = self.scenarios[sid], self.started.get(sid)
        if since is None or not scenario.event_log:
            return None
        row = self.db.df(
            "SELECT incident_id, status, report_json FROM incidents WHERE cause_component = ? AND last_seen >= ? ORDER BY incident_id DESC LIMIT 1",
            [scenario.event_log[0]["component"], since],
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
        since = self.started.get(sid)
        if since is None:
            return []
        hours = int((self.now - since) / HOUR)
        if hours < 0:
            return [f"It is night in the simulation (too few shoppers to notice anything): the failure starts at {since:%H:%M}."]
        lines = [f"Hour {hours} since the fault started: the agent scores every metric each simulated hour."]
        market = self.broken_market.get(sid) or self.scenarios[sid].scope.get("market", "all")
        anomaly = self.db.df(
            "SELECT ts, metric, segment_json, actual, expected, z FROM anomalies WHERE ts >= ? AND NOT planned "
            "AND (? = 'all' OR segment_json LIKE ?) ORDER BY attention DESC LIMIT 1",
            [since, market, f'%"{market}"%'],
        )
        if anomaly.empty:
            return [*lines, "No unusual numbers yet."]
        a = anomaly.iloc[0]
        where = ", ".join(json.loads(a["segment_json"]).values()) or "all traffic"
        name = self.pipeline.graph.metric(a["metric"]).description if a["metric"] in self.pipeline.graph.specs else a["metric"]
        lines.append(f"Anomaly at {a['ts']:%H:00}: {name} in {where} is {a['actual']:,.3g} against a normal "
                     f"{a['expected']:,.3g} ({a['z']:+.1f} standard deviations).")  # fmt: skip
        case = self.db.df(
            "SELECT case_id FROM cases WHERE kind = 'failure' AND ts >= ? ORDER BY ts DESC LIMIT 1", [since]
        )
        if case.empty:
            return [*lines, "Waiting for the anomaly to repeat before opening a case."]
        steps = self.db.df(
            "SELECT step, tool, reasoning FROM investigations WHERE case_id = ? ORDER BY step", [case["case_id"].iloc[0]]
        )
        if steps.empty:
            return [*lines, f"Case {case['case_id'].iloc[0]} opened; the investigation is starting."]
        if (found := self.finding(sid)) is not None:
            done = f"{len(steps)} checks; finding confirmed as incident #{found['incident_id']} (see below)"
            return [*lines, f"Case {case['case_id'].iloc[0]} investigated with {done}."]
        last = steps.iloc[-1]
        latest = f"'{last['tool']}' ({last['reasoning'] or 'gathering evidence'})"
        return [*lines, f"Investigating case {case['case_id'].iloc[0]}: {len(steps)} checks so far, latest {latest}."]

    def search_chart(self, sid: str) -> pd.DataFrame:
        """L1 per closed hour: share of searches that found products in the broken country, and the normal share for that hour.

        Shows a few hours before Simulate up to now, so the drop, the person's own searches and the recovery are all visible.
        """
        market = self.broken_market.get(sid, self.journey_market())
        if market not in self._normal_found:
            clean = self.db.df(
                "SELECT hour(ts) AS h, 1 - sum(zero_result_searches) / nullif(sum(searches), 0) AS found FROM fact_hourly "
                "WHERE market = ? AND ts < ? GROUP BY 1",
                [market, self.settings.demo_day_start],
            )
            self._normal_found[market] = dict(zip(clean["h"], clean["found"], strict=True))
        frame = self.db.df(
            "SELECT ts, 1 - sum(zero_result_searches) / nullif(sum(searches), 0) AS found FROM fact_hourly "
            "WHERE market = ? AND ts >= ? AND ts < ? GROUP BY ts ORDER BY ts",
            [market, self.chart_start(sid), self.now],
        )
        return frame.assign(expected=frame["ts"].dt.hour.map(self._normal_found[market]), ts=frame["ts"] + HOUR)

    def chart_start(self, sid: str) -> datetime:
        """Left edge of the step 1 chart: a few hours before Simulate, but never more than three days back."""
        return max(self.started[sid] - HOUR * CHART_LEAD_HOURS, self.now - HOUR * CHART_HOURS)

    def ads_day(self, sid: str) -> datetime:
        """Midnight of the simulated day the AD1 chart shows: the current day, or the day the simulation was ended."""
        return (self.ended.get(sid, self.now) - HOUR).replace(hour=0, minute=0)

    def ads_chart(self, sid: str) -> pd.DataFrame:
        """AD1 for the simulated day: cumulative actual and planned spend of the campaign, and its fixed daily budget."""
        day = self.ads_day(sid)
        frame = self.db.df(
            "SELECT ts, budget_daily_eur, planned_spend_eur, spend_eur FROM ads_hourly WHERE campaign_id = ? "
            "AND ts >= ? AND ts < ? ORDER BY ts",
            [AD_CAMPAIGN[sid], day, min(self.ended.get(sid, self.now), day + HOUR * 24)],
        )
        # every simulation starts from a campaign that is on plan: hours before Simulate count as planned,
        # so an earlier simulation on the same day does not carry its overspend into this one
        counted = frame["spend_eur"].where(frame["ts"] >= self.started[sid], frame["planned_spend_eur"])
        return frame.assign(ts=frame["ts"] + HOUR, spend=counted.cumsum(), planned=frame["planned_spend_eur"].cumsum())

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
        """Record one real storefront interaction (search, click, add to cart, ...) and count it in the simulated hour."""
        row = {"ts": datetime.now(), "session_id": session, "market": market, "platform": platform, "event": event,
               "query": query, "position": position, "value": value}  # fmt: skip
        self.db.insert_df("ux_events", pd.DataFrame([row]))
        self.pipeline.sim.shopper_action(event, market, platform, value)

    def point(self, metric: str, segment: dict, hour: datetime) -> dict | None:
        """Actual, expected, spread and z of a metric for a closed hour (cached per hour).

        The page never computes while the simulation is advancing (that made the screen wait and slowed the
        simulation down): the worker fills in the hours for every series a page has asked for, and until
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
        """After an hour is simulated: score it for every series the pages show (called with the lock held).

        Series drawn as a chart also get their earlier hours filled in once, because monitoring never pauses.
        """
        for metric, segment in list(self._wanted):
            for k in range(1, self._history.get((metric, segment), 1) + 1):
                key = (metric, segment, self.now - HOUR * k)
                if key not in self._points:
                    self._points[key] = self.pipeline.watcher.score_hour(metric, dict(segment), key[2])

    def _known(self, metric: str, segment: dict, hour: datetime) -> dict | None:
        """The value for exactly this hour, or None if it is not known yet (the chart adds it on a later refresh)."""
        self.point(metric, segment, hour)
        return self._points.get((metric, tuple(sorted(segment.items())), hour))

    def band(self, metric: str, segment: dict | None = None, hours: int = 36) -> pd.DataFrame:
        """Hourly actual with the expected band for the last `hours` closed hours."""
        rows = []
        self._history[(metric, tuple(sorted((segment or {}).items())))] = hours
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
    """Speed of the simulated clock. Monitoring itself is always live; there is no start or stop button."""
    current = min(SPEEDS, key=lambda name: abs(SPEEDS[name] - rt.seconds_per_hour))
    labels = {name: f"{name} ({seconds:.0f} s)" for name, seconds in SPEEDS.items()}
    choice = st.segmented_control(
        "Clock speed (real seconds per simulated hour)", list(SPEEDS), default=current, format_func=labels.get,
        key=f"{key}_speed",
    )  # fmt: skip
    rt.seconds_per_hour = SPEEDS[choice or current]


@st.fragment(run_every=1)
def _status(rt: Runtime) -> None:
    active = rt.active()
    faults = "".join(f"<br>● {sid}: {rt.scenarios[sid].name}" for sid in active) or "<br>none"
    clock = "live" if rt.running else "stopped"
    st.markdown(
        f'<div class="side-status"><span class="muted">Simulated time ({clock})</span><br><b>{rt.now:%a %d %b, %H:%M}</b>'
        f'<br><span class="muted">Running simulations</span>{faults}</div>',
        unsafe_allow_html=True,
    )
    if active:
        st.button("End all simulations", key="side_fix", width="stretch", on_click=rt.end_simulation)


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
                "Removes every incident and running simulation and goes back to the 14 clean days of history. "
                "Scenarios you wrote and metric edits are kept."
            )
            if st.button("Reset now", type="primary"):
                reset_demo()
                st.rerun()
    return rt, palette


def last_hour(rt: Runtime) -> datetime:
    """Start of the most recent closed hour."""
    return rt.now - timedelta(hours=1)
