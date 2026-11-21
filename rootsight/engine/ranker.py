"""Ranking modes: normal BM25, the broken v2 ranker (S1) and the recency boost (S7)."""

from __future__ import annotations

import zlib

import numpy as np

from rootsight.engine.index import MarketIndex

BM25, V2_IRRELEVANT, BOOST_RECENCY = "bm25", "v2_irrelevant", "boost_recency"
V2_POOL = 300
BOOST_POOL = 15
BM25_WEIGHT, RECENCY_WEIGHT = 0.2, 0.8


def _top(values: np.ndarray, k: int) -> np.ndarray:
    """Indices of the `k` largest values, best first (ties broken by index for stable results)."""
    k = min(k, len(values))
    if k == 0:
        return np.empty(0, dtype=np.int64)
    part = np.argpartition(-values, k - 1)[:k]
    return part[np.lexsort((part, -values[part]))]


def rank(
    index: MarketIndex, bm25: np.ndarray, visible: np.ndarray, mode: str, query: str, k: int = 10
) -> tuple[np.ndarray, np.ndarray]:
    """Return (document indices, scores) of the top `k` results; empty arrays mean zero results."""
    empty = np.empty(0, dtype=np.int64), np.empty(0, dtype=np.float64)
    if not ((bm25 > 0) & visible).any():
        return empty
    if mode == V2_IRRELEVANT:
        static = np.where(visible, index.title_len * index.brand_pop, -1.0)
        pool = _top(static, V2_POOL)
        pool = pool[static[pool] >= 0]
        if len(pool) == 0:
            return empty
        picked = np.random.default_rng(zlib.crc32(query.encode())).choice(
            len(pool), min(k, len(pool)), replace=False
        )
        chosen = pool[np.sort(picked)]
        return chosen, static[chosen]
    scores = np.where(visible, bm25, 0.0)
    if mode == BOOST_RECENCY:
        pool = _top(scores, BOOST_POOL)
        pool = pool[scores[pool] > 0]
        if len(pool) == 0:
            return empty
        final = BM25_WEIGHT * scores[pool] / scores[pool].max() + RECENCY_WEIGHT * index.recency[pool]
        order = np.lexsort((pool, -final))[:k]
        return pool[order], final[order]
    top = _top(scores, k)
    top = top[scores[top] > 0]
    return top, scores[top]
