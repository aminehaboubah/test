"""Local inventory of a project folder: classify every file and profile it.

Nothing here calls a model. The result (a "manifest") is shown on the dashboard
as-is and is also what the AI step reads.
"""
from __future__ import annotations

import csv
import io
import json
import re
import statistics
import struct
import zipfile
from pathlib import Path

DATA_EXT = {".csv", ".tsv", ".json", ".xlsx", ".xls", ".mat", ".npy", ".npz", ".h5",
            ".hdf5", ".parquet", ".dat", ".log", ".out", ".xml", ".yaml", ".yml", ".pkl"}
SCRIPT_EXT = {".py": "Python", ".ipynb": "Jupyter", ".m": "MATLAB", ".r": "R", ".jl": "Julia",
              ".sh": "Shell", ".c": "C", ".cpp": "C++", ".h": "C/C++", ".f90": "Fortran",
              ".js": "JavaScript", ".ts": "TypeScript", ".java": "Java", ".rs": "Rust",
              ".go": "Go", ".sql": "SQL", ".do": "Stata", ".sas": "SAS"}
FIGURE_EXT = {".png", ".jpg", ".jpeg", ".svg", ".tif", ".tiff", ".eps", ".gif", ".bmp", ".webp"}
DOC_EXT = {".pdf", ".docx", ".doc", ".tex", ".md", ".rst", ".bib", ".odt", ".rtf", ".txt"}
ENV_FILES = {"requirements.txt", "environment.yml", "environment.yaml", "pyproject.toml",
             "setup.py", "package.json", "renv.lock", "description", "project.toml",
             "manifest.toml", "dockerfile", "makefile", "pipfile", "conda.yml"}

TEXT_LIMIT = 60_000          # chars of a script/doc shown to the AI per file
IGNORED_PARTS = {"__pycache__", ".git", ".ipynb_checkpoints", "__MACOSX", ".DS_Store", "node_modules"}

REF_RE = re.compile(r"""["']([^"'\n]{1,200}?\.(?:csv|tsv|txt|json|xlsx|xls|mat|npy|npz|h5|hdf5|parquet|dat|log|png|jpe?g|svg|pdf|eps|tiff?|gif|pkl|out|xml|ya?ml))["']""", re.I)
WRITE_HINTS = re.compile(r"(savefig|to_csv|to_excel|to_json|to_parquet|np\.save|savetxt|imwrite|imsave|"
                         r"write_csv|writematrix|writetable|saveas|exportgraphics|print\s*\(\s*['\"]-d|"
                         r"ggsave|png\(|pdf\(|dump|\.write|open\([^)]*['\"]w)", re.I)


def kind_of(path: Path, head: bytes) -> str:
    ext = path.suffix.lower()
    name = path.name.lower()
    parts = {p.lower() for p in path.parts[:-1]}
    if name in ENV_FILES:
        return "script"
    if ext in SCRIPT_EXT:
        return "script"
    if ext in FIGURE_EXT:
        return "figure"
    if ext == ".pdf":
        in_fig_dir = any(p.startswith(("fig", "plot", "image", "graph")) for p in parts)
        if in_fig_dir or name.startswith(("fig", "plot")):
            return "figure"
        return "doc"
    if ext == ".txt":
        if _looks_tabular(head) or parts & {"results", "result", "output", "outputs", "out", "logs", "log", "data"}:
            return "data"
        return "doc"
    if ext in DATA_EXT:
        return "data"
    if ext in DOC_EXT:
        return "doc"
    return "other"


def _looks_tabular(head: bytes) -> bool:
    text = head.decode("utf-8", "replace")
    lines = [l for l in text.splitlines()[:30] if l.strip()]
    if len(lines) < 3:
        return False
    numeric = sum(1 for l in lines if re.fullmatch(r"[\s\d.eE+\-,;:\t|]+", l))
    return numeric / len(lines) > 0.5


# --------------------------------------------------------------------------- profilers

def _num(v: str):
    try:
        return float(v)
    except ValueError:
        return None


def profile_table(text: str, delimiter: str | None = None) -> dict:
    sample = text[:20_000]
    if delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=",\t;| ").delimiter
        except csv.Error:
            delimiter = ","
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return {"rows": 0, "columns": []}
    first = rows[0]
    has_header = sum(_num(c) is None for c in first) > len(first) / 2
    header = [c.strip() for c in first] if has_header else [f"col{i+1}" for i in range(len(first))]
    body = rows[1:] if has_header else rows
    cols = []
    for i, name in enumerate(header[:40]):
        vals = [r[i].strip() for r in body if i < len(r) and r[i].strip() != ""]
        nums = [x for x in (_num(v) for v in vals) if x is not None]
        col = {"name": name, "non_empty": len(vals)}
        if vals and len(nums) >= 0.8 * len(vals):
            col.update(type="number", min=min(nums), max=max(nums),
                       mean=round(statistics.fmean(nums), 6))
            if len(nums) > 1:
                col["std"] = round(statistics.pstdev(nums), 6)
        else:
            col["type"] = "text"
            col["distinct"] = len(set(vals))
            col["examples"] = list(dict.fromkeys(vals))[:5]
        cols.append(col)
    return {"rows": len(body), "column_count": len(header), "has_header": has_header,
            "columns": cols, "preview": [r[:12] for r in body[:5]]}


def profile_json(text: str) -> dict:
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        return {"error": f"invalid JSON: {e}"}

    def shape(o, depth=0):
        if depth > 3:
            return "…"
        if isinstance(o, dict):
            return {k: shape(v, depth + 1) for k, v in list(o.items())[:25]}
        if isinstance(o, list):
            return [f"list[{len(o)}]", shape(o[0], depth + 1)] if o else "list[0]"
        return o if isinstance(o, (int, float, bool)) or o is None else str(o)[:80]
    return {"structure": shape(obj)}


def profile_xlsx(path: Path) -> dict:
    try:
        import openpyxl
    except ImportError:
        return {"note": "openpyxl not installed; spreadsheet not profiled"}
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheets = []
    for ws in wb.worksheets[:8]:
        buf = io.StringIO()
        w = csv.writer(buf)
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i >= 5000:
                break
            w.writerow(["" if v is None else v for v in row])
        p = profile_table(buf.getvalue(), ",")
        p["sheet"] = ws.title
        sheets.append(p)
    return {"sheets": sheets}


def profile_npy(path: Path) -> dict:
    try:
        import numpy as np
        arr = np.load(path, mmap_mode="r", allow_pickle=False)
        out = {"shape": list(arr.shape), "dtype": str(arr.dtype)}
        if arr.size and arr.dtype.kind in "fiu":
            out.update(min=float(arr.min()), max=float(arr.max()), mean=float(arr.mean()))
        return out
    except Exception as e:  # noqa: BLE001 - any failure is just reported
        return {"note": f"could not read: {e}"}


def profile_script(path: Path, text: str) -> dict:
    ext = path.suffix.lower()
    code = text
    info: dict = {}
    if ext == ".ipynb":
        try:
            nb = json.loads(text)
            cells = nb.get("cells", [])
            code = "\n\n".join("".join(c.get("source", "")) for c in cells if c.get("cell_type") == "code")
            md = "\n\n".join("".join(c.get("source", "")) for c in cells if c.get("cell_type") == "markdown")
            info.update(cells=len(cells), markdown_excerpt=md[:2000],
                        has_outputs=any(c.get("outputs") for c in cells))
        except json.JSONDecodeError:
            pass
    lines = code.splitlines()
    imports = sorted(set(re.findall(r"^\s*(?:import|from)\s+([\w.]+)", code, re.M)
                         + re.findall(r"^\s*(?:library|require)\(([\w.]+)\)", code, re.M)))
    funcs = re.findall(r"^\s*(?:def|function)\s+(?:\[?[\w,\s]*\]?\s*=\s*)?(\w+)", code, re.M)
    refs, writes = [], []
    for ln in lines:
        for m in REF_RE.findall(ln):
            refs.append(m)
            if WRITE_HINTS.search(ln):
                writes.append(m)
    comments = [l.strip() for l in lines[:40] if l.strip().startswith(("#", "%", "//", '"""', "'''"))]
    info.update(language=SCRIPT_EXT.get(ext, "config/environment"), lines=len(lines),
                imports=imports[:40], functions=funcs[:40],
                files_referenced=sorted(set(refs)), files_written=sorted(set(writes)),
                header_comments=comments[:15],
                random_seed=bool(re.search(r"seed\s*\(|random_state\s*=|rng\(|set\.seed", code)))
    info["_text"] = code
    return info


def image_size(path: Path, data: bytes) -> tuple[int, int] | None:
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            return im.size
    except Exception:  # noqa: BLE001
        pass
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24])
    return None


def svg_text(text: str) -> str:
    labels = re.findall(r"<(?:title|text|tspan)[^>]*>([^<]{1,120})<", text)
    return " | ".join(dict.fromkeys(l.strip() for l in labels if l.strip()))[:1500]


def docx_text(path: Path) -> str:
    try:
        import docx  # python-docx
        d = docx.Document(str(path))
        parts = []
        for p in d.paragraphs:
            style = (p.style.name or "") if p.style is not None else ""
            t = p.text.strip()
            if t:
                parts.append(("# " if style.lower().startswith(("heading", "title")) else "") + t)
        return "\n".join(parts)
    except Exception:  # noqa: BLE001
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf8", "replace")
        xml = re.sub(r"</w:p>", "\n", xml)
        return re.sub(r"<[^>]+>", "", xml)


def pdf_info(path: Path) -> dict:
    try:
        from pypdf import PdfReader
        r = PdfReader(str(path))
        text = "\n".join((p.extract_text() or "") for p in r.pages[:60])
        return {"pages": len(r.pages), "_text": text}
    except Exception as e:  # noqa: BLE001
        return {"note": f"could not read PDF text: {e}"}


SECTION_WORDS = ["abstract", "introduction", "related work", "background", "method", "materials",
                 "experiment", "result", "discussion", "conclusion", "acknowledg", "reference",
                 "data availability", "code availability", "appendix", "supplementary"]


def doc_profile(path: Path, text: str) -> dict:
    low = text.lower()
    heads = re.findall(r"\\(?:sub)*section\*?\{([^}]+)\}", text) or \
        re.findall(r"^#{1,3}\s+(.+)$", text, re.M) or \
        [l.strip() for l in text.splitlines() if 2 < len(l.strip()) < 60 and
         any(l.strip().lower().lstrip("0123456789. ivx").startswith(w) for w in SECTION_WORDS)]
    words = len(re.findall(r"\w+", text))
    cites = len(re.findall(r"\\cite[pt]?\{|\[\d+(?:[,–-]\s*\d+)*\]|\(\w+ et al\.,? \d{4}\)", text))
    is_paper = (
        path.suffix.lower() == ".tex" and "\\documentclass" in text
    ) or (words > 800 and sum(w in low for w in ("abstract", "introduction", "conclusion", "reference")) >= 2) \
      or (words > 250 and sum(w in " ".join(heads).lower() for w in
                              ("abstract", "introduction", "method", "result", "conclusion", "reference")) >= 3)
    return {"words": words, "headings": heads[:40], "citations_found": cites,
            "looks_like_paper": bool(is_paper),
            "bib_entries": len(re.findall(r"^@\w+\{", text, re.M)) if path.suffix.lower() == ".bib" else None}


# --------------------------------------------------------------------------- main

def build_manifest(root: Path) -> dict:
    files = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or any(part in IGNORED_PARTS for part in p.parts):
            continue
        rel = p.relative_to(root)
        data = p.read_bytes()
        kind = kind_of(rel, data[:4096])
        entry: dict = {"path": rel.as_posix(), "kind": kind, "ext": p.suffix.lower(), "bytes": len(data)}
        text = None
        if kind in ("script", "data", "doc") and p.suffix.lower() not in {".xlsx", ".xls", ".npy", ".npz",
                                                                        ".mat", ".h5", ".hdf5", ".parquet",
                                                                        ".pkl", ".pdf", ".docx", ".doc"}:
            text = data.decode("utf-8", "replace")
        try:
            if kind == "data":
                ext = p.suffix.lower()
                if ext in (".csv", ".tsv", ".dat") or (ext == ".txt" and _looks_tabular(data[:4096])):
                    entry["profile"] = profile_table(text, "\t" if ext == ".tsv" else None)
                elif ext == ".json":
                    entry["profile"] = profile_json(text)
                elif ext in (".xlsx", ".xls"):
                    entry["profile"] = profile_xlsx(p)
                elif ext == ".npy":
                    entry["profile"] = profile_npy(p)
                elif text is not None:
                    entry["profile"] = {"lines": text.count("\n") + 1, "head": text[:3000]}
                else:
                    entry["profile"] = {"note": "binary data format; contents not profiled"}
            elif kind == "script":
                entry["profile"] = profile_script(rel, text or "")
            elif kind == "figure":
                prof: dict = {}
                if p.suffix.lower() == ".svg":
                    prof["labels"] = svg_text(data.decode("utf8", "replace"))
                size = image_size(p, data)
                if size:
                    prof["width"], prof["height"] = size
                entry["profile"] = prof
            elif kind == "doc":
                ext = p.suffix.lower()
                if ext == ".pdf":
                    info = pdf_info(p)
                elif ext == ".docx":
                    info = {"_text": docx_text(p)}
                else:
                    info = {"_text": text or ""}
                body = info.get("_text", "")
                info.update(doc_profile(rel, body))
                entry["profile"] = info
        except Exception as e:  # noqa: BLE001 - one bad file must not stop the inventory
            entry["profile"] = {"error": str(e)}
        files.append(entry)

    link_files(files)
    return {"files": files, "counts": counts(files), "env_files": [f["path"] for f in files
                                                                  if Path(f["path"]).name.lower() in ENV_FILES],
            "readme": [f["path"] for f in files if Path(f["path"]).name.lower().startswith("readme")]}


def link_files(files: list[dict]) -> None:
    """Match file names mentioned in scripts against the uploaded files."""
    by_name: dict[str, list[dict]] = {}
    for f in files:
        by_name.setdefault(Path(f["path"]).name.lower(), []).append(f)
    for f in files:
        f.setdefault("produced_by", [])
        f.setdefault("read_by", [])
    for s in files:
        if s["kind"] != "script":
            continue
        prof = s.get("profile", {})
        written = {Path(w).name.lower() for w in prof.get("files_written", [])}
        prof["missing_refs"] = []
        for ref in prof.get("files_referenced", []):
            name = Path(ref).name.lower()
            targets = by_name.get(name, [])
            if not targets:
                if "{" not in ref and "%" not in ref and "*" not in ref:
                    prof["missing_refs"].append(ref)
                continue
            for t in targets:
                (t["produced_by"] if name in written else t["read_by"]).append(s["path"])
    for f in files:
        f["produced_by"] = sorted(set(f["produced_by"]))
        f["read_by"] = sorted(set(f["read_by"]))


def counts(files: list[dict]) -> dict:
    c = {k: 0 for k in ("data", "script", "figure", "doc", "other")}
    for f in files:
        c[f["kind"]] += 1
    c["total"] = len(files)
    c["bytes"] = sum(f["bytes"] for f in files)
    c["data_rows"] = sum(f.get("profile", {}).get("rows", 0) or 0 for f in files if f["kind"] == "data")
    c["script_lines"] = sum(f.get("profile", {}).get("lines", 0) or 0 for f in files if f["kind"] == "script")
    c["drafts"] = [f["path"] for f in files if f["kind"] == "doc" and f.get("profile", {}).get("looks_like_paper")]
    return c


def public(manifest: dict) -> dict:
    """Manifest without the raw text fields, for the browser."""
    out = json.loads(json.dumps(manifest))
    for f in out["files"]:
        f.get("profile", {}).pop("_text", None)
    return out
