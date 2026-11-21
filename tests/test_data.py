"""Data preparation on a small sample: schemas, Exact labels per query, and reproducibility."""

from datetime import datetime

import pandas as pd
import pytest

from rootsight.config import load_settings
from rootsight.data.prepare import prepare
from rootsight.data.synthetic import traffic_profile

SETTINGS = load_settings()
NOW = datetime(2026, 11, 21)

needs_esci = pytest.mark.skipif(
    not (SETTINGS.data_raw_dir / "esci" / "queries").is_dir(), reason="ESCI not downloaded"
)


@pytest.fixture(scope="module")
def processed(tmp_path_factory):
    out = tmp_path_factory.mktemp("processed")
    prepare(SETTINGS.data_raw_dir, out, seed=42, now=NOW, n_queries=40)
    return out


@needs_esci
def test_schemas_and_exact_labels(processed):
    products = pd.read_parquet(processed / "products.parquet")
    queries = pd.read_parquet(processed / "queries.parquet")
    labels = pd.read_parquet(processed / "labels.parquet")
    assert {
        "market",
        "product_id",
        "title",
        "price_eur",
        "stock",
        "seller_id",
        "created_at",
        "popularity",
    } <= set(products.columns)
    assert set(products["market"]) == {"US", "ES", "JP", "DE"}
    assert (queries["n_exact"] > 0).all()
    assert queries.groupby("market")["weight"].sum().round(6).eq(1).all()
    assert set(labels["gain"]) <= {3.0, 1.0, 0.5, 0.0}
    assert products["price_eur"].between(5, 500).all() and products["stock"].between(0, 200).all()


@needs_esci
def test_reproducible(processed, tmp_path):
    prepare(SETTINGS.data_raw_dir, tmp_path, seed=42, now=NOW, n_queries=40)
    for name, keys in (("products", ["market", "product_id"]), ("queries", ["market", "query_id"]),
                       ("labels", ["market", "query_id", "product_id"])):  # fmt: skip
        a, b = (
            pd.read_parquet(d / f"{name}.parquet").sort_values(keys).reset_index(drop=True)
            for d in (processed, tmp_path)
        )
        pd.testing.assert_frame_equal(a, b)


def test_traffic_profile():
    profile = traffic_profile()
    assert len(profile) == 48
    assert profile.groupby("day_type")["weight"].sum().round(9).eq(1).all()
