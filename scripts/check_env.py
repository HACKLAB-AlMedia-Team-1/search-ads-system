"""Check the local setup (packages, .env, ESCI data). Makes no network calls and writes nothing."""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]

PACKAGES = [
    "anthropic", "httpx", "dotenv", "pydantic", "yaml", "pandas", "numpy", "pyarrow", "duckdb",
    "huggingface_hub", "rank_bm25", "snowballstemmer", "unidecode", "scipy", "networkx", "sqlglot",
    "streamlit", "streamlit_agraph", "plotly", "tqdm", "pytest", "ruff",
]  # fmt: skip
LLM_MODES = {"offline", "live", "record", "replay"}
LINKUP_MODES = {"offline", "live"}
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _report(ok: bool, text: str) -> bool:
    print(f"[{'OK' if ok else 'FAIL'}] {text}")
    return ok


def _is_http_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
        return parts.scheme in {"http", "https"} and bool(parts.hostname)
    except ValueError:
        return False


def _is_loopback(url: str) -> bool:
    try:
        return _is_http_url(url) and urlsplit(url).hostname in LOOPBACK_HOSTS
    except ValueError:
        return False


def _esci_files(raw_dir: Path) -> list[Path]:
    base = raw_dir / "esci"
    if not base.is_dir():
        return []
    files = [p for p in base.rglob("*") if p.is_file()]
    files = [p for p in files if not any(part.startswith(".") for part in p.relative_to(base).parts)]
    return sorted(files)


def main() -> int:
    """Run every check, print a line per check, and return 1 if a required check failed."""
    sys.path.insert(0, str(ROOT))
    ok = True

    ok &= _report(sys.version_info[:2] == (3, 11), f"Python 3.11 (found {sys.version.split()[0]})")

    for name in PACKAGES:
        try:
            import_module(name)
            _report(True, f"package {name}")
        except ImportError:
            ok = _report(False, f"package {name} cannot be imported") and ok

    env_file = ROOT / ".env"
    if not env_file.is_file():
        print("[FAIL] .env is missing. Copy .env.example to .env (SETUP Step 4).")
        return 1

    from rootsight.config import load_settings

    try:
        settings = load_settings(env_file)
    except ValueError:
        print("[FAIL] .env could not be parsed (a value has the wrong format). Compare it with .env.example.")
        return 1

    llm_ok = settings.llm_mode in LLM_MODES
    ok &= _report(llm_ok, f"LLM_MODE valid ({settings.llm_mode if llm_ok else 'invalid value'})")
    link_ok = settings.linkup_mode in LINKUP_MODES
    ok &= _report(link_ok, f"LINKUP_MODE valid ({settings.linkup_mode if link_ok else 'invalid value'})")

    if settings.llm_mode in {"live", "record"}:
        has_url = bool(settings.llm_base_url)
        ok &= _report(has_url, f"LLM_BASE_URL {'set' if has_url else 'missing'}")
        if has_url:
            ok &= _report(_is_http_url(settings.llm_base_url), "LLM_BASE_URL is an http(s) URL")
        for label, value in (("LLM_MODEL_AGENT", settings.llm_model_agent),
                             ("LLM_MODEL_FAST", settings.llm_model_fast)):  # fmt: skip
            ok &= _report(bool(value), f"{label} {'set' if value else 'missing'}")
        if has_url and not _is_loopback(settings.llm_base_url):
            has_key = bool(settings.llm_api_key)
            ok &= _report(has_key, f"LLM_API_KEY {'set' if has_key else 'missing'} (required: non-local endpoint)")
        else:
            _report(True, f"LLM_API_KEY {'set' if settings.llm_api_key else 'missing'} (not required: local endpoint)")
    else:
        _report(True, f"LLM settings not needed in mode {settings.llm_mode}")

    if settings.linkup_mode == "live":
        has_key = bool(settings.linkup_api_key)
        ok &= _report(has_key, f"LINKUP_API_KEY {'set' if has_key else 'missing'}")
    else:
        _report(True, f"LINKUP_API_KEY {'set' if settings.linkup_api_key else 'missing'} (not needed in offline mode)")

    files = _esci_files(settings.data_raw_dir)
    for path in files:
        print(f"      {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")
    has_parquet = any(p.suffix == ".parquet" for p in files)
    if not _report(has_parquet, f"ESCI data in {settings.data_raw_dir / 'esci'} ({len(files)} files, need a .parquet)"):
        print("      Download it with SETUP Step 6: hf download milistu/amazon-esci-data --repo-type dataset --local-dir data/raw/esci")
        ok = False

    print("All checks passed." if ok else "Some required checks failed.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
