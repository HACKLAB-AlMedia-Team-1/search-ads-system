"""The ShopLens search engine: BM25 per market, filters, cache, and the injected-fault behaviour."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from rootsight.data.german import understand_german, wrong_language
from rootsight.data.loaders import MARKETS
from rootsight.engine import ranker
from rootsight.engine.analyzers import analyze
from rootsight.engine.cache import NORMAL_TTL_MIN, STALE_TTL_MIN, SearchCache
from rootsight.engine.index import Catalogue, MarketIndex, load_or_build
from rootsight.sim import faults as fault_names
from rootsight.sim.faults import FaultRegistry

PARTIAL_INDEX_MISSING_SHARDS = (0, 1)


@dataclass(frozen=True)
class SearchFilters:
    """Optional filters; a hashable value so it can be part of the cache key."""

    in_stock: bool | None = None
    brand: str | None = None
    min_price: float | None = None
    max_price: float | None = None


@dataclass(frozen=True)
class SearchResult:
    """Top results of one search plus the product state (price, stock) as it was when computed."""

    query: str
    market: str
    platform: str
    doc_idx: tuple[int, ...]
    product_ids: tuple[str, ...]
    scores: tuple[float, ...]
    prices: tuple[float, ...]
    in_stock: tuple[bool, ...]
    latency_ms: float
    zero_result: bool
    total_matches: int = 0
    cache_hit: bool = False
    result_age_min: float = 0.0


class SearchEngine:
    """Search over all markets. Reads the fault registry to decide how each search behaves."""

    def __init__(
        self, products: pd.DataFrame, faults: FaultRegistry, seed: int, cache_dir: Path | None = None
    ):
        self.faults = faults
        self.cache = SearchCache()
        self._rng = np.random.default_rng(seed)
        self.indexes: dict[str, MarketIndex] = {}
        self.catalogues: dict[str, Catalogue] = {}
        for market, (_, lang) in MARKETS.items():
            frame = products[products["market"] == market].reset_index(drop=True)
            if frame.empty:
                continue
            self.indexes[market] = load_or_build(frame, market, lang, cache_dir)
            self.catalogues[market] = Catalogue(frame)

    def doc_count(self, market: str, sim_time: datetime) -> int:
        """Number of products currently searchable in a market (drops when the index is partial)."""
        return int(self._visible(market, sim_time).sum())

    def _visible(self, market: str, sim_time: datetime) -> np.ndarray:
        visible = ~self.catalogues[market].delisted
        if self.faults.active(fault_names.PARTIAL_INDEX, sim_time, market):
            visible &= ~np.isin(self.indexes[market].shard, PARTIAL_INDEX_MISSING_SHARDS)
        return visible

    def _filter_mask(
        self, market: str, platform: str, filters: SearchFilters, sim_time: datetime
    ) -> np.ndarray:
        index, cat = self.indexes[market], self.catalogues[market]
        mask = np.ones(index.doc_count(), dtype=bool)
        if (
            self.faults.active(fault_names.ANDROID_FILTER_NULL, sim_time, market, platform)
            and platform == "android"
        ):
            return np.zeros_like(
                mask
            )  # the app sends in_stock=null, which the API reads as "stock must be null"
        if filters.in_stock:
            mask &= cat.stock > 0
        if filters.brand:
            mask &= index.brand == filters.brand.lower()
        if filters.min_price is not None:
            mask &= cat.price >= filters.min_price
        if filters.max_price is not None:
            mask &= cat.price <= filters.max_price
        return mask

    def _mode(self, market: str, sim_time: datetime) -> str:
        if self.faults.active(fault_names.RANKER_V2_IRRELEVANT, sim_time, market):
            return ranker.V2_IRRELEVANT
        if self.faults.active(fault_names.RANKING_BOOST_RECENCY, sim_time, market):
            return ranker.BOOST_RECENCY
        return ranker.BM25

    def _latency(self, n_tokens: int, cache_hit: bool) -> float:
        base = 3.0 if cache_hit else 20.0 + 6.0 * n_tokens
        return float(base * self._rng.lognormal(0.0, 0.15))

    def search(
        self,
        query: str,
        market: str,
        platform: str,
        filters: SearchFilters,
        sim_time: datetime,
        limit: int = 10,
        *,
        local_language_only: bool = False,
    ) -> SearchResult:
        """Run one search (or serve it from the cache) and return the top `limit` results."""
        blocked = (
            local_language_only or self.faults.active(fault_names.FOREIGN_LANGUAGE_BLOCKED, sim_time, market)
        ) and wrong_language(query, market)
        key = (market, platform, query, filters, limit, blocked)
        stale = self.faults.active(fault_names.CACHE_STALE, sim_time, market)
        hit = self.cache.get(key, sim_time, STALE_TTL_MIN if stale else NORMAL_TTL_MIN)
        if hit:
            cached, age = hit
            return dataclasses.replace(
                cached, cache_hit=True, result_age_min=age, latency_ms=self._latency(0, cache_hit=True)
            )

        index, cat = self.indexes[market], self.catalogues[market]
        lang = (
            "en"
            if self.faults.active(fault_names.REGIONAL_ANALYZER_ENGLISH, sim_time, market)
            else index.lang
        )
        text = understand_german(query) if market == "US" else query
        tokens = [] if blocked else analyze(text, lang)
        visible = self._visible(market, sim_time) & self._filter_mask(market, platform, filters, sim_time)
        bm25 = index.scores(tokens)
        idx, scores = ((), ()) if blocked else ranker.rank(
            index, bm25, visible, self._mode(market, sim_time), query, limit
        )
        result = SearchResult(
            query=query,
            market=market,
            platform=platform,
            doc_idx=tuple(int(i) for i in idx),
            product_ids=tuple(str(index.product_ids[i]) for i in idx),
            scores=tuple(round(float(s), 4) for s in scores),
            prices=tuple(float(cat.price[i]) for i in idx),
            in_stock=tuple(bool(cat.stock[i] > 0) for i in idx),
            latency_ms=self._latency(len(tokens), cache_hit=False),
            zero_result=len(idx) == 0,
            total_matches=int(((bm25 > 0) & visible).sum()),
        )
        self.cache.put(key, result, sim_time)
        return result
