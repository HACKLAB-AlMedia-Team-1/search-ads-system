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

**Monitoring is live from the first page load.** The simulated clock (shown in the sidebar) starts by itself and never pauses: one simulated
hour every 2 seconds. There is no start or stop button and no "+1 hour" button. The healthy shop runs all the time, so the KPI tiles, the
charts and the Control room keep updating also when no simulation runs.

To stop the app: press `Ctrl+C` in the terminal.

**Every start is a clean start.** Everything goes back to the 14 normal days in exactly two cases: the app is started again, or
**Reset demo** (sidebar) is pressed. (Faults only exist while the app runs, so keeping old incidents would be misleading.)

| A reset clears | A reset keeps (on purpose) |
|---|---|
| The database: it is restored from `data/rootsight.backfill.duckdb`, so incidents, cases, anomalies and store events are gone | Scenarios you wrote yourself (`scenarios/<ID>.yaml`) |
| Metrics you added (`data/metrics_custom.yaml`) | Edits to built-in metrics (`rootsight/graph/metrics.yaml`) |
| Everything in memory: all faults, the search-result cache, the watcher's caches, the ad pacing state | The search index files `data/processed/index_*.pkl` (built once from the products) |
| | The store tab's own browser settings (country, light/dark) |

The folder `data/cache/` holds only the optional Linkup web-answer cache. It is empty while `LINKUP_MODE=offline`.

---

## 3. Run the demo (the shopper journey)

Open the dashboard. You are on the **Shopper journey** page. The clock is already running (see section 2).
*Clock speed* above the tiles is the only clock control: Slow (3 s), Normal (2 s, the default) or Fast (1 s of real time per simulated hour).

1. *Demo step* (under the KPI tiles) opens on **Step 1**. You can pick **Step 2**, **Step 3** or **All steps**; the page remembers your choice
   while you visit other pages (a browser refresh starts again on Step 1).
2. In **Step 1 - Foreign-language searches fail**, press **Simulate it**. The failure is injected into the running stream, in the country
   the store "Deliver to" is set to (Germany: English searches fail; US: German searches fail). Every simulation starts from a normal shop:
   the ad budget is put back on plan at this moment too.
3. The step's chart appears. Per hour it shows the share of searches that found products in the broken country (orange) against the normal
   share for that hour of day from the 14 clean days (grey dotted). It runs from 6 hours before Simulate up to now (at most the last
   72 hours) and has dashed markers at *Simulate it* and *End Simulation*. The orange line drops while the failure lasts (about one search
   in five is in the other language), drops further when you search something that finds nothing, rises a little when your search finds
   products, and returns to the normal line after End Simulation.
4. Press **See it in the store** to look as a shopper. The store tab reloads by itself when a simulation starts or ends, or when the store
   would look different. What you do there counts in the monitored numbers: each search, empty result, add-to-cart, blocked add-to-cart
   and order of yours is counted in the simulated hour that is running, on the organic traffic of your country and device. One action stands
   for 100 shoppers, but never more than a tenth of that hour's shoppers on the same device (and at least 1). So your action is clearly
   visible without drowning the simulated crowd. The number of searches stays the same, so nothing looks like a traffic spike: a search of
   yours that finds nothing means that crowd of the hour's shoppers found nothing too (the zero-result rate rises by up to 10 points); a
   search that finds products means a crowd that would have found nothing found products instead. Their clicks, carts and orders follow in
   proportion. Cart and order actions add carts and orders. The step also lists your own counts under *Your store activity*.
5. *What the agent found (live)* updates every second: hours since the fault, the anomaly it saw, the case it opened, the checks so far.
   When the agent is sure, the finding replaces it: a plain-language summary, the cause, where, since when, the **Cost so far** (only the
   costs that apply; it keeps growing while the fault lasts), the **Failed check** (why it failed, expected vs. received value, and the query),
   the **Possible next action**, the evidence checklist, the ruled-out causes, and *How the agent investigated*.
6. In *How the agent investigated* every step is one **tool** the agent used (`get_metric`, `drill_down`, ...; these are tools, not metrics).
   A step shows the tool name (bold, orange, monospace), why the agent used it, and one plain sentence with what it found, for example
   "zero_result_rate was 19.7% in the latest hour against a normal 0.0%; unusual since 2026-11-21 09:00." or "market = DE explains 97.3%
   of the change". Under it is one collapsed query in quiet grey: the step's main query, named after the metric or table, its segment and
   hours, with its row count (for example `zero_result_rate by market · 21 Nov 09:00 to 21 Nov 10:00 · 4 rows`). Open it to see its SQL and
   the rows it returned; the rows were saved when the agent ran the query, nothing is run again. The tool's raw JSON answer and its helper
   queries (calendar, data arrivals, earlier days) are not shown.
7. The simulation never ends by itself (only the late-data scenario DQ1 keeps its single late hour). Press **End Simulation**: the failure
   is switched off and the store is repaired at once (search cache emptied, top sellers restocked, ad budget back on plan). Nothing else
   happens by hand. Monitoring keeps running, so the agent itself sees the numbers recover and closes the incident after three normal hours
   that could be judged: about 6 seconds at Normal speed in daytime. Quiet night hours with too few shoppers do not count. The simulated
   night (01:00 to 06:59) is passed without waiting, about half a second per hour, and a failure you start at night switches on at 07:00,
   a few seconds later (the step says so). Until then the step shows the incident as *open*, with the note "The failure is switched off. The agent closes the
   incident once it has seen three normal hours." An incident whose cause was fixed with End Simulation is never reopened: the same failure
   simulated again is a new incident with a fresh report.
8. Repeat with **Step 2** and **Step 3** (top sellers out of stock). The Step 2 chart shows the whole simulated day from 00:00 to 24:00:
   cumulative ad spend vs. planned spend vs. the fixed €250 budget, with markers where you pressed Simulate it and End Simulation. If you
   end Step 2 and simulate it again on the same simulated day, the "actual spend" line starts on the plan line again and the rest of the
   day's €250 budget is available again: the overspend of the earlier simulation is not carried over.

What you should see:

| Step | In the store | Agent should blame |
|---|---|---|
| 1. Other-language search | Germany: "headphones" finds nothing; US: "kopfhörer" finds nothing | config `search-language[DE] = local only` |
| 2. Ad budget | The sponsored product at the top disappears once the budget is spent; a yellow note says so | release `pacing-service 1.4.0` |
| 3. Out of stock | The products with the **Bestseller** badge (also the sponsored one, if it is one) show "Derzeit nicht verfügbar" and cannot be added; checkout refuses items that sold out after they were added | overdue purchase order (`goods-receiving`) |

Top sellers are the products that exactly match the 100 most-searched queries of a country. They are the products a supplier delivery
replenishes, so step 3 empties exactly them. The store shows why a product is a top seller: `#1 Best Seller in "<search>" · 5,000+ sold`
(the search it is a top seller for, and its rank inside that search by units sold), plus the **Best Seller** badge. Every other product
shows a small sold count ("50+ sold").

Tips:

- Step 2 is easiest to see in the simulated morning (simulated time is in the sidebar): the campaign then spends about €25 per hour, the
  €250 budget is gone about nine simulated hours later (roughly 20 seconds at Normal speed), and the sponsored product disappears from
  the open store tab by itself. Pressed at night, the failure starts at 07:00. The clock does not wait for you.
- Several simulations can run together, but the reports are clearer one at a time.
- The sidebar always shows the simulated time (live) and which simulations are running. **End all simulations** ends every running
  simulation; monitoring keeps running.
- A problem that cannot be measured for a while (too few shoppers at night) stays open: only hours with enough data count as "normal again".
- Your own store actions are part of the monitored numbers. Several empty searches of yours in one simulated hour can raise an alert even
  when no simulation runs. This is expected.
- **Reset demo** (sidebar) goes back to the clean 14 days. Section 2 lists what it clears and what it keeps.

---

## 4. The other pages

| Page | What to do there |
|---|---|
| **All scenarios** | Every scenario explained in plain words, with a Simulate it / End Simulation button and the *Clock speed* choice. The second tab has the two innocent changes (planned campaign, late data) that must NOT create an incident; the third tab, *Your scenarios*, has the ones you wrote. |
| **Control room** | Live all the time, also when no simulation runs: the key numbers against what is expected (green / amber / red), a chart with the expected range, alerts and the latest finding. Filter by country. It has the *Clock speed* choice too. |
| **Incidents** | One row per problem. Pick one to read the full report or download it. |
| **Metric graph** | Pick a metric to see what feeds into it. Red = unusual right now. |
| **Add or edit a metric** | Both tabs have the same three fields: name, description, SQL. *Add a metric*: type them (for example name `no_click_search_rate`, SQL `(SUM(searches) - SUM(searches_with_click)) / NULLIF(SUM(searches), 0) FROM fact_hourly`), press **Place it in the graph**. The system proposes the links and checks them on history; weak links are marked "Needs a human look". *Edit a metric*: the name is a dropdown of every metric (built-in too); change its description or SQL, press **Save the change**. The SQL is run on 7 days of history, the metric's links are re-checked, and the change is written to `rootsight/graph/metrics.yaml` (built-in) or `data/metrics_custom.yaml` (added). |
| **Add a scenario** | Write the title, an id, what breaks, where, and what a shopper sees; press **Let the agent check it**. The agent picks the matching failure the simulator can produce and writes what the numbers will do and what the agent should do. **Save the scenario** writes `scenarios/<ID>.yaml`; it appears on *All scenarios → Your scenarios*. If no simulator failure matches (or the country/device is not possible), you get the reason instead. |

In the store you can also switch the country (top left), the device (Web / Android app / iOS app) and light/dark mode (moon button).
For example: simulate **S3** on *All scenarios*, then set the device to "Android app" in the store and search: no results on Android only.

What else the store shows:

- Home page: a "Black Friday Week" banner ("Up to 40% off", a countdown to midnight, three perks) and a "Best sellers" row.
- Some products show a strike-through list price and a discount badge.
- Cart: adding the same product again raises its quantity instead of adding a second row. The cart has - and + buttons; the order total
  and the cart counter use the quantities.
- Product pictures are drawn by the app itself (see "Good to know").

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
| `pytest -q` | Search engine, simulator, metric graph, new-metric onboarding, metric edits, user-written scenarios, SQL display, config | ~1-3 min | all pass (the last line says `passed`, no `failed`) |
| `pytest -m integration` | Every scenario end to end: found, traced to the right cause, one incident, then resolved; innocent changes raise no incident | ~2-6 min | all pass |
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
| An alert although no simulation runs | Your own store actions count as shoppers (one action = 100). Several empty searches in one simulated hour look like a real problem. The incident closes by itself after three normal hours, or press **Reset demo**. |
| The incident is still "open" after End Simulation | This is expected: the agent closes it after three normal hours (about 6 seconds at Normal speed; longer at night, when quiet hours do not count). |
| A scenario I wrote is still there after Reset demo | On purpose. Delete its file `scenarios/<ID>.yaml`, then restart the app or press **Reset demo** again. |
| `conda` or `streamlit` not recognized | Use Anaconda Prompt and run `conda activate rootsight` first. |

---

## Good to know

- The German store is a demo: US products with search words translated word by word. Product titles stay in English.
- No AI model runs by default (`LLM_MODE=offline`): the investigator, the plain-language wording and the scenario check are rule-based code. With `LLM_MODE=live` and an OpenAI-compatible endpoint in `.env`, the agent model drives the investigation, the fast model rewrites findings (numbers must come from the tools) and reads your scenarios; any failure falls back to the rules.
- Prices, stock, ratings, ads and shoppers are simulated. Products, search queries and relevance labels are real Amazon data.
- Sold counts, review counts, list prices and discounts in the store are made up, but fixed per product: a product shows the same numbers
  on every visit. Review counts follow the sold numbers.
- Product pictures are drawn in code as SVG (`app/pictures.py`): no photos, no people, nothing downloaded. The product type is read from
  the product noun in the title (so "Lightweight ... Pants" shows pants, not a lamp). The picture uses the product's own colours, its pack
  size and small per-product variations, so two products of one type look different. Why drawn: the dataset has no images; Amazon's image
  server returns a blank pixel for product ids (only books work); a keyword photo service (loremflickr) answered with errors; free-licence
  photos from Wikimedia Commons often show people.
- Your own actions in the store count in the monitored numbers: one action stands for 100 shoppers, at most a tenth of that
  hour's shoppers on the same device. The number of searches does not change; a crowd moves between "found products" and "found nothing".
