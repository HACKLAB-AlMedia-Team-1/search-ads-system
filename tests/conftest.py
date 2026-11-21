"""Shared fixtures: a small search engine built from the processed data (first 300 queries per market)."""

import shutil
from datetime import datetime

import pandas as pd
import pytest

from rootsight.config import load_settings
from rootsight.engine.search import SearchEngine
from rootsight.pipeline import Pipeline
from rootsight.sim.faults import FaultRegistry, load_scenarios
from rootsight.store.db import Database

N_QUERIES = 300
T0 = datetime(2026, 11, 21, 10, 0)

SETTINGS = load_settings()
PROCESSED = SETTINGS.data_processed_dir


@pytest.fixture(scope="session")
def sample():
    """(products, queries, labels) restricted to the first 300 queries of every market."""
    if not (PROCESSED / "products.parquet").is_file():
        pytest.skip("run scripts/prepare_data.py first")
    products, queries, labels = (
        pd.read_parquet(PROCESSED / f"{n}.parquet") for n in ("products", "queries", "labels")
    )
    queries = queries.sort_values(["market", "query_id"]).groupby("market").head(N_QUERIES)
    labels = labels.merge(queries[["market", "query_id"]], on=["market", "query_id"])
    products = products.merge(labels[["market", "product_id"]].drop_duplicates(), on=["market", "product_id"])
    return products, queries, labels


@pytest.fixture(scope="session")
def engine(sample):
    """One engine for the whole test session; each test adds and clears its own faults."""
    return SearchEngine(sample[0], FaultRegistry(), seed=42)


def _private_db(tmp_path_factory):
    """A private copy of the backfilled database (14 clean days), so tests never touch the real one."""
    snapshot = SETTINGS.duckdb_path.with_suffix(".backfill.duckdb")
    if not snapshot.is_file():
        pytest.skip("run scripts/backfill.py first")
    copy = tmp_path_factory.mktemp("db") / "history.duckdb"
    shutil.copy(snapshot, copy)
    return Database(copy)


@pytest.fixture(scope="session")
def history_db(tmp_path_factory):
    """Shared read-mostly copy of the history for the fast tests."""
    db = _private_db(tmp_path_factory)
    yield db
    db.close()


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    """The full pipeline (real engine, real watcher) on its own copy of the history; one per test module."""
    db = _private_db(tmp_path_factory)
    pipeline = Pipeline.from_settings(SETTINGS, db)
    pipeline.scenarios = load_scenarios(SETTINGS.data_raw_dir.parents[1] / "scenarios")
    yield pipeline
    db.close()
