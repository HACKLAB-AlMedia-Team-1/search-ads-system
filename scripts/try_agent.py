"""Show the agent's model paths end to end on a private copy of the 14 clean days (the real database is never touched).

1. Planning: plain words that name a metric become a rule (no model); the rest is planned by the model.
2. A model watch during a real failure (S12, German searches find nothing): the model looks, its verdict is checked in
   code, and the problem is investigated (rules first: the recipe confirms the cause, the model is not needed).
3. Takeover: a question whose cause the rule recipe cannot confirm, so the model continues the investigation.

    python scripts/try_agent.py --local qwen3.5:9b   # local Ollama model (free; the script starts and stops Ollama)
    python scripts/try_agent.py                      # the model in .env, e.g. LLM_BASE_URL=devin-cli with opus (uses credits)
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rootsight.agent.watches import MODEL, as_model, check_model_watch
from rootsight.config import load_settings
from rootsight.logging_setup import setup_logging
from rootsight.pipeline import Pipeline
from rootsight.sim.faults import load_scenarios
from rootsight.store.db import Database

PORT = 11435
FAULT_HOUR = 10
REQUESTS = (
    "Watch zero results in Germany on Android",
    "Watch whether shoppers in Germany get search results that match what they typed",
    "Watch the share of carts that do not become an order",
)


def start_ollama() -> subprocess.Popen:
    """An Ollama server for this script only (own port, models from `models/ollama`, thinking off is set per request)."""
    exe = shutil.which("ollama") or str(
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
    )
    env = {
        **os.environ,
        "OLLAMA_HOST": f"127.0.0.1:{PORT}",
        "OLLAMA_CONTEXT_LENGTH": "12288",
        "OLLAMA_KEEP_ALIVE": "15m",
    }
    if (ROOT / "models" / "ollama").is_dir():
        env["OLLAMA_MODELS"] = str(ROOT / "models" / "ollama")
    server = subprocess.Popen([exe, "serve"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            httpx.get(f"http://127.0.0.1:{PORT}/api/version", timeout=1)
            return server
        except httpx.HTTPError:
            time.sleep(0.5)
    server.terminate()
    raise SystemExit("Ollama did not start")


def timed(label: str, started: float) -> None:
    print(f"   ({label}: {time.perf_counter() - started:.0f} s)")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--local", help="a local Ollama model, e.g. qwen3.5:9b (otherwise the model in .env is used)"
    )
    args = parser.parse_args()
    setup_logging()
    base, server = load_settings(), None
    if args.local:
        server = start_ollama()
        settings = replace(base, llm_mode="live", llm_base_url=f"http://127.0.0.1:{PORT}/v1", llm_api_key="",
                           llm_model_agent=args.local, llm_model_fast=args.local, llm_extra_body='{"reasoning_effort": "none"}')  # fmt: skip
    else:
        settings = replace(base, llm_mode="live")
    print(f"Model: {settings.llm_model_agent} via {settings.llm_base_url}")
    folder = Path(tempfile.mkdtemp(prefix="rootsight_agent_"))
    copy = folder / "history.duckdb"
    shutil.copy(base.duckdb_path.with_suffix(".backfill.duckdb"), copy)
    db = Database(copy)
    try:
        pipeline = Pipeline.from_settings(settings, db, folder / "metrics_custom.yaml")
        print("\n1. Planning watches (rules first, the model only when no metric is named)")
        for request in REQUESTS:
            started = time.perf_counter()
            plan = pipeline.plan_watch(request)
            sql = f"\n   SQL: {plan.new_metric['sql']}" if plan.new_metric else ""
            print(
                f"- {request}\n   -> {plan.kind} (planned by {plan.by}): {plan.metric or ''} {plan.segment or ''}\n   {plan.reason}{sql}"
            )
            timed("planning", started)

        fault_at = pipeline.now.replace(hour=FAULT_HOUR)
        pipeline.run_until(fault_at)
        plan = pipeline.plan_watch(REQUESTS[1])
        watch, _ = pipeline.add_watch(
            plan if plan.kind == MODEL else as_model(plan)
        )  # show the model path even if a rule fits
        pipeline.sim.activate(load_scenarios(ROOT / "scenarios")["S12"], at=fault_at)
        print(
            f"\n2. Model watch {watch.watch_id} ({watch.kind}) during S12 (German searches find nothing), {fault_at:%a %H:00}"
        )
        started = time.perf_counter()
        result = pipeline.step()
        timed("one simulated hour with the model's look", started)
        looked = next(w for w in pipeline.watches.all() if w.watch_id == watch.watch_id)
        print(f"   model verdict: {looked.last_verdict} - {looked.last_note}")
        for event in result.events:
            found = (
                f"{event.report.cause_component} {event.report.status}, found by {event.report.method}"
                if event.report
                else ""
            )
            print(
                f"   incident #{event.incident_id} {event.kind}: {event.case.headline if event.case else ''} {found}"
            )
        pipeline.sim.stop_all(pipeline.now)
        pipeline.run_until(pipeline.now + timedelta(hours=4))

        print(
            "\n3. Takeover: a question the rule recipe cannot confirm (the numbers are normal, nothing changed)"
        )
        started = time.perf_counter()
        answer = pipeline.ask("Why are orders in Japan where they are?", always=True)
        timed("investigation", started)
        report = answer.report
        print(
            f"   {answer.text}\n   found by: {report.method}; status {report.status}; cause: {report.cause}"
        )
        print("   trail: " + " > ".join(s["tool"] for s in report.trail))
        # one more look after the repair: the verdict should be ok again
        started = time.perf_counter()
        verdict, note, _ = check_model_watch(
            looked, pipeline.toolbox, pipeline.llm, pipeline.now - timedelta(hours=1)
        )
        timed("model look after the repair", started)
        print(f"   after End Simulation the model says: {verdict} - {note}")
    finally:
        db.close()
        if server:
            server.terminate()
        shutil.rmtree(folder, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
