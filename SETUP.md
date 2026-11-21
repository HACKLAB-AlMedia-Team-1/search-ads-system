# SETUP.md — Commands YOU run (not the AI agent)

Do every step here **yourself**, in order, before asking any AI agent to write code.
The coding agent is told (in `CLAUDE.md`) never to install packages or download data.
It only builds on what you set up here.

Time needed: ~30–45 min (mostly waiting for downloads).
Commands are shown for **Windows (Anaconda Prompt or PowerShell)**. Where macOS/Linux
differs, both versions are given.

---

## Step 0 — Things to have installed once

| Tool | Why we need it | Get it |
|------|----------------|--------|
| **Miniconda** (or Anaconda) | Creates an isolated Python "box" for this project, so its packages don't clash with other projects on your laptop. | https://docs.conda.io/en/latest/miniconda.html |
| **Git** | Saves versions of the code and pushes them to GitHub (we must submit a public repo). | https://git-scm.com/downloads |
| **Claude Code** (CLI) | The coding agent that will write the code with Sonnet. | https://docs.claude.com (Claude Code section) |
| A **GitHub** account | For the submission repo. | https://github.com |

Accounts and keys you need:

- **Linkup API key** (optional): app.linkup.so → API key. Only needed for `LINKUP_MODE=live`.
- **No LLM key is required.** The default `LLM_MODE=offline` uses a deterministic rule-based
  agent. No model is needed before Phase 6; then you may optionally run a local model
  (for example Ollama at `http://127.0.0.1:11434/v1`, no key needed).

You do **not** need a GPU. Everything runs on CPU.

---

## Step 1 — Open the project folder and save the kit in Git

The kit files are already in **`D:\hacklab-almedia`**. Open **Anaconda Prompt** and go there:

```bash
cd /d D:\hacklab-almedia
dir
```

You should see `README.md`, `SETUP.md`, `PLAN.md`, `CLAUDE.md`, `AGENTS.md`, `docs\`, etc.
(In PowerShell use `cd D:\hacklab-almedia` without `/d`.)

```bash
git init
git add .
git commit -m "Project kit: plan, setup, agent rules"
```

**Why:** `git init` turns the folder into a Git repository. The first commit saves the
plan files, so you can always see what the agent changed afterwards.

---

## Step 2 — Create the conda environment

```bash
conda env create -f environment.yml
conda activate rootsight
```

**What this does:** reads `environment.yml`, creates a new environment called
`rootsight` with **Python 3.11**, then installs every package listed in
`requirements.txt` using pip. `conda activate` switches your terminal into that box.
Every time you open a new terminal for this project, run `conda activate rootsight` first.

If it fails halfway (network hiccup), run:
```bash
conda activate rootsight
pip install -r requirements.txt
```

---

## Step 3 — What each package is for (simple words)

| Package | Why we need it |
|---------|----------------|
| `anthropic` | Legacy, currently unused. LLM calls will go through plain HTTP (`httpx`) in Phase 6. |
| `httpx` | Sends web requests. We use it to call the Linkup web search API. |
| `python-dotenv` | Reads your secret keys from the `.env` file so they are never written in code. |
| `pydantic` | Defines clean data shapes (a report, an incident) so nothing is malformed. |
| `pyyaml` | Reads `.yaml` files: the metric graph and the fault scenarios are written in YAML. |
| `pandas`, `numpy` | Tables and maths in Python. |
| `pyarrow` | Reads and writes Parquet, the compressed table format the dataset comes in. |
| `duckdb` | Our shop's database. A full SQL database that is just a file, with no server to run. |
| `huggingface_hub` | Gives the `hf` command that downloads the Amazon dataset (Step 6). |
| `rank-bm25` | **The search engine algorithm.** BM25 is the classic ranking method that real shops use as a baseline. |
| `snowballstemmer` | Cuts words to their root ("running" → "run", "zapatillas" → "zapatill") so search finds variants. Needed per language, which is exactly what the regional failure breaks. |
| `unidecode` | Removes accents ("canción" → "cancion") for Spanish search. |
| `scipy` | Statistics: median, MAD (a robust spread measure), correlation. Used by the watcher. |
| `networkx` | Builds the **metric graph** (nodes = metrics, edges = relationships). |
| `sqlglot` | Reads the SQL of a newly added metric, so the agent knows which tables and columns it uses. |
| `streamlit` | Builds the web UI (the shop + the control room) in pure Python. |
| `streamlit-agraph` | Draws the interactive metric graph inside Streamlit. |
| `plotly` | Charts with the "expected" band shaded. |
| `tqdm` | Progress bars while preparing data. |
| `pytest` | Runs automated tests, so we know each failure is detected correctly. |
| `ruff` | Keeps code tidy (formatting and simple mistakes). |

Check that everything installed:

```bash
python -c "import anthropic, httpx, dotenv, pydantic, yaml, pandas, numpy, pyarrow, duckdb, rank_bm25, snowballstemmer, unidecode, scipy, networkx, sqlglot, streamlit, plotly; print('ALL OK')"
```

You should see `ALL OK`. If a name is missing, run `pip install <that-package>`.

---

## Step 4 — Create your `.env`

```bash
# Windows PowerShell
Copy-Item .env.example .env
# Windows Anaconda Prompt (cmd)
copy .env.example .env
# macOS/Linux
cp .env.example .env
```

The defaults work as they are: `LLM_MODE=offline` and `LINKUP_MODE=offline` make no model
or web calls and cost nothing. No LLM key or model name is needed until Phase 6, and even
then only if you choose `live` / `record` (optionally with a local model such as Ollama).
Only fill in `LINKUP_API_KEY` if you decide to use live web search.

**Why:** `.env` may hold secrets and is listed in `.gitignore`, so it is never uploaded to GitHub.

---

## Step 5 — (Optional) Test the Linkup key (may cost a little)

Skip this unless you want `LINKUP_MODE=live`. No LLM test is needed.

**Linkup:**
```bash
python -c "import os,httpx; from dotenv import load_dotenv; load_dotenv(); r=httpx.post('https://api.linkup.so/v1/search',headers={'Authorization':'Bearer '+os.environ['LINKUP_API_KEY']},json={'q':'Is 27 November 2026 Black Friday?','depth':'standard','outputType':'sourcedAnswer'},timeout=60); print(r.status_code); print(r.text[:400])"
```
Expected: `200` and a short answer.
If it is not 200, check the current request format at https://docs.linkup.so and note
the working format in `docs/MEMORY.md` → "Environment facts".

---

## Step 6 — Download the Amazon ESCI dataset (required, ~1.2 GB)

**What it is:** real Amazon product search data, around **130k real customer queries** in
**English, Spanish and Japanese**, with product titles, descriptions, brands, and
human labels saying whether each result is relevant (Exact / Substitute / Complement /
Irrelevant). This gives our shop **real products and real searches**, and a ground truth
for "is this search result good?". Licence: Apache-2.0.

```bash
hf download milistu/amazon-esci-data --repo-type dataset --local-dir data/raw/esci
```

**What this does:** the `hf` command (from `huggingface_hub`) downloads the whole dataset
repository from Hugging Face into `data/raw/esci/`. No login is needed for public data.

If `hf` is "not recognized", use the older command name:
```bash
huggingface-cli download milistu/amazon-esci-data --repo-type dataset --local-dir data/raw/esci
```

**Fallback** (only if Hugging Face fails): the original Amazon GitHub repo. This needs Git LFS (https://git-lfs.com):
```bash
git lfs install
git clone https://github.com/amazon-science/esci-data.git data/raw/esci-github
```

---

## Step 7 — (Optional) Taobao user behaviour data, for a real traffic rhythm

**What it is:** ~100M real shopping actions from Alibaba's Taobao (Nov–Dec 2017). We use
it only to copy the **real hour-of-day and weekday traffic shape** into our simulator.
If you skip this, the code uses a built-in realistic curve. **The project works either way.**

1. Log in at https://tianchi.aliyun.com/dataset/649 (free Alibaba Cloud account).
2. Download `UserBehavior.csv.zip`, then unzip it (~3.5 GB).
3. Put the CSV here: `data/raw/taobao/UserBehavior.csv`

Skip this if the download is slow. It only makes the traffic curve "real" instead of "realistic".

---

## Step 8 — Record what you downloaded (so the agent knows)

```bash
python -c "import os; [print(os.path.join(r,f), round(os.path.getsize(os.path.join(r,f))/1e6,1),'MB') for r,_,fs in os.walk('data/raw') for f in fs]"
```

**Copy the output** and paste it into `docs/MEMORY.md` under **"Environment facts →
Downloaded files"**. Also fill in the other lines there: OS, Python version
(`python --version`), whether Taobao is present, and whether both key tests passed.

**Why:** the coding agent reads `MEMORY.md` first. With the exact file list, it can write
the data-loading code without guessing paths or downloading anything.

Then commit:
```bash
git add docs/MEMORY.md
git commit -m "Setup done: environment facts recorded"
```

---

## Step 9 — Create the GitHub repo

Create an empty repo called `rootsight` on GitHub (private for now, **public before submission**), then:

```bash
git remote add origin https://github.com/<your-username>/rootsight.git
git branch -M main
git push -u origin main
```

---

## Step 10 — Start the coding agent

```bash
conda activate rootsight
claude
```

Paste this **first prompt**:

```
Read CLAUDE.md, then docs/MEMORY.md, then PLAN.md, docs/DOSSIER.md and docs/SCENARIOS.md.
Setup is done by me (see Environment facts in MEMORY.md). Do not install or download anything.
Confirm in 5 bullet points what you understood, list anything missing from my setup,
then start Phase 0 of PLAN.md. Stop after Phase 0 and wait for my "go".
```

After each phase, check the summary, run the commands it gives you (for example
`pytest` or `streamlit run ...`), and reply `go` for the next phase.

**If the agent asks you to install a package:** it will give you the exact
`pip install ...` command and the reason. Run it yourself inside `conda activate rootsight`,
add the package to `requirements.txt`, and tell the agent "installed".

### Using Devin in parallel (optional)

Give Devin one self-contained phase at a time (good ones: **Phase 2 search engine** or
**Phase 8 UI**) with this prompt:

```
Repo: <github url>. Read AGENTS.md, docs/MEMORY.md and PLAN.md.
Implement only Phase <N> on a new branch `devin/phase-<N>`, following the acceptance
criteria exactly. Do not change other phases' files. Open a PR when tests pass.
```

Devin runs on its own machine, so it will set up its own environment using `environment.yml`.
That's fine, because it's Devin's machine, not yours. Review and merge its PRs yourself.

---

## Daily commands (cheat sheet)

```bash
conda activate rootsight                 # always first
python scripts/check_env.py              # is everything in place?
python scripts/prepare_data.py           # build data/processed (once)
python scripts/backfill.py               # simulate 14 clean days (once; --force to redo)
python scripts/demo.py                   # terminal demo on a private copy of the history
streamlit run app/Home.py                # the UI
pytest -q                                # fast tests; `pytest -m integration` for the full scenarios
```
