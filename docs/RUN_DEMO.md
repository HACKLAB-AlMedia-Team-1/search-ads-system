# How to run and test the RootSight demo

Everything runs on your laptop. No account, no API key, nothing to pay.
All commands are for **Anaconda Prompt** (or PowerShell) on Windows.

---

## 1. One-time setup

Skip any step you have already done.

```bat
cd /d D:\hacklab-almedia
conda activate rootsight
python scripts/check_env.py
```

`check_env.py` must end with `All checks passed.` If it does not, follow `SETUP.md`.

Then build the data (only needed once, or after the code that creates data has changed):

```bat
python scripts/prepare_data.py
python scripts/backfill.py --force
```

| Command | What it does | Time |
|---|---|---|
| `prepare_data.py` | Picks the products and search queries from the Amazon dataset | ~10 s |
| `backfill.py --force` | Simulates 14 normal days so the system knows what "normal" looks like | ~2 min |

---

## 2. Start the app

```bat
cd /d D:\hacklab-almedia
conda activate rootsight
streamlit run app/Home.py
```

Wait for `You can now view your Streamlit app in your browser`, then open:

| What | Address |
|---|---|
| Dashboard (monitoring, demo controls) | http://localhost:8501 |
| ShopLens store (what a shopper sees) | http://localhost:8600 |

The first page load takes about 20-30 seconds (the search engine is loading). The store only works while the dashboard is running.

To stop the app: press `Ctrl+C` in the terminal.

**Every start is a clean start.** When the app launches it goes back to the 14 normal days: incidents, injected faults and added metrics from the previous run are gone. (Faults only exist while the app runs, so keeping old incidents would be misleading.)

---

## 3. Run the demo (the shopper journey)

Open the dashboard. You are on the **Shopper journey** page.

1. Under the KPI tiles, pick **Step 1**, **Step 2**, **Step 3** or **All steps** in *Demo step*.
2. In **Step 1 - Foreign-language searches fail**, press **Simulate it**. The fault starts in the country the store "Deliver to" is set to
   (Germany: English searches fail; US: German searches fail), and the clock starts at one simulated hour per second (*Fast*).
3. The step's chart appears: cumulative expected orders from searches in the failing language against the orders received (flat while it is broken).
4. *What the agent found (live)* updates every second: hours since the fault, the anomaly it saw, the case it opened, the checks so far.
   When the agent is sure, the finding replaces it: a plain-language summary, the cause, where, since when, the cost, the **Failed check**
   (SQL, tables, expected vs. received value, why it failed), the **Possible next action**, the evidence checklist, the ruled-out causes,
   and *How the agent investigated* with the SQL each step ran.
5. Press **See it in the store** to look as a shopper. Press **Fix it** and let about 4 simulated hours pass so the incident closes.
6. Repeat with **Step 2** (chart: cumulative ad spend vs. planned spend vs. the fixed €250 budget) and **Step 3** (top sellers out of stock).
   You can still use **Start the clock**, **+1 hour** / **+6 hours** and the speed choice at any time.

What you should see:

| Step | In the store | Agent should blame |
|---|---|---|
| 1. Other-language search | Germany: "headphones" finds nothing; US: "kopfhörer" finds nothing | config `search-language[DE] = local only` |
| 2. Ad budget | The sponsored product at the top disappears once the budget is spent; a yellow note says so | release `pacing-service 1.4.0` |
| 3. Out of stock | Products (also the sponsored one) show "Derzeit nicht verfügbar" and cannot be added; checkout refuses items that sold out after they were added | overdue purchase order (`goods-receiving`) |

Tips:

- Step 2 is easiest to see if you simulate it shortly after midnight (simulated time is in the sidebar) and then press **+6 hours** twice. The budget is gone by about 10:00.
- Leave a few simulated hours between steps. If two failures overlap, the reports are less clear.
- The sidebar always shows the simulated time and which faults are active. **Fix all faults** ends everything.
- **Reset demo** (sidebar) removes all incidents and goes back to the clean 14 days.

---

## 4. The other pages

| Page | What to do there |
|---|---|
| **All scenarios** | Every scenario explained in plain words, with a Simulate it / Fix it button. The second tab has the two innocent changes (planned campaign, late data) that must NOT create an incident; the third tab, *Your scenarios*, has the ones you wrote. |
| **Control room** | The key numbers against what is expected (green / amber / red), a chart with the expected range, alerts and the latest finding. Filter by country. |
| **Incidents** | One row per problem. Pick one to read the full report or download it. |
| **Metric graph** | Pick a metric to see what feeds into it. Red = unusual right now. |
| **Add or edit a metric** | *Add a metric*: pick an example, press **Place it in the graph**. The system proposes the links and checks them on history; weak links are marked "Needs a human look". *Edit a metric*: pick any metric (built-in too), change its description or SQL, press **Save the change**. The SQL is run on 7 days of history, the metric's links are re-checked, and the change is written to `rootsight/graph/metrics.yaml` (built-in) or `data/metrics_custom.yaml` (added). |
| **Add a scenario** | Write the title, an id, what breaks, where, and what a shopper sees; press **Let the agent check it**. The agent picks the matching failure the simulator can produce and writes what the numbers will do and what the agent should do. **Save the scenario** writes `scenarios/<ID>.yaml`; it appears on *All scenarios → Your scenarios*. If no simulator failure matches (or the country/device is not possible), you get the reason instead. |

In the store you can also switch the country (top left), the device (Web / Android app / iOS app) and light/dark mode (moon button).
For example: break **S3** on *All scenarios*, then set the device to "Android app" in the store and search: no results on Android only.

---

## 5. Terminal demo (no browser)

```bat
python scripts/demo.py
```

Plays the whole story in about 2 minutes and prints every alert and report: a planned campaign (no incident), the three journey steps,
two new metrics, and one more failure. It works on its own copy of the data, so it never changes the app's database.
Do not run it while the app is running if your laptop is slow; both are CPU-heavy.

---

## 6. Run the tests

Stop the app first (`Ctrl+C`), then:

```bat
pytest -q
pytest -m integration
ruff check .
python scripts/smoke_ui.py
```

| Command | What it checks | Time | Expected |
|---|---|---|---|
| `pytest -q` | Search engine, simulator, metric graph, new-metric onboarding, metric edits, user-written scenarios, SQL display, config | ~3 min | `38 passed` |
| `pytest -m integration` | Every scenario end to end: found, traced to the right cause, one incident, then resolved; innocent changes raise no incident | ~6 min | 17 tests; `L1` currently fails (an extra wasted-ad-spend incident after the fix; also fails on the unchanged Test_N code) |
| `ruff check .` | Code style | seconds | `All checks passed!` |
| `python scripts/smoke_ui.py` | Every dashboard page renders without an error | ~1 min | seven lines starting with `ok` |

`smoke_ui.py` uses the real database; the app resets it on its next start anyway.

---

## 7. If something goes wrong

| Problem | Fix |
|---|---|
| `Port 8501 is already in use` | An old copy is still running. Close its terminal, or run `streamlit run app/Home.py --server.port 8502`. |
| The store page does not open | The dashboard must be running, and port 8600 must be free. Restart the app. |
| Page stays empty for a long time | First load takes 20-30 s. Refresh the browser once. |
| Error mentioning a missing table or column | The data is from an older version. Stop the app and run `python scripts/backfill.py --force`. |
| `rootsight.duckdb` is "being used by another process" | Stop the app before running `backfill.py` or the tests. |
| Strange numbers or old incidents | Press **Reset demo**, or simply restart the app (every start is clean). |
| `conda` or `streamlit` not recognized | Use Anaconda Prompt and run `conda activate rootsight` first. |

---

## Good to know

- The German store is a demo: US products with search words translated word by word. Product titles stay in English.
- No AI model runs by default (`LLM_MODE=offline`): the investigator, the plain-language wording and the scenario check are rule-based code. With `LLM_MODE=live` and an OpenAI-compatible endpoint in `.env`, the agent model drives the investigation, the fast model rewrites findings (numbers must come from the tools) and reads your scenarios; any failure falls back to the rules.
- Prices, stock, ratings, ads and shoppers are simulated. Products, search queries and relevance labels are real Amazon data.
