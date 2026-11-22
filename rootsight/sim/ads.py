"""Advertising: three campaigns (EUR 1,000/day) with a pacing controller that follows the traffic schedule."""

from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pandas as pd

from rootsight.sim import faults as fault_names
from rootsight.sim.faults import FaultRegistry

CAMPAIGNS = {
    "US": ("CMP-US", 400.0),
    "DE": ("CMP-DE", 250.0),
    "ES": ("CMP-ES", 200.0),
    "JP": ("CMP-JP", 150.0),
}
BASE_CPC = 0.40
CPC_JITTER = 0.10
PACING_JITTER = 0.08
SESSIONS_PER_CLICK = 0.92
CLICK_THROUGH_RATE = 0.02
RUNAWAY_HOURLY_SHARE, RUNAWAY_PLAN_FACTOR = 0.10, 3.0
CTR_JITTER = 0.05
PUSH_BUDGET_FACTOR = 2.0


class AdPacer:
    """Decides each campaign's hourly spend; the daily budget is never exceeded."""

    def __init__(self) -> None:
        self._spent: dict[tuple[str, date], float] = {}
        self._normal_spend: dict[str, tuple[date, float]] = {}

    def spent(self, market: str, day: date) -> float:
        """Campaign spend charged against the current day's available budget."""
        return self._spent.get((CAMPAIGNS[market][0], day), 0.0)

    def recover(self, market: str, day: date) -> None:
        """Return to the budget position the normal pacing schedule would have reached."""
        normal = self._normal_spend.pop(market, None)
        if normal and normal[0] == day:
            self._spent[(CAMPAIGNS[market][0], day)] = normal[1]

    def budget(self, market: str, ts: datetime, faults: FaultRegistry) -> float:
        """Daily campaign budget including any active planned push."""
        return CAMPAIGNS[market][1] * (PUSH_BUDGET_FACTOR if faults.active(fault_names.CAMPAIGN_PUSH, ts, market) else 1.0)

    def restore(self, ads_today: pd.DataFrame, day: date) -> None:
        """Re-load today's spend per campaign (used when the simulation resumes mid-day)."""
        for row in ads_today.itertuples():
            self._spent[(row.campaign_id, day)] = float(row.spend)

    def step(
        self, ts: datetime, market: str, weight: float, faults: FaultRegistry, rng: np.random.Generator
    ) -> dict:
        """Spend, clicks and paid sessions of the market's campaign in the hour starting at `ts`."""
        campaign = CAMPAIGNS[market][0]
        budget = self.budget(market, ts, faults)
        planned = budget * weight
        spent = self.spent(market, ts.date())
        remaining = max(budget - spent, 0.0)
        cpc = BASE_CPC * rng.uniform(1 - CPC_JITTER, 1 + CPC_JITTER)
        jitter = rng.uniform(1 - PACING_JITTER, 1 + PACING_JITTER)
        wanted = planned * jitter
        runaway = faults.active(fault_names.AD_PACING_RUNAWAY, ts, market)
        normal = self._normal_spend.get(market)
        if normal and normal[0] != ts.date():
            del self._normal_spend[market]
            normal = None
        if runaway or normal:
            normal_spent = normal[1] if normal else spent
            normal_spent += round(min(wanted, max(budget - normal_spent, 0.0)), 2)
            self._normal_spend[market] = (ts.date(), normal_spent)
        if runaway:
            wanted = max(budget * RUNAWAY_HOURLY_SHARE, planned * RUNAWAY_PLAN_FACTOR) * jitter
        spend = round(min(wanted, remaining), 2)
        self._spent[(campaign, ts.date())] = spent + spend
        clicks = spend / cpc
        return {
            "ts": ts,
            "market": market,
            "campaign_id": campaign,
            "budget_daily_eur": budget,
            "planned_spend_eur": round(planned, 2),
            "spend_eur": spend,
            "impressions": round(clicks / (CLICK_THROUGH_RATE * rng.uniform(1 - CTR_JITTER, 1 + CTR_JITTER))),
            "paid_clicks": round(clicks, 2),
            "cpc_eur": round(cpc, 4),
            "paid_sessions": round(SESSIONS_PER_CLICK * clicks),
        }
