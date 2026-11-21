# How RootSight decides (algorithm)

RootSight runs one loop per simulated hour: **simulate -> score -> group -> investigate -> track**.
Statistics and the evidence checklist are code. A language model is optional and only chooses which tool to call next.

## 1. What to monitor

- Every hour: the top KPIs (orders, revenue, search CTR, ROAS, ad spend, pacing, zero-result rate) and the component health
  metrics (index size, cache hit rate, cache age), each for all traffic and for every market.
- A rotating batch of about 40 other (metric, segment) pairs per tick. Segments are market, platform and source, singly or in pairs.
- Anything that was unusual last tick is scored again (a "watch list").
- A newly added metric is pinned and scored on every tick.

## 2. What is normal

- Expected value = median of the same hour on up to 7 earlier days of the same type (weekday or weekend), 14 days of history.
- Spread = the largest of: 1.4826 x MAD, 0.5 x standard deviation, and a noise floor that depends on volume
  (binomial for shares, Poisson for counts, a per-metric relative floor in `metrics.yaml`). Ratios with fewer than 30 events are skipped.
- Noisy ads outcomes (ROAS, paid orders, ...) are scored on rolling 6-hour windows.
- Planned events (calendar) multiply the expected value and tag the metrics they explain as `planned`.
- A source table that is less than 90% complete (late data) makes the metrics that read it unscorable; a "data delay" notice is raised instead.
- A move in the harmless direction (orders up) never alarms.

## 3. When it is an anomaly, and a case

- |robust z| >= 3 for two consecutive hours, or >= 5 once. Attention = |z| x business weight x (1 + 0.5 x hours in a row).
- Anomalies are grouped into one case when their metrics are related in the graph (one upstream of the other, or both affected
  by the same event component) and their segments do not contradict each other. At most two failure cases per tick go on.
- A case that matches an open incident updates it instead of starting a new investigation.

## 4. How the investigation walks the graph

1. Pick the earliest-onset anomalous metric that has no anomalous metric upstream of it (the first cause, not the symptom).
2. `decompose` the reported metric along its formula edges (which factor moved).
3. `drill_down` by market and platform: a segment holding at least 70% of the deviation while its siblings stay normal localises the change.
4. `get_events` (decoys included), keep events whose component feeds the metric or anything upstream of it (context edges), nearest before onset first.
5. `component_health`, `sample_searches` + `judge_relevance` for search problems.
6. `record_hypothesis` runs the evidence checklist.
7. `estimate_impact`, `finish`. The report is assembled in code from tool results; the model never writes a number.

## 5. When the evidence is sufficient (computed in `agent/evidence.py`)

| Check | Passes when |
|---|---|
| Size | the affected segment explains >= 70% of the deviation |
| Location | the segment's z is beyond 3 and every sibling segment is within 2 |
| Timing | the change starts 0-120 minutes after the event |
| Alternatives | at least 2 other explanations were tested and rejected, none left open |

Alternatives tested: late data, planned event, traffic-mix shift (or "search problem" for ads metrics), and every other event near the onset.
An event is rejected when its component is not connected to the metric in the graph, or its platform does not fit (an iOS release cannot explain an Android change).
4 passes = SUPPORTED, 3 = LIKELY, fewer = HYPOTHESIS. The report says what is missing.

## 6. Incidents

Fingerprint = `root metric | segment | cause component`. Open -> ongoing -> resolved (after 3 normal hours).
A person is re-notified only when the money impact grows by more than 50% or the scope widens.

## 7. Adding a metric

`{name, description, sql}` -> parse with sqlglot -> propose edges (shared columns; the fast model if configured) -> validate in code
(the SQL must run on history, dimensions must exist, a correlation edge needs |r| >= 0.6 over 7 days at lags 0-2 hours, otherwise it is kept
with half the confidence and flagged AMBIGUOUS) -> write to `metric_registry` and `data/metrics_custom.yaml` -> the watcher scores it next tick.
