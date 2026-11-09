"""Turn a project manifest into the one-page overview.

Two paths:
  * AI review  - Claude reads the profiled files, the scripts, the draft and the figures
                 and returns a structured review (needs Anthropic credentials).
  * Local scan - heuristics only, so the dashboard still works without credentials.
"""
from __future__ import annotations

import base64
import io
import json
import os
from pathlib import Path
from typing import Callable, Literal, Optional

from pydantic import BaseModel

from inventory import TEXT_LIMIT

MODEL = os.environ.get("PAPER_DRAFT_MODEL", "claude-opus-5-5")
MAX_IMAGES = 40
MAX_IMAGE_SIDE = 1568
MAX_PDF_BYTES = 20 * 1024 * 1024
TOTAL_TEXT_BUDGET = 900_000  # chars across all scripts/docs sent to the model


# --------------------------------------------------------------------------- schema

class Readiness(BaseModel):
    score: int                      # 0-100
    label: str                      # e.g. "Early", "Needs work", "Nearly ready"
    rationale: str


class Finding(BaseModel):
    finding: str
    evidence_files: list[str]
    strength: Literal["strong", "moderate", "weak"]


class FileInsight(BaseModel):
    path: str
    role: str                       # e.g. "main analysis script", "raw measurements"
    summary: str
    status: Literal["good", "needs_attention", "unclear"]
    note: str


class FigureReview(BaseModel):
    path: str
    what_it_shows: str
    suggested_caption: str
    produced_by: str                # script path, or "unknown"
    quality_issues: list[str]
    keep_for_paper: Literal["main", "supplementary", "drop", "unsure"]


class Gap(BaseModel):
    item: str
    why_it_matters: str
    severity: Literal["critical", "important", "nice_to_have"]
    category: Literal["data", "code", "figures", "text", "references", "reproducibility", "metadata"]
    how_to_fix: str


class SectionCoverage(BaseModel):
    section: str
    status: Literal["covered", "partial", "missing"]
    supported_by: list[str]
    note: str


class DraftReview(BaseModel):
    path: str
    overall: str
    strengths: list[str]
    weaknesses: list[str]
    ai_style_signals: list[str]     # generic phrasing, unsupported claims, invented citations...


class Check(BaseModel):
    check: str
    status: Literal["ok", "warning", "problem"]
    detail: str


class ProjectReview(BaseModel):
    title_guess: str
    one_line_summary: str
    research_summary: str
    field: str
    paper_type: str                 # e.g. "journal article (experimental)"
    readiness: Readiness
    key_findings: list[Finding]
    file_insights: list[FileInsight]
    figures: list[FigureReview]
    gaps: list[Gap]
    coverage: list[SectionCoverage]
    draft_reviews: list[DraftReview]
    consistency_checks: list[Check]
    questions_for_author: list[str]
    next_steps: list[str]


SYSTEM = """You review a researcher's materials before a paper is written or rewritten. \
They have already done the work: code that produced results (tables, logs, CSV and similar) \
and figures. Your job is the "last mile" overview: what they have, what it shows, and what \
is missing or should be added before a strong paper can be written.

Ground everything in the files you are given and name the files you rely on. Do not invent \
results, numbers, citations or methods. When something cannot be determined from the \
files, say so and put it in questions_for_author.

Scenario handling:
- "draft": the user already has a paper (often produced with an off-the-shelf AI model) and \
is not satisfied. Review it against the evidence: claims without support, numbers that do not \
match the data, figures referenced but absent (or present but unused), missing sections, \
generic AI-sounding prose, invented or missing references.
- "fresh": no paper yet. Judge whether the materials can support a paper, and which sections \
they already cover.

Field guidance:
- readiness.score is 0-100: how close the materials are to supporting a submission-quality paper.
- coverage lists the standard sections for this kind of paper (title, abstract, introduction, \
related work, methods, results, discussion, conclusion, references, data availability, code \
availability, plus field-specific ones) with what supports each.
- file_insights covers every file the user uploaded, using the exact paths given.
- figures covers every figure file, using the exact paths given.
- gaps are concrete and actionable, ordered from most to least severe.
- next_steps is a short ordered plan (5-8 items).
- Write for the researcher: plain, specific, brief."""


# --------------------------------------------------------------------------- AI path

def _image_block(path: Path) -> dict | None:
    from PIL import Image
    try:
        with Image.open(path) as im:
            im.load()
            if max(im.size) > MAX_IMAGE_SIDE:
                im.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
            if im.mode not in ("RGB", "L"):
                bg = Image.new("RGB", im.size, "white")
                bg.paste(im.convert("RGBA"), mask=im.convert("RGBA").split()[-1])
                im = bg
            buf = io.BytesIO()
            im.save(buf, "PNG", optimize=True)
    except Exception:  # noqa: BLE001 - unreadable image: describe it in text instead
        return None
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                         "data": base64.standard_b64encode(buf.getvalue()).decode()}}


def _pdf_block(path: Path) -> dict:
    return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                            "data": base64.standard_b64encode(path.read_bytes()).decode()}}


def build_content(root: Path, manifest: dict, scenario: str, notes: str) -> tuple[list[dict], list[str]]:
    """User-message content blocks, plus notes on anything not sent in full."""
    omitted: list[str] = []
    budget = TOTAL_TEXT_BUDGET
    slim_files = []
    texts: list[tuple[str, str]] = []
    for f in manifest["files"]:
        prof = dict(f.get("profile", {}))
        text = prof.pop("_text", None)
        slim = {k: v for k, v in f.items() if k != "profile"}
        slim["profile"] = prof
        slim_files.append(slim)
        if text and f["kind"] in ("script", "doc"):
            if f["ext"] == ".pdf" and prof.get("looks_like_paper") and f["bytes"] <= MAX_PDF_BYTES:
                continue  # sent as a PDF document block below
            shown = text[:min(TEXT_LIMIT, max(budget, 0))]
            budget -= len(shown)
            if len(shown) < len(text):
                omitted.append(f"{f['path']}: showing the first {len(shown):,} of {len(text):,} characters")
            if shown:
                texts.append((f["path"], shown))

    head = {
        "scenario": scenario,
        "author_notes": notes or "(none)",
        "counts": manifest["counts"],
        "environment_files": manifest["env_files"],
        "readme_files": manifest["readme"],
        "files": slim_files,
        "not_sent_in_full": omitted,
    }
    content: list[dict] = [{"type": "text", "text":
                            "Project inventory (profiled locally; data files are summarised, not sent row by row):\n"
                            + json.dumps(head, indent=1, default=str)}]
    for path, text in texts:
        content.append({"type": "text", "text": f"<file path=\"{path}\">\n{text}\n</file>"})

    images = 0
    for f in manifest["files"]:
        p = root / f["path"]
        if f["kind"] == "figure":
            if f["ext"] == ".pdf":
                if f["bytes"] <= MAX_PDF_BYTES:
                    content += [{"type": "text", "text": f"Figure file: {f['path']}"}, _pdf_block(p)]
                else:
                    omitted.append(f"{f['path']}: PDF figure too large to send")
                continue
            if f["ext"] in (".svg", ".eps"):
                omitted.append(f"{f['path']}: vector figure described from its text labels only")
                continue
            if images >= MAX_IMAGES:
                omitted.append(f"{f['path']}: not shown (image limit of {MAX_IMAGES} reached)")
                continue
            block = _image_block(p)
            if block:
                content += [{"type": "text", "text": f"Figure file: {f['path']}"}, block]
                images += 1
            else:
                omitted.append(f"{f['path']}: image could not be opened")
        elif f["kind"] == "doc" and f["ext"] == ".pdf" and f.get("profile", {}).get("looks_like_paper"):
            if f["bytes"] <= MAX_PDF_BYTES:
                content += [{"type": "text", "text": f"Draft paper (PDF): {f['path']}"}, _pdf_block(p)]
            else:
                omitted.append(f"{f['path']}: draft PDF too large; extracted text profile only")

    content.append({"type": "text", "text":
                    f"Scenario: {scenario}. Produce the overview for this project."})
    return content, omitted


def ai_review(root: Path, manifest: dict, scenario: str, notes: str,
              stage: Callable[[str], None]) -> dict:
    import anthropic

    content, omitted = build_content(root, manifest, scenario, notes)
    stage("Claude is reading your files")
    client = anthropic.Anthropic()
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=64000,
        system=SYSTEM,
        messages=[{"role": "user", "content": content}],
        output_config={"effort": "high"},
        output_format=ProjectReview,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    ) as stream:
        written = 0
        for event in stream:
            if event.type == "content_block_delta" and getattr(event.delta, "type", "") == "text_delta":
                written += len(event.delta.text)
                if written % 2000 < len(event.delta.text):
                    stage("Writing the overview")
        msg = stream.get_final_message()

    if msg.stop_reason == "refusal":
        raise RuntimeError("The model declined to review these files.")
    if msg.stop_reason == "max_tokens":
        raise RuntimeError("The overview was cut off (output limit reached).")
    review = msg.parsed_output
    if review is None:
        raise RuntimeError("The model did not return a valid overview.")
    usage = msg.usage
    return {
        "mode": "ai",
        "model": msg.model,
        "review": review.model_dump(),
        "omitted": omitted,
        "usage": {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
                  "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0},
        "request_id": getattr(msg, "_request_id", None),
    }


def have_credentials() -> bool:
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    return (Path.home() / ".config" / "anthropic").exists()


# --------------------------------------------------------------------------- local path

STANDARD_SECTIONS = ["Title & abstract", "Introduction", "Related work", "Methods", "Results",
                     "Discussion", "Conclusion", "References", "Data availability", "Code availability"]
SECTION_KEYS = {"Title & abstract": ["abstract"], "Introduction": ["introduction"],
                "Related work": ["related", "background", "literature"],
                "Methods": ["method", "material", "experiment", "approach"],
                "Results": ["result", "evaluation", "finding"], "Discussion": ["discussion"],
                "Conclusion": ["conclusion", "summary"], "References": ["reference", "bibliography"],
                "Data availability": ["data availability"], "Code availability": ["code availability"]}


def local_review(manifest: dict, scenario: str, notes: str) -> dict:
    files = manifest["files"]
    c = manifest["counts"]
    by_kind = {k: [f for f in files if f["kind"] == k] for k in ("data", "script", "figure", "doc")}
    drafts = [f for f in by_kind["doc"] if f["profile"].get("looks_like_paper")]
    gaps: list[dict] = []

    def gap(item, why, sev, cat, fix):
        gaps.append(dict(item=item, why_it_matters=why, severity=sev, category=cat, how_to_fix=fix))

    if not by_kind["data"]:
        gap("No result data files", "Numbers in the paper need a traceable source.", "critical", "data",
            "Upload the CSV/TXT/JSON outputs your scripts produced.")
    if not by_kind["script"]:
        gap("No code", "Reviewers and readers expect the analysis to be reproducible.", "important", "code",
            "Upload the scripts or notebooks that produced the results and figures.")
    if not by_kind["figure"]:
        gap("No figures", "Most papers carry their main result in a figure.", "important", "figures",
            "Upload the figures, or the scripts that generate them.")
    if scenario == "draft" and not drafts:
        gap("Draft paper not found", "You said you have a draft, but no uploaded document looks like a paper.",
            "critical", "text", "Upload the draft as .docx, .tex, .md or .pdf.")
    if not manifest["readme"]:
        gap("No README", "Explains how files relate and how to rerun the analysis.", "nice_to_have",
            "reproducibility", "Add a short README listing each script, its inputs and outputs.")
    if by_kind["script"] and not manifest["env_files"]:
        gap("No environment file", "Without versions the code may not run for others.", "important",
            "reproducibility", "Add requirements.txt / environment.yml (or equivalent).")
    for s in by_kind["script"]:
        for ref in s["profile"].get("missing_refs", []):
            gap(f"{s['path']} uses {ref}, which was not uploaded",
                "The script cannot be checked or rerun without it.", "important", "data",
                f"Upload {ref} or fix the path in the script.")
    orphan_figs = [f for f in by_kind["figure"] if not f["produced_by"]]
    if orphan_figs and by_kind["script"]:
        gap(f"{len(orphan_figs)} figure(s) with no generating script",
            "Figure provenance matters for revisions and reproducibility.", "nice_to_have", "figures",
            "Upload the plotting code, or note how each figure was made: "
            + ", ".join(f["path"] for f in orphan_figs[:5]))
    low_res = [f for f in by_kind["figure"] if f["profile"].get("width") and max(
        f["profile"]["width"], f["profile"].get("height", 0)) < 1000]
    if low_res:
        gap(f"{len(low_res)} low-resolution figure(s)", "Journals usually need about 300 dpi at print size.",
            "important", "figures", "Re-export as vector (PDF/SVG) or at higher resolution: "
            + ", ".join(f["path"] for f in low_res[:5]))
    if by_kind["script"] and not any(s["profile"].get("random_seed") for s in by_kind["script"]):
        gap("No random seed found in the code", "Stochastic results should be repeatable.", "nice_to_have",
            "reproducibility", "Set and report seeds if any step is random.")
    if not any(f["ext"] == ".bib" for f in files) and not any(
            (f["profile"].get("citations_found") or 0) > 0 for f in by_kind["doc"]):
        gap("No references", "A paper needs to position the work against prior literature.", "important",
            "references", "Add a .bib file or a reference list.")

    headings = " ".join(" ".join(d["profile"].get("headings", [])) + " " for d in drafts).lower()
    coverage = []
    for sec in STANDARD_SECTIONS:
        hit = any(k in headings for k in SECTION_KEYS[sec])
        coverage.append(dict(section=sec, status="covered" if hit else "missing",
                             supported_by=[d["path"] for d in drafts] if hit else [],
                             note="Found in draft headings." if hit else
                             ("Not found in the draft." if drafts else "No draft yet.")))

    score = 0
    score += 25 if by_kind["data"] else 0
    score += 20 if by_kind["script"] else 0
    score += 20 if by_kind["figure"] else 0
    score += 15 if drafts else 0
    score += 10 if manifest["env_files"] else 0
    score += 10 if manifest["readme"] else 0
    score -= 5 * sum(g["severity"] == "critical" for g in gaps)
    score = max(0, min(60, score))  # a local scan sees which materials exist, not their quality
    label = "Early" if score < 30 else "Content not checked yet"

    def role(f):
        p = f["profile"]
        if f["kind"] == "script":
            if not p.get("lines") and Path(f["path"]).name.lower() in {"requirements.txt", "environment.yml"}:
                return "environment"
            outs = p.get("files_written", [])
            if any(Path(o).suffix.lower() in (".png", ".pdf", ".svg", ".jpg", ".eps") for o in outs):
                return "figure generation"
            return "analysis / processing" if outs else "code"
        if f["kind"] == "data":
            return "result data" if f["produced_by"] else "input or result data"
        if f["kind"] == "doc":
            return "draft paper" if p.get("looks_like_paper") else (
                "bibliography" if f["ext"] == ".bib" else "document")
        return f["kind"]

    def summary(f):
        p = f["profile"]
        if f["kind"] == "data" and "rows" in p:
            cols = ", ".join(c["name"] for c in p.get("columns", [])[:6])
            return f"{p['rows']:,} rows × {p.get('column_count', 0)} columns ({cols})"
        if f["kind"] == "script":
            return f"{p.get('language', '')}, {p.get('lines', 0)} lines; writes {len(p.get('files_written', []))} file(s)"
        if f["kind"] == "doc":
            return f"{p.get('words', 0):,} words, {len(p.get('headings', []))} headings"
        if f["kind"] == "figure" and p.get("width"):
            return f"{p['width']}×{p['height']} px"
        return f"{f['bytes']:,} bytes"

    insights = [dict(path=f["path"], role=role(f), summary=summary(f),
                     status="needs_attention" if (f["kind"] == "figure" and f in low_res) or
                     (f["kind"] == "script" and f["profile"].get("missing_refs")) else "good",
                     note="") for f in files if f["kind"] != "other"]
    figures = [dict(path=f["path"], what_it_shows="Not analysed in a local scan.", suggested_caption="",
                    produced_by=f["produced_by"][0] if f["produced_by"] else "unknown",
                    quality_issues=["Low resolution"] if f in low_res else [],
                    keep_for_paper="unsure") for f in by_kind["figure"]]
    heads = drafts[0]["profile"].get("headings") if drafts else None
    title = heads[0] if heads else (Path(drafts[0]["path"]).stem.replace("_", " ") if drafts else "Your project")
    order = {"critical": 0, "important": 1, "nice_to_have": 2}
    gaps.sort(key=lambda g: order[g["severity"]])
    review = dict(
        title_guess=title,
        one_line_summary=", ".join(f"{n} {w if n == 1 else w + 's'}" for n, w in
                                   ((c["data"], "data file"), (c["script"], "script"), (c["figure"], "figure"),
                                    (c["doc"], "document"))) + ".",
        research_summary="This is a local scan of file types, structure and links between scripts and outputs. "
                         "Connect an Anthropic API key to have the materials read and summarised.",
        field="Unknown (local scan)", paper_type="Unknown (local scan)",
        readiness=dict(score=score, label=label, rationale="Local scan: scored on which materials are present (max 60). "
                                                     "Turn on AI review to judge their content."),
        key_findings=[], file_insights=insights, figures=figures, gaps=gaps, coverage=coverage,
        draft_reviews=[], consistency_checks=[],
        questions_for_author=["What is the main claim the paper should make?",
                              "Which journal or venue are you targeting?"],
        next_steps=[g["how_to_fix"] for g in gaps[:6]] or ["Run the AI review for a full reading."],
    )
    ProjectReview.model_validate(review)  # keep both paths on one schema
    return {"mode": "local", "model": None, "review": review, "omitted": [], "usage": None}
