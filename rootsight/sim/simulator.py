"""The hourly simulation loop: traffic, ads, funnel, nightly jobs, events and data arrival into DuckDB."""

from __future__ import annotations

import logging
from collections import Counter
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
# One action of the real person at the store stands for 100 shoppers, but never more than a tenth of that hour's
# shoppers on the same device (and at least 1): clearly visible, yet the simulated crowd still decides the picture.
SHOPPER_WEIGHT, SHOPPER_SHARE, SHOPPER_MIN = 100, 0.10, 1
SHOPPER_COLUMNS = ("results_total", "searches_with_click", "clicks_top3", "sum_relevance10", "sum_ndcg10", "sum_first_exact_pos",
                   "carts", "cart_unavailable_errors", "price_mismatch_clicks", "checkouts", "orders", "revenue_eur",
                   "sum_click_position", "refinements", "bounces")  # fmt: skip


class Simulator:
    """Simulates one hour at a time and stores every result in the database."""

    def __init__(self, db: Database, engine: SearchEngine, pool: QueryPool, traffic: Traffic, seed: int):
        self.db, self.engine, self.seed = db, engine, seed
        self.faults = engine.faults
        self.funnel = Funnel(engine, pool)
        self.traffic = traffic
        self.pacer = AdPacer()
        self._pending: dict[datetime, tuple[datetime, pd.DataFrame]] = {}
        self._shopper: Counter = Counter()
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
        self._count_shopper(facts)
        self._store(ts, pd.DataFrame(facts), pd.DataFrame(ads), pd.DataFrame(samples), event_rows)

    def shopper_action(self, event: str, market: str, platform: str, value: float = 0.0) -> None:
        """Remember one action of the real person at the store; it is counted in the hour being simulated next."""
        self._shopper[(market, platform, event)] += 1
        if event == "checkout":
            self._shopper[(market, platform, "revenue")] += value

    def _count_shopper(self, facts: list[dict]) -> None:
        """Count the real person's store actions in this hour's organic rows, each one standing for a crowd of shoppers.

        The number of searches stays the same (no traffic spike): a search of the person that found nothing means a
        crowd of this hour's shoppers found nothing too, a search that found products means a crowd that would have
        found nothing found products instead. What successful searchers do (clicks, carts, orders) follows in
        proportion. Cart and order actions add carts and orders.
        """
        pending, self._shopper = self._shopper, Counter()
        for row in facts:
            did = lambda event, row=row: pending.get((row["market"], row["platform"], event), 0)
            if row["source"] != "organic" or not any(key[:2] == (row["market"], row["platform"]) for key in pending):
                continue
            crowd = min(SHOPPER_WEIGHT, max(SHOPPER_MIN, SHOPPER_SHARE * row["searches"]))
            empty, found = did("zero_result"), max(did("search") - did("zero_result"), 0)
            ok = row["searches"] - row["zero_result_searches"]
            lost = max(-row["zero_result_searches"], min(ok, crowd * (empty - found)))  # searchers who now find nothing
            if ok > 0:
                for column in SHOPPER_COLUMNS:
                    row[column] *= (ok - lost) / ok
            row["zero_result_searches"] += lost
            row["bounces"] = max(row["bounces"] + lost, 0.0)
            row["carts"] += crowd * did("add_to_cart")
            row["cart_unavailable_errors"] += crowd * did("cart_unavailable")
            row["checkouts"] += crowd * did("checkout")
            row["orders"] += crowd * did("checkout")
            row["revenue_eur"] += crowd * pending.get((row["market"], row["platform"], "revenue"), 0.0)

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

    @property
    def late_supply(self) -> frozenset[str]:
        """Markets whose top-seller delivery is overdue right now."""
        return frozenset(self._late_supply)

    def _supply(self, ts: datetime) -> None:
        """Supplier deliveries for top sellers: while a delivery is late they stay sold out; on arrival they are restocked."""
        for market, top in self.top_products.items():
            if self.faults.active(fault_names.SUPPLIER_DELIVERY_LATE, ts, market):
                if market not in self._late_supply:
                    self._late_supply.add(market)
                    self._purchase_order(ts, market, received=False)
                self.engine.catalogues[market].stock[top] = 0
            elif market in self._late_supply:
                self._deliver(ts, market)
            elif ts.hour == NIGHTLY_HOUR:
                self._purchase_order(ts, market, received=True)

    def _deliver(self, ts: datetime, market: str) -> None:
        """The overdue delivery arrives: top sellers are back in stock and the purchase order is marked received."""
        self._late_supply.discard(market)
        self.engine.catalogues[market].stock[self.top_products[market]] = UNITS_ORDERED
        self.db.execute(
            "UPDATE purchase_orders SET qty_received = qty_ordered, received_at = ? WHERE market = ? AND received_at IS NULL",
            [ts, market],
        )

    def restore(self, at: datetime) -> None:
        """Put the shop back to normal right after a fault was stopped at `at`, without waiting for the next hour.

        Overdue deliveries arrive, and a campaign that spent ahead of its plan gets the rest of today's budget back.
        """
        for market in [m for m in self._late_supply if not self.faults.active(fault_names.SUPPLIER_DELIVERY_LATE, at, m)]:
            self._deliver(at, market)
        planned = self.db.df(
            "SELECT market, sum(planned_spend_eur) AS planned FROM ads_hourly WHERE ts >= ? AND ts < ? GROUP BY market",
            [at.replace(hour=0, minute=0), at],
        )
        for market, so_far in zip(planned["market"], planned["planned"], strict=True):
            if not self.faults.active(fault_names.AD_PACING_RUNAWAY, at, market):
                self.pacer.back_on_plan(market, at, float(so_far))

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
