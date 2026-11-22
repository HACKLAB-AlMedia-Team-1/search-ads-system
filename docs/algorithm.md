# How RootSight decides (algorithm)

RootSight is one agent that runs one loop per simulated hour: **simulate -> score -> group -> investigate -> track**.
Its rule is **rules first, the model only where rules cannot**:

| Job | Rules (always on, no model) | Model (only when rules cannot) |
|---|---|---|
| Watch | every metric of the graph, scored every hour by statistics; a watch someone asks for becomes a rule when a metric can express it | a watch no metric can express (it needs reading or judging): the model looks every 6 simulated hours |
| Find the cause | the fixed recipe walks the graph and the 4-point evidence checklist decides | takes over when the recipe cannot confirm a cause, and continues the same trail |
| Read plain words | phrases that name a metric, country or device | picks a metric, writes a metric's SQL, or says it needs judgement |

Code checks everything a model produces before it counts: the evidence checklist, every number against the tool results,
every metric and segment it names, and any SQL it writes (run on history and shown to the person).

In the dashboard this loop runs all the time: one simulated hour every 1-3 real seconds, from the moment the dashboard loads. It never pauses.
Actions of a real person in the ShopLens store are added to the organic numbers of the hour being simulated, for that country and device.
One action stands for 100 shoppers, but at most a tenth of that hour's shoppers on the same device. The number of searches stays the same:
an empty search moves that crowd from "found products" to "found nothing", a search with results moves a crowd the other way.
The simulated night (01:00-06:59) is passed without waiting, and a failure started at night switches on at 07:00.

## 1. What to monitor

- Every hour: the top KPIs (orders, revenue, search CTR, ROAS, ad spend, pacing, zero-result rate) and the component health
  metrics (index size, cache hit rate, cache age), each for all traffic and for every market.
- A rotating batch of about 40 other (metric, segment) pairs per tick. Segments are market, platform and source, singly or in pairs.
- Anything that was unusual last tick is scored again (a "watch list").
- A newly added metric is pinned and scored on every tick.
- A rule watch someone asked for on the *Agent* page (a metric in a segment) is pinned and scored on every tick.

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

This order is the rule recipe (`agent/offline_policy.py`), and it always runs first. If it confirms a cause (SUPPORTED),
the investigation ends there and no model is called. If it does not and a model is switched on, the model **takes over**
(`Investigator._rules_then_model`): it gets the case, the causes the recipe tested and the checks that failed, and calls
the same tools (fresh limit of 12 calls, prompt `agent/prompts/takeover.md`). Its hypotheses go through the same checklist;
the report keeps the best-supported cause and says who found it (`method`: rules, or rules then the model). If the model
fails or tests nothing, the recipe's result stands. A model that has not tested a cause four calls before the limit is reminded to.

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
Only hours in which the incident's metric could be judged count as normal: a night hour with too few shoppers says nothing, so the incident stays open.
A person is re-notified only when the money impact grows by more than 50% or the scope widens. The report's cost is refreshed with every matching case.
When a person fixes the cause (*End Simulation* in the dashboard: the fault is switched off and the store repaired) nobody closes the incident by hand.
Monitoring keeps running, the agent sees the numbers recover and closes it after three normal hours that could be judged, like any other incident.
The same cause coming back within 24 hours normally reopens the incident. A fixed incident is the exception: it is never reopened, so the same
cause coming back later is a new incident with a fresh report (`IncidentManager.fixed`).

## 7. Watches and questions (the *Agent* page)

**Watch something.** A plain request ("zero results in Germany on Android") is planned rules first (`agent/watches.py`):
1. Phrases that name a metric (`PHRASES`, or the metric's own name) plus country and device words -> a **rule watch**: that
   metric in that segment is pinned and scored every hour by the statistics above (no model).
2. No metric named and a model is on -> the model decides: an existing metric (validated: it must exist, the segment must
   exist) -> rule watch; a new metric -> it writes the SQL, which is run on 7 days and shown before it is added; it needs
   judgement -> a **model watch**.
3. No model -> the model watch is saved and waits for one.

The person sees the plan first and can switch it (a rule to the model, or the model to a rule when the words name a metric).
A model watch looks every 6 simulated daytime hours with the read-only tools and ends with `verdict` (ok or problem).
Code checks the verdict: a problem must name an existing metric and a valid segment, and its sentence may only use numbers
from the tool results (otherwise the sentence is dropped). A checked problem becomes a case and goes through the normal
investigation (rules first) and incident flow. Watches live in the `watches` table, so *Reset demo* clears them.

**Ask why.** "Why do searches find nothing in Germany?" -> the number and segment (plain words first, the model if no
metric is named) -> its score for the latest closed hour. If it and everything upstream of it is normal, the answer says
so with the numbers. Otherwise (or when asked to investigate anyway) a case is built from the unusual metrics and
investigated exactly like a watcher case.

## 8. Adding a metric

`{name, description, sql}` -> parse with sqlglot -> propose edges (shared columns; the fast model if configured) -> validate in code
(the SQL must run on history, dimensions must exist, a correlation edge needs |r| >= 0.6 over 7 days at lags 0-2 hours, otherwise it is kept
with half the confidence and flagged AMBIGUOUS) -> write to `metric_registry` and `data/metrics_custom.yaml` -> the watcher scores it next tick.
With a model, the SQL itself can be written from a plain description (`draft_metric`): the statement is run on 7 days of
history and shown to the person, who decides. It is never added unseen, because a statement can run and still be wrong.

## 9. Rules or a language model

Measured on 22 Nov 2026 (`docs/MODEL_COMPARISON.md`, one run per scenario): the rule recipe finds and confirms all nine
known failures in 0.3 s; Claude Opus also confirms all nine without a recipe (38 s); two local models (Qwen 3.5, 4B and 9B)
find eight and nine but confirm only six and seven. Reading a person's description: keywords 4 of 12, local models 10,
cloud models 12. Writing SQL from words: rules cannot, local models right 2-3 of 6, cloud models 6 of 6.
So: rules where the failure is known and speed matters, a model for language and for cases no recipe covers, and code for
every number and every check either of them produces. That is how the agent is built (section 0): with the nine known
failures the rules confirm every cause, so the model is never called and the results are the same with or without it.
