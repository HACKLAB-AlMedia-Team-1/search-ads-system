"""Search engine: normal quality, and every fault moves its signature metric but not the others."""

from datetime import timedelta
from time import perf_counter

import pytest
from conftest import T0

from rootsight.engine.relevance import first_exact_position, ndcg_at_10, relevance_at_10
from rootsight.engine.search import SearchFilters
from rootsight.sim import faults as f
from rootsight.sim.faults import Fault


def measure(engine, sample, market, platform="ios", at=T0):
    """Average quality metrics over the sampled queries of one market."""
    _, queries, labels = sample
    lab = {
        q: g.set_index("product_id")["esci_label"].to_dict()
        for q, g in labels[labels["market"] == market].groupby("query_id")
    }
    rows = []
    for q in queries[queries["market"] == market].itertuples():
        res = engine.search(q.query, market, platform, SearchFilters(), at)
        ids = res.product_ids
        rows.append((relevance_at_10(ids, lab[q.query_id]), ndcg_at_10(ids, lab[q.query_id]),
                     first_exact_position(ids, lab[q.query_id]), res.zero_result, res.total_matches))  # fmt: skip
    non_empty = [r[0] for r in rows if r[0] is not None]
    return {
        "relevance": sum(non_empty) / max(len(non_empty), 1),
        "ndcg": sum(r[1] for r in rows) / len(rows),
        "first_exact": sum(r[2] for r in rows) / len(rows),
        "zero_rate": sum(r[3] for r in rows) / len(rows),
        "results": sum(r[4] for r in rows) / len(rows),
    }


@pytest.fixture(autouse=True)
def clean_faults(engine):
    engine.faults.clear()
    engine.cache.clear()
    yield


def test_normal_quality(engine, sample):
    for market in ("US", "ES", "JP"):
        m = measure(engine, sample, market)
        print(market, {k: round(v, 3) for k, v in m.items()})
        assert m["relevance"] >= 0.45 or market == "JP"
        assert m["zero_rate"] < 0.15


def test_s1_ranker_v2(engine, sample):
    base = measure(engine, sample, "US")
    later = T0 + timedelta(hours=2)
    engine.faults.add(Fault(f.RANKER_V2_IRRELEVANT, later))
    bad = measure(engine, sample, "US", at=later)
    assert bad["relevance"] < 0.5 * base["relevance"] and bad["ndcg"] < 0.5 * base["ndcg"]
    assert abs(bad["zero_rate"] - base["zero_rate"]) < 0.02


def test_s12_regional(engine, sample):
    base = {m: measure(engine, sample, m) for m in ("ES", "US")}
    later = T0 + timedelta(hours=2)
    engine.faults.add(Fault(f.REGIONAL_ANALYZER_ENGLISH, later, scope={"market": "ES"}))
    es, us = measure(engine, sample, "ES", at=later), measure(engine, sample, "US", at=later)
    assert es["relevance"] < 0.9 * base["ES"]["relevance"] and es["zero_rate"] > base["ES"]["zero_rate"]
    assert us == pytest.approx(base["US"])


def test_s3_android(engine, sample):
    base = measure(engine, sample, "US", platform="android")
    later = T0 + timedelta(hours=2)
    engine.faults.add(Fault(f.ANDROID_FILTER_NULL, later, scope={"platform": "android"}))
    assert measure(engine, sample, "US", platform="android", at=later)["zero_rate"] > 0.95
    assert measure(engine, sample, "US", platform="ios", at=later)["zero_rate"] == pytest.approx(
        base["zero_rate"]
    )


def test_s2_partial_index(engine, sample):
    base = measure(engine, sample, "US")
    later = T0 + timedelta(hours=2)
    before = engine.doc_count("US", T0)
    engine.faults.add(Fault(f.PARTIAL_INDEX, later))
    assert 0.5 < engine.doc_count("US", later) / before < 0.7
    bad = measure(engine, sample, "US", at=later)
    assert bad["zero_rate"] > base["zero_rate"] and bad["results"] < 0.9 * base["results"]


def test_s7_recency_boost(engine, sample):
    base = measure(engine, sample, "US")
    later = T0 + timedelta(hours=2)
    engine.faults.add(Fault(f.RANKING_BOOST_RECENCY, later))
    bad = measure(engine, sample, "US", at=later)
    assert bad["first_exact"] > base["first_exact"] + 0.4 and bad["ndcg"] < 0.92 * base["ndcg"]
    assert bad["relevance"] == pytest.approx(base["relevance"], rel=0.1)
    assert bad["zero_rate"] == pytest.approx(base["zero_rate"])


def test_s15_stale_cache(engine, sample):
    measure(engine, sample, "US")
    engine.cache.pop_window_stats()
    later = T0 + timedelta(hours=6)
    measure(engine, sample, "US", at=later)
    normal = engine.cache.pop_window_stats()
    engine.faults.add(Fault(f.CACHE_STALE, later + timedelta(hours=1)))
    measure(engine, sample, "US", at=later + timedelta(hours=2))
    stale = engine.cache.pop_window_stats()
    assert normal["cache_hit_rate"] < 0.1
    assert stale["cache_hit_rate"] > 0.95 and stale["cache_result_age_min"] > 60


def test_filters_and_speed(engine, sample):
    queries = sample[1]
    q = queries[queries["market"] == "US"]["query"].iloc[0]
    cheap = engine.search(q, "US", "web", SearchFilters(max_price=20.0), T0)
    assert all(p <= 20.0 for p in cheap.prices)
    start = perf_counter()
    for text in queries[queries["market"] == "US"]["query"].head(100):
        engine.search(text, "US", "web", SearchFilters(), T0 + timedelta(days=1))
    assert (perf_counter() - start) / 100 < 0.05
