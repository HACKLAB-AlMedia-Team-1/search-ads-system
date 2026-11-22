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
BUDGET_SPENT = 0.99  # share of the daily budget after which the campaign stops delivering


class AdPacer:
    """Decides each campaign's hourly spend; the daily budget is never exceeded."""

    def __init__(self) -> None:
        self._spent: dict[tuple[str, date], float] = {}
        self._budget: dict[tuple[str, date], float] = {}

    def restore(self, ads_today: pd.DataFrame, day: date) -> None:
        """Re-load today's spend per campaign (used when the simulation resumes mid-day)."""
        for row in ads_today.itertuples():
            self._spent[(row.campaign_id, day)] = float(row.spend)

    def budget(self, market: str, ts: datetime) -> float:
        """The daily budget of the market's campaign on the day of `ts` (doubled during a campaign push)."""
        campaign, base = CAMPAIGNS[market]
        return self._budget.get((campaign, ts.date()), base)

    def spent(self, market: str, ts: datetime) -> float:
        """What the market's campaign has spent so far on the day of `ts`."""
        return self._spent.get((CAMPAIGNS[market][0], ts.date()), 0.0)

    def delivering(self, market: str, ts: datetime) -> bool:
        """Does the market's campaign still have budget left on the day of `ts` (so the shop shows a sponsored product)?"""
        return self.spent(market, ts) < BUDGET_SPENT * self.budget(market, ts)

    def back_on_plan(self, market: str, ts: datetime, planned_so_far: float) -> None:
        """After a pacing failure was fixed: count only the planned spend, so the rest of the day's budget is available again."""
        key = (CAMPAIGNS[market][0], ts.date())
        if key in self._spent:
            self._spent[key] = min(self._spent[key], planned_so_far)

    def step(
        self, ts: datetime, market: str, weight: float, faults: FaultRegistry, rng: np.random.Generator
    ) -> dict:
        """Spend, clicks and paid sessions of the market's campaign in the hour starting at `ts`."""
        campaign, base_budget = CAMPAIGNS[market]
        push = faults.active(fault_names.CAMPAIGN_PUSH, ts, market)
        budget = self._budget[(campaign, ts.date())] = base_budget * (PUSH_BUDGET_FACTOR if push else 1.0)
        planned = budget * weight
        remaining = max(budget - self._spent.get((campaign, ts.date()), 0.0), 0.0)
        cpc = BASE_CPC * rng.uniform(1 - CPC_JITTER, 1 + CPC_JITTER)
        if faults.active(fault_names.AD_PACING_RUNAWAY, ts, market):
            wanted = max(budget * RUNAWAY_HOURLY_SHARE, planned * RUNAWAY_PLAN_FACTOR) * rng.uniform(
                1 - PACING_JITTER, 1 + PACING_JITTER
            )
        else:
            wanted = planned * rng.uniform(1 - PACING_JITTER, 1 + PACING_JITTER)
        spend = round(min(wanted, remaining), 2)
        self._spent[(campaign, ts.date())] = self._spent.get((campaign, ts.date()), 0.0) + spend
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
