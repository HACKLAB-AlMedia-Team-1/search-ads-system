# CLAUDE.md — Rules for the coding agent

You are building **RootSight — AdSearch Sentinel** for a hackathon (deadline Sun 22 Nov 2026, 16:30;
code freeze Sun 12:00). Work fast, but follow these rules exactly.

## 1. Start of every session

Read in this order, before writing any code:
1. `CLAUDE.md` (this file)
2. `docs/MEMORY.md`: current status, decisions, environment facts, last session's notes
3. `PLAN.md`: only the current phase in detail, plus the overall architecture
4. `docs/SCENARIOS.md` and `docs/DOSSIER.md`: when the phase needs them

Then state in 3–5 bullets: current phase, what is already done, what you will do now.

## 2. Hard rules: environment, installs, downloads

- **Never** run `pip install`, `conda install`, `conda create`, `npm install`, or any package manager.
- **Never** download datasets, models or files from the internet (`hf download`, `wget`, `curl`, `git clone`, ...).
- The human sets up everything (see `SETUP.md`). The environment is the conda env `rootsight` (Python 3.11).
- If something is missing (a package, a file, a key), **stop** and tell the human:
  - the exact command to run (e.g. `pip install foo>=1.2`),
  - one sentence explaining why it is needed in simple words,
  - and ask them to add it to `requirements.txt`.
  Then wait.
- Only use packages that are in `requirements.txt` (plus the Python standard library).
- You **may** run: `python ...`, `pytest`, `ruff`, `git status/diff/add/commit`, and `streamlit run` for a quick check.

## 3. Hard rules: money (Claude API + Linkup)

- During development and in all tests use `LLM_MODE=offline` and `LINKUP_MODE=offline`.
- Never run anything with `LLM_MODE=live|record` or `LINKUP_MODE=live` unless the human says so in this session.
- Every LLM call goes through `rootsight/agent/llm.py` (one place handles modes, caching, recording and token logging).
- Never print or log API keys. Keys come only from `.env` via `rootsight/config.py`.

## 4. How to work

- Build **one phase of `PLAN.md` at a time**. At the end of a phase:
  1. run `pytest -q` and `ruff check .`, and fix failures,
  2. update `docs/MEMORY.md` (status table, decisions, session log, next step),
  3. `git add -A && git commit -m "Phase N: <summary>"`,
  4. give the human a short summary: what works, the commands they can run to see it, what's next.
  Then **stop and wait for "go"**.
- Meet the phase's **acceptance criteria** before calling it done. If you can't, say which one fails and why.
- Do not change scope. Ideas for extra features go into `docs/MEMORY.md` → "Ideas / later", not into code.
- If `PLAN.md` and reality conflict (e.g. dataset columns differ), choose the simplest fix,
  write it in MEMORY.md → "Decisions", and continue.
- Prefer small, readable modules over clever code. Judges will read the repo.

## 5. Code conventions

- Python 3.11, type hints everywhere, docstrings on public functions (1–3 lines).
- Package code lives in `rootsight/`; runnable entry points in `scripts/`; UI in `app/`; tests in `tests/`.
- All configuration comes from `rootsight/config.py` (reads `.env`). No hard-coded paths or keys.
- All randomness is seeded from `SIM_SEED`, so runs are reproducible (important for the demo).
- Data files: raw in `data/raw/` (read-only, never modify), processed in `data/processed/`, database `data/rootsight.duckdb`.
- **Numbers in reports must come from tool results.** The LLM never computes or invents numbers.
- The 4-point evidence checklist is computed **in code** (`rootsight/agent/evidence.py`), not judged by the LLM.
- Log in plain English with the `logging` module; no print statements in package code.
- Tests must run offline in < 60 s total (use a small sample of the data).

## 6. Memory file discipline

`docs/MEMORY.md` is the project's shared memory across sessions and agents. Keep it short and current:
- Status table: one row per phase, status `todo / in progress / done / blocked`.
- Decisions: one line each, dated, with the reason.
- Session log: newest first, 3–6 bullets per session.
- Do not paste code or long outputs into it.

## 7. When stuck

After 2 failed attempts at the same problem, stop, explain the problem in plain words,
give 2 options, and ask the human which one to take.
