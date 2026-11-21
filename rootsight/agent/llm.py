"""The only place that talks to a language model (any OpenAI-compatible endpoint, e.g. a local Ollama)."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import httpx

from rootsight.config import Settings
from rootsight.store.db import Database

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 300
RECORDINGS_DIR = Path(__file__).with_name("recordings")


class LLMUnavailable(RuntimeError):
    """Raised when no model can be called (offline mode, no recording, endpoint down); callers fall back."""


class LLMClient:
    """Chat with the model in one of four modes: offline, live, record (live + save) or replay (saved only)."""

    def __init__(self, settings: Settings, db: Database | None = None, recordings: Path = RECORDINGS_DIR):
        self.settings, self.db, self.recordings = settings, db, recordings
        self.mode = settings.llm_mode
        self._cursor: dict[str, int] = {}

    @property
    def available(self) -> bool:
        """Can this client produce answers (everything except offline mode)?"""
        return self.mode != "offline"

    def chat(
        self, role: str, messages: list[dict], tools: list[dict] | None, case_id: str, now: datetime
    ) -> dict:
        """Return the assistant message (with optional `tool_calls`) for `role` = `agent` or `fast`."""
        if self.mode == "offline":
            raise LLMUnavailable("LLM_MODE is offline")
        if self.mode == "replay":
            return self._replay(case_id)
        message, usage = self._post(role, messages, tools)
        if self.mode == "record":
            self._save(case_id, message)
        if self.db is not None:
            row = {"ts": now, "case_id": case_id, "role": role, "model": self._model(role), "mode": self.mode,
                   "input_tokens": usage.get("prompt_tokens", 0), "output_tokens": usage.get("completion_tokens", 0)}  # fmt: skip
            self.db.execute("INSERT INTO llm_calls VALUES (?, ?, ?, ?, ?, ?, ?)", list(row.values()))
        return message

    def _model(self, role: str) -> str:
        return self.settings.llm_model_agent if role == "agent" else self.settings.llm_model_fast

    def _post(self, role: str, messages: list[dict], tools: list[dict] | None) -> tuple[dict, dict]:
        s = self.settings
        if not (s.llm_base_url and self._model(role)):
            raise LLMUnavailable("LLM_BASE_URL and the model name must be set in .env")
        headers = {"Authorization": f"Bearer {s.llm_api_key}"} if s.llm_api_key else {}
        body = {
            "model": self._model(role),
            "messages": messages,
            "max_tokens": s.max_output_tokens_per_call,
            "temperature": 0,
        }
        if tools:
            body["tools"] = tools
        try:
            response = httpx.post(
                f"{s.llm_base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=body,
                timeout=TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"], data.get("usage", {})
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise LLMUnavailable(f"model call failed: {type(exc).__name__}") from exc

    def _path(self, case_id: str) -> Path:
        return self.recordings / f"{case_id}.json"

    def _save(self, case_id: str, message: dict) -> None:
        saved = (
            json.loads(self._path(case_id).read_text(encoding="utf-8"))
            if self._path(case_id).is_file()
            else []
        )
        self.recordings.mkdir(parents=True, exist_ok=True)
        self._path(case_id).write_text(json.dumps([*saved, message], indent=1), encoding="utf-8")

    def _replay(self, case_id: str) -> dict:
        if not self._path(case_id).is_file():
            raise LLMUnavailable(f"no recording for {case_id}")
        saved = json.loads(self._path(case_id).read_text(encoding="utf-8"))
        index = self._cursor.get(case_id, 0)
        if index >= len(saved):
            raise LLMUnavailable("recording is exhausted")
        self._cursor[case_id] = index + 1
        return saved[index]
