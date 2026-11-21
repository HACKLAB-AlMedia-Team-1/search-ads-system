# SCENARIOS.md — What we break, and how the agent tells failures apart

Every scenario is a **fault switch** in the simulator plus an **event-log entry** (a release,
config change or job run). This is how real companies work: something changes, then metrics move.
The agent must find the change **without being told which scenario is running**.

The headline story ("AdSearch"): the company spends **€1,000/day on ads**. Ads bring
visitors to search. When search breaks, ad spend and traffic stay normal, but clicks and
purchases fall, so **ad money is wasted**. Every search failure is therefore also reported
in € of wasted ad spend.

---

## Overview

| ID | Name (list #) | Tier | Where it hits | Event-log entry the agent should find |
|----|---------------|------|---------------|----------------------------------------|
| **S1** | Search algorithm failure (#1) | **Must** (headline) | All markets, all platforms | `release search-ranker v2.0.0` |
| **S12** | Regional search failure (#12) | **Must** | ES market only | `config search-analyzer[ES] = english` |
| **S3** | Mobile search failure (#3) | **Must** | Android only | `release android-app 5.2.0` |
| **AD1** | Ad budget pacing anomaly | **Must** | One campaign (ES) | `deploy pacing-service 1.4.0` |
| **EV1** | Planned marketing event (innocent) | **Must** | Paid traffic | `calendar campaign black-friday-push` |
| **DQ1** | Late data (innocent) | **Must** | `search_events` table | none (data arrival lag) |
| **S2** | Product indexing failure (#2) | Should | All markets | `job index-build #812 status=partial` |
| **S7** | Ranking regression (#7) | Should | All markets | `config ranking.boost_recency 0.0 -> 0.8` |
| **S15** | Search cache failure (#15) | Could | All markets | `config search-cache.ttl 60s -> 86400s` |

Build order: S1 → AD1 → EV1 → DQ1 → S12 → S3 → S2 → S7 → S15.
**Must** = shown in the video. **Should/Could** = implemented if time allows; shown in a quick "more scenarios" montage.

---

## How each fault is implemented (simulator side)

| ID | What the code actually changes | Signature metrics that move | Metrics that must NOT move (proves locality) |
|----|--------------------------------|------------------------------|-----------------------------------------------|
| S1 | Ranker v2 scores by title length + brand popularity instead of BM25 text match → irrelevant top 10 | `relevance_at_10` ↓↓, `ndcg_at_10` ↓↓, `search_ctr` ↓, `orders` ↓, `roas` ↓ | `searches`, `ad_spend`, `paid_sessions`, `zero_result_rate`, `latency` |
| S12 | ES analyzer switched to English stemmer, accents kept → Spanish words no longer match | ES: `relevance_at_10` ↓, `zero_result_rate` ↑ slightly, `search_ctr` ↓ | US/JP all metrics; all platforms equally hit within ES |
| S3 | Android app sends `filter.in_stock=null` which the API reads as "no stock allowed" → empty results | Android: `zero_result_rate` ↑↑ (≈80%), `search_ctr` ↓↓ | iOS + web; `relevance_at_10` (computed on non-empty results) |
| AD1 | Pacing controller ignores the hourly schedule, bids ×2.5 → ES budget spent by ~10:00, then 0 | `pacing_ratio` ↑↑ (3× early), `cpc` ↑, `ad_spend` hourly spike then 0, afternoon `paid_sessions` = 0 | Organic `sessions`, `search_ctr`, `relevance_at_10` |
| EV1 | Campaign: budget ×2 for one day, new low-intent audience (purchase intent ×0.5) | `paid_sessions` ↑, `conversion_rate` ↓ (paid only), total `orders` ↑ | Organic conversion; search quality metrics |
| DQ1 | One hour of `search_events` arrives 2 h late (rows missing, then backfilled) | `rows_received / rows_expected` ↓ for that table only | Ads table, orders table complete |
| S2 | Index rebuild only loads 60% of products (shards 0–1 of 5 missing) | `index_doc_count` ↓40%, `zero_result_rate` ↑, `result_count_avg` ↓ | `latency`, relevance on non-empty results roughly OK |
| S7 | Recency boost pushes newest products up → relevant items still in top 10 but lower | `first_exact_position` ↑ (≈1.8 → 6+), `ndcg_at_10` ↓, `top3_ctr` ↓; `relevance_at_10` ≈ unchanged | `zero_result_rate`, `index_doc_count` |
| S15 | Cache TTL 1 day → results from yesterday: includes delisted products, old prices, sold-out items | `cache_hit_rate` → ~99%, `cache_result_age_min` ↑↑, `unavailable_on_click_rate` ↑, `price_mismatch_rate` ↑, `add_to_cart_rate` ↓ | `relevance_at_10` mostly OK, `zero_result_rate` |

---

## Differential diagnosis: how the agent separates look-alike failures

S1, S2, S7, S12 and S15 all end in "search clicks and orders went down". The agent must
**prove which one** with targeted checks. This table is also a slide in the pitch.

| Check (tool) | S1 algorithm | S2 indexing | S7 ranking | S12 regional | S15 cache | S3 mobile |
|---|---|---|---|---|---|---|
| `drill_down(search_ctr, market)` | all markets | all | all | **ES only** | all | all |
| `drill_down(search_ctr, platform)` | all | all | all | all | all | **Android only** |
| `zero_result_rate` | normal | **↑** | normal | slight ↑ | normal | **↑↑** |
| `relevance_at_10` (labels / judge) | **↓↓** | OK on non-empty | ≈ normal | **↓** (ES) | ≈ normal | n/a |
| `first_exact_position` | n/a | normal | **↑↑** | ↑ | normal | n/a |
| `component_health(index)` | OK | **doc count ↓40%** | OK | OK | OK | OK |
| `component_health(cache)` | OK | OK | OK | OK | **hit 99%, age 24 h** | OK |
| `sample_searches` + `judge_relevance` (Claude Haiku) | "results unrelated to query" | "few results" | "relevant items lower down" | "Spanish words not matched" | "items unavailable / old prices" | "empty result, filter=null" |
| `get_events(6h)` | ranker v2.0.0 | index-build partial | boost_recency | analyzer ES | cache ttl | android 5.2.0 |

The agent explores; it does not run a fixed script. The **graph edges** suggest what to check
next, and the **evidence checklist** (below) decides when to stop.

---

## The 4-point evidence checklist (computed in code)

A hypothesis "event E caused the change in metric M" is **SUPPORTED** only if all four pass:

1. **Size**: the affected segment explains ≥ 70% of the total deviation of M.
2. **Location**: the affected segment's z-score is ≤ −3 (or ≥ +3), and every comparable
   sibling segment stays within ±2.
3. **Timing**: the anomaly onset is between 0 and 2 simulated hours after E's timestamp.
4. **Alternatives**: at least 2 other candidate causes (other events, data delay, traffic
   mix, planned calendar event) were tested and rejected, each with a reason.

3 of 4 → **LIKELY** (the report says what's missing). ≤ 2 → **HYPOTHESIS**.

## Innocent-change rules

- **Planned event (EV1):** if a calendar entry covers the time and the change is explained by
  traffic mix (paid share ↑ and paid conversion ↓ while organic is normal), classify as
  `expected` → shown as an info card, **no incident**. Linkup `web_check` can add outside context
  (e.g. "27 Nov 2026 is Black Friday").
- **Late data (DQ1):** if `rows_received/rows_expected < 0.9` for a table, metrics from that
  table are marked `incomplete` and are **not** sent to the agent. A "data delay" notice is
  shown and closes automatically when the rows arrive.

## Impact formulas (shown in every report)

- Lost orders = Σ over affected hours (expected orders − actual orders)
- Lost revenue (€) = lost orders × expected AOV
- **Wasted ad spend (€)** = Σ ad_spend × (1 − actual ROAS / expected ROAS), floored at 0
- For AD1: budget spent outside the plan (€), plus estimated lost afternoon paid orders.

## Scenario file format (`scenarios/*.yaml`)

```yaml
id: S1
name: Search algorithm failure
fault: ranker_v2_irrelevant        # name of the fault switch in rootsight/sim/faults.py
start: "2026-11-24T14:00:00"
end:   "2026-11-24T22:00:00"      # null = until manually stopped
scope: {market: all, platform: all}
event_log:
  - {ts: "2026-11-24T13:55:00", type: release, component: search-ranker, detail: "v2.0.0 rolled out 100%"}
expected_root_cause: search-ranker v2.0.0   # used ONLY by tests, never shown to the agent
```
