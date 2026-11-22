"""Render every dashboard page once (headless) and report exceptions; a quick check that the UI starts."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "app")]

from streamlit.testing.v1 import AppTest

VIEWS = ("journey", "scenarios", "control_room", "incidents", "graph", "agent", "add_scenario")


def main() -> int:
    """Run each page; return 1 if any raised."""
    failed = 0
    for view in VIEWS:
        at = AppTest.from_file(str(ROOT / "app" / "views" / f"{view}.py"), default_timeout=180).run()
        errors = [e.value for e in at.exception]
        print(f"{'FAIL' if errors else 'ok  '} {view} {errors[:1]}")
        failed += bool(errors)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
