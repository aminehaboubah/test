# Paper Draft

Part one of the Paper Parse workflow: from a researcher's results to the first version of the paper.
Paper Parse (part two) takes that draft and handles reading, editing, review and export.

**Step 1 (this version): materials overview.** The user uploads what they already have: the code that
produced their results, the result files (CSV, TXT, JSON, XLSX…), the figures, and a draft paper if
one exists (for example one written with an off-the-shelf AI model that they are not happy with).
The app returns a one-page, dashboard-style overview:

- what the work is about and what the materials show (key findings, each with the files behind it)
- a readiness score
- what is missing or should be added (critical / important / nice to have, with how to fix each)
- coverage of each paper section
- a check of the draft against the results (when there is a draft)
- every figure with what it shows, a starting caption, and quality issues
- how scripts, data and figures connect (which script reads and writes what)
- every file with its role and status
- questions for the author and ordered next steps

The look (colours, type, components) is taken from Paper Parse; `app/static/base.css` is copied from
its "Your space" page so the two parts match.

## Run

```bash
pip install -r requirements.txt
export DEEPINFRA_API_KEY=...        # AI review through Deep Infra (two agents, below)
python app/server.py                # http://127.0.0.1:8765
```

Never commit the key; keep it in the environment (or a local `.env` you do not check in).
Without `DEEPINFRA_API_KEY` the app falls back to `ANTHROPIC_API_KEY` (single Claude call) and,
without either, to a local scan.

| Variable | Default | Meaning |
|---|---|---|
| `PAPER_DRAFT_ORCHESTRATOR` | `google/gemini-3.7-flash` | Deep Infra model that plans and writes the overview |
| `PAPER_DRAFT_EXECUTOR` | `anthropic/claude-haiku-4-5` | Deep Infra model that reads files and runs checks |
| `PAPER_DRAFT_PLAN_EFFORT` / `PAPER_DRAFT_REVIEW_EFFORT` | `medium` / `high` | Orchestrator reasoning effort |
| `PAPER_DRAFT_WORKERS` | `6` | Parallel executor calls |
| `HOST`, `PORT`, `PAPER_DRAFT_DATA` | `127.0.0.1`, `8765`, `data/projects` | Server and storage |
| `PAPER_DRAFT_DEBUG` | unset | Log every model call with its duration |

## Two-level agents (`app/agents.py`)

1. **Orchestrator plans.** It sees the file inventory only (types, sizes, data profiles, which
   script reads/writes which file) and returns a focus for every file plus 3-8 cross-checks that
   need several files (e.g. "do the draft's numbers match `results/summary_stats.txt`?").
2. **Executors read files**, in parallel: each gets one file (text, data profile + sample, or the
   figure image) and returns a structured note: role, summary, exact numbers, issues, and for
   figures/drafts what they show or claim.
3. **Executors run the cross-checks**, each returning ok / warning / problem with the values quoted.
4. **Orchestrator writes the overview** from the inventory, the notes and the check results.

Every call uses a strict JSON schema; the dashboard's "How this overview was made" panel shows the
plan, the cross-checks and each call's time and tokens.

On the sample project a full run takes about 1.5-2 minutes: the orchestrator (Gemini 3.7 Flash)
needs ~10 s to plan and ~60 s to write the overview, and the 16-19 executor calls run in parallel
in about 25 s of wall time. (With `openai/gpt-oss-120b` as orchestrator the same run took ~6 minutes.)
Deep Infra currently appears to ignore the reasoning-effort setting for Gemini 3.7 Flash.

To try it, upload one of the samples (see `samples/SOURCES.md`):

- `samples/18650-clustering-zenodo` — a real open dataset with code (CC BY 4.0); choose "No paper yet".
- `samples/battery-study` — synthetic, with a deliberately flawed AI draft; choose "I have a draft".

## How it works

1. **Upload** – files, whole folders, or zips (unpacked on the server) are stored under
   `data/projects/<id>/files/`.
2. **Local inventory** (`app/inventory.py`) – every file is classified (data / code / figure / doc)
   and profiled: table shape and per-column statistics, script imports, the file names each script
   reads and writes, image sizes, document headings and word counts, whether a document looks like a
   paper. Scripts are linked to the data and figures they mention.
3. **AI review** – with Deep Infra, the two-level agents above. With only an Anthropic key
   (`app/analyze.py`), Claude receives the profiles (data is summarised, not sent row
   by row), the scripts and draft text, figures as images, PDF drafts as documents, and returns a
   structured review validated against a Pydantic schema (`ProjectReview`). Anything not sent in full
   is listed at the bottom of the dashboard.
   Without credentials, a **local scan** fills the same schema from heuristics.
4. **Dashboard** (`app/static/`) – plain HTML/CSS/JS, one page.

## Privacy

Files stay on the machine running the server. With AI review on, the contents described above are
sent to Deep Infra (or the Anthropic API when only an Anthropic key is set).
