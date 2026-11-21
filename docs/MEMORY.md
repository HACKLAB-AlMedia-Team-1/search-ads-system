# MEMORY.md — Project memory (read first, keep current)

Shared memory for every agent session and every teammate. Keep it short. Newest log entries first.

## Environment facts

- OS: Windows. Python 3.11.18 (conda env `rootsight`). Resolved libs: pandas 3.1, numpy 2.4, duckdb 2.0, pydantic 2.14, streamlit 1.67, ruff 0.17.
- `scripts/check_env.py` (2026-11-21): all green (packages, modes, ESCI).
- No LLM key is used. `anthropic` is installed but unused. Linkup key is set in `.env`, `LINKUP_MODE=offline`.
- ESCI downloaded with `hf download` into `data/raw/esci` (13 files, 1.24 GB: products 1.8M rows, queries 2.6M labelled pairs, plus sources/retrieval). Column names differ from PLAN (`product_title`, labels live in `queries/`).
- Taobao UserBehavior: not downloaded (skipped on purpose).
- `devin` is not on PATH in the user's shell; the bundled binary is `D:\Devin\resources\app\extensions\windsurf\devin\bin\devin.exe`. The ponytail plugin install (`devin plugins install DietrichGebert/ponytail`) is still pending.
- Windows gotcha: Git-Bash `/tmp` paths are invisible to the conda Python; set `PYTHONIOENCODING=utf-8` when printing JP/ES text.

## Status

| Phase | Name | Status | Notes |
|-------|------|--------|-------|
| Setup | Human setup | done | env, ESCI, `.env` |
| 0 | Bootstrap | done | committed once on `devin/phase-0` (the only agent commit; has a Devin co-author trailer) |
| 1 | Data preparation | done | 4.6 s; US 29,294 / ES 37,175 / JP 39,814 products; 1,500 queries per market |
| 2 | Search engine + faults | done | 12 engine tests; all 6 search faults verified |
| 3 | Simulator, ads, database | done | backfill 96 s, 336 h, spend EUR ~1,000/day, paid ROAS 3.34 |
| 4 | Metric graph | done | 33 metrics, 5 edge types, DAG, all 7 formulas hold (0% error) |
| 5 | Watcher | done | 0 false cases in 5 clean days; S1/S12/S3/AD1 found within 2 h; EV1 planned; DQ1 notice |
| 6 | Investigator + incidents | done | 15 tools, evidence checklist, rule-based policy, LLM client (untested against a real endpoint), incident manager, `pipeline.py`; every scenario traced to its cause |
| 7 | New-metric onboarding | done | both demo metrics placed; weak edges flagged AMBIGUOUS |
| 8 | Streamlit UI | done | control room, ShopLens storefront (dark mode), metric graph, incidents, add metric; `scripts/smoke_ui.py` renders all pages |
| 9+ | Journey rework + UI rebuild | done | DE journey (S12, AD1, INV1), web shop, new dashboard |
| 9 | Demo hardening + docs | done (no recordings) | `scripts/demo.py`, README, `docs/algorithm.md`; Opus review not run (see Open questions) |

Scenario status: all nine (S1, AD1, EV1, DQ1, S12, S3, S2, S7, S15) work in simulator, watcher and agent; the 15 integration tests cover them.
Tests: `pytest -q` = 31 fast tests (~50 s); `pytest -m integration` = 15 scenario tests (~2.7 min); ruff clean; `scripts/smoke_ui.py` ok.

## Decisions (dated, one line each, with reason)

- 2026-11-21 · Project = RootSight / AdSearch Sentinel: ads + search monitoring on one metric graph. Reason: strongest story + covers 40/40/20.
- 2026-11-21 · Data = Amazon ESCI (real products, queries EN/ES/JP, labels). Ads and users are simulated (EUR 1,000/day, 3 campaigns). Markets US/ES/JP.
- 2026-11-21 · No Anthropic key. Devin keys cannot call models from an app (checked the docs). LLM access is one OpenAI-compatible client (`agent/llm.py`) with roles `agent`/`fast`; default `LLM_MODE=offline` runs the rule-based investigator; a local model (e.g. Ollama) is optional. Supersedes the old "Claude $25" budget line.
- 2026-11-21 · The user does all installs/downloads. The agent makes NO git commits from now on (user request); this overrides CLAUDE.md section 4 step 3.
- 2026-11-21 · User chose to build all phases without stopping, scenarios S1/S12/S3/AD1/EV1/DQ1/S2/S7/S15, demo = Streamlit UI + terminal script, Taobao skipped.
- 2026-11-21 · Taobao skipped: built-in 24 h traffic curve and assumed funnel rates (30% cart, 70% checkout, 95% payment). Possible later use: measure real rates.
- 2026-11-21 · Query sample = 1,500 per market chosen among small-version queries with at least one Exact label (so relevance is attainable). Unlabelled results count as Irrelevant. Catalogue is ~106k products, above PLAN's 50-80k, still fast.
- 2026-11-21 · Own sparse BM25 (`engine/index.py`: precomputed Okapi weights, Lucene-style idf) instead of `rank-bm25`, whose per-document Python loop was too slow. `rank-bm25` stays in requirements but is unused. A document must match at least half of the distinct query tokens (needed so a partial index changes result counts).
- 2026-11-21 · Cache key includes platform (otherwise Android's empty result would be served to iOS). S15 stale mode = TTL 24 h, not a snapshot.
- 2026-11-21 · Shop hides sold-out and delisted products (sim uses `in_stock=True`), so "unavailable on click" is ~0 normally and only a stale cache raises it. Nightly job at 03:00: restock, 4% sell-out churn, 8% price changes, 0.5% delist / 25% relist.
- 2026-11-21 · S1 keeps zero-result unchanged (empty only when BM25 finds nothing), otherwise picks from the top 300 by title length x brand popularity. S7 reorders only the top-15 BM25 hits by recency (relevance stays within 10%, first-exact position rises).
- 2026-11-21 · Measured baseline: relevance@10 US 0.60, ES 0.65, JP 0.58; first-exact position ~3.1 (PLAN assumed 1.8). Single search < 50 ms.
- 2026-11-21 · Paid traffic intent 0.17 gives paid ROAS 3.34. Daily-order CV: US 7%, JP 9.2%, ES 10.0% (weekend multiplier 1.15 included; weekdays-only is lower). EV1 uses effective paid intent x0.75 (half the audience is new at x0.5) so orders rise.
- 2026-11-21 · `component_hourly` has an extra `scope` column (market or all). DQ1 is modelled with three arrival tables `search_events`, `orders`, `ads`; only `search_events` columns are degraded to 35% and repaired 2 h later.
- 2026-11-21 · Graph deviations: `search_latency_p95` is the AVERAGE of hourly p95s (MAX was too noisy); `sessions -> searches` also a may_be_caused_by edge; cause edge `ad_spend -> paid_clicks` replaced by `pacing_ratio -> paid_clicks` so the graph stays a DAG.
- 2026-11-21 · Watcher deviations from PLAN: minimum volume is 30 events in the metric's own denominator (PLAN said 200 searches; ES peaks at ~260/h); history lookback 14 days (weekend baselines need 3+ weekend days); noisy ads outcomes (roas, paid_orders, paid_revenue, cost_per_order) scored on 6-hour windows; per-metric noise hints in `metrics.yaml` (noise, cv, min_spread, rel_floor); moves in the harmless direction (orders up) never alarm.
- 2026-11-21 · Tests: slow full-engine scenario tests carry `@pytest.mark.integration` and are skipped by default (`pytest -q` is the fast suite, `pytest -m integration` runs scenarios). Tests copy the backfilled DB to a temp file and never touch the real one.
- 2026-11-21 · Code review: a read-only `reviewer` subagent profile (`.devin/agents/reviewer.md`, `model: opus`) exists but failed to start in this session, so no Opus review has run. Reviews are done by the main agent with the ponytail rules (smallest complete change, delete dead code, keep tests).

- 2026-11-21 · UX measures: simulated `avg_click_position`, `refinement_rate`, `bounce_rate` (in `fact_hourly`, graph, watcher) plus real storefront telemetry (`ux_events`: search latency, zero result, click position, refine, add to cart, cart errors, price mismatch, render time) shown on the control room.
- 2026-11-21 · Storefront stays in Streamlit (custom HTML/CSS in an Amazon-like layout, dark-mode toggle, Sponsored cards tied to live ad spend). A stand-alone web shop would need a new dependency, which the rules forbid without the user.
- 2026-11-21 · Incident grouping and matching use `MetricGraph.related`: equal, one upstream of the other, or sharing an event component. Cost: simultaneous unrelated faults sharing a family can merge into one case.
- 2026-11-21 · Evidence rejects a rival event by scope (an iOS release cannot explain an Android change); `events.app` has a `platform_of` map in `metrics.yaml`.
- 2026-11-21 · EV1 produces no anomalies after the calendar adjustment, so the watcher emits a "planned event active" info card when a calendar entry first appears; `stop_all` also ends active calendar entries.
- 2026-11-21 · Onboarded ratio metrics whose history lies in [0, 1] get unit `share` (binomial noise floor); without it the watcher raised false alarms on the new metric.
- 2026-11-21 · `scripts/backfill.py` also saves `data/rootsight.backfill.duckdb`; `scripts/demo.py` copies it to `data/demo.duckdb` and uses its own `demo_metrics.yaml`, so the demo never touches the real database. The UI works on `data/rootsight.duckdb` (restore it by copying the snapshot over it).

- 2026-11-21 · DEMO STORY CHANGED (user): one shopper journey in Germany with three failures in a row: regional search failure (S12, now DE), ad pacing failure (AD1, now DE), supplier delivery delay (new INV1). Other scenarios stay available.
- 2026-11-21 · German store is FAKE on purpose (user chose it; ESCI has no German): market `DE` = US catalogue + 489 US queries translated word by word with a hand-made 268-word vocabulary (`rootsight/data/german.py`); the `de` analyzer maps German words back to English. Say so openly in the pitch.
- 2026-11-21 · Markets are now US, ES, JP, DE; ad budgets 400/200/150/250 = EUR 1,000/day. Fault `es_analyzer_english` renamed `regional_analyzer_english` (works for any market).
- 2026-11-21 · Ads formula is now `ad_spend = impressions x ad_click_rate x cpc` (was clicks x cpc). AD1 no longer raises CPC: the overspend comes from impressions, so the agent can rule out a cost-per-click spike and a site-traffic spike.
- 2026-11-21 · Inventory domain added: `purchase_orders` table, `in_stock_rate_top` and `product_views` metrics, context `events.inventory` (goods-receiving), tool `purchase_orders`. Top sellers (Exact products of the 100 most searched queries) are replenished by purchase orders and never randomly sold out; INV1 leaves a due purchase order unreceived. Checks: order existed (not a reorder failure), ordered >= needed (not under-ordering).
- 2026-11-21 · The shop now shows out-of-stock products (sim no longer filters `in_stock`); products that sell out are auto-reordered (50 units) so availability noise stays low.
- 2026-11-21 · Evidence: named look-alike causes per domain are tested (indexing failure, mobile release, CPC spike, traffic spike, reorder failure, under-ordering). Sibling threshold relaxed from 2 to 3 (with 4 markets a calm sibling at z=2.1-2.8 was blocking SUPPORTED).
- 2026-11-21 · Incidents: a case joins an open incident only if that incident's cause component can explain the case's most upstream metrics (before: any graph relation, which glued the ad failure onto the search incident). The same cause returning within 24 h REOPENS the incident. Impact is counted inside the affected market/platform. Policy widens the event lookback to 24 h when the last 6 h explain nothing.
- 2026-11-21 · Watcher: quality metrics (relevance, ndcg, first exact position) scored every tick; minimum volume 60 (was 30).
- 2026-11-21 · UI REBUILT after user feedback ("bland, buggy, cluttered, not like a real store"): (1) ShopLens is a real web shop: `app/shop/` (HTML/CSS/JS) served by `app/shop_server.py` (Python standard library, port 8600, started by the dashboard), Amazon-like layout, 4 languages, light/dark toggle, sponsored slot tied to the live ad budget, live stock at add-to-cart, a "Demo note" strip. (2) Dashboard stays Streamlit with `st.navigation`: Shopper journey (guided 3 steps, Break it / Fix it, finding appears in the step), All scenarios (plain-language catalogue, `app/guide.py`), Control room, Incidents, Metric graph (focus on one metric), Add a metric. Dark mode switches Streamlit's own theme so widgets match. `.streamlit/config.toml` hides Streamlit's Deploy button (that was the "start trial" popup; nothing here needs an account). Old `app/pages/` and `shop_ui.py` deleted. "Reset demo" restores the backfill snapshot.
- 2026-11-21 · UI is checked with real headless-Chrome screenshots (scratch tool in `.shots/`, git-ignored), not only `scripts/smoke_ui.py`.
- 2026-11-21 · Tech choices (asked by user): DuckDB for data; NetworkX (not Neo4j) for the 40-node graph because it lives in memory and needs no server; own small agent loop (not LangGraph) because LangGraph is not installed and the loop is ~40 lines; optional open-source LLM through Ollama's OpenAI-compatible API; statistics/BM25/graph algorithms for everything that does not need a language model. Flowchart image: `docs/how_rootsight_works.png`.

## Open questions

- Team size and who owns which phase? (default plan assumes 3-4 people + Devin)
- Should the Phase 0 commit (Devin co-author trailer) be reworded before pushing?
- Run the Opus reviewer (`.devin/agents/reviewer.md`) in a fresh session, and install ponytail with the full path of `devin.exe`?
- The live LLM path (`LLM_MODE=live`) is only unit-tested with a fake endpoint; try it once against a local Ollama model.

## Ideas / later (not in scope unless time is left)

- Use real Taobao behaviour to measure funnel rates and traffic shape.
- Extra scenarios: search latency (#6), checkout failure (#11), feed quality (#13). Slack-style alerts.
- Watcher: real-time per-hour streak across restarts is in memory only; persist if the loop is restarted often.

## Session log (newest first)

- 2026-11-21 · Bug fix (page greyed out after +1 / +6 hours): the page's live panels were computing metric scores themselves and waiting for the simulation's lock, so Streamlit faded the page for 2-3 s and the two also slowed each other down (+6 hours took 11-13 s). Now the background worker scores the newest hour for every series the pages show (`Runtime._score_wanted`); pages only read cached values while the simulation is advancing; the watcher caches each hour's calendar/completeness lookup; the stale fade is disabled in CSS. Measured in a browser: no greyed time, +1 hour ~0.6 s, +6 hours first update ~0.6 s and done in 3.6-5.8 s (7 s with a fault active).
- 2026-11-21 · Bug fix (restart): faults live only in memory, so after restarting the app the database still held old incidents while no fault was active; a re-injected fault then matched the stale open incident and the journey step never showed a finding. The app now starts fresh on every launch (`fresh_start` in `app/common.py` restores the backfill snapshot, drops the leftover `.wal` and custom metrics). `Runtime.finding` matches on `last_seen` so a reopened incident is shown too. Decision: nothing from a demo run survives a restart.
- 2026-11-21 · Speed: metric SQL is parsed once and cached (`split_sql`, `_tables_of`); "+1 hour / +6 hours" run in a background worker (`Runtime.advance`) so the page is not frozen and shows each hour as it passes; live panels refresh every second. Measured in a browser: +1 hour about 0.6 s; +6 hours first update after about 0.7 s, all six done after about 4.8 s (about 0.5-0.7 s of real work per simulated hour, mostly the watcher's ~250 SQL queries).
- 2026-11-21 · Bug fix: dark mode was lost when changing dashboard page (Streamlit drops a widget's state when the widget is not drawn during a page switch). The choice is now kept in its own session key (`dark_mode`) in `app/common.py`. Checked in a real browser across three pages, both directions.
- 2026-11-21 · Added `docs/RUN_DEMO.md`: how to start the app, run the journey, run the tests, and fix common problems.
- 2026-11-21 · Journey rework: DE market, INV1, ads formula, look-alike checks, incident matching, web shop, dashboard rebuild, flowchart. Bugs found on the way: random sell-outs of popular products caused false alarms (fixed by PO-managed top sellers + auto-reorder); EV1 lacked `impressions` in its expected effect; journey steps run back to back merged into one incident; default page URL is `/` (not `/journey`).
- 2026-11-21 · Phases 6-9 finished: pipeline wiring, incident manager, onboarding, Streamlit UI, demo script, README, `docs/algorithm.md`. Demo bugs found and fixed: calendar entries outliving `stop_all` hid a real incident; related metrics (first_exact_position vs refinement_rate) opened duplicate incidents; S12/S3 evidence stayed LIKELY until rivals were rejected by scope; component metrics were not in the every-tick KPI list so S2/S15 were missed.
- 2026-11-21 · Cleanup: removed junk left in `report.py`/`manager.py`/`investigator.py`, deduplicated linked-component logic into the graph, ruff format + unsafe fixes, dead-symbol scan found nothing unreferenced. Unused dependencies: `rank-bm25`, `anthropic`.
- 2026-11-21 · Phase 6 in progress: `agent/{tools,evidence,offline_policy,report,investigator,llm,linkup}.py`, `incidents/manager.py` written. Next: `pipeline.py` wiring, agent tests, then onboarding, UI, demo and docs.
- 2026-11-21 · Phase 5: watcher first raised ~100 false cases per 5 clean days. Fixed with volume-aware noise floors (binomial/Poisson), 6 h windows for ads outcomes, std-based spread term, bad-direction filter and 14-day history. Integration tests initially failed because scenario windows overlapped and the weekend lookback was too short; both fixed.
- 2026-11-21 · Phase 4: `graph/{graph,series,validate}.py`, `metrics.yaml`; formulas validated on 7 days (median error 0).
- 2026-11-21 · Phase 3: simulator, ads pacer, funnel, events, arrivals, scenarios YAML (all 9), DuckDB schema, backfill. Bug found: query weights did not sum to 1 on subsets (QueryPool now normalises).
- 2026-11-21 · Phase 2: engine + faults. Bugs found: cache poisoning across tests (cache cleared per test), S7 effect too weak (pool 30 -> 15), partial index invisible (min-should-match added).
- 2026-11-21 · Phase 1: `data/{loaders,synthetic,prepare}.py`, `scripts/prepare_data.py`. Phase 0: skeleton, config, check_env. Kit created earlier.
