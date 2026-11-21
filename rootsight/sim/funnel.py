"""The shopping funnel: run real searches for sessions, then clicks, carts, checkouts and orders."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import numpy as np

from rootsight.engine.relevance import first_exact_position, ndcg_at_10, relevance_at_10
from rootsight.engine.search import SearchEngine, SearchFilters
from rootsight.sim.users import QueryPool, click_position

CART_RATE, CHECKOUT_RATE, PAYMENT_RATE = 0.30, 0.70, 0.95
REFINE_AFTER_MISS, REFINE_AFTER_CLICK = 0.35, 0.05
AUTO_REORDER_UNITS = 50
SAMPLE_CAP = 400
DEFAULT_FILTERS = SearchFilters()
COUNT_COLUMNS = [
    "zero_result_searches",
    "results_total",
    "searches_with_click",
    "clicks_top3",
    "sum_relevance10",
    "sum_ndcg10",
    "sum_first_exact_pos",
    "latency_ms_sum",
    "carts",
    "cart_unavailable_errors",
    "price_mismatch_clicks",
    "checkouts",
    "orders",
    "revenue_eur",
    "sum_click_position",
    "refinements",
    "bounces",
]


class Funnel:
    """Simulates one (market, platform, source) group of sessions for one hour."""

    def __init__(self, engine: SearchEngine, pool: QueryPool):
        self.engine = engine
        self.pool = pool

    def run_cell(
        self,
        ts: datetime,
        market: str,
        platform: str,
        source: str,
        n_sessions: int,
        intent: float,
        rng: np.random.Generator,
        n_samples: int = 4,
    ) -> tuple[dict, list[dict]]:
        """Return the hourly fact row (counts scaled up from at most SAMPLE_CAP sessions) and a few search samples."""
        n = min(n_sessions, SAMPLE_CAP)
        scale = n_sessions / n if n else 0.0
        counts = dict.fromkeys(COUNT_COLUMNS, 0.0)
        latencies, samples = [], []
        times = np.sort(rng.integers(0, 3600, n))
        sample_ids = set(rng.choice(n, size=min(n_samples, n), replace=False).tolist()) if n else set()
        catalogue = self.engine.catalogues[market]
        for i, (query_id, query) in enumerate(self.pool.draw(market, n, rng)):
            res = self.engine.search(
                query, market, platform, DEFAULT_FILTERS, ts + timedelta(seconds=int(times[i]))
            )
            labels = self.pool.labels.get((market, query_id), {})
            latencies.append(res.latency_ms)
            counts["latency_ms_sum"] += res.latency_ms
            counts["zero_result_searches"] += res.zero_result
            counts["results_total"] += res.total_matches
            pos = None
            if not res.zero_result:
                counts["sum_relevance10"] += relevance_at_10(res.product_ids, labels)
                counts["sum_ndcg10"] += ndcg_at_10(res.product_ids, labels)
                counts["sum_first_exact_pos"] += first_exact_position(res.product_ids, labels)
                pos = click_position(labels, res.product_ids, rng)
            refined = rng.random() < (REFINE_AFTER_CLICK if pos is not None else REFINE_AFTER_MISS)
            counts["refinements"] += refined
            counts["bounces"] += pos is None and not refined
            if pos is not None:
                counts["sum_click_position"] += pos
                counts["searches_with_click"] += 1
                counts["clicks_top3"] += pos <= 3
                doc = res.doc_idx[pos - 1]
                counts["price_mismatch_clicks"] += abs(res.prices[pos - 1] - catalogue.price[doc]) > 1e-9
                if catalogue.stock[doc] <= 0 or catalogue.delisted[doc]:
                    counts["cart_unavailable_errors"] += 1
                elif rng.random() < CART_RATE * intent:
                    counts["carts"] += 1
                    if rng.random() < CHECKOUT_RATE:
                        counts["checkouts"] += 1
                        if rng.random() < PAYMENT_RATE:
                            counts["orders"] += 1
                            counts["revenue_eur"] += catalogue.price[doc]
                            left = catalogue.stock[doc] - max(1, round(scale))
                            # the warehouse re-orders automatically when the last units sell
                            catalogue.stock[doc] = left if left > 0 else AUTO_REORDER_UNITS
            if i in sample_ids:
                samples.append(
                    {
                        "ts": ts + timedelta(seconds=int(times[i])),
                        "market": market,
                        "platform": platform,
                        "source": source,
                        "query": query,
                        "filters_json": json.dumps(
                            {"in_stock": None} if res.zero_result and platform == "android" else {}
                        ),
                        "result_ids_json": json.dumps(list(res.product_ids[:5])),
                        "zero_result": bool(res.zero_result),
                        "latency_ms": round(res.latency_ms, 1),
                        "clicked_pos": pos,
                    }
                )
        row = {
            "ts": ts,
            "market": market,
            "platform": platform,
            "source": source,
            "sessions": float(n_sessions),
        }
        row["searches"] = float(n_sessions)
        row.update({k: v * scale for k, v in counts.items()})
        row["latency_ms_p95"] = float(np.percentile(latencies, 95)) if latencies else 0.0
        return row, samples
