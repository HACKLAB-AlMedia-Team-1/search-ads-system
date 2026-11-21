"""Seeded synthetic product fields, query popularity and the hourly traffic profile."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from scipy.stats import norm

N_SELLERS = 200
SOLD_OUT_SHARE = 0.08
# Relative traffic per hour of day: quiet 02-06, rising from 07, lunch bump 12-13, evening peak 19-22.
HOURLY_CURVE = [
    0.9, 0.6, 0.4, 0.3, 0.3, 0.4, 0.7, 1.2, 1.8, 2.3, 2.6, 2.9,
    3.4, 3.4, 3.0, 2.9, 3.0, 3.3, 3.8, 4.5, 4.9, 4.8, 4.2, 2.4,
]  # fmt: skip
WEEKEND_MULTIPLIER = 1.15


def stable_uniform(keys: pd.Series, seed: int, salt: str) -> np.ndarray:
    """Deterministic uniform [0, 1) value per key (same on every run and machine)."""
    hashed = pd.util.hash_pandas_object(keys.astype(str) + f"|{seed}|{salt}", index=False)
    return (hashed.to_numpy(dtype="uint64") >> np.uint64(11)).astype(np.float64) / float(1 << 53)


def add_synthetic_fields(products: pd.DataFrame, seed: int, now: datetime) -> pd.DataFrame:
    """Add price, stock, seller, creation date and Zipf popularity to a market's products."""
    out = products.copy()
    key = out["product_id"]
    brand_key = out["brand"].fillna("").where(out["brand"].fillna("") != "", key)
    mu = 2.5 + 2.5 * stable_uniform(brand_key, seed, "brand_price")
    z = norm.ppf(np.clip(stable_uniform(key, seed, "price"), 1e-6, 1 - 1e-6))
    out["price_eur"] = np.round(np.clip(np.exp(mu + 0.4 * z), 5, 500), 2)
    sold_out = stable_uniform(key, seed, "sold_out") < SOLD_OUT_SHARE
    out["stock"] = np.where(sold_out, 0, 1 + (stable_uniform(key, seed, "stock") * 200).astype(int))
    seller = (stable_uniform(brand_key, seed, "seller") * N_SELLERS).astype(int)
    out["seller_id"] = [f"S{s:03d}" for s in seller]
    age_days = (stable_uniform(key, seed, "age") * 365).astype(int)
    out["created_at"] = [now - timedelta(days=int(d)) for d in age_days]
    rank = pd.Series(stable_uniform(key, seed, "popularity")).rank(method="first").to_numpy()
    out["popularity"] = (1.0 / rank) / (1.0 / rank).sum()
    return out


def add_query_weights(queries: pd.DataFrame, seed: int) -> pd.DataFrame:
    """Add Zipf popularity weights (sum 1) so frequent queries are searched more often."""
    out = queries.copy()
    rank = pd.Series(stable_uniform(out["query_id"], seed, "query_rank")).rank(method="first").to_numpy()
    out["weight"] = (1.0 / rank) / (1.0 / rank).sum()
    return out


def traffic_profile() -> pd.DataFrame:
    """24 hourly weights per day type (each sums to 1) plus a daily volume multiplier."""
    base = np.array(HOURLY_CURVE) / sum(HOURLY_CURVE)
    rows = [
        {"day_type": day_type, "hour": h, "weight": float(w), "day_multiplier": mult}
        for day_type, mult in (("weekday", 1.0), ("weekend", WEEKEND_MULTIPLIER))
        for h, w in enumerate(base)
    ]
    return pd.DataFrame(rows)
