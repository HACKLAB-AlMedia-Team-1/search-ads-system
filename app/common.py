"""Shared by every dashboard page: the live runtime (simulation thread + web shop), the sidebar and small UI helpers."""

from __future__ import annotations

import json
import logging
import shutil
import sys
import threading
import time
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
SPEEDS = {"Slow": 6.0, "Normal": 3.0, "Fast": 1.0}


class Runtime:
    """One shared pipeline for all browser sessions; a background thread advances the simulated clock."""

    def __init__(self) -> None:
        setup_logging()
        self.settings = load_settings()
        self.db = Database(self.settings.duckdb_path)
        self.pipeline = Pipeline.from_settings(self.settings, self.db)
        self.scenarios: dict[str, Scenario] = load_scenarios(ROOT / "scenarios")
        self.lock = threading.RLock()
        self.seconds_per_hour = self.settings.seconds_per_sim_hour
        self.running = False
        self.started: dict[str, datetime] = {}
        self._thread: threading.Thread | None = None
        self._points: dict[tuple, dict | None] = {}
        try:
            self.shop = start_shop(self, SHOP_PORT)
        except OSError:
            self.shop = None
            logger.warning("Port %d is in use; the web shop was not started", SHOP_PORT)

    @property
    def now(self) -> datetime:
        """The next simulated hour (everything before it is already in the database)."""
        return self.pipeline.now

    def step(self, hours: int = 1) -> None:
        """Advance the simulation by whole hours."""
        for _ in range(hours):
            with self.lock:
                self.pipeline.step()

    def start(self) -> None:
        """Run the simulation continuously in the background, one hour every `seconds_per_hour`."""
        if self.running:
            return
        self.running = True

        def loop() -> None:
            while self.running:
                self.step()
                time.sleep(self.seconds_per_hour)

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def pause(self) -> None:
        """Stop the background simulation and wait for the hour in progress to finish."""
        self.running = False
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=60)

    def active(self) -> list[str]:
        """Ids of the scenarios whose fault is switched on right now."""
        names = set(self.pipeline.sim.faults.active_names(self.now))
        return [sid for sid, s in self.scenarios.items() if s.fault in names]

    def inject(self, sid: str) -> None:
        """Switch a scenario on, starting at the next simulated hour."""
        with self.lock:
            self.pipeline.sim.activate(self.scenarios[sid], at=self.now)
            self.started[sid] = self.now

    def fix(self, sid: str | None = None) -> None:
        """End one running scenario (or all of them) at the next simulated hour."""
        with self.lock:
            if sid is None:
                self.pipeline.sim.stop_all(self.now)
            else:
                self.pipeline.sim.faults.stop(self.scenarios[sid].fault, self.now)
                if self.scenarios[sid].calendar:
                    self.db.execute(
                        "UPDATE calendar SET end_ts = ? WHERE start_ts <= ? AND end_ts > ?",
                        [self.now, self.now, self.now],
                    )

    def finding(self, sid: str) -> dict | None:
        """The agent's report for a scenario started from the UI: the incident that blames the scenario's component."""
        scenario, since = self.scenarios[sid], self.started.get(sid)
        if since is None or not scenario.event_log:
            return None
        row = self.db.df(
            "SELECT incident_id, status, report_json FROM incidents WHERE cause_component = ? AND first_seen >= ? ORDER BY incident_id LIMIT 1",
            [scenario.event_log[0]["component"], since - HOUR],
        )
        if row.empty:
            return None
        return {
            "incident_id": int(row["incident_id"].iloc[0]),
            "state": row["status"].iloc[0],
            **json.loads(row["report_json"].iloc[0])["report"],
        }

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
        """Actual, expected, spread and z of a metric for a closed hour (cached per hour)."""
        key = (metric, tuple(sorted(segment.items())), hour)
        if key not in self._points:
            with self.lock:
                self._points[key] = self.pipeline.watcher.score_hour(metric, segment, hour)
        return self._points[key]

    def band(self, metric: str, segment: dict | None = None, hours: int = 36) -> pd.DataFrame:
        """Hourly actual with the expected band for the last `hours` closed hours."""
        rows = []
        for k in range(hours, 0, -1):
            hour = self.now - HOUR * k
            p = self.point(metric, segment or {}, hour)
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


def reset_demo() -> None:
    """Throw away everything that happened in the demo and restore the 14 clean days of history."""
    rt = get_runtime()
    rt.shutdown()
    path = rt.settings.duckdb_path
    shutil.copy(path.with_suffix(".backfill.duckdb"), path)
    rt.pipeline.custom_metrics.unlink(missing_ok=True)
    get_runtime.clear()


def controls(rt: Runtime, key: str) -> None:
    """Time controls: start/pause the simulated clock, jump ahead, choose the speed."""
    run, one, six, speed = st.columns([1.3, 1, 1, 2.2], vertical_alignment="bottom")
    label = "⏸ Pause" if rt.running else "▶ Start the clock"
    run.button(
        label,
        key=f"{key}_run",
        type="primary",
        width="stretch",
        on_click=rt.pause if rt.running else rt.start,
    )
    one.button("+1 hour", key=f"{key}_1", width="stretch", on_click=rt.step, args=(1,), disabled=rt.running)
    six.button("+6 hours", key=f"{key}_6", width="stretch", on_click=rt.step, args=(6,), disabled=rt.running)
    current = min(SPEEDS, key=lambda name: abs(SPEEDS[name] - rt.seconds_per_hour))
    choice = speed.segmented_control(
        "Speed (one simulated hour)", list(SPEEDS), default=current, key=f"{key}_speed"
    )
    rt.seconds_per_hour = SPEEDS[choice or current]


@st.fragment(run_every=2)
def _status(rt: Runtime) -> None:
    active = rt.active()
    faults = "".join(f"<br>● {sid}: {rt.scenarios[sid].name}" for sid in active) or "<br>none"
    clock = "running" if rt.running else "paused"
    st.markdown(
        f'<div class="side-status"><span class="muted">Simulated time ({clock})</span><br><b>{rt.now:%a %d %b, %H:%M}</b>'
        f'<br><span class="muted">Active faults</span>{faults}</div>',
        unsafe_allow_html=True,
    )
    if active:
        st.button("Fix all faults", key="side_fix", width="stretch", on_click=rt.fix)


def page() -> tuple[Runtime, dict[str, str]]:
    """Common page setup: theme (dark-mode switch) and the sidebar status box. Returns (runtime, palette)."""
    st.session_state.setdefault("dark", st.query_params.get("theme") == "dark")
    with st.sidebar:
        palette = theme.apply(st.toggle("Dark mode", key="dark"))
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
