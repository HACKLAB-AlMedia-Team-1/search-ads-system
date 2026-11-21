"""Read the raw Amazon ESCI parquet files (read-only) with DuckDB."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# market -> (ESCI locale, analyzer language). DE is a demo market: German queries on the US catalogue.
MARKETS: dict[str, tuple[str, str]] = {
    "US": ("us", "en"),
    "ES": ("es", "es"),
    "JP": ("jp", "ja"),
    "DE": ("us", "de"),
}
GAIN = {"E": 3.0, "S": 1.0, "C": 0.5, "I": 0.0}
TEXT_LIMIT = 500


def _glob(raw_dir: Path, part: str) -> str:
    return (raw_dir / "esci" / part / "*.parquet").as_posix()


def sample_queries(
    raw_dir: Path, locale: str, n: int, seed: int, keep: Callable[[str], bool] | None = None
) -> pd.DataFrame:
    """Sample `n` small-version queries of a locale with at least one Exact label (seeded); `keep` filters by query text."""
    frame = (
        duckdb.connect()
        .execute(
            f"""SELECT DISTINCT query_id, "query" AS query FROM read_parquet('{_glob(raw_dir, "queries")}')
            WHERE product_locale = ? AND small_version = 1 AND esci_label = 'E' ORDER BY query_id""",
            [locale],
        )
        .fetchdf()
    )
    if keep:
        frame = frame[frame["query"].map(keep)]
    ids = frame["query_id"].drop_duplicates().to_numpy()
    chosen = np.sort(np.random.default_rng(seed).choice(ids, size=min(n, len(ids)), replace=False))
    logger.info("Sampled %d of %d eligible %s queries", len(chosen), len(ids), locale)
    return pd.DataFrame({"query_id": chosen})


def load_labels(raw_dir: Path, locale: str, query_ids: pd.DataFrame) -> pd.DataFrame:
    """All labelled (query, product) pairs of the sampled queries, one row per pair."""
    con = duckdb.connect()
    con.register("sampled", query_ids)
    return con.execute(
        f"""SELECT DISTINCT q.query_id, q."query" AS query, q.product_id, q.esci_label
            FROM read_parquet('{_glob(raw_dir, "queries")}') q JOIN sampled s USING (query_id)
            WHERE q.product_locale = ? AND q.small_version = 1""",
        [locale],
    ).fetchdf()


def load_products(raw_dir: Path, locale: str, product_ids: pd.Series) -> pd.DataFrame:
    """Product text for the given ids, with long text trimmed to `TEXT_LIMIT` characters."""
    con = duckdb.connect()
    con.register("wanted", pd.DataFrame({"product_id": product_ids.unique()}))
    return con.execute(
        f"""SELECT DISTINCT ON (p.product_id) p.product_id, p.product_title AS title,
                   left(p.product_description, {TEXT_LIMIT}) AS description,
                   left(p.product_bullet_point, {TEXT_LIMIT}) AS bullet_point,
                   p.product_brand AS brand, p.product_color AS color
            FROM read_parquet('{_glob(raw_dir, "products")}') p JOIN wanted w USING (product_id)
            WHERE p.product_locale = ? AND p.product_title IS NOT NULL""",
        [locale],
    ).fetchdf()
