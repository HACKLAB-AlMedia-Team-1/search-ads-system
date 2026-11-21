"""Per-market BM25 index (sparse inverted index) and the mutable catalogue state (price, stock, delisting)."""

from __future__ import annotations

import hashlib
import logging
import pickle
import zlib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import csc_matrix

from rootsight.engine.analyzers import analyze

logger = logging.getLogger(__name__)

K1, B = 1.5, 0.75
N_SHARDS = 5


@dataclass
class MarketIndex:
    """BM25 weights per (document, term) plus static per-product features used by the rankers."""

    market: str
    lang: str
    signature: str
    product_ids: np.ndarray
    vocab: dict[str, int]
    weights: csc_matrix
    shard: np.ndarray
    title_len: np.ndarray
    brand_pop: np.ndarray
    recency: np.ndarray
    brand: np.ndarray

    def doc_count(self) -> int:
        """Number of products in the index."""
        return len(self.product_ids)

    def scores(self, tokens: list[str]) -> np.ndarray:
        """BM25 score per document; documents matching fewer than half the distinct query tokens score 0."""
        distinct = set(tokens)
        out = np.zeros(self.doc_count(), dtype=np.float32)
        matched = np.zeros(self.doc_count(), dtype=np.int16)
        for token in distinct:
            col = self.vocab.get(token)
            if col is not None:
                lo, hi = self.weights.indptr[col], self.weights.indptr[col + 1]
                out[self.weights.indices[lo:hi]] += self.weights.data[lo:hi]
                matched[self.weights.indices[lo:hi]] += 1
        out[matched < -(-len(distinct) // 2)] = 0.0
        return out


class Catalogue:
    """Live price, stock and delisting state of one market's products; the simulator mutates it."""

    def __init__(self, products: pd.DataFrame):
        self.price = products["price_eur"].to_numpy(dtype=np.float64).copy()
        self.stock = products["stock"].to_numpy(dtype=np.int64).copy()
        self.delisted = np.zeros(len(products), dtype=bool)


def _signature(product_ids: pd.Series) -> str:
    return hashlib.md5("|".join(product_ids.astype(str)).encode()).hexdigest()


def build_index(products: pd.DataFrame, market: str, lang: str) -> MarketIndex:
    """Build the index from one market's products (columns as in `products.parquet`)."""
    rows, cols, tfs, doc_len = [], [], [], np.zeros(len(products), dtype=np.float32)
    vocab: dict[str, int] = {}
    texts = zip(
        products["title"], products["brand"], products["bullet_point"], products["description"], strict=True
    )
    for doc, (title, brand, bullet, description) in enumerate(texts):
        title, brand, bullet, description = (t or "" for t in (title, brand, bullet, description))
        counts = Counter(analyze(f"{title} {title} {brand} {bullet} {description}", lang))
        doc_len[doc] = sum(counts.values())
        for token, tf in counts.items():
            rows.append(doc)
            cols.append(vocab.setdefault(token, len(vocab)))
            tfs.append(tf)
    rows, cols, tfs = np.array(rows), np.array(cols), np.array(tfs, dtype=np.float32)
    n = len(products)
    doc_freq = np.bincount(cols, minlength=len(vocab))
    idf = np.log(1 + (n - doc_freq + 0.5) / (doc_freq + 0.5)).astype(np.float32)
    norm = K1 * (1 - B + B * doc_len[rows] / doc_len.mean())
    weights = csc_matrix((idf[cols] * tfs * (K1 + 1) / (tfs + norm), (rows, cols)), shape=(n, len(vocab)))
    brand = products["brand"].fillna("").str.lower().to_numpy()
    brand_counts = pd.Series(brand).map(pd.Series(brand).value_counts()).to_numpy(dtype=np.float64)
    created = pd.to_datetime(products["created_at"]).astype("int64").to_numpy(dtype=np.float64)
    return MarketIndex(
        market=market,
        lang=lang,
        signature=_signature(products["product_id"]),
        product_ids=products["product_id"].to_numpy(),
        vocab=vocab,
        weights=weights,
        shard=np.array([zlib.crc32(p.encode()) % N_SHARDS for p in products["product_id"]]),
        title_len=products["title"].fillna("").str.len().to_numpy(dtype=np.float64),
        brand_pop=brand_counts / brand_counts.max(),
        recency=(created - created.min()) / max(created.max() - created.min(), 1.0),
        brand=brand,
    )


def load_or_build(products: pd.DataFrame, market: str, lang: str, cache_dir: Path | None) -> MarketIndex:
    """Return the cached pickle if it matches these products, otherwise build (and cache) the index."""
    path = cache_dir / f"index_{market}.pkl" if cache_dir else None
    if path and path.is_file():
        with path.open("rb") as f:
            index = pickle.load(f)
        if index.signature == _signature(products["product_id"]):
            return index
        logger.info("Index cache for %s is out of date, rebuilding", market)
    index = build_index(products, market, lang)
    logger.info("Built %s index: %d products, %d terms", market, index.doc_count(), len(index.vocab))
    if path:
        cache_dir.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as f:
            pickle.dump(index, f)
    return index
