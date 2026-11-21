"""Settings loading: process env wins for modes, paths resolve from the project root, secrets are hidden."""

from rootsight.config import PROJECT_ROOT, load_settings


def test_load_settings(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("LLM_MODE=live\nLLM_API_KEY=test-only-secret\nDATA_RAW_DIR=custom/raw\n")
    monkeypatch.setenv("LLM_MODE", "offline")

    settings = load_settings(env_file)

    assert settings.llm_mode == "offline"
    assert settings.data_raw_dir == PROJECT_ROOT / "custom/raw"
    assert settings.llm_api_key == "test-only-secret"
    assert "test-only-secret" not in repr(settings)
