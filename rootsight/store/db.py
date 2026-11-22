"""Thread-safe DuckDB wrapper used by the simulator, watcher, agent and UI."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

SCHEMA_FILE = Path(__file__).with_name("schema.sql")
CAPTURED_ROWS = 5


def _literal(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, datetime):
        return f"TIMESTAMP '{value:%Y-%m-%d %H:%M:%S}'"
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return str(value)


def inline_sql(sql: str, params: list | None = None) -> str:
    """The statement with its `?` parameters written in, for showing to people (never for running)."""
    parts = " ".join(sql.split()).split("?")
    if len(parts) - 1 != len(params or []):
        return " ".join(sql.split())
    return parts[0] + "".join(_literal(p) + rest for p, rest in zip(params or [], parts[1:], strict=True))


class Database:
    """One DuckDB connection shared by all threads (guarded by a lock); the schema is created on open."""

    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._con = duckdb.connect(str(path))
        self._lock = threading.RLock()
        self._captured = threading.local()
        self.execute(SCHEMA_FILE.read_text(encoding="utf-8"))

    @contextmanager
    def capture(self) -> Iterator[list[dict]]:
        """Collect every query this thread runs inside the block: the SQL (parameters written in) and its first rows."""
        queries: list[dict] = []
        self._captured.queries = queries
        try:
            yield queries
        finally:
            self._captured.queries = None

    def _record(self, sql: str, params: list | None, frame: pd.DataFrame) -> None:
        if (queries := getattr(self._captured, "queries", None)) is not None:
            queries.append({"sql": inline_sql(sql, params), "row_count": len(frame), "columns": [str(c) for c in frame.columns],
                            "rows": json.loads(frame.head(CAPTURED_ROWS).to_json(orient="values", date_format="iso"))})  # fmt: skip

    def execute(self, sql: str, params: list | None = None) -> None:
        """Run a statement that returns nothing."""
        with self._lock:
            self._con.execute(sql, params or [])

    def df(self, sql: str, params: list | None = None) -> pd.DataFrame:
        """Run a query and return the result as a DataFrame."""
        with self._lock:
            frame = self._con.execute(sql, params or []).fetchdf()
        self._record(sql, params, frame)
        return frame

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
