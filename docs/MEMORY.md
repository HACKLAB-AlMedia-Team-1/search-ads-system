# MEMORY.md — Project memory (read first, keep current)

Shared memory for every agent session and every teammate. Keep it short. Newest log entries first.

## Environment facts (filled in by the HUMAN after SETUP.md)

- OS: Windows
- Python version (`python --version`): 3.11.18
- Conda env name: `rootsight`
- `scripts/check_env.py` result: 2026-11-21 all packages + modes OK; only ESCI missing (exit 1)
- Anthropic: legacy package installed but not used; no Anthropic key or test needed.
- Linkup key test (SETUP Step 5): <passed / failed>   Working request format: <default from SETUP / changed to ...>
- ESCI downloaded via: <hf / huggingface-cli / github-lfs>
- Taobao UserBehavior present: <yes / no>
- Downloaded files (paste output of SETUP Step 8):
```
<paste here>
```

## Status

| Phase | Name | Status | Notes |
|-------|------|--------|-------|
| Setup | Human setup (SETUP.md) | in progress | env done; ESCI (Step 6) not downloaded yet |
| 0 | Bootstrap | blocked | code written; acceptance needs ESCI so `check_env.py` is green |
| 1 | Data preparation | todo | |
| 2 | Search engine + faults | todo | Devin candidate |
| 3 | Simulator, ads, database | todo | |
| 4 | Metric graph | todo | |
| 5 | Watcher | todo | |
| 6 | Investigator agent + incidents | todo | core |
| 7 | New-metric onboarding | todo | |
| 8 | Streamlit UI | todo | Devin candidate |
| 9 | Demo hardening + docs | todo | code freeze Sun 12:00 |

Scenario build status: S1 todo · AD1 todo · EV1 todo · DQ1 todo · S12 todo · S3 todo · S2 todo · S7 todo · S15 todo

## Decisions (dated, one line each, with reason)

- 2026-11-21 · Project = RootSight / AdSearch Sentinel: ads + search monitoring on one metric graph. Reason: strongest story + covers 40/40/20.
- 2026-11-21 · Data = Amazon ESCI (products + real queries EN/ES/JP + relevance labels) + optional Taobao traffic rhythm. Reason: real text and ground truth for search quality; Taobao has no text.
- 2026-11-21 · Ads are simulated (€1,000/day, 3 campaigns). Reason: the public Taobao ad dataset is a 2.44 GB preprocessed zip, too heavy for the time we have.
- 2026-11-21 · Markets US (en), ES (es), JP (ja). The regional failure uses Spanish (ESCI has no German).
- 2026-11-21 · Must scenarios: S1, S12, S3, AD1, EV1, DQ1. Should: S2, S7. Could: S15.
- 2026-11-21 · Numbers and the evidence checklist are computed in code; the LLM chooses tools, judges relevance and writes the story.
- 2026-11-21 · LLM_MODE offline by default; record/replay for the demo. Budget: Claude $25, Linkup $20.
- 2026-11-21 · Runtime: offline deterministic by default; optional local Ollama (OpenAI-compatible, two roles agent/fast, no key on loopback); optional cloud only if explicitly chosen later; evidence stays deterministic; offline demo needs no recording. No Anthropic key (package unused). Reason: no paid dependency.
- 2026-11-21 · The human does all installs/downloads; agents never install or download (see CLAUDE.md).

## Open questions

- Team size and who owns which phase? (default plan assumes 3–4 people + Devin)
- Exact Claude model names confirmed in SETUP Step 5?

## Ideas / later (not in scope unless time is left)

- Search latency failure (#6), checkout failure (#11), feed quality (#13) as extra scenarios.
- Slack-style alert output.

## Session log (newest first)

- 2026-11-21 · Phase 0 bootstrap (branch devin/phase-0): package skeleton with docstring-only modules, `config.py` (Settings, `load_settings`), `logging_setup.py`, `scripts/check_env.py`, `pyproject.toml`, `tests/test_config.py`.
- `.env.example`, SETUP Steps 0/3/4/5 changed to an LLM-key-free, offline-default setup (Linkup optional). No monitoring, agent, or UI implemented yet.
- Blocked on ESCI: human runs SETUP Step 6, then `python scripts/check_env.py` before Phase 1.

- 2026-11-21 · Kit created: README, SETUP, CLAUDE, AGENTS, PLAN, DOSSIER, SCENARIOS, MEMORY, environment.yml, requirements.txt, .env.example. Next: human runs SETUP.md, then Phase 0.
