"""Compare who should drive the agent: the rule-based investigator, local models (Ollama) and cloud models.

Every contender gets exactly the same cases (the simulation and the watcher run once per scenario), the same tools
and the same evidence checklist. Four jobs are measured:

  1. investigate   find the first cause of each failure scenario (right component? evidence level? time? tokens?)
  2. scenarios     turn a shop manager's plain description into the right simulator fault ("Add a scenario" page)
  3. metrics       propose graph links for a new metric; links are then validated in code ("Add a metric" page)
  4. sql           write a metric's SQL from a plain description; it must run and give the reference numbers
                   (only a model can do this: the rules are listed as "not possible")

Usage (PowerShell, conda env `rootsight`):
  python scripts/compare_models.py                      # rules + the local models; cloud models too if a key is set
  python scripts/compare_models.py --only rules qwen3.5:4b --scenarios L1 AD1
  python scripts/compare_models.py --cloud anthropic/claude-opus-5.5 anthropic/claude-haiku-5.5 --max-cost 5

Local models: the script starts its own Ollama server on port 11435 (models from `models/ollama`, a context window
large enough for an investigation) and stops it again. Cloud models use LLM_BASE_URL + LLM_API_KEY from `.env`.
`LLM_MODE` in `.env` is not touched. Results: `data/model_comparison/results.json` (merged run after run) and the
tables in `docs/model_comparison_results.md`.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx
import numpy as np
from tqdm import tqdm

from rootsight.agent.investigator import Investigator
from rootsight.agent.llm import DEVIN_CLI, LLMClient, LLMUnavailable
from rootsight.agent.report import plain_summary
from rootsight.config import Settings, load_settings
from rootsight.graph import onboarding
from rootsight.graph.graph import MetricGraph
from rootsight.logging_setup import setup_logging
from rootsight.pipeline import Pipeline
from rootsight.sim import faults as F
from rootsight.sim.clock import HOUR
from rootsight.sim.custom import draft_scenario
from rootsight.sim.faults import load_scenarios
from rootsight.store.db import Database

FAILURES = ("L1", "S12", "AD1", "INV1", "S1", "S3", "S2", "S7", "S15")
LOCAL_MODELS = ("qwen3.5:4b", "qwen3.5:9b")
CLOUD_MODELS = ("anthropic/claude-opus-5.5", "anthropic/claude-haiku-5.5")
DEVIN_CLI_MODELS = ("opus", "sonnet")  # when LLM_BASE_URL=devin-cli (a Devin account instead of a model API key)
DEVIN_KEYS = ("apk_", "cog_")  # Devin's own keys: they cannot call a model and are never sent to another provider
LOCAL_PORT, LOCAL_CONTEXT = 11435, 12288
START_HOUR, MAX_FAULT_HOURS = 10, 8
# one live line per job: done/total, percent, time so far < time left, speed, and what is running right now
BAR = {"dynamic_ncols": True, "smoothing": 0, "mininterval": 0.3,
       "bar_format": "{desc} {percentage:3.0f}% |{bar}| {n_fmt}/{total_fmt} [{elapsed} so far, {remaining} left, {rate_fmt}{postfix}]"}  # fmt: skip
OUT_DIR, REPORT = ROOT / "data" / "model_comparison", ROOT / "docs" / "model_comparison_results.md"

# A shop manager's words -> the fault the simulator should produce (None = cannot be simulated, must be refused).
# Half of them avoid the words of the keyword fallback on purpose: that is what a language model is for.
DESCRIPTIONS = [
    ("Customers who type English words in our German shop get an empty page since this morning.", "Germany", "An empty results page.", F.FOREIGN_LANGUAGE_BLOCKED),
    ("The newest items are shown first even when they barely match what people look for.", "all markets", "Good matches sit far down the page.", F.RANKING_BOOST_RECENCY),
    ("People using the Android app see no products at all after yesterday's app update.", "all markets", "The app says no results.", F.ANDROID_FILTER_NULL),
    ("About half of our catalogue seems to have vanished: shoppers look for things we sell and we do not show them.", "all markets", "Fewer products than usual.", F.PARTIAL_INDEX),
    ("Shoppers see one amount on the results page and a different amount when they open the product.", "all markets", "The amount changes after the click.", F.CACHE_STALE),
    ("Our marketing money for the day is used up before lunch.", "Spain", "The promoted product at the top is gone in the afternoon.", F.AD_PACING_RUNAWAY),
    ("The truck with our most popular products never reached the warehouse.", "Japan", "The popular products cannot be bought.", F.SUPPLIER_DELIVERY_LATE),
    ("What we show has nothing to do with what the customer typed.", "all markets", "Random-looking products.", F.RANKER_V2_IRRELEVANT),
    ("Spanish words with accents no longer bring up any product in the Spanish store.", "Spain", "An empty page for normal Spanish words.", F.REGIONAL_ANALYZER_ENGLISH),
    ("The card payment provider rejects every credit card at checkout.", "Germany", "Payment fails.", None),
    ("Every page of the website takes ten seconds to load.", "all markets", "Shoppers wait and leave.", None),
    ("The delivery company lost a week of parcels, customers complain by email.", "Spain", "Orders arrive late.", None),
]  # fmt: skip
# A plain wish -> the SQL a person would write for it. A model's SQL counts as right when it runs on 7 days of history
# and gives the same hourly numbers as this reference (the wording of the SQL may differ).
SQL_WISHES = [
    ("Share of searches that end without any click", "(SUM(searches) - SUM(searches_with_click)) / NULLIF(SUM(searches), 0) FROM fact_hourly"),
    ("Average revenue per order in euros", "SUM(revenue_eur) / NULLIF(SUM(orders), 0) FROM fact_hourly"),
    ("Share of carts that do not become an order", "(SUM(carts) - SUM(orders)) / NULLIF(SUM(carts), 0) FROM fact_hourly"),
    ("What we pay per paid ad click, in euros", "SUM(spend_eur) / NULLIF(SUM(paid_clicks), 0) FROM ads_hourly"),
    ("Orders per session, counting only visitors who came through paid ads", "SUM(orders) / NULLIF(SUM(sessions), 0) FROM fact_hourly WHERE source = 'paid'"),
    ("Share of searches on the Android app that found nothing", "SUM(zero_result_searches) / NULLIF(SUM(searches), 0) FROM fact_hourly WHERE platform = 'android'"),
]  # fmt: skip
NEW_METRICS = [
    ("no_click_search_rate", "Share of searches without a click",
     "(SUM(searches) - SUM(searches_with_click)) / NULLIF(SUM(searches), 0) FROM fact_hourly"),
    ("cart_abandon_rate", "Share of carts that do not become an order",
     "(SUM(carts) - SUM(orders)) / NULLIF(SUM(carts), 0) FROM fact_hourly"),
    ("revenue_per_search", "Revenue earned per search", "SUM(revenue_eur) / NULLIF(SUM(searches), 0) FROM fact_hourly"),
]  # fmt: skip


@dataclass
class Contender:
    """One way to drive the agent: the rules, a local model or a cloud model."""

    name: str
    kind: str  # rules | local | cloud
    settings: Settings
    price_in: float | None = None  # USD per token (cloud only)
    price_out: float | None = None
    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    seconds: float = 0.0
    notes: list[str] = field(default_factory=list)

    def client(self) -> LLMClient:
        """A model client that counts every call, its tokens and its time for this contender."""
        llm = LLMClient(self.settings, None)
        post = llm._post

        def counted(role: str, messages: list[dict], tools: list[dict] | None) -> tuple[dict, dict]:
            started = time.perf_counter()
            try:
                message, usage = post(role, messages, tools)
            finally:
                self.calls, self.seconds = self.calls + 1, self.seconds + time.perf_counter() - started
            self.tokens_in += int(usage.get("prompt_tokens") or 0)
            self.tokens_out += int(usage.get("completion_tokens") or 0)
            return message, usage

        llm._post = counted
        return llm

    def used(self) -> dict:
        """Counters so far (subtract two snapshots to get the cost of one job)."""
        return {"calls": self.calls, "tokens_in": self.tokens_in, "tokens_out": self.tokens_out, "llm_seconds": self.seconds}

    def cost(self, used: dict) -> float | None:
        if self.kind != "cloud" or self.price_in is None:
            return 0.0 if self.kind != "cloud" else None
        return used["tokens_in"] * self.price_in + used["tokens_out"] * self.price_out


def since(contender: Contender, before: dict) -> dict:
    now = contender.used()
    used = {k: round(now[k] - before[k], 2) for k in now}
    used["usd"] = contender.cost(used)
    return used


# ---------------------------------------------------------------------------------------------- local server


def ollama_exe() -> str | None:
    found = shutil.which("ollama")
    default = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
    return found or (str(default) if default.is_file() else None)


def start_local_server() -> subprocess.Popen | None:
    """Start an Ollama server for this comparison only (own port, project model folder, larger context window)."""
    exe = ollama_exe()
    if exe is None:
        return None
    env = {**os.environ, "OLLAMA_HOST": f"127.0.0.1:{LOCAL_PORT}", "OLLAMA_CONTEXT_LENGTH": str(LOCAL_CONTEXT),
           "OLLAMA_KEEP_ALIVE": "15m", "OLLAMA_NUM_PARALLEL": "1"}  # fmt: skip
    if (ROOT / "models" / "ollama").is_dir():
        env["OLLAMA_MODELS"] = str(ROOT / "models" / "ollama")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log = (OUT_DIR / "ollama.log").open("w", encoding="utf-8")
    server = subprocess.Popen([exe, "serve"], env=env, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(60):
        try:
            httpx.get(f"http://127.0.0.1:{LOCAL_PORT}/api/version", timeout=1)
            return server
        except httpx.HTTPError:
            time.sleep(0.5)
    server.terminate()
    return None


def local_models() -> list[str]:
    tags = httpx.get(f"http://127.0.0.1:{LOCAL_PORT}/api/tags", timeout=10).json()
    return [m["name"] for m in tags.get("models", [])]


def warm_up(contender: Contender) -> None:
    """Load a local model before it is timed, and note how long that took and how much of it sits on the GPU."""
    started = time.perf_counter()
    try:
        LLMClient(contender.settings, None).chat("agent", [{"role": "user", "content": "Reply with the word ready."}], None, "warm-up", None)
    except LLMUnavailable as exc:
        contender.notes.append(f"warm-up failed: {exc}")
        return
    loaded = httpx.get(f"http://127.0.0.1:{LOCAL_PORT}/api/ps", timeout=10).json().get("models", [])
    mine = next((m for m in loaded if m["name"] == contender.name), None)
    on_gpu = f"{100 * mine['size_vram'] / mine['size']:.0f}% on the GPU ({mine['size'] / 1e9:.1f} GB loaded)" if mine else "GPU share unknown"
    contender.notes.append(f"loaded in {time.perf_counter() - started:.0f} s, {on_gpu}, context {LOCAL_CONTEXT} tokens")


# ------------------------------------------------------------------------------------------------- contenders


def build_contenders(args: argparse.Namespace, base: Settings) -> tuple[list[Contender], subprocess.Popen | None]:
    wanted = set(args.only or [])
    keep = lambda name: not wanted or name in wanted
    contenders, server = [], None
    if keep("rules"):
        contenders.append(Contender("rules", "rules", replace(base, llm_mode="offline")))
    local = [m for m in args.local if keep(m)]
    if local:
        server = start_local_server()
        available = local_models() if server else []
        for model in local:
            if model not in available:
                tqdm.write(f"  skip {model}: not found by the local server (pull it first; see docs/MODEL_COMPARISON.md)")
                continue
            settings = replace(base, llm_mode="live", llm_base_url=f"http://127.0.0.1:{LOCAL_PORT}/v1", llm_api_key="",
                               llm_model_agent=model, llm_model_fast=model, llm_extra_body=args.local_body)  # fmt: skip
            contenders.append(Contender(model, "local", settings))
    via_cli = base.llm_base_url == DEVIN_CLI
    chosen = args.cloud if args.cloud is not None else DEVIN_CLI_MODELS if via_cli else CLOUD_MODELS
    cloud = [m for m in chosen if keep(m)]
    if cloud and not via_cli and not (base.llm_base_url and base.llm_api_key):
        tqdm.write("  skip the cloud models: LLM_BASE_URL and LLM_API_KEY are not both set in .env")
        cloud = []
    if cloud and not via_cli and base.llm_api_key.startswith(DEVIN_KEYS):
        tqdm.write("  skip the cloud models: LLM_API_KEY is a Devin key; it cannot call a model and is not sent to "
                   f"{base.llm_base_url}. Use LLM_BASE_URL=devin-cli, or a key of that provider.")  # fmt: skip
        cloud = []
    prices = cloud_prices(base) if cloud and not via_cli else {}
    for model in cloud:
        settings = replace(base, llm_mode="live", llm_model_agent=model, llm_model_fast=model, llm_extra_body="",
                           llm_api_key="" if via_cli else base.llm_api_key)  # fmt: skip
        contender = Contender(model, "cloud", settings, *prices.get(model, (None, None)))
        if via_cli:
            contender.notes.append("through the Devin CLI: one process per model turn, tokens estimated (characters / 4), "
                                   "paid by the Devin plan (no price per token)")  # fmt: skip
        contenders.append(contender)
    return contenders, server


def cloud_prices(base: Settings) -> dict[str, tuple[float, float]]:
    """USD per input/output token from the provider's model list (OpenRouter publishes it); empty if unknown."""
    try:
        data = httpx.get(f"{base.llm_base_url.rstrip('/')}/models", timeout=20).json()["data"]
        return {m["id"]: (float(m["pricing"]["prompt"]), float(m["pricing"]["completion"])) for m in data if m.get("pricing")}
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        return {}


# ---------------------------------------------------------------------------------------------- 1. investigate


def fresh_pipeline(base: Settings, folder: Path) -> Pipeline:
    """The full pipeline on a private copy of the 14 clean days (the real database is never touched)."""
    copy = folder / f"history_{time.time_ns()}.duckdb"
    shutil.copy(base.duckdb_path.with_suffix(".backfill.duckdb"), copy)
    return Pipeline.from_settings(replace(base, llm_mode="offline"), Database(copy), copy.with_suffix(".yaml"))


def first_case(pipeline: Pipeline, scenario) -> tuple | None:
    """Run clean hours up to 10:00, switch the fault on and return (case, hours until the watcher raised it)."""
    start = pipeline.now.replace(hour=START_HOUR)
    pipeline.run_until(start)
    pipeline.sim.activate(scenario, at=start)
    for hours in range(1, MAX_FAULT_HOURS + 1):
        hour = pipeline.now
        pipeline.sim.tick(hour)
        cases = [c for c in pipeline.watcher.run_tick(hour) if c.kind == "failure"]
        pipeline.now = hour + HOUR
        if cases:
            return cases[0], hours
    return None


def investigate(contender: Contender, pipeline: Pipeline, case, scenario, bar: tqdm) -> dict:
    """One investigation of one case by one contender, with everything worth comparing."""
    investigator = Investigator(contender.settings, pipeline.toolbox, contender.client())
    store, model_drove = pipeline.toolbox.on_step, {"ok": contender.kind == "rules", "why": ""}

    model_tools: list[str] = []

    def show(step) -> None:
        if not model_drove["why"] and contender.kind != "rules":
            model_tools.append(step.tool)
        bar.set_postfix_str(f"{scenario.id} · {contender.name} · step {step.n} {step.tool}", refresh=True)
        store(step)

    pipeline.toolbox.on_step = show
    run_llm = investigator._run_llm

    def run_and_note(the_case) -> None:
        try:
            run_llm(the_case)
        except Exception as exc:  # noted for the report, then handled by the investigator as before
            model_drove["why"] = f"{type(exc).__name__}: {exc}"[:160]
            raise
        model_drove["ok"] = True  # reached only when the model finished the investigation itself

    investigator._run_llm = run_and_note
    before, started = contender.used(), time.perf_counter()
    report = investigator.run(case)
    seconds = time.perf_counter() - started
    want, where = scenario.event_log[0]["component"], scenario.scope.get("market", "all")
    return {
        "scenario": scenario.id, "right_cause": report.cause_component == want, "found": report.cause_component or "none",
        "expected": want, "status": report.status, "right_place": where == "all" or report.scope.get("market") == where,
        "tool_calls": len(report.trail), "tools": [s["tool"] for s in report.trail], "seconds": round(seconds, 1),
        "model_drove": model_drove["ok"], "why_failed": model_drove["why"], "model_tools": model_tools, "reworded": report.summary != plain_summary(report), "summary": report.summary,
        **since(contender, before),
    }  # fmt: skip


def run_investigations(contenders: list[Contender], base: Settings, scenario_ids: list[str], repeat: int, max_cost: float) -> list[dict]:
    scenarios = load_scenarios(ROOT / "scenarios")
    rows, spent = [], 0.0
    with tempfile.TemporaryDirectory() as tmp, tqdm(total=len(scenario_ids) * len(contenders) * repeat, desc="1/4 investigate", unit="run", **BAR) as bar:
        for sid in scenario_ids:
            bar.set_postfix_str(f"{sid} · simulating until the watcher raises a case")
            pipeline = fresh_pipeline(base, Path(tmp))
            found = first_case(pipeline, scenarios[sid])
            if found is None:
                tqdm.write(f"  [{sid}] the watcher raised no case in {MAX_FAULT_HOURS} h; skipped")
                bar.update(len(contenders) * repeat)
                continue
            case, hours = found
            tqdm.write(f"  [{sid}] {scenarios[sid].name}: case after {hours} h - {case.headline}")
            for contender in contenders:
                for attempt in range(repeat):
                    if contender.kind == "cloud" and spent >= max_cost:
                        bar.update(1)
                        continue
                    row = {"contender": contender.name, "attempt": attempt + 1, "detected_after_h": hours,
                           **investigate(contender, pipeline, case, scenarios[sid], bar)}  # fmt: skip
                    spent += row["usd"] or 0.0
                    rows.append(row)
                    mark = "RIGHT" if row["right_cause"] else "WRONG"
                    how = "" if row["model_drove"] else f" (model failed, rules took over: {row['why_failed']})"
                    cost = f"  ${row['usd']:.3f}" if row["usd"] else ""
                    tqdm.write(f"      {contender.name:28s} {mark} {row['found']:16s} {row['status']:10s} {row['tool_calls']:2d} tools "
                               f"{row['seconds']:6.1f} s  {row['tokens_in'] + row['tokens_out']:>7,.0f} tokens{cost}{how}")  # fmt: skip
                    bar.update(1)
            pipeline.db.close()
    return rows


# ------------------------------------------------------------------------------------------------ 2. scenarios


def run_descriptions(contenders: list[Contender], base: Settings) -> list[dict]:
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "history.duckdb"
        shutil.copy(base.duckdb_path.with_suffix(".backfill.duckdb"), copy)
        db, graph = Database(copy), MetricGraph.load()
        with tqdm(total=len(DESCRIPTIONS) * len(contenders), desc="2/4 scenarios  ", unit="text", **BAR) as bar:
            for contender in contenders:
                llm = contender.client()
                for n, (what, where, shop, want) in enumerate(DESCRIPTIONS, start=1):
                    bar.set_postfix_str(f"{contender.name} · description {n}")
                    before, started = contender.used(), time.perf_counter()
                    draft = draft_scenario(db, graph, llm, set(), f"T{n}", "Test", what, where, shop, base.demo_day_start)
                    rows.append({"contender": contender.name, "n": n, "what": what, "expected": want or "refuse", "got": draft.fault or "refuse",
                                 "right": draft.fault == want, "seconds": round(time.perf_counter() - started, 2), **since(contender, before)})  # fmt: skip
                    bar.update(1)
        db.close()
    return rows


# -------------------------------------------------------------------------------------------------- 3. metrics


def run_metrics(contenders: list[Contender], base: Settings) -> list[dict]:
    rows, propose = [], onboarding.propose_with_llm
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "history.duckdb"
        shutil.copy(base.duckdb_path.with_suffix(".backfill.duckdb"), copy)
        db = Database(copy)
        with tqdm(total=len(NEW_METRICS) * len(contenders), desc="3/4 metrics    ", unit="metric", **BAR) as bar:
            for contender in contenders:
                llm, used_model = contender.client(), {"ok": False}

                def noted(*a, used_model=used_model, **k):
                    out = propose(*a, **k)
                    used_model["ok"] = bool(out)
                    return out

                onboarding.propose_with_llm = noted
                for name, description, sql in NEW_METRICS:
                    bar.set_postfix_str(f"{contender.name} · {name}")
                    used_model["ok"] = False
                    before, started = contender.used(), time.perf_counter()
                    result = onboarding.onboard(db, MetricGraph.load(), name, description, sql, base.demo_day_start, llm)
                    links = [f"{p.source}->{p.target} ({'ok' if p.status == 'validated' else 'weak'})" for p in result.proposals]
                    rows.append({"contender": contender.name, "metric": name, "added": result.added, "by_model": used_model["ok"],
                                 "links": len(result.proposals), "validated": sum(p.status == "validated" for p in result.proposals),
                                 "detail": links, "seconds": round(time.perf_counter() - started, 2), **since(contender, before)})  # fmt: skip
                    bar.update(1)
        onboarding.propose_with_llm = propose
        db.close()
    return rows


# ----------------------------------------------------------------------------------------------------- output


def run_sql(contenders: list[Contender], base: Settings) -> list[dict]:
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "history.duckdb"
        shutil.copy(base.duckdb_path.with_suffix(".backfill.duckdb"), copy)
        db, graph, end = Database(copy), MetricGraph.load(), base.demo_day_start
        with tqdm(total=len(SQL_WISHES) * len(contenders), desc="4/4 write SQL  ", unit="metric", **BAR) as bar:
            for contender in contenders:
                llm = contender.client()
                for n, (wish, reference) in enumerate(SQL_WISHES, start=1):
                    bar.set_postfix_str(f"{contender.name} · wish {n}")
                    row = {"contender": contender.name, "n": n, "wish": wish, "reference": reference, "possible": contender.kind != "rules",
                           "sql": "", "runs": False, "right": False, "problem": "", "seconds": 0.0, "usd": 0.0}  # fmt: skip
                    if contender.kind != "rules":
                        before, started = contender.used(), time.perf_counter()
                        try:
                            row["sql"] = onboarding.draft_metric(llm, db, graph, wish, end)["sql"]
                            frame, row["problem"] = onboarding.try_sql(db, row["sql"], end)
                        except LLMUnavailable as exc:
                            frame, row["problem"] = None, str(exc)
                        want, _ = onboarding.try_sql(db, reference, end)
                        row["runs"] = frame is not None
                        if frame is not None:
                            both = want.merge(frame, on="ts", how="outer", suffixes=("_want", "_got"))
                            row["right"] = bool(np.allclose(both["value_want"], both["value_got"], rtol=1e-6, equal_nan=True))
                        row.update(seconds=round(time.perf_counter() - started, 2), **since(contender, before))
                    rows.append(row)
                    bar.update(1)
        db.close()
    return rows


def table(head: list[str], lines: list[list]) -> str:
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head), *("| " + " | ".join(str(c) for c in line) + " |" for line in lines)])


def money(rows: list[dict]) -> str:
    known = [r["usd"] for r in rows if r.get("usd") is not None]
    return "-" if not rows or len(known) < len(rows) else "free" if not sum(known) else f"${sum(known):.2f}"


def write_report(results: dict) -> None:
    names = list(dict.fromkeys(r["contender"] for key in ("investigate", "scenarios", "metrics", "sql") for r in results.get(key, [])))
    by = lambda key, name: [r for r in results.get(key, []) if r["contender"] == name]
    out = ["# Model comparison: measured results", "",
           (f"Generated by `scripts/compare_models.py` on {results['when']}. Do not edit by hand; the reading of these numbers is in "
           "`docs/MODEL_COMPARISON.md`."), "", "## Contenders", ""]  # fmt: skip
    out.append(table(["Contender", "Kind", "Notes"], [[n, results["contenders"][n]["kind"], "; ".join(results["contenders"][n]["notes"]) or "-"] for n in names if n in results["contenders"]]))
    out += ["", "## 1. Finding the cause of a failure", "",
            ("Same case, same tools, same evidence checklist for everyone. *Right cause* = the report blames the component the "
            "scenario really broke. *Confirmed* = all four evidence checks passed (computed in code). *Model drove* = the model "
            "finished the investigation itself; otherwise its run failed and the rules took over."), ""]  # fmt: skip
    lines = []
    for name in names:
        rows = by("investigate", name)
        if rows:
            n = len(rows)
            lines.append([name, f"{sum(r['right_cause'] for r in rows)}/{n}", f"{sum(r['status'] == 'SUPPORTED' and r['right_cause'] for r in rows)}/{n}",
                          f"{sum(r['model_drove'] for r in rows)}/{n}", f"{sum(r['seconds'] for r in rows) / n:.1f} s", f"{max(r['seconds'] for r in rows):.0f} s",
                          f"{sum(r['tool_calls'] for r in rows) / n:.1f}", f"{sum(r['tokens_in'] + r['tokens_out'] for r in rows) / n:,.0f}", money(rows)])  # fmt: skip
    out.append(table(["Contender", "Right cause", "Right and confirmed", "Model drove", "Avg time", "Slowest", "Avg tool calls", "Avg tokens", "Cost (all runs)"], lines))
    scenario_ids = list(dict.fromkeys(r["scenario"] for r in results.get("investigate", [])))
    cell = lambda r: ("ok" if r["right_cause"] else f"WRONG ({r['found']})") + f" {r['status'][:4].lower()} {r['seconds']:.0f}s" + ("" if r["model_drove"] else " *")
    out += ["", ("Per scenario (first attempt): result, evidence level (supp = confirmed, like = likely, hypo = unconfirmed), seconds. "
            "`*` = the model's run failed and the rules took over."), ""]  # fmt: skip
    out.append(table(["Scenario", *names], [[sid, *[next((cell(r) for r in by("investigate", n) if r["scenario"] == sid), "-") for n in names]] for sid in scenario_ids]))
    repeats = {n: by("investigate", n) for n in names if any(r["attempt"] > 1 for r in by("investigate", n))}
    if repeats:
        out += ["", "Same answer on every repeat (cause and evidence level):", ""]
        same = lambda rows, sid: len({(r["found"], r["status"]) for r in rows if r["scenario"] == sid}) == 1
        out.append(table(["Contender", "Scenarios with identical repeats"], [[n, f"{sum(same(rows, s) for s in scenario_ids)}/{len(scenario_ids)}"] for n, rows in repeats.items()]))
    out += ["", "## 2. Reading a plain description (Add a scenario)", "",
            (f"{len(DESCRIPTIONS)} descriptions: {sum(d[3] is not None for d in DESCRIPTIONS)} should map to a simulator fault, "
            f"{sum(d[3] is None for d in DESCRIPTIONS)} cannot be simulated and must be refused. The rules use keywords."), ""]  # fmt: skip
    out.append(table(["Contender", "Right", "Avg time", "Cost"], [[n, f"{sum(r['right'] for r in by('scenarios', n))}/{len(by('scenarios', n))}",
                      f"{sum(r['seconds'] for r in by('scenarios', n)) / len(by('scenarios', n)):.2f} s", money(by("scenarios", n))] for n in names if by("scenarios", n)]))  # fmt: skip
    wrong = [[r["contender"], r["what"][:70], r["expected"], r["got"]] for r in results.get("scenarios", []) if not r["right"]]
    if wrong:
        out += ["", "Misses:", "", table(["Contender", "Description", "Expected", "Got"], wrong)]
    out += ["", "## 3. Proposing links for a new metric (Add a metric)", "",
            ("The contender proposes which existing metrics the new one is linked to; code then checks every link against 7 days "
            "of history (validated = correlation of at least 0.6). *By model* = the model's answer was usable."), ""]  # fmt: skip
    out.append(table(["Contender", "Metrics added", "By model", "Links proposed", "Links validated", "Avg time", "Cost"],
                     [[n, f"{sum(r['added'] for r in by('metrics', n))}/{len(by('metrics', n))}", f"{sum(r['by_model'] for r in by('metrics', n))}/{len(by('metrics', n))}",
                       sum(r["links"] for r in by("metrics", n)), sum(r["validated"] for r in by("metrics", n)),
                       f"{sum(r['seconds'] for r in by('metrics', n)) / len(by('metrics', n)):.1f} s", money(by("metrics", n))] for n in names if by("metrics", n)]))  # fmt: skip
    if results.get("sql"):
        out += ["", "## 4. Writing a metric's SQL from a plain description", "",
                (f"{len(SQL_WISHES)} wishes in plain words. *Runs* = the SQL the model wrote runs on 7 days of history. *Right* = it also "
                "gives the same hourly numbers as the SQL a person wrote for that wish. The rules cannot write SQL at all."), ""]  # fmt: skip
        lines = []
        for name in names:
            rows = by("sql", name)
            if rows and not rows[0]["possible"]:
                lines.append([name, "not possible", "not possible", "-", "-"])
            elif rows:
                lines.append([name, f"{sum(r['runs'] for r in rows)}/{len(rows)}", f"{sum(r['right'] for r in rows)}/{len(rows)}",
                              f"{sum(r['seconds'] for r in rows) / len(rows):.1f} s", money(rows)])  # fmt: skip
        out.append(table(["Contender", "Runs", "Right", "Avg time", "Cost"], lines))
        out += ["", "What each model wrote (`ok` = right numbers, `runs` = runs but different numbers, `fails` = does not run):", ""]
        mark = lambda r: "ok" if r["right"] else "runs" if r["runs"] else "fails"
        show = lambda r: f"{mark(r)}: `{r['sql'] or r['problem']}`".replace("|", "\\|")
        models = [n for n in names if by("sql", n) and by("sql", n)[0]["possible"]]
        for n, (wish, reference) in enumerate(SQL_WISHES, start=1):
            out += [f"**{n}. {wish}**", "", f"- reference: `{reference}`",
                    *[f"- {m}: {show(next(r for r in by('sql', m) if r['n'] == n))}" for m in models if any(r["n"] == n for r in by("sql", m))], ""]  # fmt: skip
    REPORT.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", nargs="+", help="run only these contenders (rules, a local model name, a cloud model name)")
    parser.add_argument("--local", nargs="*", default=list(LOCAL_MODELS), help="local Ollama models")
    parser.add_argument("--cloud", nargs="*", default=None, help="cloud models (default: two Claude models; opus and sonnet with LLM_BASE_URL=devin-cli)")
    parser.add_argument("--check", action="store_true", help="only ask every contender for one word and say whether it answers")
    parser.add_argument("--scenarios", nargs="+", default=list(FAILURES), help="failure scenarios to investigate")
    parser.add_argument("--repeat", type=int, default=1, help="investigations per scenario and contender (2+ shows consistency)")
    parser.add_argument("--skip", nargs="*", default=[], choices=["investigate", "scenarios", "metrics", "sql"], help="jobs to leave out")
    parser.add_argument("--max-cost", type=float, default=5.0, help="stop paying for cloud investigations after this many USD")
    parser.add_argument("--local-body", default='{"reasoning_effort": "none"}', help="extra JSON sent to local models (default: thinking off)")
    args = parser.parse_args()
    setup_logging(level=40)
    base = load_settings()
    if not base.duckdb_path.with_suffix(".backfill.duckdb").is_file():
        print("Run scripts/backfill.py first.")
        return 1
    contenders, server = build_contenders(args, base)
    try:
        if not contenders:
            print("Nothing to compare.")
            return 1
        print("Contenders: " + ", ".join(c.name for c in contenders))
        for contender in (c for c in contenders if c.kind == "local"):
            print(f"  loading {contender.name} ...", flush=True)
            warm_up(contender)
            print(f"  {contender.name}: {'; '.join(contender.notes)}")
        if args.check:
            for contender in contenders:
                if contender.kind == "rules":
                    print("  rules: ok (no model needed)")
                    continue
                started = time.perf_counter()
                try:
                    ask = [{"role": "user", "content": "Reply with the single word ready."}]
                    said = contender.client().chat("fast", ask, None, "check", None)["content"].strip()[:40]
                    print(f"  {contender.name}: ok in {time.perf_counter() - started:.1f} s, answered {said!r}")
                except LLMUnavailable as exc:
                    print(f"  {contender.name}: NOT WORKING - {exc}")
            return 0
        names = [c.name for c in contenders]
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUT_DIR / "results.json"
        jobs = {"investigate": lambda: run_investigations(contenders, base, args.scenarios, args.repeat, args.max_cost),
                "scenarios": lambda: run_descriptions(contenders, base), "metrics": lambda: run_metrics(contenders, base),
                "sql": lambda: run_sql(contenders, base)}  # fmt: skip
        for key, job in jobs.items():
            if key not in args.skip:
                rows = job()
                # read the file again right before writing: a second run (e.g. the cloud models in another window)
                # may have added its rows meanwhile; only this run's contenders are replaced
                results = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"contenders": {}}
                results[key] = [r for r in results.get(key, []) if r["contender"] not in names] + rows
                results["when"] = time.strftime("%Y-%m-%d %H:%M")
                results["contenders"].update({c.name: {"kind": c.kind, "notes": c.notes} for c in contenders})
                path.write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
                write_report(results)
        print(f"\nDone. Tables: {REPORT.relative_to(ROOT)}   Raw results: {path.relative_to(ROOT)}")
        return 0
    finally:
        if server:
            server.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
