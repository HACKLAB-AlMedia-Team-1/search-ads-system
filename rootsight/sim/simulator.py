"""The hourly simulation loop: traffic, ads, funnel, nightly jobs, events and data arrival into DuckDB."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from rootsight.config import Settings
from rootsight.data.loaders import MARKETS
from rootsight.engine.search import SearchEngine
from rootsight.sim import arrivals, events
from rootsight.sim import faults as fault_names
from rootsight.sim.ads import CAMPAIGNS, AdPacer
from rootsight.sim.clock import HOUR, hours
from rootsight.sim.faults import FaultRegistry, Scenario
from rootsight.sim.funnel import Funnel
from rootsight.sim.traffic import Traffic, split_platforms
from rootsight.sim.users import QueryPool
from rootsight.store.db import Database

logger = logging.getLogger(__name__)

PAID_INTENT = 0.17
PUSH_INTENT_FACTOR = 0.75
RESTOCK_BELOW, RESTOCK_RANGE = 5, (50, 151)
NIGHTLY_HOUR = 3
SOLD_OUT_CHURN, DELIST_RATE, RELIST_RATE, PRICE_CHANGE_RATE = 0.04, 0.005, 0.25, 0.08
TOP_QUERIES, UNITS_NEEDED, UNITS_ORDERED, PO_LEAD_DAYS = 100, 100, 120, 3


class Simulator:
    """Simulates one hour at a time and stores every result in the database."""

    def __init__(self, db: Database, engine: SearchEngine, pool: QueryPool, traffic: Traffic, seed: int):
        self.db, self.engine, self.seed = db, engine, seed
        self.faults = engine.faults
        self.funnel = Funnel(engine, pool)
        self.traffic = traffic
        self.pacer = AdPacer()
        self._pending: dict[datetime, tuple[datetime, pd.DataFrame]] = {}
        self._late_supply: set[str] = set()
        self.top_products = {
            market: np.flatnonzero(
                np.isin(index.product_ids, list(pool.top_exact_products(market, TOP_QUERIES)))
            )
            for market, index in engine.indexes.items()
        }

    @classmethod
    def from_settings(cls, settings: Settings, db: Database) -> Simulator:
        """Build the simulator from the processed parquet files."""
        read = lambda name: pd.read_parquet(settings.data_processed_dir / f"{name}.parquet")
        products, queries, labels, profile = (
            read(n) for n in ("products", "queries", "labels", "traffic_profile")
        )
        engine = SearchEngine(products, FaultRegistry(), settings.sim_seed, settings.data_processed_dir)
        return cls(db, engine, QueryPool(queries, labels), Traffic(profile), settings.sim_seed)

    def activate(self, scenario: Scenario, at: datetime | None = None) -> None:
        """Turn a scenario on (optionally moved to start at `at`) and write its event-log and calendar rows."""
        scenario = scenario.shifted(at) if at else scenario
        self.faults.add(scenario.to_fault())
        self.db.insert_df("events", pd.DataFrame(events.scenario_event_rows(scenario)))
        self.db.insert_df("calendar", pd.DataFrame(events.calendar_rows(scenario)))
        logger.info("Scenario %s active from %s", scenario.id, scenario.start)

    def stop_all(self, at: datetime) -> None:
        """End every running fault at `at`."""
        for name in self.faults.active_names(at):
            self.faults.stop(name, at)
        self.db.execute("UPDATE calendar SET end_ts = ? WHERE start_ts <= ? AND end_ts > ?", [at, at, at])

    def run(self, start: datetime, end: datetime) -> None:
        """Simulate every hour from `start` (inclusive) to `end` (exclusive)."""
        for ts in hours(start, end):
            self.tick(ts)

    def tick(self, ts: datetime) -> None:
        """Simulate the hour starting at `ts`; its rows become visible when the hour closes."""
        rng = np.random.default_rng([self.seed, int((ts - datetime(2000, 1, 1)).total_seconds())])
        self._apply_late_rows(ts)
        event_rows = events.events_between(ts, ts + HOUR, self.seed)
        if ts.hour == NIGHTLY_HOUR:
            event_rows.append(self._nightly_job(ts, rng))
        self._supply(ts)
        weight = self.traffic.weight(ts)
        facts, ads, samples = [], [], []
        for market in MARKETS:
            ad = self.pacer.step(ts, market, weight, self.faults, rng)
            push = self.faults.active(fault_names.CAMPAIGN_PUSH, ts, market)
            groups = {
                "organic": (self.traffic.organic_sessions(ts, market, rng), 1.0),
                "paid": (ad["paid_sessions"], PAID_INTENT * (PUSH_INTENT_FACTOR if push else 1.0)),
            }
            for source, (n, intent) in groups.items():
                for platform, k in split_platforms(n, rng).items():
                    if k:
                        row, picked = self.funnel.run_cell(ts, market, platform, source, k, intent, rng)
                        facts.append(row)
                        samples.extend(picked)
            paid = [r for r in facts if r["market"] == market and r["source"] == "paid"]
            ad["paid_orders"] = sum(r["orders"] for r in paid)
            ad["paid_revenue_eur"] = sum(r["revenue_eur"] for r in paid)
            ads.append(ad)
        self._store(ts, pd.DataFrame(facts), pd.DataFrame(ads), pd.DataFrame(samples), event_rows)

    def _store(
        self,
        ts: datetime,
        facts: pd.DataFrame,
        ads: pd.DataFrame,
        samples: pd.DataFrame,
        event_rows: list[dict],
    ):
        fraction = arrivals.search_events_fraction(self.faults, ts)
        if fraction < 1.0:
            self._pending[ts + timedelta(hours=arrivals.DELAY_HOURS)] = (ts, facts)
        self.db.insert_df("fact_hourly", arrivals.degrade(facts, fraction) if fraction < 1.0 else facts)
        self.db.insert_df("ads_hourly", ads)
        self.db.insert_df("search_samples", samples)
        self.db.insert_df("events", pd.DataFrame(event_rows))
        self.db.insert_df(
            "data_arrivals", pd.DataFrame(arrivals.arrival_records(ts, facts, len(CAMPAIGNS), fraction))
        )
        self.db.insert_df("component_hourly", pd.DataFrame(self._components(ts)))

    def _apply_late_rows(self, ts: datetime) -> None:
        """Replace the partial rows of a late hour by the complete ones once they arrive."""
        if ts in self._pending:
            late_ts, full = self._pending.pop(ts)
            self.db.execute("DELETE FROM fact_hourly WHERE ts = ?", [late_ts])
            self.db.insert_df("fact_hourly", full)

    def _top_in_stock(self, market: str) -> float:
        return float((self.engine.catalogues[market].stock[self.top_products[market]] > 0).mean())

    def _purchase_order(self, ts: datetime, market: str, received: bool) -> None:
        """Record the purchase order for the market's top sellers that is due now (ordered with a 20% margin)."""
        n = len(self.top_products[market])
        row = {"po_id": f"PO-{market}-{ts:%m%d%H}", "market": market, "supplier": f"top-seller supplier {market}",
               "created_at": ts - timedelta(days=PO_LEAD_DAYS), "due_at": ts, "qty_needed": n * UNITS_NEEDED,
               "qty_ordered": n * UNITS_ORDERED, "qty_received": n * UNITS_ORDERED if received else 0,
               "received_at": ts if received else None}  # fmt: skip
        self.db.insert_df("purchase_orders", pd.DataFrame([row]))

    def _supply(self, ts: datetime) -> None:
        """Supplier deliveries for top sellers: while a delivery is late they stay sold out; on arrival they are restocked."""
        for market, top in self.top_products.items():
            cat = self.engine.catalogues[market]
            if self.faults.active(fault_names.SUPPLIER_DELIVERY_LATE, ts, market):
                if market not in self._late_supply:
                    self._late_supply.add(market)
                    self._purchase_order(ts, market, received=False)
                cat.stock[top] = 0
            elif market in self._late_supply:
                self._late_supply.discard(market)
                cat.stock[top] = UNITS_ORDERED
                self.db.execute(
                    "UPDATE purchase_orders SET qty_received = qty_ordered, received_at = ? WHERE market = ? AND received_at IS NULL",
                    [ts, market],
                )
            elif ts.hour == NIGHTLY_HOUR:
                self._purchase_order(ts, market, received=True)

    def _components(self, ts: datetime) -> list[dict]:
        mid = ts + timedelta(minutes=30)
        rows = []
        for market in MARKETS:
            v2 = self.faults.active(fault_names.RANKER_V2_IRRELEVANT, mid, market)
            boost = self.faults.active(fault_names.RANKING_BOOST_RECENCY, mid, market)
            rows += [
                (ts, "index", market, "index_doc_count", self.engine.doc_count(market, mid)),
                (ts, "search-ranker", market, "ranker_version", 2.0 if v2 else 1.0),
                (ts, "ranking", market, "boost_recency", 0.8 if boost else 0.0),
                (ts, "inventory", market, "in_stock_rate_top", self._top_in_stock(market)),
            ]
        stale = self.faults.active(fault_names.CACHE_STALE, mid)
        rows.append((ts, "search-cache", "all", "ttl_seconds", 86400.0 if stale else 60.0))
        rows += [(ts, "search-cache", "all", m, v) for m, v in self.engine.cache.pop_window_stats().items()]
        return [dict(zip(("ts", "component", "scope", "metric", "value"), r, strict=True)) for r in rows]

    def _nightly_job(self, ts: datetime, rng: np.random.Generator) -> dict:
        """Restock, sell-out churn, price changes and delisting; leaves a harmless job event."""
        totals = dict.fromkeys(("restocked", "delisted", "repriced"), 0)
        for market, cat in self.engine.catalogues.items():
            low = np.flatnonzero(cat.stock < RESTOCK_BELOW)
            cat.stock[low] = rng.integers(*RESTOCK_RANGE, len(low))
            in_stock = np.flatnonzero(cat.stock > 0)
            cat.stock[rng.choice(in_stock, int(SOLD_OUT_CHURN * len(in_stock)), replace=False)] = 0
            repriced = rng.choice(len(cat.price), int(PRICE_CHANGE_RATE * len(cat.price)), replace=False)
            cat.price[repriced] = np.round(
                np.clip(cat.price[repriced] * rng.uniform(0.8, 1.2, len(repriced)), 5, 500), 2
            )
            gone = np.flatnonzero(cat.delisted)
            cat.delisted[rng.choice(gone, int(RELIST_RATE * len(gone)), replace=False)] = False
            live = np.flatnonzero(~cat.delisted)
            cat.delisted[rng.choice(live, int(DELIST_RATE * len(live)), replace=False)] = True
            top = self.top_products[market]  # top sellers stay listed and are replenished by purchase orders
            cat.stock[top], cat.delisted[top] = np.maximum(cat.stock[top], UNITS_ORDERED), False
            totals["restocked"] += len(low)
            totals["delisted"] += int(cat.delisted.sum())
            totals["repriced"] += len(repriced)
        detail = f"completed ok: restocked {totals['restocked']}, repriced {totals['repriced']}"
        return {
            "ts": ts,
            "type": "job",
            "component": "nightly-inventory-sync",
            "detail": detail,
            "scope_json": "{}",
        }

    def save_state(self) -> None:
        """Store price, stock and delisting state so a later run can continue from here."""
        self.db.execute("DELETE FROM catalogue_state")
        for market, cat in self.engine.catalogues.items():
            frame = pd.DataFrame(
                {"market": market, "product_id": self.engine.indexes[market].product_ids, "price_eur": cat.price,
                 "stock": cat.stock, "delisted": cat.delisted}
            )  # fmt: skip
            self.db.insert_df("catalogue_state", frame)

    def load_state(self, next_tick: datetime) -> bool:
        """Restore the saved catalogue state and today's ad spend; False if nothing was saved."""
        state = self.db.df("SELECT * FROM catalogue_state")
        if state.empty:
            return False
        for market, group in state.groupby("market"):
            cat = self.engine.catalogues[market]
            ordered = group.set_index("product_id").loc[self.engine.indexes[market].product_ids]
            cat.price[:], cat.stock[:], cat.delisted[:] = (
                ordered["price_eur"].to_numpy(), ordered["stock"].to_numpy(), ordered["delisted"].to_numpy(),
            )  # fmt: skip
        today = self.db.df(
            "SELECT campaign_id, sum(spend_eur) AS spend FROM ads_hourly WHERE CAST(ts AS DATE) = ? GROUP BY 1",
            [next_tick.date()],
        )
        self.pacer.restore(today, next_tick.date())
        return True
