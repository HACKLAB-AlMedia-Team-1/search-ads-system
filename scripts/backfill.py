"""Simulate the clean history (SIM_START up to DEMO_DAY_START) into a fresh DuckDB file."""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rootsight.config import load_settings
from rootsight.logging_setup import setup_logging
from rootsight.sim.simulator import Simulator
from rootsight.store.db import Database


def main() -> int:
    """Create the database and simulate 14 clean days; refuses to overwrite without --force."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="replace an existing database file")
    args = parser.parse_args()
    setup_logging()
    settings = load_settings()
    path = settings.duckdb_path
    if path.exists():
        if not args.force:
            print(f"{path} already exists. Re-run with --force to replace it.")
            return 1
        path.unlink()
    started = time.time()
    db = Database(path)
    sim = Simulator.from_settings(settings, db)
    sim.run(settings.sim_start, settings.demo_day_start)
    sim.save_state()
    db.close()
    shutil.copy(path, path.with_suffix(".backfill.duckdb"))
    print(f"Backfill done in {time.time() - started:.0f}s -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
