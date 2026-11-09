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
export ANTHROPIC_API_KEY=...        # optional; without it the app runs a local scan only
python app/server.py                # http://127.0.0.1:8765
```

`HOST`, `PORT`, `PAPER_DRAFT_DATA` (where projects are stored, default `data/projects`) and
`PAPER_DRAFT_MODEL` (default `claude-opus-5-5`) can be set in the environment.

To try it, upload the folder `samples/battery-study` and choose "I have a draft".

## How it works

1. **Upload** – files, whole folders, or zips (unpacked on the server) are stored under
   `data/projects/<id>/files/`.
2. **Local inventory** (`app/inventory.py`) – every file is classified (data / code / figure / doc)
   and profiled: table shape and per-column statistics, script imports, the file names each script
   reads and writes, image sizes, document headings and word counts, whether a document looks like a
   paper. Scripts are linked to the data and figures they mention.
3. **AI review** (`app/analyze.py`) – Claude receives the profiles (data is summarised, not sent row
   by row), the scripts and draft text, figures as images, PDF drafts as documents, and returns a
   structured review validated against a Pydantic schema (`ProjectReview`). Anything not sent in full
   is listed at the bottom of the dashboard.
   Without credentials, a **local scan** fills the same schema from heuristics.
4. **Dashboard** (`app/static/`) – plain HTML/CSS/JS, one page.

## Privacy

Files stay on the machine running the server. With AI review on, the contents described above are
sent to the Anthropic API.
