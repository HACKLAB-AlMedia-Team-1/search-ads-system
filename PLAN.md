# PLAN.md — RootSight (AdSearch Sentinel) build plan

**Goal:** a working, autonomous loop: *observe → detect → investigate → report → track*
on a simulated marketplace with **real Amazon products and search queries**, a **real BM25
search engine**, **simulated advertising (€1,000/day)**, and injected faults.

**Judging:** 40% metric graph + auto-extension · 40% autonomous monitoring + investigation · 20% demo.
Every phase below names which criterion it serves.

Rules for the coding agent are in `CLAUDE.md`. Scenario details are in `docs/SCENARIOS.md`.

---

## 0. Architecture at a glance

```
 data/raw (ESCI, optional Taobao)
        │  scripts/prepare_data.py
        ▼
 data/processed/*.parquet ──► rootsight/engine  (BM25 search, analyzers, index, cache, fault switches)
                                     │
                    rootsight/sim  (clock, traffic, ads + pacing, clicks/carts/orders, events, data arrival)
                                     │ writes every simulated hour
                                     ▼
                         data/rootsight.duckdb   (hourly facts, search samples, ads, events, arrivals)
                                     │
        rootsight/graph (metrics.yaml → networkx)   rootsight/monitor (baselines, completeness, calendar, attention)
                     │                                        │ top anomalies
                     └──────────────► rootsight/agent ◄───────┘
                                      (Claude Sonnet + tools; Haiku judge; Linkup web_check;
                                       evidence checklist in code; record/replay)
                                              │
                                 rootsight/incidents (fingerprint, open/ongoing/resolved)
                                              │
                         app/ (Streamlit: Control room · ShopLens · Graph · Incidents · Add metric)
```

### Repository layout (target)

```
rootsight/
  __init__.py
  config.py                # reads .env, all paths/settings
  logging_setup.py
  data/      loaders.py    # read ESCI + Taobao raw files
  engine/    analyzers.py  index.py  ranker.py  cache.py  search.py  relevance.py
  sim/       clock.py  traffic.py  users.py  ads.py  funnel.py  faults.py  events.py  arrivals.py  simulator.py
  store/     db.py  schema.sql
  graph/     metrics.yaml  graph.py  validate.py  onboarding.py
  monitor/   baseline.py  completeness.py  calendar.py  watcher.py
  agent/     llm.py  linkup.py  tools.py  evidence.py  investigator.py  offline_policy.py  report.py
             prompts/investigator_system.md  prompts/judge.md  prompts/onboarding.md
             recordings/   # JSON recordings for replay (committed)
  incidents/ manager.py
scenarios/   S1.yaml S12.yaml S3.yaml AD1.yaml EV1.yaml DQ1.yaml S2.yaml S7.yaml S15.yaml
scripts/     check_env.py  prepare_data.py  backfill.py  run_live.py  run_scenario.py  demo.py
app/         Home.py  pages/1_ShopLens.py  pages/2_Metric_Graph.py  pages/3_Incidents.py  pages/4_Add_Metric.py
tests/       test_engine.py  test_sim.py  test_graph.py  test_watcher.py  test_agent_offline.py  test_onboarding.py
docs/        DOSSIER.md  SCENARIOS.md  MEMORY.md  algorithm.md  architecture.png
```

---

## Timeline (Sat 21 → Sun 22 Nov 2026)

| When | Phase |
|------|-------|
| Sat 14:30–15:30 | **Human: SETUP.md** (env, keys, downloads) |
| Sat 15:30–16:00 | Phase 0 — bootstrap |
| Sat 16:00–17:00 | Phase 1 — data preparation |
| Sat 17:00–18:30 | Phase 2 — search engine + faults (Devin can take this) |
| Sat 18:30–20:00 | Phase 3 — simulator + ads + database |
| Sat 20:00–21:00 | Phase 4 — metric graph |
| Sat 21:00–22:00 | Phase 5 — watcher |
| Sat 22:00–01:00 | Phase 6 — investigator agent + incidents (**the core**) |
| Sun 08:30–09:30 | Phase 7 — new-metric onboarding |
| Sun 09:30–11:30 | Phase 8 — Streamlit UI (Devin can start this on Saturday) |
| Sun 11:30–12:00 | Phase 9 — demo hardening, recordings → **CODE FREEZE 12:00** |
| Sun 12:00–14:00 | Record + edit video |
| Sun 14:00–15:30 | Slides, README, repo public, **submit by 15:30** (deadline 16:30) |

**Cut order if late:** S15 → S7 → S2 → Graph page polish → onboarding LLM step (keep the code validation).
**Never cut:** S1, AD1, EV1, DQ1, the evidence checklist, new-metric demo, replay mode.

---

## Phase 0 — Bootstrap (all criteria)

**Build**
- Package skeleton as in the layout (empty modules with docstrings).
- `rootsight/config.py`: dataclass `Settings` loaded from `.env` via `python-dotenv`; all paths as `pathlib.Path`.
- `rootsight/logging_setup.py`: one function `setup_logging(level)`.
- `scripts/check_env.py`: imports every package in `requirements.txt`, checks `.env` keys exist (prints only "set"/"missing"),
  checks that `data/raw/esci` exists and lists its files. Exit code 1 if anything is missing.
- `pyproject.toml` with ruff config (line length 110) and pytest config (`testpaths = ["tests"]`).

**Acceptance**
- `python scripts/check_env.py` prints all green on the human's machine.
- `pytest -q` runs (even with 0–1 tests) and `ruff check .` is clean.

---

## Phase 1 — Data preparation (serves: demo realism, search scenarios)

**Input:** ESCI files under `data/raw/esci/` (inspect the actual files first; MEMORY.md lists them).
Expected content: an *examples* table (query, query_id, product_id, product_locale, esci_label, small_version, split)
and a *products* table (product_id, title, description, bullet_point, brand, color, locale).
Optional: `data/raw/taobao/UserBehavior.csv`.

**Build** `scripts/prepare_data.py` (+ helpers in `rootsight/data/loaders.py`):
1. Markets: `US` = locale `us` (English), `ES` = `es` (Spanish), `JP` = `jp` (Japanese).
2. Use the `small_version == 1` subset. Per market sample **1,500 queries** (seeded), and keep every labelled product of those queries.
   → catalogue ≈ 50–80k products total. Keep `title, description(trimmed 500 chars), bullet_point(trimmed), brand, color`.
3. `labels.parquet`: (market, query_id, query, product_id, esci_label, gain) with gain E=3, S=1, C=0.5, I=0.
   Products returned for a query with **no label** count as Irrelevant (gain 0). Write this decision into MEMORY.md.
4. Synthetic product fields (seeded, stable per product_id hash):
   `price_eur` (lognormal by brand, 5–500), `stock` (0–200, 8% start sold out), `seller_id` (brand → one of 200 sellers),
   `created_at` (spread over the last 365 days; used by the S7 recency boost), `popularity` (Zipf).
5. Query popularity weights per market (Zipf over sampled queries), so searches feel realistic.
6. Traffic profile `traffic_profile.parquet`: 24 hourly weights × weekday/weekend.
   If Taobao exists: compute from `pv` events by hour and weekday (sample with DuckDB, don't load into pandas fully).
   Else: built-in curve (low 02–06, rising from 07, lunch bump 12–13, peak 19–22) + weekend ×1.15.
7. Write `data/processed/{products,queries,labels,traffic_profile}.parquet` and print counts per market.

**Acceptance**
- Script runs in < 10 min; prints counts; re-running gives identical output (seeded).
- `tests/test_data.py` checks schemas and that each market has ≥ 1,000 queries with ≥ 1 Exact label.

---

## Phase 2 — Search engine + fault switches (serves: 40% investigation, demo)

**Build** `rootsight/engine/`:
- `analyzers.py`: `analyze(text, lang)`
  - `en`: lowercase, split on non-alphanumerics, English Snowball stem, drop stopwords (small built-in list).
  - `es`: lowercase, `unidecode` (strip accents), Spanish Snowball stem, Spanish stopwords.
  - `ja`: character bigrams of the text (no extra dependency).
- `index.py`: one `BM25Okapi` index per market over `title ×2 + brand + bullet_point + description`.
  Keep `doc_ids` and a `shard = hash(product_id) % 5` per product. Build once, cache with pickle in `data/processed/index_<market>.pkl`.
  Exposes `doc_count()`.
- `ranker.py`: `rank(query_tokens, market, mode)`; modes: `bm25` (normal), `v2_irrelevant` (S1: score = title length × brand popularity, text match ignored),
  `boost_recency` (S7: final = 0.2·bm25_norm + 0.8·recency_norm).
- `cache.py`: in-memory result cache keyed by (market, query, filters) with TTL; tracks hit rate and result age;
  `stale_mode` (S15) serves the snapshot from 24 simulated hours earlier (with old price/stock and delisted products).
- `search.py`: `search(query, market, platform, filters, sim_time) -> SearchResult`
  (top 10 product ids, scores, latency_ms, zero_result flag, cache_hit, result_age_min).
  Reads the **active faults** from `rootsight/sim/faults.py` (a simple registry) to switch behaviour:
  - S1 `ranker_v2_irrelevant` → ranker mode `v2_irrelevant`
  - S12 `es_analyzer_english` → ES queries and the ES index use the `en` analyzer path (re-analyze query only; index stays Spanish → mismatch)
  - S3 `android_filter_null` → when platform == android, filter `in_stock` is applied as "stock must be null" → empty results
  - S2 `partial_index` → products in shards {0,1} invisible
  - S7 `ranking_boost_recency` → ranker mode `boost_recency`
  - S15 `cache_stale` → cache `stale_mode`
- `relevance.py`: `relevance_at_10` (share of top-10 with label E or S), `ndcg_at_10` (gains above), `first_exact_position` (1–11, 11 = none).

**Acceptance** (`tests/test_engine.py`, on a 300-query sample per market)
- Normal mode: `relevance_at_10` ≥ 0.45 for US and ES (measure; if lower, record it in MEMORY.md and keep going).
- Each fault moves its **signature metric** strongly in the expected direction and leaves its **must-not-move** metrics within ±10%
  (table in `docs/SCENARIOS.md`).
- A single search takes < 50 ms on average (cache the tokenized corpus).

---

## Phase 3 — Simulator, ads and database (serves: 40% monitoring, demo)

**Database** `rootsight/store/schema.sql` (DuckDB):
- `fact_hourly(ts, market, platform, source, sessions, searches, zero_result_searches, results_total, searches_with_click,
   clicks_top3, sum_relevance10, sum_ndcg10, sum_first_exact_pos, latency_ms_sum, latency_ms_p95, carts, cart_unavailable_errors,
   price_mismatch_clicks, checkouts, orders, revenue_eur)`
- `ads_hourly(ts, market, campaign_id, budget_daily_eur, planned_spend_eur, spend_eur, impressions, paid_clicks, cpc_eur,
   paid_sessions, paid_orders, paid_revenue_eur)`
- `component_hourly(ts, component, metric, value)`: index_doc_count, cache_hit_rate, cache_result_age_min, ranker_version, etc.
- `search_samples(ts, market, platform, source, query, filters_json, result_ids_json, zero_result, latency_ms, clicked_pos)`
  (≈ 20 per market×platform per hour, for the agent to inspect)
- `events(ts, type, component, detail, scope_json)`: releases, config changes, jobs, calendar entries
- `data_arrivals(ts, table_name, rows_expected, rows_received, arrived_at)`
- `calendar(start_ts, end_ts, name, kind, scope_json, expected_effect_json)`
- `metric_registry(name, definition, sql, added_at, added_by)`, `incidents(...)`, `investigations(...)`, `llm_calls(...)`.

**Simulation** `rootsight/sim/` (one tick = one simulated hour):
- **Traffic:** organic sessions per market (US 6,000/day, ES 3,000/day, JP 3,000/day) × `traffic_profile` × noise (±5%).
  Platform split: android 45%, ios 30%, web 25%. Each session = 1 search with a query drawn by popularity.
- **Ads** (`ads.py`): campaigns `CMP-US` €500/day, `CMP-ES` €300/day, `CMP-JP` €200/day = **€1,000/day**.
  Planned hourly spend = budget × traffic weight. Pacing controller: spend_h ≈ planned_h (±8%); CPC ≈ €0.40 (±10%);
  paid_clicks = spend / CPC; paid_sessions = 0.92 × paid_clicks; source = `paid`. Budget never exceeded.
  AD1 fault: pacing ignores the schedule and bids ×2.5 → CPC ×1.6, budget exhausted by ~10:00, then spend 0.
- **Funnel** (`funnel.py`): run the real search for a sample of sessions (≤ 300 per market×platform×source per hour) and
  scale the counts up to the full session count. Click model: P(click at position p) = attract(label) × 0.85^(p−1), with
  attract E=0.55, S=0.25, C=0.10, I=0.03; zero results → no click. Add-to-cart 30% of clickers (0 if the product is out of stock
  or delisted → `cart_unavailable_errors`); checkout 70%; payment 95%; revenue = price. Paid traffic has its own intent factor
  (1.0 normally; 0.5 during EV1 for new audience).
- **Faults** (`faults.py`): registry of active faults loaded from `scenarios/*.yaml` with start/end times; the engine and sim read it.
  Each scenario writes its `event_log` rows to `events` at the right simulated time. Also add 3–5 **harmless decoy events**
  per day (e.g. `release web-frontend 3.4.1`, `config email-templates`) so the agent has to rule things out.
- **Data arrival** (`arrivals.py`): each table normally arrives complete within the hour; DQ1 delays `fact_hourly` rows for
  one hour by 2 h (rows inserted later, `data_arrivals` shows the gap).
- **Stock:** decreases with orders; restock job daily at 03:00 (so cache staleness shows sold-out items).

**Scripts**
- `scripts/backfill.py`: simulate **2026-11-07 → 2026-11-20** (14 clean days) into a fresh DuckDB. Target < 3 min.
- `scripts/run_live.py`: continue from the last tick, one tick every `SECONDS_PER_SIM_HOUR`; runs the watcher after each tick.
- `scripts/run_scenario.py S1`: activates a scenario starting at the current sim time (for the demo panel and tests).

**Acceptance**
- Backfill produces 14×24 hours for all markets; daily orders per market are stable (CV < 10%); ROAS ≈ 2.5–4.
- `tests/test_sim.py`: with S1 active for 4 h, ES/US/JP `searches` and `ad_spend` stay within ±10% while `orders` drop ≥ 25%.

---

## Phase 4 — Metric graph (serves: 40% graph)

**Build** `rootsight/graph/metrics.yaml`: ~30 metrics. Each entry:
```yaml
search_ctr:
  description: Share of searches with at least one result click
  sql: "SUM(searches_with_click) / NULLIF(SUM(searches),0) FROM fact_hourly"
  kind: ratio              # count | ratio | money | component
  unit: share
  dims: [market, platform, source]
  business_weight: 0.8     # used by the attention score
  edges:
    - {type: formula, to: orders, role: factor}          # orders = searches × search_ctr × cart_rate × checkout_rate
    - {type: may_be_caused_by, from: zero_result_rate, confidence: 0.7}
    - {type: may_be_caused_by, from: relevance_at_10, confidence: 0.8}
    - {type: may_be_caused_by, from: first_exact_position, confidence: 0.6}
    - {type: context, from: events.search, note: "search releases / configs"}
```

**Metric list** (minimum):
- Business: `revenue`, `orders`, `aov`, `conversion_rate`
- Funnel: `sessions`, `searches`, `search_ctr`, `add_to_cart_rate`, `checkout_rate`, `top3_ctr`
- Search quality: `zero_result_rate`, `result_count_avg`, `relevance_at_10`, `ndcg_at_10`, `first_exact_position`, `search_latency_p95`
- Availability: `unavailable_on_click_rate`, `price_mismatch_rate`
- Components: `index_doc_count`, `cache_hit_rate`, `cache_result_age_min`
- Ads: `ad_spend`, `paid_clicks`, `cpc`, `paid_sessions`, `paid_orders`, `paid_revenue`, `roas`, `cost_per_order`, `pacing_ratio`
- Data quality: `rows_completeness` per table

**Exact identities** (must hold in the data; the validator checks them):
- `orders = searches × search_ctr × add_to_cart_rate × checkout_rate × payment_rate`
- `revenue = orders × aov`
- `sessions = organic_sessions + paid_sessions`
- `ad_spend = paid_clicks × cpc`
- `roas = paid_revenue / ad_spend`; `cost_per_order = ad_spend / paid_orders`
- Cross-system: `paid_sessions → sessions` (formula, additive), `ad_spend → paid_clicks` (pacing causes)

**Edge types** (networkx `MultiDiGraph`, attribute `type`):
`formula` (exact maths, with operator `×`/`+`/`÷` and role), `split_by` (dimension), `funnel` (ordered steps),
`may_be_caused_by` (hypothesis + confidence), `context` (event types that can affect a metric).

**Build** `graph.py` (load, query neighbors, upstream walk, export tree for UI), `validate.py`:
- formula check: recompute on 7 days of history per segment; pass if median abs error < 1%
- dims check: each dim exists in the source table
- causal check: lagged correlation / co-movement on history (for confidence display only)

**Acceptance**
- `tests/test_graph.py`: all formula edges validate on backfilled data; graph has ≥ 30 nodes and all 5 edge types;
  `upstream("orders")` returns the funnel + search quality + ads chain.

---

## Phase 5 — Watcher (serves: 40% monitoring)

**Build** `rootsight/monitor/`:
- `completeness.py`: per table and hour, `rows_received / rows_expected`; < 0.9 → `incomplete` (DQ1). Incomplete metrics are not scored.
- `baseline.py`: expected value for metric m, segment s, hour h = **median of the same hour on the last 7 comparable days**
  (weekday vs weekend), spread = 1.4826 × MAD (floor at 2% of the median). Robust z = (actual − expected) / spread.
  Ratios need a minimum volume (≥ 200 searches in the segment-hour) to be scored.
- `calendar.py`: if a calendar entry covers (ts, scope), apply `expected_effect_json` (e.g. paid_sessions ×2.5) to the expected value
  and tag the anomaly `planned`.
- `watcher.py`, once per tick:
  1. Score the **top KPIs** (orders, revenue, search_ctr, roas, ad_spend, pacing_ratio, zero_result_rate) at market level every hour.
  2. Score a **rotating batch** of segments (market × platform × source; campaigns), ~40 per tick, plus any segment that was anomalous last tick.
  3. Attention score = `|z| × business_weight × (1 + 0.5·n_consecutive_hours)`; anomalies need |z| ≥ 3 for 2 consecutive hours
     (or |z| ≥ 5 once).
  4. Group anomalies that share a graph ancestor within ±2 h into one **case**; send the top 1–2 cases per tick to the agent.
  5. If a case matches an open incident's fingerprint, update that incident instead of opening a new investigation.

**Acceptance** (`tests/test_watcher.py`)
- 3 clean days: ≤ 1 false case per day.
- S1, AD1, S12, S3 each raise a case within 2 simulated hours of the fault start.
- EV1 → case tagged `planned`, not sent to the agent as a failure.
- DQ1 → a `data delay` notice, no business case.

---

## Phase 6 — Investigator agent + incidents (serves: 40% investigation, the core)

**`agent/llm.py`**: one wrapper for all Claude calls. Modes: `offline` (raise → caller uses the offline policy), `live`,
`record` (live + save request/response JSON to `agent/recordings/<case_id>.json`), `replay` (read the JSON, no API).
Logs tokens per call into `llm_calls`. Uses `CLAUDE_MODEL_AGENT` for the investigator and `CLAUDE_MODEL_FAST` for the judge and onboarding.
Use prompt caching for the system prompt + graph summary.

**`agent/linkup.py`**: `web_check(question) -> {answer, sources}`, using httpx POST to Linkup `/v1/search`
(format confirmed in SETUP Step 5); disk cache in `data/cache/linkup/`; `LINKUP_MODE=offline` returns `{"skipped": true}`.

**`agent/tools.py`**: pure Python, deterministic, return **small JSON** (≤ 15 rows, rounded numbers):

| Tool | Returns |
|------|---------|
| `get_metric(name, segment, hours)` | actual, expected, z, onset hour |
| `decompose(metric, segment, window)` | log-share of each formula factor in the change (Σ = 100%) |
| `drill_down(metric, dimension, segment, window)` | segments ranked by share of total deviation + their z |
| `graph_neighbors(metric)` | parents/children/causes with edge types and confidence |
| `get_events(hours_back, component?)` | events incl. decoys, with timestamps |
| `check_completeness(table, hours)` | rows ratio per hour |
| `component_health(component)` | index doc count, cache hit rate / age, ranker version, latency |
| `sample_searches(market, platform, n)` | real queries with top-5 titles, filters, zero-result flag |
| `judge_relevance(samples)` | **Claude Haiku** rates each result vs query (E/S/I) + one-line pattern summary; cross-checked with ESCI labels |
| `ad_pacing(campaign, day)` | planned vs actual cumulative spend per hour, exhaustion hour |
| `calendar_lookup(ts, scope)` | planned events |
| `web_check(question)` | Linkup answer (outside context) |
| `record_hypothesis(cause, metric, segment, event_id?)` | runs `evidence.check()` in code → SUPPORTED / LIKELY / HYPOTHESIS + the 4 results |
| `estimate_impact(case)` | lost orders, lost revenue €, wasted ad spend € |
| `finish(summary)` | ends the loop; the report is assembled in code from recorded hypotheses + tool results |

**`agent/evidence.py`**: the 4-point checklist exactly as in `docs/SCENARIOS.md`.

**`agent/investigator.py`**: loop:
1. Input = case (anomalies, z, onset, segment, top-level graph context).
2. System prompt (`prompts/investigator_system.md`) explains the goal, the tools, the checklist, "never state a number
   that is not in a tool result", "test ≥ 2 alternatives", "separate symptoms from first cause: walk upstream and prefer the
   earliest-onset upstream anomaly", "stop when one hypothesis is SUPPORTED and alternatives are rejected, or at MAX_TOOL_CALLS".
3. Claude chooses tool calls (native tool use) → results appended → repeat.
4. Every step is stored in `investigations` (step, tool, args, short result, Claude's 1-line reasoning) → streamed to the UI.

**`agent/offline_policy.py`**: a deterministic, rule-based investigator that walks the graph with the same tools
(decompose → drill_down on each dim → component_health → get_events → record_hypothesis). Used in tests and when
`LLM_MODE=offline`. It proves the loop works without spending money; the LLM version is the smarter, explained one.

**`agent/report.py`**: pydantic `Report` → markdown: headline, impact (€), root cause + status, evidence checklist table,
rejected alternatives with reasons, investigation trail, what is still uncertain, suggested next action.

**`incidents/manager.py`**: fingerprint = `root_metric|segment|cause_component`; states `open → ongoing → resolved`
(resolved after 3 normal hours); re-notify only if impact grows > 50% or the scope widens.

**Acceptance** (`tests/test_agent_offline.py`, offline mode)
- For S1, AD1, S12, S3 (and S2, S7, S15 if built): the identified root-cause component equals the scenario's `expected_root_cause`,
  with status SUPPORTED, and ≥ 2 rejected alternatives.
- EV1 produces no incident; DQ1 produces no incident.
- An ongoing fault for 6 h produces exactly **1** incident (no duplicates); it resolves after the fault ends.
- Human runs once with `LLM_MODE=record` for S1 and confirms the live agent reaches the same cause (cost check in `llm_calls`).

---

## Phase 7 — New-metric onboarding (serves: 40% graph extension)

**Build** `graph/onboarding.py`, input = `{name, description, sql}` only. Steps:
1. **Parse:** `sqlglot` → tables, columns, aggregations used.
2. **Propose:** Claude Haiku gets the parsed SQL + the graph summary (names, descriptions, edges) and proposes edges as JSON
   (type, target, confidence, reason). Offline mode: heuristic proposals (shared columns → same subtree; ratio of X → formula child of X).
3. **Validate in code:** run the SQL on history; dims exist; formula edges must match within 1%; correlation edges need |r| ≥ 0.6
   over 7 days, else downgraded to `may_be_caused_by` with lower confidence and flagged **ambiguous**.
4. **Add:** write to `metric_registry` + an `metrics_custom.yaml`, reload graph, the watcher picks it up next tick.

**Demo metrics** (must work):
- `no_click_search_rate` = searches without click / searches → child of `search_ctr` (opposite), split by market/platform.
- `wasted_spend_share` = ad spend on paid sessions with zero-result or no-click searches / total ad spend → links ads ↔ search
  (this is the AdSearch "money" metric; ambiguous edge to `roas`).

**Acceptance:** both demo metrics are placed with the expected parents; the ambiguous edge is flagged; the metric is scored on the next tick.

---

## Phase 8 — Streamlit UI (serves: 20% demo)

`streamlit run app/Home.py`. Use `st.fragment(run_every=...)` for live refresh while `run_live` runs in the same process.

- **Home = Control room**
  - Top: sim clock, speed slider, start/pause, LLM mode badge (offline/live/replay), API spend so far.
  - KPI tiles: orders, revenue, ROAS, ad spend vs plan, search CTR, zero-result rate (green / amber / red).
  - Live charts (plotly) with the expected band shaded.
  - Alert feed (cases), and the **investigation trail** streaming step by step (tool, short result, reasoning).
  - Report card: headline, € impact, root cause + SUPPORTED badge, the 4-point checklist with ticks, rejected alternatives, uncertainty.
  - **Demo panel** (sidebar): buttons S1, S12, S3, AD1, EV1, DQ1 (+ S2, S7, S15), "stop all faults".
- **ShopLens** (the marketplace): search box, market (US/ES/JP) + platform switch, filters (brand, price, in stock);
  product cards (title, brand, €price, stock badge, "Sponsored" tag on paid placements); "Add to cart" button.
  It uses the **same engine with the same active faults**, so the audience sees the bug.
  Show the response time and "served from cache (age)" in small text.
- **Metric Graph:** `streamlit-agraph`; node colour = status (normal/anomalous/incomplete), edge style per type
  (solid formula, dotted split, dashed cause); the current investigation path highlighted; click a node for its chart.
- **Incidents:** table (fingerprint, status, first seen, last seen, impact €), expand for the full report (markdown).
- **Add Metric:** text fields name/description/SQL → runs onboarding → shows proposed edges, validation results, ambiguous flags.

**Acceptance:** the full demo storyline (Phase 9) runs from the UI without the terminal.

---

## Phase 9 — Demo hardening + docs (serves: 20% demo, repo quality)

- `scripts/demo.py`: resets the DB to the backfill snapshot, then plays the storyline:
  Mon 21 normal → EV1 (Black Friday push on Fri 27, can be time-jumped) → S1 at 14:00 → AD1 next morning → S12/S3 quick → add metric → resolve.
- With the human's OK: run S1, AD1, S12 and S3 once each with `LLM_MODE=record`. Commit the recordings; the UI can then run in `replay`.
- `docs/algorithm.md` (judges read this): how we choose what to monitor, which edges to follow, which groups to examine,
  when evidence is sufficient. Diagrams welcome.
- README: what it is, a 60-second quickstart (pointing to SETUP.md), screenshots/GIF, architecture image, scenario table,
  honest "real vs simulated" section.
- `pytest -q` green, `ruff check .` clean, then tag `v1.0-submission`.

---

## Definition of done (submission)

- [ ] Repo public with README, SETUP, PLAN, docs/algorithm.md, architecture image
- [ ] Demo runs end-to-end from the UI in `replay` mode on a fresh clone + setup
- [ ] 3-min video (unlisted YouTube) with a team member on camera
- [ ] 5-min slide deck (PDF)
- [ ] Form submitted at https://tally.so/r/GexoxQ before 16:30 Sunday
