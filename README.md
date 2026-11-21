# RootSight — AdSearch Sentinel

An autonomous AI agent that watches a marketplace's **advertising and search** metrics,
detects problems by itself, traces them back to the release or config change that
caused them, estimates the cost, and writes an evidence-based report.

Built for the hackathon track **"Eye of the System: Fully Agentic Monitoring"** (Almedia).

---

## Read these files in this order

| # | File | Who it is for | What it contains |
|---|------|---------------|------------------|
| 1 | `SETUP.md` | **You (human)** | Every command you run yourself: conda env, packages, API keys, dataset downloads. With simple explanations. Do this **before** any AI agent writes code. |
| 2 | `CLAUDE.md` | Claude Code (Sonnet) | Rules the coding agent must follow (it must NOT install or download anything). |
| 3 | `AGENTS.md` | Devin / any other coding agent | Same rules, short form. |
| 4 | `PLAN.md` | Coding agent + team | The full build plan: phases, files, acceptance tests. |
| 5 | `docs/DOSSIER.md` | Everyone | The project in one place: brief, idea, scenarios, architecture, demo, pitch. |
| 6 | `docs/SCENARIOS.md` | Coding agent | Exact spec of every failure we inject and how the agent tells them apart. |
| 7 | `docs/MEMORY.md` | Coding agent (updates it) | Living project memory: status, decisions, environment facts, session log. |

## Quick start

1. Follow `SETUP.md` from top to bottom (about 30–45 minutes, mostly downloads).
2. Open the folder in Claude Code and paste the **first prompt** from the end of `SETUP.md`.
3. The agent builds one phase of `PLAN.md` at a time and updates `docs/MEMORY.md` after each.

## Deadline

Submission closes **Sunday 22 Nov 2026, 16:30** (form: https://tally.so/r/GexoxQ).
Code freeze: **Sunday 12:00**.
