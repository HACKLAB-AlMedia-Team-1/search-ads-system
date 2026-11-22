"""Build the processed parquet files (products, queries, labels, traffic profile) from raw ESCI."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

from rootsight.data.german import to_german, translatable
from rootsight.data.loaders import GAIN, MARKETS, load_labels, load_products, sample_queries
from rootsight.data.synthetic import add_query_weights, add_synthetic_fields, traffic_profile

logger = logging.getLogger(__name__)

QUERIES_PER_MARKET = 1500


def _build_market(raw_dir: Path, market: str, n_queries: int, seed: int, now: datetime):
    locale, lang = MARKETS[market]
    sampled = sample_queries(raw_dir, locale, n_queries, seed, keep=translatable if lang == "de" else None)
    labels = load_labels(raw_dir, locale, sampled)
    if lang == "de":
        labels["query"] = labels["query"].map(to_german)
    products = load_products(raw_dir, locale, labels["product_id"])
    labels = labels[labels["product_id"].isin(products["product_id"])].copy()
    labels["market"] = market
    labels["gain"] = labels["esci_label"].map(GAIN)
    queries = (
        labels.groupby("query_id", as_index=False)
        .agg(query=("query", "first"), n_exact=("esci_label", lambda s: int((s == "E").sum())))
        .assign(market=market, lang=lang)
    )
    queries = add_query_weights(queries[queries["n_exact"] > 0], seed)
    products = add_synthetic_fields(products, seed, now)
    products.insert(0, "market", market)
    return products, queries, labels[["market", "query_id", "query", "product_id", "esci_label", "gain"]]


def _german_shoppers_in_us(parts: list, markets: list[str]) -> None:
    """Give the US store the products and labels of the German queries, so German-speaking US shoppers find them."""
    us, de = parts[markets.index("US")], parts[markets.index("DE")]
    products = pd.concat([us[0], de[0].assign(market="US")]).drop_duplicates(["market", "product_id"])
    labels = pd.concat([us[2], de[2].assign(market="US")]).drop_duplicates(
        ["market", "query_id", "product_id"]
    )
    parts[markets.index("US")] = (products.reset_index(drop=True), us[1], labels.reset_index(drop=True))


def prepare(
    raw_dir: Path, out_dir: Path, seed: int, now: datetime, n_queries: int = QUERIES_PER_MARKET
) -> dict:
    """Write `products`, `queries`, `labels` and `traffic_profile` parquet files; return row counts."""
    parts = [_build_market(raw_dir, m, n_queries, seed, now) for m in MARKETS]
    _german_shoppers_in_us(parts, list(MARKETS))
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = {
        "products": pd.concat([p[0] for p in parts], ignore_index=True),
        "queries": pd.concat([p[1] for p in parts], ignore_index=True),
        "labels": pd.concat([p[2] for p in parts], ignore_index=True),
        "traffic_profile": traffic_profile(),
    }
    for name, frame in frames.items():
        frame.to_parquet(out_dir / f"{name}.parquet", index=False)
    counts = {
        name: frame.groupby("market").size().to_dict() for name, frame in frames.items() if "market" in frame
    }
    for name, per_market in counts.items():
        logger.info("%s: %s", name, per_market)
    return counts
