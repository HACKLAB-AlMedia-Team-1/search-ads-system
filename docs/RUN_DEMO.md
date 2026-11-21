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

---

## 3. Run the demo (the shopper journey)

Open the dashboard. You are on the **Shopper journey** page.

1. Press **Start the clock**. One simulated hour passes every few seconds (choose Slow / Normal / Fast).
   Instead of the clock you can also press **+1 hour** or **+6 hours** (pause the clock first).
2. In **Step 1 - German search returns nothing**, press **Break it**.
3. Press **See it in the store**. The store opens on the search "kopfhörer" in Germany and shows no results.
4. Go back to the dashboard and wait 1-3 simulated hours. The agent's finding appears inside the step:
   the cause, where, since when, the cost, the evidence checklist, the explanations it ruled out and the steps it took.
5. Press **Fix it**. Let about 4 simulated hours pass so the incident closes.
6. Repeat with **Step 2** (ad budget) and **Step 3** (top sellers out of stock).

What you should see:

| Step | In the store | Agent should blame |
|---|---|---|
| 1. German search | "Keine Ergebnisse für kopfhörer" | config `search-analyzer[DE] = english` |
| 2. Ad budget | The sponsored product at the top disappears once the budget is spent; a yellow note says so | release `pacing-service 1.4.0` |
| 3. Out of stock | Products show "Derzeit nicht verfügbar" and cannot be added to the cart | overdue purchase order (`goods-receiving`) |

Tips:

- Step 2 is easiest to see if you break it shortly after midnight (simulated time is in the sidebar) and then press **+6 hours** twice. The budget is gone by about 10:00.
- Leave a few simulated hours between steps. If two failures overlap, the reports are less clear.
- The sidebar always shows the simulated time and which faults are active. **Fix all faults** ends everything.
- **Reset demo** (sidebar) removes all incidents and goes back to the clean 14 days.

---

## 4. The other pages

| Page | What to do there |
|---|---|
| **All scenarios** | Every scenario explained in plain words, with a Break it / Fix it button. The second tab has the two innocent changes (planned campaign, late data) that must NOT create an incident. |
| **Control room** | The key numbers against what is expected (green / amber / red), a chart with the expected range, alerts and the latest finding. Filter by country. |
| **Incidents** | One row per problem. Pick one to read the full report or download it. |
| **Metric graph** | Pick a metric to see what feeds into it. Red = unusual right now. |
| **Add a metric** | Pick an example, press **Place it in the graph**. The system proposes the links and checks them on history; weak links are marked "Needs a human look". |

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
| `pytest -q` | Search engine, simulator, metric graph, new-metric onboarding, config | ~1 min | `31 passed` |
| `pytest -m integration` | Every scenario end to end: found, traced to the right cause, one incident, then resolved; innocent changes raise no incident | ~3 min | `16 passed` |
| `ruff check .` | Code style | seconds | `All checks passed!` |
| `python scripts/smoke_ui.py` | Every dashboard page renders without an error | ~1 min | six lines starting with `ok` |

`smoke_ui.py` uses the real database. Afterwards, restore the clean state with **Reset demo** in the app or the copy command in section 7.

---

## 7. If something goes wrong

| Problem | Fix |
|---|---|
| `Port 8501 is already in use` | An old copy is still running. Close its terminal, or run `streamlit run app/Home.py --server.port 8502`. |
| The store page does not open | The dashboard must be running, and port 8600 must be free. Restart the app. |
| Page stays empty for a long time | First load takes 20-30 s. Refresh the browser once. |
| Error mentioning a missing table or column | The data is from an older version. Stop the app and run `python scripts/backfill.py --force`. |
| `rootsight.duckdb` is "being used by another process" | Stop the app before running `backfill.py` or the tests. |
| Strange numbers or old incidents | Press **Reset demo**, or stop the app and run: `copy /Y data\rootsight.backfill.duckdb data\rootsight.duckdb` |
| `conda` or `streamlit` not recognized | Use Anaconda Prompt and run `conda activate rootsight` first. |

---

## Good to know

- The German store is a demo: US products with search words translated word by word. Product titles stay in English.
- No AI model runs by default (`LLM_MODE=offline`): the investigator is rule-based code. An open-source model through Ollama is optional and not yet tried.
- Prices, stock, ratings, ads and shoppers are simulated. Products, search queries and relevance labels are real Amazon data.
