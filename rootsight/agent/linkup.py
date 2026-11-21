"""Linkup web search for outside context (e.g. "is this date Black Friday?"), cached on disk."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx

from rootsight.config import Settings

URL = "https://api.linkup.so/v1/search"
TIMEOUT_SECONDS = 60


class Linkup:
    """`web_check` answers a question from the web; in offline mode it does nothing and costs nothing."""

    def __init__(self, settings: Settings, cache_dir: Path):
        self.mode, self._key, self._cache = settings.linkup_mode, settings.linkup_api_key, cache_dir

    def web_check(self, question: str) -> dict:
        """Return `{"answer", "sources"}` for the question, or `{"skipped": True}` when Linkup is off."""
        if self.mode != "live" or not self._key:
            return {"skipped": True}
        path = self._cache / f"{hashlib.sha1(question.encode()).hexdigest()}.json"
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
        response = httpx.post(
            URL,
            headers={"Authorization": f"Bearer {self._key}"},
            json={"q": question, "depth": "standard", "outputType": "sourcedAnswer"},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        body = response.json()
        result = {
            "answer": body.get("answer", ""),
            "sources": [s.get("url") for s in body.get("sources", [])][:3],
        }
        self._cache.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result), encoding="utf-8")
        return result
