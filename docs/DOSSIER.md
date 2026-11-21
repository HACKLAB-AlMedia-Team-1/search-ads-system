# DOSSIER.md — RootSight (AdSearch Sentinel), the whole project on one page

## 1. The challenge (Almedia track: "Eye of the System — Fully Agentic Monitoring")

Build an autonomous monitoring system for an Amazon-like marketplace. It must decide what to watch,
detect meaningful changes, investigate them by itself, and tell the story with evidence, without
anyone asking questions. Its understanding of the business is a **graph of metrics and their relationships**.

What the system must do: build and maintain the metric graph · auto-place new metrics · monitor
continuously (seasonality, data completeness, planned events) · investigate autonomously (choose
next query, follow edges, compare explanations, stop at sufficient evidence, separate symptoms
from first causes) · communicate and adapt (alerts with numbers + trail, track persist/resolve, no repeats).

**Judging:** 40% metric graph + automatic extension · 40% autonomous monitoring + investigation · 20% working demo
(introduce a fault and an innocent change, add a new metric, let the system respond).

**Submission (Sun 22 Nov 2026, 16:30, https://tally.so/r/GexoxQ):** 3-min video (team member on camera, show the
solution) · public GitHub repo with docs · short slide deck (5-min stage pitch if we win).

## 2. Our idea in one paragraph

A marketplace spends **€1,000 a day on ads** that bring visitors to its **search**. When a release or config
change quietly breaks search, ad spend and traffic look normal, but clicks and purchases fall, so **ad money is
burned**. **RootSight** watches ads and search together, notices the problem by itself, follows a metric graph
from the money metrics down to the broken component, checks recent releases and configs, rules out innocent
explanations, and writes a report: *what broke, where, since when, why (with evidence) and what it costs*.

**Pitch line:** "Your ads keep running when your search breaks. RootSight notices within the hour, finds the
release that did it, and tells you how much money it is burning."

**Why it's relevant to Almedia without being about Almedia:** ad spend efficiency, budget pacing, search/catalogue
quality, mobile releases, multi-market users and planned campaigns are daily concerns of any ad-funded consumer
platform, including Almedia's rewards platform. We stay a general marketplace.

## 3. What is real and what is simulated (be open about this)

| Real | Simulated |
|------|-----------|
| ~50–80k Amazon products (titles, descriptions, brands) from the **ESCI** dataset (Amazon, Apache-2.0) | Users, sessions, clicks, carts, orders (click model driven by the real relevance labels) |
| Real customer **search queries in English, Spanish, Japanese** | Ads: 3 campaigns, €1,000/day, CPC, pacing controller |
| Human **relevance labels** (Exact/Substitute/Complement/Irrelevant): ground truth for search quality | Price, stock, seller, product age |
| A real **BM25 search engine** with per-language analyzers; failures are real bugs in it | Release / config / job event log (+ harmless decoy events) |
| (Optional) real hourly traffic rhythm from **Taobao** user behaviour | 14 days of history + live days (21–29 Nov 2026) |

## 4. Scenarios

Our 15 candidate failures, and what we do with each:

| # | Candidate | Decision | Why |
|---|-----------|----------|-----|
| 1 | Search algorithm failure | **S1, headline** | Clearest story; ads keep spending, sales drop |
| 12 | Regional search failure | **S12, must** | Real Spanish queries → shows market split + language |
| 3 | Mobile search failure | **S3, must** | Platform split; very relatable (app releases) |
| 2 | Product indexing failure | **S2, should** | Different signature (zero results, index doc count) |
| 7 | Ranking regression | **S7, should** | Subtle: relevant items still there but lower → shows deeper reasoning |
| 15 | Search cache failure | **S15, could** | Stale results, prices, stock → component health check |
| — | **Ad budget pacing anomaly** | **AD1, must** | Ads side of the graph; budget gone by 10:00 |
| 5 | Marketing campaign (low intent) | **EV1, must (innocent)** | Proves the agent doesn't cry wolf |
| — | Late data | **DQ1, must (innocent)** | Data completeness requirement |
| 4, 6, 8, 9, 10, 11, 13, 14 | inventory, latency, price, category, recommendations, checkout, feed quality, filters | Not built | Same graph paths as above or hard to show in 3 min; mention as "the graph extends to these" |

Full spec and the **differential-diagnosis table** are in `docs/SCENARIOS.md`.

## 5. Architecture (short)

Data prep → **ShopLens** engine + simulator → DuckDB (hourly facts, ads, component health, search samples, events,
data arrivals) → **Watcher** (statistics, no LLM) → **Investigator agent** (Claude Sonnet with tool calling; Claude Haiku
as relevance judge; Linkup web check) → **Evidence checklist** (code) → **Incidents** → **Streamlit** UI (control room,
shop, graph, incidents, add metric). Full diagram + file layout in `PLAN.md` §0.

## 6. The algorithm (what judges asked us to explain)

**What to monitor:** top money KPIs every hour; segments (market × platform × traffic source, campaigns) on a rotating
batch; anything that moved last hour gets re-checked. Priority = `|robust z| × business weight × persistence`.

**What is "normal":** median of the same hour on the last 7 comparable days (weekday/weekend), robust spread (MAD),
minimum volume for ratios, calendar adjustments for planned events, completeness gate for late data.

**Which graph edges to follow:** `formula` edges first (exact log-decomposition says which factor moved), then
`split_by` (which segment holds ≥ 70% of the deviation), then `may_be_caused_by` edges ranked by confidence and by
whether the cause metric is itself anomalous **earlier** (first cause, not symptom), then `context` edges to the event log.

**Which groups to examine:** the dimensions on the current node, ranked by how concentrated the deviation is
(the share of the deviation in the top segment vs its share of volume).

**When evidence is sufficient:** the 4-point checklist (size, location, timing, alternatives) computed in code.
SUPPORTED → stop and report; LIKELY/HYPOTHESIS → keep looking until the tool-call limit, then report honestly with
what's missing.

**Where the LLM is used, and where not:** statistics and the checklist are code (reliable, cheap, no invented numbers).
Claude decides **which tool to call next**, judges **search relevance** on real result samples (something statistics
can't do), interprets **logs/events** and writes the **story**. The onboarding agent proposes graph links for new
metrics; code validates them.

## 7. Demo storyline (3-min video)

| Time | Screen | Say |
|------|--------|-----|
| 0:00–0:20 | **Team member on camera** | "Companies spend thousands a day on ads that send people to search. When search breaks, the ads keep running. We built an AI agent that catches that by itself." |
| 0:20–0:40 | Architecture + "real vs simulated" | Real Amazon products and queries in 3 languages, real search engine, €1,000/day ads, Claude agent with tools, metric graph |
| 0:40–0:55 | Control room green, ShopLens search works | "A normal day. Nobody is watching. RootSight is." |
| 0:55–1:10 | **EV1** Black Friday push | Conversion drops, orders rise → "planned campaign, mix shift, no incident" |
| 1:10–1:55 | **S1**: click → ShopLens shows junk results → alert → trail streams → report | Read the checklist ticks; "€X of ad spend wasted per hour; cause: search-ranker v2.0.0; rejected: traffic, data delay, Android release" |
| 1:55–2:15 | **AD1** pacing | Budget bar empty by 10:00 → "pacing-service 1.4.0" |
| 2:15–2:35 | **Add metric** `wasted_spend_share` | Agent places it between ads and search; one edge flagged ambiguous |
| 2:35–2:45 | Montage: S12 (Spanish), S3 (Android) | "Same agent, different branch of the graph" |
| 2:45–3:00 | Incidents resolve → **back to camera** | "It noticed, investigated and explained. No one asked." |

## 8. Slides (5 minutes, 7 slides)

1. Problem: ads keep spending when search silently breaks
2. RootSight in one picture (architecture)
3. The metric graph: 5 edge types; ads ↔ search connected; new metrics placed automatically
4. How the agent decides: attention score → formula → split → cause → events → 4-point checklist
5. Telling look-alike failures apart (differential-diagnosis table)
6. Results: scenarios found, false alarms on clean days, time to root cause, cost per investigation
7. Plug it into any company: their metrics + event log + catalogue → same agent

## 9. Tools and budget

- **Claude API ($25):** Sonnet = investigator; Haiku = judge + onboarding. Offline mode for dev/tests; record once, replay for the video.
- **Linkup ($20):** `web_check` only (calendar / outside context), cached.
- **Devin:** isolated phases (Phase 2 engine, Phase 8 UI) on branches → PRs we review.
- **Laptop:** CPU only. No local models.

## 10. Risks and fallbacks

| Risk | Fallback |
|------|----------|
| ESCI download slow/fails | GitHub LFS mirror (SETUP Step 6); worst case: use a 20k-product subset |
| Live agent unstable on stage/video | `replay` mode from recordings |
| Running out of API credit | offline policy agent gives the same result; LLM only for recorded runs |
| UI live refresh flaky | the demo script advances time in steps on button click |
| Time | Cut order in PLAN.md |

## 11. Glossary (plain words)

- **BM25:** classic search-ranking formula: scores a product higher when it contains the query's words, especially rare ones.
- **Analyzer:** turns text into searchable tokens (lowercase, remove accents, cut word endings). Different per language.
- **CTR:** click-through rate, the share of searches where the user clicks a result.
- **ROAS:** return on ad spend = revenue from ad visitors ÷ ad spend.
- **Pacing:** spreading an ad budget evenly over the day instead of spending it all in the morning.
- **Robust z-score:** how many "normal spreads" a value is away from the usual value; robust = not fooled by outliers.
- **MAD:** median absolute deviation, a robust measure of spread.
- **nDCG@10:** search-quality score that rewards relevant results near the top of the first 10.
- **Mix shift:** an average moves because the mix of visitors changed, not because anything broke.
- **Fingerprint:** a short ID for a problem so the same problem isn't reported twice.
