"""Thread-safe DuckDB wrapper used by the simulator, watcher, agent and UI."""

from __future__ import annotations

import threading
from pathlib import Path

import duckdb
import pandas as pd

SCHEMA_FILE = Path(__file__).with_name("schema.sql")


class Database:
    """One DuckDB connection shared by all threads (guarded by a lock); the schema is created on open."""

    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._con = duckdb.connect(str(path))
        self._lock = threading.RLock()
        self.execute(SCHEMA_FILE.read_text(encoding="utf-8"))

    def execute(self, sql: str, params: list | None = None) -> None:
        """Run a statement that returns nothing."""
        with self._lock:
            self._con.execute(sql, params or [])

    def df(self, sql: str, params: list | None = None) -> pd.DataFrame:
        """Run a query and return the result as a DataFrame."""
        with self._lock:
            return self._con.execute(sql, params or []).fetchdf()

    def insert_df(self, table: str, frame: pd.DataFrame) -> None:
        """Append the rows of `frame` to `table` (columns matched by name)."""
        if frame.empty:
            return
        cols = ", ".join(f'"{c}"' for c in frame.columns)
        with self._lock:
            self._con.register("_incoming", frame)
            try:
                self._con.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM _incoming")
            finally:
                self._con.unregister("_incoming")

    def close(self) -> None:
        """Close the connection."""
        with self._lock:
            self._con.close()
