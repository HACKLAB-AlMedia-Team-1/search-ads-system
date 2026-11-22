# Who should drive the agent: rules, a local model or a cloud model?

Status (2026-11-22): all five contenders have been run on all four jobs. The measured tables (including every SQL
statement each model wrote) are in `docs/model_comparison_results.md`; this file explains the method and what the
numbers mean. Short answer: no single contender is best at everything, so the product should combine them (see
"Conclusion").

## The five contenders

| Contender | What it is | Where it runs | Needs |
|---|---|---|---|
| `rules` | The traditional method: a fixed investigation recipe in code (`rootsight/agent/offline_policy.py`), keyword matching for scenario texts, a column heuristic for new metrics | In the app | Nothing |
| `qwen3.5:4b` | Open model, 3.3 GB, 4-bit | Laptop GPU (RTX 4070, 8 GB): 100% on the GPU | Ollama, weights in `models/ollama` |
| `qwen3.5:9b` | Open model, 6.6 GB, 4-bit | Laptop GPU: 86% on the GPU, the rest on the CPU | Ollama, weights in `models/ollama` |
| `opus` | Claude Opus | Cloud, through the Devin CLI | A Devin account (`devin auth login`) |
| `sonnet` | Claude Sonnet | Cloud, through the Devin CLI | A Devin account (`devin auth login`) |

With a model API key (OpenRouter, Anthropic or any OpenAI-compatible endpoint) the cloud contenders can also be called
directly: set `LLM_BASE_URL` and `LLM_API_KEY` in `.env`; the tool then uses `anthropic/claude-opus-5.5` and
`anthropic/claude-haiku-5.5` by default (`--cloud` changes that) and reads real token counts and prices.

## What is the same for everyone

- The simulation and the watcher run once per scenario. Every contender gets exactly the same case.
- The same 15 tools, the same limit of 12 tool calls, the same system prompt (`rootsight/agent/prompts/investigator_system.md`).
- The numbers in a report, the 4-point evidence checklist (size, location, timing, alternatives) and the cost estimate
  are computed in code for everyone. A model only chooses the steps and the wording. It cannot invent a figure.
- If a model fails (no answer, broken reply, no hypothesis tested), the rules finish the job. The tool records this as
  "model drove: no", so a rescued run is never counted as the model's own success.

## The four jobs

1. **Finding the cause** (`investigate`): the nine failure scenarios (L1, S12, AD1, INV1, S1, S3, S2, S7, S15). Measured per
   run: right cause component, evidence level (confirmed / likely / unconfirmed), right place, seconds, tool calls, tokens,
   cost, and whether the model drove the investigation itself. `--repeat 2` or more also shows whether the answer is the
   same every time.
2. **Reading a plain description** (`scenarios`, the *Add a scenario* page): twelve short texts a shop manager could write.
   Nine should map to one of the simulator's faults, three cannot be simulated and must be refused. Half of the texts
   avoid the keywords of the rule-based fallback on purpose.
3. **Linking a new metric** (`metrics`, the *Agent → Add or edit a metric (SQL)* page): three new metrics. The contender proposes links to
   existing metrics; code then checks each link against 7 days of history (validated = correlation of at least 0.6).

4. **Writing a metric's SQL from a plain description** (`sql`, the *Agent → Add or edit a metric (SQL)* page, "describe it in words"): six wishes
   such as "share of carts that do not become an order". The model writes the SQL (`onboarding.draft_metric`); code runs it
   on 7 days of history and compares the hourly numbers with the SQL a person wrote for the same wish. Only a model can do
   this job: the rules are listed as "not possible".

## How to run it

```powershell
conda activate rootsight
python scripts/compare_models.py --check                                  # every contender answers one word (seconds)
python scripts/compare_models.py --only rules qwen3.5:4b qwen3.5:9b       # traditional method + both local models
python scripts/compare_models.py --only opus sonnet                       # the cloud models (second window is fine)
```

- The tool starts its own Ollama server (port 11435, models from `models/ollama`, context window 12,288 tokens, thinking
  switched off with `{"reasoning_effort": "none"}`) and stops it at the end. Nothing has to be started by hand.
- One progress line per job: percent, done/total, time so far, time left, speed, and what is running right now
  (scenario, contender, tool step). Every finished investigation prints one result line.
- Results are merged: each run replaces only its own contenders in `data/model_comparison/results.json` and rewrites
  `docs/model_comparison_results.md`. Two windows can run at the same time (local models use the GPU, cloud models only
  the network); for clean timing of the 9b model run them one after the other.
- Useful options: `--scenarios L1 AD1`, `--skip scenarios metrics`, `--repeat 2`, `--max-cost 5` (direct cloud keys only).
- Close the Streamlit app while it runs: both are CPU-heavy.

## Known limits of this comparison (say them when presenting)

- **Opus and Sonnet through the Devin CLI are not the raw models.** The CLI has no tool-calling API, so the conversation
  and the tool list are written into one prompt and the model answers with one JSON object. The CLI also adds its own
  instructions around ours and starts one process per model turn. Their times include that overhead, their token counts
  are estimates (characters / 4), and there is no price per token (usage is paid by the Devin plan).
- **Local models run with thinking off** and a 12k context window. Thinking on was not measured.
- **Nine scenarios, one run each by default.** That is a small sample: one scenario is 11 percentage points. Use
  `--repeat` before drawing fine distinctions.
- **Our scenarios are the ones the rules were written for.** The rule recipe is expected to be right on all nine. The
  comparison shows whether a model can do the same without a recipe, not that rules are better in general; a failure
  nobody scripted is where a model should gain, and that is not measured here.

## Results (2026-11-22, one run per scenario)

| Job | rules | qwen3.5:4b (local) | qwen3.5:9b (local) | sonnet (cloud) | opus (cloud) |
|---|---|---|---|---|---|
| 1. Right cause, of 9 failures | 9 | 8 | 9 | 9 | 9 |
| 1. Right cause and all four evidence checks passed | 9 | 6 | 7 | 8 | 9 |
| 1. Average time per investigation | 0.3 s | 22 s | 52 s | 25 s | 38 s |
| 1. Slowest investigation | under 1 s | 37 s | 97 s | 42 s | 55 s |
| 1. Average tool calls | 9.8 | 10.4 | 10.9 | 6.3 | 7.7 |
| 2. Scenario descriptions read correctly, of 12 | 4 | 10 | 10 | 12 | 12 |
| 3. Metric links proposed / passed validation (3 metrics) | 3 / 1 | 5 / 1 | 7 / 1 | 41 / 5 | 75 / 6 |
| 4. SQL from words: runs / right numbers, of 6 | not possible | 5 / 3 | 5 / 2 | 6 / 6 | 6 / 6 |
| Needs | nothing | 8 GB GPU, 3.3 GB download | 8 GB GPU, 6.6 GB download | internet, Devin account | internet, Devin account |
| Cost per use | none | none (electricity) | none (electricity) | paid by the Devin plan, not measured | paid by the Devin plan, not measured |

In every investigation the model drove the work itself: the rule-based fallback was never needed for any model.
Every contender that named a cause also named the right place (country or device).

### Job 1: finding the cause

- **All contenders except the 4b model found all nine causes.** The 4b missed one (L1: it explored and never named a
  cause, so the report said "no cause found").
- **The rules and Opus are the only two with a fully confirmed finding every time.** Sonnet left one finding unconfirmed
  (S7, the recency boost), the 9b two (S2, S7), the 4b three. "Unconfirmed" means the right component was named but the
  model did not gather what the evidence checklist needs (for example it did not test the alternatives), so a person
  reading the report would see "Unconfirmed" where the rules show "Cause confirmed".
- **Speed is the rules' clear advantage:** 0.3 s against 22 to 52 s. For the cloud models part of the time is the Devin
  CLI starting one process per model turn; a direct API would be faster, but this was not measured.
- **The cloud models need fewer steps.** Sonnet used 6.3 tool calls on average and Opus 7.7, against 9.8 for the fixed
  recipe and about 10.5 for the local models. They skip checks that the case at hand does not need; the recipe always
  runs all of them, and the small models wander.
- **Why the rules look so good here:** the recipe was written for exactly these nine failures. This job shows that a
  model can do the same without a recipe (Opus: nine of nine, confirmed). It does not show what happens on a failure
  nobody scripted, where a recipe has nothing to follow. That case was not measured.

### Job 2: reading a plain description

- Keywords (rules): 4 of 12. They refuse six descriptions that do not happen to use their words, and they accept one
  that cannot be simulated.
- Local models: 10 of 12 each. Both wrongly accept "the delivery company lost a week of parcels" as the supplier fault,
  and each confuses the two language faults once.
- Cloud models: 12 of 12, including the three descriptions that must be refused.

### Job 3: linking a new metric

- The cloud models propose many links (Sonnet 41, Opus 75 for three metrics) and five or six pass the correlation
  check. The rules and the local models get one validated link each.
- So the cloud models find more true links, but about nine of ten of their proposals fail validation. That is harmless
  only because every link is checked in code before it is trusted; shown raw, it would be noise.

### Job 4: writing SQL from words

- The rules cannot do this at all.
- Cloud models: 6 of 6 right. Every statement runs and gives the same numbers as the reference.
- Local models: 5 of 6 run, but only 3 (4b) and 2 (9b) are right. The mistakes: a missing bracket, numerator and
  denominator swapped, a wrong column, an invented join. A statement that runs is not a statement that is right.

## Conclusion: when to use which

| Situation | Best choice | Why (from the numbers above) |
|---|---|---|
| Known failure types, an answer at once, no dependency on anything | **Rules** | 9 of 9 confirmed in 0.3 s, free, the same on every run |
| Understanding what a person wrote (Add a scenario) | **Cloud model** | 12 of 12 against 4 of 12 for keywords |
| Writing a metric's SQL from words (Agent → Add or edit a metric (SQL)) | **Cloud model**, with the SQL shown to the person | 6 of 6 right; the rules cannot, the local models are right 2 or 3 times in 6 |
| Proposing links for a new metric | **Cloud model plus the code validation** | 5 to 6 validated links against 1, but only because code filters out the rest |
| A failure nobody wrote a recipe for | **A model as the investigator, rules as the fallback** | Opus matched the rules on all nine without a recipe; unscripted failures were not measured |
| No internet, or data that must not leave the laptop | **qwen3.5:9b** (4b when speed matters more) | 9 of 9 causes locally; weaker on evidence, descriptions and SQL |

What we recommend for the product, and why not one option alone:

- **Rules only** would be fast and free, but could not read plain descriptions (4 of 12) and could not write SQL.
- **A cloud model only** would be right almost everywhere, but takes 25 to 40 seconds per investigation, depends on a
  network and an account, and has a usage cost we could not measure.
- **A local model only** keeps everything on the machine, but is the least reliable on evidence, descriptions and SQL.
- **The combination:** the rules investigate first (instant, deterministic); a model does the language work
  (descriptions, SQL, link proposals, plain wording) and can drive the investigation when no recipe fits; code keeps
  computing the numbers, the evidence checklist and the validation, so a model's mistake is caught and not shown as fact.
  The code is already built this way: every model call has a rule-based fallback.

Between the two cloud models: Opus was the only model with all nine findings confirmed; Sonnet was about a third
faster and equal on jobs 2 and 4. Between the two local models: the 9b found one more cause, the 4b is more than twice
as fast and fits fully on the GPU.

## What these results do not show

- One run per scenario. One scenario is 11 percentage points, so "8 of 9" against "9 of 9" is one case, not a trend.
  `--repeat 3` would show how stable each model is; this was not run.
- The cloud models ran through the Devin CLI, not a raw API (see the limits above). Their times and token counts are
  not comparable with a direct API call, and no price was measured.
- Local timings were taken while the dashboard was open for about two minutes of the run, so single values can be high.
- The nine failures are the ones the rules were written for, and the twelve descriptions and six SQL wishes were
  written by us; half of the descriptions avoid the rules' keywords on purpose.
- The app itself still runs with `LLM_MODE=offline`. Which model the stage demo uses is a separate decision.
