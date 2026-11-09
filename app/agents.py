"""Two-level agent review through Deep Infra (OpenAI-compatible API).

  Orchestrator (reasoning model, default openai/gpt-oss-120b)
      1. plans: reads the file inventory, decides what to look for in each file and which
         cross-checks to run (e.g. "do the draft's numbers match results/summary.txt?")
      4. synthesises: turns the executors' notes and check results into the overview
  Executor (default anthropic/claude-haiku-4-5), many calls in parallel
      2. reads each file (text, data profile and sample, or the figure image) -> a file note
      3. runs each cross-check on the files it names -> ok / warning / problem

Set DEEPINFRA_API_KEY. Models can be changed with PAPER_DRAFT_ORCHESTRATOR / PAPER_DRAFT_EXECUTOR.
"""
from __future__ import annotations

import base64
import copy
import io
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, ValidationError

from analyze import SYSTEM as REVIEW_SYSTEM, Check, FigureReview, FileInsight, ProjectReview
from inventory import TEXT_LIMIT

BASE_URL = os.environ.get("DEEPINFRA_BASE_URL", "https://api.deepinfra.com/v1/openai")
ORCHESTRATOR = os.environ.get("PAPER_DRAFT_ORCHESTRATOR", "openai/gpt-oss-120b")
EXECUTOR = os.environ.get("PAPER_DRAFT_EXECUTOR", "anthropic/claude-haiku-4-5")
WORKERS = int(os.environ.get("PAPER_DRAFT_WORKERS", "6"))
PLAN_EFFORT = os.environ.get("PAPER_DRAFT_PLAN_EFFORT", "medium")      # low | medium | high
REVIEW_EFFORT = os.environ.get("PAPER_DRAFT_REVIEW_EFFORT", "high")
DATA_SAMPLE_CHARS = 20_000
MAX_IMAGE_SIDE = 1568


def log(msg: str) -> None:
    if os.environ.get("PAPER_DRAFT_DEBUG"):
        import sys
        print(time.strftime("%H:%M:%S"), msg, file=sys.stderr, flush=True)


def available() -> bool:
    return bool(os.environ.get("DEEPINFRA_API_KEY"))


# --------------------------------------------------------------------------- schemas

class FileTask(BaseModel):
    path: str
    focus: str


class CrossCheckTask(BaseModel):
    check: str            # the question to answer
    files: list[str]      # exact paths the executor needs


class Plan(BaseModel):
    working_title: str
    what_the_project_seems_to_be: str
    file_tasks: list[FileTask]
    cross_checks: list[CrossCheckTask]


class NumberFact(BaseModel):
    label: str
    value: str
    unit: str


class FigureNote(BaseModel):
    what_it_shows: str
    suggested_caption: str
    quality_issues: list[str]
    keep_for_paper: Literal["main", "supplementary", "drop", "unsure", "not_a_figure"]


class DraftNote(BaseModel):
    sections_found: list[str]
    numeric_claims: list[str]
    figures_referenced: list[str]
    references_found: int
    ai_style_signals: list[str]


class FileNote(BaseModel):
    path: str
    role: str
    summary: str
    key_facts: list[str]
    numbers: list[NumberFact]
    issues: list[str]
    figure: FigureNote          # fill only for figures; otherwise keep_for_paper="not_a_figure"
    draft: DraftNote            # fill only for a draft paper; otherwise empty lists and 0


class CheckResult(BaseModel):
    check: str
    status: Literal["ok", "warning", "problem"]
    detail: str


# --------------------------------------------------------------------------- client

class Trace:
    def __init__(self):
        self.calls: list[dict] = []
        self.lock = threading.Lock()

    def add(self, **kw):
        with self.lock:
            self.calls.append(kw)

    def totals(self) -> dict:
        out = {"calls": len(self.calls), "input_tokens": 0, "output_tokens": 0}
        by_role: dict[str, dict] = {}
        for c in self.calls:
            out["input_tokens"] += c.get("input_tokens", 0)
            out["output_tokens"] += c.get("output_tokens", 0)
            r = by_role.setdefault(c["role"], {"model": c["model"], "calls": 0, "input_tokens": 0,
                                               "output_tokens": 0, "seconds": 0.0})
            r["calls"] += 1
            r["input_tokens"] += c.get("input_tokens", 0)
            r["output_tokens"] += c.get("output_tokens", 0)
            r["seconds"] = round(r["seconds"] + c.get("seconds", 0), 1)
        out["by_role"] = by_role
        return out


def strict_schema(model: type[BaseModel]) -> dict:
    """Pydantic schema -> strict JSON schema (every object closed, every property required)."""
    schema = copy.deepcopy(model.model_json_schema())

    def fix(node):
        if isinstance(node, dict):
            node.pop("title", None)
            node.pop("default", None)
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"])
            for v in node.values():
                fix(v)
        elif isinstance(node, list):
            for v in node:
                fix(v)
    fix(schema)
    return schema


def _client():
    from openai import OpenAI
    return OpenAI(api_key=os.environ["DEEPINFRA_API_KEY"], base_url=BASE_URL, timeout=900, max_retries=2)


def _parse(text: str, model: type[BaseModel]):
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    start = text.find("{")
    return model.model_validate_json(text[start:] if start > 0 else text)


def _complete_streaming(client, kw, progress):
    """Stream one completion, reporting generated size; returns (content, finish_reason, usage)."""
    content, finish, usage, n, last = [], None, None, 0, 0.0
    stream = client.chat.completions.create(**kw, stream=True, stream_options={"include_usage": True})
    for ch in stream:
        if getattr(ch, "usage", None):
            usage = ch.usage
        if not ch.choices:
            continue
        c = ch.choices[0]
        d = c.delta
        if d is not None:
            piece = d.content or ""
            content.append(piece)
            n += len(piece) + len(getattr(d, "reasoning_content", None) or "")
        if c.finish_reason:
            finish = c.finish_reason
        if progress and time.time() - last > 1.5:
            progress(n // 4)
            last = time.time()
    return "".join(content), finish, usage


def call(trace: Trace, role: str, model_id: str, system: str, user_content, out: type[BaseModel],
         max_tokens: int, reasoning: str | None = None, label: str = "",
         progress: Callable[[int], None] | None = None):
    client = _client()
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user_content}]
    kw = dict(model=model_id, messages=messages, max_tokens=max_tokens,
              response_format={"type": "json_schema",
                               "json_schema": {"name": out.__name__, "schema": strict_schema(out), "strict": True}})
    if reasoning:
        kw["reasoning_effort"] = reasoning
    last_err = None
    for attempt in range(2):
        t0 = time.time()
        log(f"-> {role} {model_id} [{label}] attempt {attempt + 1}")
        if progress:
            text, finish, u = _complete_streaming(client, kw, progress)
        else:
            r = client.chat.completions.create(**kw)
            text, finish, u = r.choices[0].message.content, r.choices[0].finish_reason, r.usage
        log(f"<- {role} [{label}] {time.time() - t0:.1f}s finish={finish} out={getattr(u, 'completion_tokens', '?')}")
        trace.add(role=role, model=model_id, label=label, seconds=round(time.time() - t0, 1),
                  input_tokens=getattr(u, "prompt_tokens", 0) or 0,
                  output_tokens=getattr(u, "completion_tokens", 0) or 0,
                  finish=finish, attempt=attempt + 1)
        try:
            return _parse(text, out)
        except (ValidationError, ValueError) as e:
            last_err = e
            if finish == "length":
                kw["max_tokens"] = int(kw["max_tokens"] * 1.6)
            messages.append({"role": "assistant", "content": text or ""})
            messages.append({"role": "user", "content": f"That was not valid JSON for the schema ({str(e)[:300]}). "
                                                        "Reply again with only the JSON object."})
    raise RuntimeError(f"{role} ({model_id}) did not return valid JSON for {label or out.__name__}: {last_err}")


# --------------------------------------------------------------------------- helpers

def _slim_manifest(manifest: dict) -> dict:
    files = []
    for f in manifest["files"]:
        prof = {k: v for k, v in f.get("profile", {}).items() if k != "_text"}
        prof.pop("preview", None)
        if isinstance(prof.get("columns"), list):
            prof["columns"] = [{k: c[k] for k in ("name", "type", "min", "max", "mean") if k in c}
                               for c in prof["columns"][:20]]
        files.append({"path": f["path"], "kind": f["kind"], "bytes": f["bytes"], "profile": prof,
                      "produced_by": f["produced_by"], "read_by": f["read_by"]})
    return {"counts": manifest["counts"], "environment_files": manifest["env_files"],
            "readme_files": manifest["readme"], "files": files}


def _image_part(path: Path) -> dict | None:
    from PIL import Image
    try:
        with Image.open(path) as im:
            im.load()
            if max(im.size) > MAX_IMAGE_SIDE:
                im.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
            if im.mode not in ("RGB", "L"):
                bg = Image.new("RGB", im.size, "white")
                rgba = im.convert("RGBA")
                bg.paste(rgba, mask=rgba.split()[-1])
                im = bg
            buf = io.BytesIO()
            im.save(buf, "PNG", optimize=True)
    except Exception:  # noqa: BLE001
        return None
    return {"type": "image_url",
            "image_url": {"url": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()}}


def _file_body(root: Path, f: dict, limit: int) -> tuple[list[dict], str | None]:
    """Content parts showing one file to the executor, plus a note if it was cut."""
    prof = {k: v for k, v in f.get("profile", {}).items() if k != "_text"}
    parts = [{"type": "text", "text": f"File: {f['path']}\nKind: {f['kind']}\nSize: {f['bytes']} bytes\n"
                                      f"Produced by: {f['produced_by'] or 'unknown'}\nRead by: {f['read_by'] or 'none'}\n"
                                      f"Local profile: {json.dumps(prof, default=str)[:12000]}"}]
    note = None
    text = f.get("profile", {}).get("_text")
    p = root / f["path"]
    if f["kind"] in ("script", "doc") and text:
        shown = text[:limit]
        if len(shown) < len(text):
            note = f"{f['path']}: executor saw the first {len(shown):,} of {len(text):,} characters"
        parts.append({"type": "text", "text": f"<content>\n{shown}\n</content>"})
    elif f["kind"] == "data" and f["ext"] in (".csv", ".tsv", ".txt", ".dat", ".json", ".log", ".out", ".yaml", ".yml", ".xml"):
        raw = p.read_text("utf-8", "replace")
        shown = raw[:DATA_SAMPLE_CHARS]
        if len(shown) < len(raw):
            note = f"{f['path']}: executor saw the full-file profile and the first {len(shown):,} of {len(raw):,} characters"
            parts.append({"type": "text", "text":
                          f"<content sample=\"first {len(shown):,} of {len(raw):,} characters only\">\n{shown}\n</content>\n"
                          "This is a TRUNCATED SAMPLE. Rows after it exist. Use the local profile above (computed on the "
                          "whole file) for row counts, distinct values and ranges; never conclude that data is missing "
                          "because it is absent from the sample."})
        else:
            parts.append({"type": "text", "text": f"<content>\n{shown}\n</content>"})
    elif f["kind"] == "figure":
        if f["ext"] in (".svg", ".eps", ".pdf"):
            note = f"{f['path']}: vector/PDF figure described from its metadata and labels only"
        else:
            img = _image_part(p)
            if img:
                parts.append(img)
            else:
                note = f"{f['path']}: image could not be opened"
    return parts, note


EXEC_FILE_SYSTEM = """You are an executor in a review of a researcher's materials. You read ONE file \
and write a factual note about it for the orchestrator, who cannot see the file. \
Only report what is in the file. Copy numbers exactly as they appear, with units. \
For figures: describe axes, series, trends and readability. For a draft paper: list its sections, \
every numeric claim (verbatim), every figure it references, how many references it has, and \
generic or AI-sounding phrasing. For fields that do not apply, use empty lists, 0, empty strings, \
and keep_for_paper="not_a_figure". Data files may be shown as a truncated sample: the local \
profile was computed on the whole file, so use it for counts, distinct values and ranges."""

EXEC_CHECK_SYSTEM = """You are an executor running ONE consistency check across a researcher's files. \
Answer only from the material given. status: "ok" if consistent, "warning" if unclear or partly \
supported, "problem" if contradicted or missing. In detail, quote the exact values on each side. \
Data files may be shown as a truncated sample; their local profile covers the whole file. Never report \
rows or values as missing just because a sample does not show them."""

PLAN_SYSTEM = """You are the orchestrator of a two-level review of a researcher's materials (code, \
result data, figures, and maybe a draft paper). You see only the file inventory, not file contents. \
Executors (a fast model) will read each file and run checks you specify.

Produce:
- file_tasks: one entry for EVERY file path in the inventory (exact paths), with a one-sentence focus \
saying what to extract from that file for the paper (e.g. "final retention values and their spread", \
"what the plot shows and whether axis labels have units").
- cross_checks: 3-8 specific checks that need several files at once, each listing the exact paths \
needed. Prefer checks that catch real problems: numbers in the draft vs. result files, figures the \
draft cites vs. figures that exist, whether scripts' outputs match the result files, missing inputs, \
methods described vs. what the code does."""


# --------------------------------------------------------------------------- pipeline

def agent_review(root: Path, manifest: dict, scenario: str, notes: str,
                 stage: Callable[[str], None]) -> dict:
    trace = Trace()
    omitted: list[str] = []
    slim = _slim_manifest(manifest)
    by_path = {f["path"]: f for f in manifest["files"]}
    readable = [f for f in manifest["files"] if f["kind"] != "other"]

    # 1. plan
    stage(f"Orchestrator is planning ({ORCHESTRATOR})")
    plan = call(trace, "orchestrator", ORCHESTRATOR, PLAN_SYSTEM,
                json.dumps({"scenario": scenario, "author_notes": notes or "(none)", "inventory": slim},
                           default=str),
                Plan, max_tokens=16000, reasoning=PLAN_EFFORT, label="plan",
                progress=lambda n: stage(f"Orchestrator is planning ({ORCHESTRATOR}) · {n:,} tokens"))
    focus = {t.path: t.focus for t in plan.file_tasks if t.path in by_path}
    for f in readable:  # every file is read, whatever the plan says
        focus.setdefault(f["path"], "Summarise what this file contains and what it contributes to the paper.")
    checks = [c for c in plan.cross_checks if any(p in by_path for p in c.files)][:8]

    # 2. executors read files
    notes_out: dict[str, FileNote] = {}
    failed: list[str] = []

    def read_one(f):
        parts, cut = _file_body(root, f, TEXT_LIMIT)
        if cut:
            omitted.append(cut)
        parts.append({"type": "text", "text": f"Project context: {plan.what_the_project_seems_to_be}\n"
                                              f"Your focus for this file: {focus[f['path']]}"})
        return call(trace, "executor", EXECUTOR, EXEC_FILE_SYSTEM, parts, FileNote,
                    max_tokens=4000, label=f["path"])

    done = 0
    stage(f"Executors are reading files (0/{len(readable)})")
    with ThreadPoolExecutor(WORKERS) as pool:
        futs = {pool.submit(read_one, f): f["path"] for f in readable}
        for fut in as_completed(futs):
            path = futs[fut]
            try:
                n = fut.result()
                n.path = path
                notes_out[path] = n
            except Exception as e:  # noqa: BLE001 - one file failing should not stop the review
                failed.append(f"{path}: {e}")
            done += 1
            stage(f"Executors are reading files ({done}/{len(readable)})")

    # 3. executors run cross-checks
    results: list[CheckResult] = []

    def run_check(c: CrossCheckTask):
        parts = [{"type": "text", "text": f"Check: {c.check}"}]
        for p in c.files:
            f = by_path.get(p)
            if not f:
                parts.append({"type": "text", "text": f"File {p}: NOT UPLOADED"})
                continue
            if f["kind"] == "figure":
                n = notes_out.get(p)
                parts.append({"type": "text", "text": f"Figure {p} (executor note): "
                                                      + (n.model_dump_json() if n else "not read")})
            else:
                body, _ = _file_body(root, f, 40_000)
                parts += body
        r = call(trace, "executor", EXECUTOR, EXEC_CHECK_SYSTEM, parts, CheckResult,
                 max_tokens=2000, label="check: " + c.check[:80])
        r.check = c.check
        return r

    if checks:
        stage(f"Executors are running cross-checks (0/{len(checks)})")
        with ThreadPoolExecutor(WORKERS) as pool:
            futs = [pool.submit(run_check, c) for c in checks]
            for i, fut in enumerate(as_completed(futs), 1):
                try:
                    results.append(fut.result())
                except Exception as e:  # noqa: BLE001
                    failed.append(f"cross-check: {e}")
                stage(f"Executors are running cross-checks ({i}/{len(checks)})")

    # 4. orchestrator writes the overview
    stage(f"Orchestrator is writing the overview ({ORCHESTRATOR})")
    synth_input = {
        "scenario": scenario, "author_notes": notes or "(none)",
        "inventory": slim,
        "executor_file_notes": [n.model_dump() for n in notes_out.values()],
        "executor_cross_checks": [r.model_dump() for r in results],
        "files_executors_could_not_read": failed,
        "not_seen_in_full": omitted,
    }
    review = call(trace, "orchestrator", ORCHESTRATOR,
                  REVIEW_SYSTEM + "\n\nYou are the orchestrator. You cannot see the files; you have the "
                  "inventory, one note per file written by executors who read it, and cross-check results. "
                  "Base every statement on those. Carry the cross-check results into consistency_checks. "
                  "Write next_steps and list items as plain sentences without numbering or emoji.",
                  json.dumps(synth_input, default=str), ProjectReview, max_tokens=32000,
                  reasoning=REVIEW_EFFORT, label="overview",
                  progress=lambda n: stage(f"Orchestrator is writing the overview ({ORCHESTRATOR}) · {n:,} tokens"))

    review = _complete(review, readable, notes_out, results)
    review.next_steps = [re.sub(r"^\s*(?:\d+[.)]|[\d\uFE0F\u20E3\U0001F51F]+|[-*•])\s*", "", s) for s in review.next_steps]
    return {
        "mode": "ai",
        "model": f"{ORCHESTRATOR} + {EXECUTOR}",
        "agents": {"orchestrator": ORCHESTRATOR, "executor": EXECUTOR, "provider": "Deep Infra",
                   "plan": plan.model_dump(), "failed": failed, "calls": trace.calls},
        "review": review.model_dump(),
        "omitted": omitted,
        "usage": trace.totals(),
    }


def _complete(review: ProjectReview, files: list[dict], notes: dict[str, FileNote],
              checks: list[CheckResult]) -> ProjectReview:
    """Make sure every file and figure appears, using executor notes where the synthesis skipped one."""
    have = {i.path for i in review.file_insights}
    for f in files:
        n = notes.get(f["path"])
        if f["path"] not in have and n:
            review.file_insights.append(FileInsight(path=f["path"], role=n.role, summary=n.summary,
                                                    status="needs_attention" if n.issues else "good",
                                                    note="; ".join(n.issues[:3])))
    figs = {g.path for g in review.figures}
    for f in files:
        n = notes.get(f["path"])
        if f["kind"] == "figure" and f["path"] not in figs and n:
            keep = n.figure.keep_for_paper if n.figure.keep_for_paper != "not_a_figure" else "unsure"
            review.figures.append(FigureReview(path=f["path"], what_it_shows=n.figure.what_it_shows or n.summary,
                                               suggested_caption=n.figure.suggested_caption,
                                               produced_by=(f["produced_by"] or ["unknown"])[0],
                                               quality_issues=n.figure.quality_issues, keep_for_paper=keep))
    if not review.consistency_checks and checks:
        review.consistency_checks = [Check(**c.model_dump()) for c in checks]
    return review
