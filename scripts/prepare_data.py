"""Build data/processed/*.parquet from the raw ESCI files (seeded, so re-runs are identical)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rootsight.config import load_settings
from rootsight.data.prepare import prepare
from rootsight.logging_setup import setup_logging


def main() -> int:
    """Run data preparation with the settings from `.env`."""
    setup_logging()
    settings = load_settings()
    prepare(settings.data_raw_dir, settings.data_processed_dir, settings.sim_seed, settings.demo_day_start)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
