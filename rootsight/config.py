"""Project settings, read from `.env` (no networking, no side effects)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True, slots=True)
class Settings:
    """All runtime settings. Secrets are hidden from `repr`."""

    llm_mode: str
    llm_base_url: str
    llm_model_agent: str
    llm_model_fast: str
    max_tool_calls: int
    max_output_tokens_per_call: int
    linkup_mode: str
    sim_seed: int
    sim_start: datetime
    demo_day_start: datetime
    seconds_per_sim_hour: float
    data_raw_dir: Path
    data_processed_dir: Path
    duckdb_path: Path
    llm_api_key: str = field(default="", repr=False)
    linkup_api_key: str = field(default="", repr=False)


def load_settings(env_file: Path = PROJECT_ROOT / ".env") -> Settings:
    """Load settings from `env_file`; only the two mode switches may be overridden by the process env."""
    values = dotenv_values(env_file, interpolate=False)

    def get(key: str, default: str = "") -> str:
        return (values.get(key) or default).strip()

    return Settings(
        llm_mode=os.environ.get("LLM_MODE", values.get("LLM_MODE") or "offline").strip(),
        llm_base_url=get("LLM_BASE_URL"),
        llm_api_key=get("LLM_API_KEY"),
        llm_model_agent=get("LLM_MODEL_AGENT"),
        llm_model_fast=get("LLM_MODEL_FAST"),
        linkup_mode=os.environ.get("LINKUP_MODE", values.get("LINKUP_MODE") or "offline").strip(),
        linkup_api_key=get("LINKUP_API_KEY"),
        max_tool_calls=int(get("MAX_TOOL_CALLS", "12")),
        max_output_tokens_per_call=int(get("MAX_OUTPUT_TOKENS_PER_CALL", "1500")),
        sim_seed=int(get("SIM_SEED", "42")),
        sim_start=datetime.fromisoformat(get("SIM_START", "2026-11-07T00:00:00")),
        demo_day_start=datetime.fromisoformat(get("DEMO_DAY_START", "2026-11-21T00:00:00")),
        seconds_per_sim_hour=float(get("SECONDS_PER_SIM_HOUR", "3")),
        data_raw_dir=PROJECT_ROOT / Path(get("DATA_RAW_DIR", "data/raw")),
        data_processed_dir=PROJECT_ROOT / Path(get("DATA_PROCESSED_DIR", "data/processed")),
        duckdb_path=PROJECT_ROOT / Path(get("DUCKDB_PATH", "data/rootsight.duckdb")),
    )
