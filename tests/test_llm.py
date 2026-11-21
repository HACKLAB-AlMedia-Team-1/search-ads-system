"""LLM client: modes, token logging, record/replay and clean failure (no network is ever used)."""

from dataclasses import replace
from datetime import datetime

import httpx
import pytest
from conftest import SETTINGS

from rootsight.agent.llm import LLMClient, LLMUnavailable
from rootsight.store.db import Database

NOW = datetime(2026, 11, 21, 12)
REPLY = {
    "role": "assistant",
    "content": "ok",
    "tool_calls": [{"id": "1", "function": {"name": "finish", "arguments": "{}"}}],
}
LIVE = replace(
    SETTINGS,
    llm_mode="live",
    llm_base_url="http://127.0.0.1:9/v1",
    llm_model_agent="agent-model",
    llm_model_fast="fast-model",
)


class FakeResponse:
    def raise_for_status(self) -> None: ...

    def json(self) -> dict:
        return {"choices": [{"message": REPLY}], "usage": {"prompt_tokens": 11, "completion_tokens": 7}}


def test_offline_and_missing_config_raise_unavailable(tmp_path):
    with pytest.raises(LLMUnavailable):
        LLMClient(replace(SETTINGS, llm_mode="offline"), None, tmp_path).chat("agent", [], None, "c", NOW)
    with pytest.raises(LLMUnavailable):
        LLMClient(replace(LIVE, llm_base_url=""), None, tmp_path).chat("agent", [], None, "c", NOW)


def test_live_logs_tokens_and_unreachable_endpoint_falls_back(tmp_path, monkeypatch):
    db = Database(":memory:")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResponse())
    assert (
        LLMClient(LIVE, db, tmp_path).chat("fast", [{"role": "user", "content": "hi"}], None, "c1", NOW)
        == REPLY
    )
    row = db.df("SELECT model, input_tokens, output_tokens FROM llm_calls").iloc[0]
    assert (row["model"], row["input_tokens"], row["output_tokens"]) == ("fast-model", 11, 7)

    def refuse(*args, **kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "post", refuse)
    with pytest.raises(LLMUnavailable):
        LLMClient(LIVE, db, tmp_path).chat("agent", [], None, "c2", NOW)


def test_record_then_replay_without_network(tmp_path, monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResponse())
    LLMClient(replace(LIVE, llm_mode="record"), None, tmp_path).chat("agent", [], None, "case-1", NOW)
    monkeypatch.setattr(httpx, "post", lambda *a, **k: pytest.fail("replay must not call the network"))
    replay = LLMClient(replace(LIVE, llm_mode="replay"), None, tmp_path)
    assert replay.chat("agent", [], None, "case-1", NOW) == REPLY
    with pytest.raises(LLMUnavailable):
        replay.chat("agent", [], None, "case-1", NOW)
