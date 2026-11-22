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

1. *Demo step* (under the KPI tiles) opens on **Step 1**. You can pick **Step 2**, **Step 3** or **All steps**; the page remembers your choice
   while you visit other pages (a browser refresh starts again on Step 1).
2. In **Step 1 - Foreign-language searches fail**, press **Simulate it**. The fault starts in the country the store "Deliver to" is set to
   (Germany: English searches fail; US: German searches fail), and the simulated clock starts: one hour every 2 seconds (*Normal*).
   *Simulation speed* above the tiles switches between Slow (3 s), Normal (2 s) and Fast (1 s). There is no other clock button: the clock
   only runs between **Simulate it** and **End Simulation**.
3. The step's chart appears: cumulative expected orders from searches in the failing language against the orders received (flat while it is broken).
4. Press **See it in the store** to look as a shopper. The store tab reloads by itself when a simulation starts, ends or changes what the
   store shows. What you do there (searches, empty results, no sponsored product, blocked add-to-cart, orders) is counted in the step under
   *Your store activity*. These are your own actions only; the monitored numbers stay the simulated shoppers.
5. *What the agent found (live)* updates every second: hours since the fault, the anomaly it saw, the case it opened, the checks so far.
   When the agent is sure, the finding replaces it: a plain-language summary, the cause, where, since when, the **Cost so far** (only the
   costs that apply; it keeps growing while the fault lasts), the **Failed check** (why it failed, expected vs. received value, and the query),
   the **Possible next action**, the evidence checklist, the ruled-out causes, and *How the agent investigated*.
6. In *How the agent investigated* every step is one **tool** the agent used (`get_metric`, `drill_down`, ...; these are tools, not metrics).
   A tool runs several queries: the metric itself, the calendar check, the data-arrival check, the same hour on earlier days. Each query is
   listed by name with its row count (for example `zero_result_rate by market · 21 Nov 09:00 to 21 Nov 10:00 · 4 rows`). Click a name to open
   its SQL and the rows it returned; the rows were saved when the agent ran the query, nothing is run again.
7. The simulation never ends by itself. Press **End Simulation**: the fault is switched off, the store is repaired at once (search cache
   emptied, top sellers restocked, ad budget back on plan), the incident is closed as *resolved*, and the clock stops.
8. Repeat with **Step 2** (chart: the whole simulated day from 00:00 to 24:00 with cumulative ad spend vs. planned spend vs. the fixed €250 budget
   and a marker where you pressed Simulate it) and **Step 3** (top sellers out of stock).

What you should see:

| Step | In the store | Agent should blame |
|---|---|---|
| 1. Other-language search | Germany: "headphones" finds nothing; US: "kopfhörer" finds nothing | config `search-language[DE] = local only` |
| 2. Ad budget | The sponsored product at the top disappears once the budget is spent; a yellow note says so | release `pacing-service 1.4.0` |
| 3. Out of stock | The products with the **Bestseller** badge (also the sponsored one, if it is one) show "Derzeit nicht verfügbar" and cannot be added; checkout refuses items that sold out after they were added | overdue purchase order (`goods-receiving`) |

Top sellers are the products that exactly match the 100 most-searched queries of a country. In the store they carry a **Best Seller** badge and
many good reviews; they are the products a supplier delivery replenishes, so step 3 empties exactly them.

Tips:

- Step 2 is easiest to see if you simulate it shortly after midnight (simulated time is in the sidebar): the budget is gone by about 10:00,
  about 20 seconds later at Normal speed, and the sponsored product disappears from the open store tab by itself.
- Several simulations can run together, but the reports are clearer one at a time. The clock stops when the last one is ended.
- The sidebar always shows the simulated time and which simulations are running. **End all simulations** ends everything.
- A problem that cannot be measured for a while (too few shoppers at night) stays open: only hours with enough data count as "normal again".
- **Reset demo** (sidebar) removes all incidents and goes back to the clean 14 days.

---

## 4. The other pages

| Page | What to do there |
|---|---|
| **All scenarios** | Every scenario explained in plain words, with a Simulate it / End Simulation button and the speed choice. The second tab has the two innocent changes (planned campaign, late data) that must NOT create an incident; the third tab, *Your scenarios*, has the ones you wrote. |
| **Control room** | The key numbers against what is expected (green / amber / red), a chart with the expected range, alerts and the latest finding. Filter by country. |
| **Incidents** | One row per problem. Pick one to read the full report or download it. |
| **Metric graph** | Pick a metric to see what feeds into it. Red = unusual right now. |
| **Add or edit a metric** | Both tabs have the same three fields: name, description, SQL. *Add a metric*: type them (for example name `no_click_search_rate`, SQL `(SUM(searches) - SUM(searches_with_click)) / NULLIF(SUM(searches), 0) FROM fact_hourly`), press **Place it in the graph**. The system proposes the links and checks them on history; weak links are marked "Needs a human look". *Edit a metric*: the name is a dropdown of every metric (built-in too); change its description or SQL, press **Save the change**. The SQL is run on 7 days of history, the metric's links are re-checked, and the change is written to `rootsight/graph/metrics.yaml` (built-in) or `data/metrics_custom.yaml` (added). |
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
| `pytest -q` | Search engine, simulator, metric graph, new-metric onboarding, metric edits, user-written scenarios, SQL display, config | ~1-3 min | `42 passed` |
| `pytest -m integration` | Every scenario end to end: found, traced to the right cause, one incident, then resolved; innocent changes raise no incident | ~2-6 min | `18 passed` |
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
