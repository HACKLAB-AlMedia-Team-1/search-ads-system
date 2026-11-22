"""The only place that talks to a language model (any OpenAI-compatible endpoint, e.g. a local Ollama)."""

from __future__ import annotations

import json
import logging
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

import httpx

from rootsight.config import Settings
from rootsight.store.db import Database

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 300
DEVIN_CLI = "devin-cli"  # LLM_BASE_URL value: use the models of a logged-in Devin CLI instead of an HTTP endpoint
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
CLI_RULES = ("You are used as a plain language model inside another program. Do not use any of your own tools: do not read "
             "files, do not run commands, do not search. Answer only from the text below.")  # fmt: skip
CLI_TOOL_REPLY = ('Reply with exactly ONE JSON object and nothing else. To call a tool: {"thought": "<one short sentence>", '
                  '"tool": "<tool name>", "arguments": {<arguments>}}. When no further tool is needed: {"final": "<one sentence>"}.')  # fmt: skip
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
        if s.llm_base_url == DEVIN_CLI:
            return self._post_cli(role, messages, tools)
        headers = {"Authorization": f"Bearer {s.llm_api_key}"} if s.llm_api_key else {}
        body = {
            "model": self._model(role),
            "messages": messages,
            "max_tokens": s.max_output_tokens_per_call,
            "temperature": 0,
        }
        if tools:
            body["tools"] = tools
        if s.llm_extra_body:  # provider-specific switches, e.g. {"reasoning_effort": "none"} for a local thinking model
            body.update(json.loads(s.llm_extra_body))
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
        except httpx.HTTPStatusError as exc:  # the provider's own words say what is wrong (never contains our key)
            detail = " ".join(exc.response.text.split())[:200]
            raise LLMUnavailable(f"model call failed: HTTP {exc.response.status_code} {detail}") from exc
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise LLMUnavailable(f"model call failed: {type(exc).__name__}") from exc

    def _post_cli(self, role: str, messages: list[dict], tools: list[dict] | None) -> tuple[dict, dict]:
        """One model turn through the Devin CLI (`devin -p`), for accounts that have Devin but no model API key.

        The CLI has no tool-calling API, so the conversation and the tool list are written into one prompt and the
        model answers with one JSON object, which is turned back into an OpenAI-style message. No key is sent
        anywhere: the CLI uses its own login (`devin auth login`). Tokens are estimated (characters / 4).
        """
        parts = [CLI_RULES]
        for m in messages:
            if m["role"] == "assistant":
                calls = [f"{c['function']['name']}({c['function']['arguments']})" for c in m.get("tool_calls") or []]
                parts.append("YOU SAID: " + (m.get("content") or "") + ("\nYOU CALLED: " + "; ".join(calls) if calls else ""))
            else:
                parts.append({"system": "INSTRUCTIONS", "tool": "TOOL RESULT"}.get(m["role"], "USER") + ":\n" + str(m["content"]))
        if tools:
            listed = [{"name": t["function"]["name"], "description": t["function"]["description"],
                       "arguments": t["function"]["parameters"]["properties"]} for t in tools]  # fmt: skip
            parts += ["TOOLS YOU MAY CALL:\n" + json.dumps(listed), CLI_TOOL_REPLY]
        prompt = "\n\n".join(parts)
        with tempfile.TemporaryDirectory() as empty:  # an empty folder: nothing for the CLI's own agent to explore
            file = Path(empty) / "prompt.txt"
            file.write_text(prompt, encoding="utf-8")
            command = [self.settings.devin_cli, "-p", "--model", self._model(role), "--prompt-file", str(file),
                       "--respect-workspace-trust", "false"]  # fmt: skip
            try:
                done = subprocess.run(command, check=False, cwd=empty, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                      timeout=TIMEOUT_SECONDS, stdin=subprocess.DEVNULL)  # fmt: skip
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise LLMUnavailable(f"the Devin CLI did not answer ({type(exc).__name__}); check DEVIN_CLI in .env") from exc
        text = ANSI.sub("", done.stdout).strip()
        if "log in" in (text + done.stderr).lower():
            raise LLMUnavailable("the Devin CLI is not logged in; run `devin auth login` once")
        if done.returncode != 0 or not text:
            raise LLMUnavailable(f"the Devin CLI failed: {' '.join((done.stderr or text).split())[:200]}")
        usage = {"prompt_tokens": len(prompt) // 4, "completion_tokens": len(text) // 4}
        if not tools:
            return {"role": "assistant", "content": text}, usage
        try:
            reply = json.loads(text[text.index("{") : text.rindex("}") + 1])
        except ValueError as exc:
            raise LLMUnavailable("the Devin CLI model did not answer with JSON") from exc
        if not reply.get("tool"):
            return {"role": "assistant", "content": str(reply.get("final") or text)}, usage
        call = {"id": f"cli-{len(messages)}", "type": "function",
                "function": {"name": str(reply["tool"]), "arguments": json.dumps(reply.get("arguments") or {})}}  # fmt: skip
        return {"role": "assistant", "content": str(reply.get("thought") or ""), "tool_calls": [call]}, usage

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
