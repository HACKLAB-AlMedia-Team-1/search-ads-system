# AGENTS.md — Rules for Devin and other coding agents

This repo is **RootSight — AdSearch Sentinel**, a hackathon project (deadline Sun 22 Nov 2026, 16:30).
The full rules are in `CLAUDE.md`. They apply to you too. The short version:

1. **Read first:** `CLAUDE.md`, `docs/MEMORY.md`, `PLAN.md` (your assigned phase), `docs/SCENARIOS.md`.
2. **Scope:** implement only the phase you were assigned, on a branch `devin/phase-<N>`. Don't touch other phases' files.
3. **Environment:** on your own machine you may create the env with `conda env create -f environment.yml`.
   Do not add packages that are not in `requirements.txt`. If you need one, say so in the PR description.
4. **Data:** if the phase needs the ESCI dataset, download it exactly as in `SETUP.md` Step 6 (on your machine only).
   Never commit anything in `data/`.
5. **Money:** keep `LLM_MODE=offline` and `LINKUP_MODE=offline`. Never call paid APIs.
6. **Done means:** the phase's acceptance criteria in `PLAN.md` pass, `pytest -q` is green, `ruff check .` is clean,
   and the PR description lists what you built, how to run it, and any decision you made.
7. **LLM:** every model call goes through `rootsight/agent/llm.py` and must have a rule-based fallback (investigator,
   `agent/narrate.py`, `sim/custom.py`, `graph/onboarding.py`). Never send a key to a provider that did not issue it.
   Tests that edit metrics use a temp copy of `metrics.yaml`. Rules vs models: `docs/MODEL_COMPARISON.md`.
8. **Memory:** add a short entry to `docs/MEMORY.md` → "Session log" in your PR (newest first).
