"""Paper Draft - local web server.

    python app/server.py            # http://127.0.0.1:8765
    PORT=9000 HOST=0.0.0.0 python app/server.py
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import sys
import threading
import time
import traceback
import uuid
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).parent))
import analyze  # noqa: E402
import inventory  # noqa: E402

HERE = Path(__file__).parent
STATIC = HERE / "static"
DATA = Path(os.environ.get("PAPER_DRAFT_DATA", HERE.parent / "data" / "projects"))
MAX_FILE = 300 * 1024 * 1024
MAX_UNZIPPED = 1024 * 1024 * 1024
ID_RE = re.compile(r"^[a-f0-9]{12}$")

JOBS: dict[str, dict] = {}
LOCK = threading.Lock()


def project_dir(pid: str) -> Path:
    if not ID_RE.match(pid):
        raise ValueError("bad project id")
    return DATA / pid


def safe_rel(path: str) -> Path:
    parts = [p for p in Path(path.replace("\\", "/")).parts if p not in ("", ".", "..", "/")]
    if not parts:
        raise ValueError("empty path")
    return Path(*parts)


def read_json(p: Path, default=None):
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def write_json(p: Path, obj) -> None:
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=1, default=str))
    tmp.replace(p)


def extract_zip(zpath: Path, dest: Path) -> list[str]:
    out, total = [], 0
    with zipfile.ZipFile(zpath) as z:
        for info in z.infolist():
            if info.is_dir() or any(x in info.filename for x in ("__MACOSX", ".DS_Store")):
                continue
            total += info.file_size
            if total > MAX_UNZIPPED:
                raise ValueError("zip expands beyond 1 GB")
            rel = safe_rel(info.filename)
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            out.append(rel.as_posix())
    return out


def run_job(pid: str, scenario: str, notes: str, mode: str) -> None:
    root = project_dir(pid)
    files = root / "files"

    def stage(s: str) -> None:
        with LOCK:
            JOBS[pid]["stage"] = s

    try:
        stage("Reading and profiling your files")
        manifest = inventory.build_manifest(files)
        write_json(root / "manifest.json", inventory.public(manifest))
        use_ai = mode == "ai" or (mode == "auto" and analyze.have_credentials())
        if use_ai:
            result = analyze.ai_review(files, manifest, scenario, notes, stage)
        else:
            stage("Running the local scan")
            result = analyze.local_review(manifest, scenario, notes)
        result.update(scenario=scenario, notes=notes, finished=time.time())
        write_json(root / "analysis.json", result)
        with LOCK:
            JOBS[pid] = {"state": "done", "stage": "Done"}
    except Exception as e:  # noqa: BLE001 - reported to the page
        traceback.print_exc()
        msg = str(e)
        if e.__class__.__name__ == "AuthenticationError":
            msg = "Anthropic credentials were rejected. Check ANTHROPIC_API_KEY."
        elif e.__class__.__name__ == "RateLimitError":
            msg = "Rate limited by the Anthropic API. Try again in a minute."
        with LOCK:
            JOBS[pid] = {"state": "error", "stage": "Failed", "error": msg}


class Handler(BaseHTTPRequestHandler):
    server_version = "PaperDraft/0.1"

    def log_message(self, fmt, *args):  # quieter log
        sys.stderr.write("%s %s\n" % (self.command, self.path.split("?")[0]))

    # -- helpers
    def send_json(self, obj, status=200):
        body = json.dumps(obj, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, p: Path, cache=False):
        if not p.is_file():
            return self.send_json({"error": "not found"}, 404)
        data = p.read_bytes()
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "max-age=3600" if cache else "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if ctype == "image/svg+xml":
            self.send_header("Content-Security-Policy", "script-src 'none'")
        self.end_headers()
        self.wfile.write(data)

    def body(self, limit=MAX_FILE) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        if n > limit:
            raise ValueError("file too large")
        return self.rfile.read(n)

    def route(self):
        u = urlparse(self.path)
        return u.path.rstrip("/") or "/", {k: v[0] for k, v in parse_qs(u.query).items()}

    # -- verbs
    def do_GET(self):
        path, q = self.route()
        try:
            if path in ("/", "/index.html") or re.fullmatch(r"/p/[a-f0-9]{12}", path):
                return self.send_file(STATIC / "index.html")
            if path.startswith("/static/"):
                return self.send_file(STATIC / safe_rel(path[len("/static/"):]))
            if path == "/api/status":
                return self.send_json({"ai_available": analyze.have_credentials(), "model": analyze.MODEL})
            if path == "/api/projects":
                items = []
                for d in sorted(DATA.glob("*"), key=lambda d: d.stat().st_mtime, reverse=True)[:20]:
                    meta = read_json(d / "meta.json", {})
                    an = read_json(d / "analysis.json")
                    items.append({"id": d.name, "created": meta.get("created"),
                                  "title": (an or {}).get("review", {}).get("title_guess") or meta.get("name"),
                                  "analysed": bool(an)})
                return self.send_json({"projects": items})
            m = re.fullmatch(r"/api/projects/([a-f0-9]{12})(/file)?", path)
            if m:
                root = project_dir(m.group(1))
                if not root.exists():
                    return self.send_json({"error": "no such project"}, 404)
                if m.group(2):
                    return self.send_file(root / "files" / safe_rel(q.get("path", "")))
                files = sorted(p.relative_to(root / "files").as_posix()
                               for p in (root / "files").rglob("*") if p.is_file())
                with LOCK:
                    job = dict(JOBS.get(m.group(1), {}))
                return self.send_json({"id": m.group(1), "meta": read_json(root / "meta.json", {}),
                                       "uploaded": files,
                                       "manifest": read_json(root / "manifest.json"),
                                       "analysis": read_json(root / "analysis.json"), "job": job})
            self.send_json({"error": "not found"}, 404)
        except ValueError as e:
            self.send_json({"error": str(e)}, 400)

    def do_POST(self):
        path, q = self.route()
        try:
            if path == "/api/projects":
                pid = uuid.uuid4().hex[:12]
                root = project_dir(pid)
                (root / "files").mkdir(parents=True)
                write_json(root / "meta.json", {"created": time.time(), "name": "Untitled project"})
                return self.send_json({"id": pid})
            m = re.fullmatch(r"/api/projects/([a-f0-9]{12})/analyze", path)
            if m:
                pid = m.group(1)
                root = project_dir(pid)
                if not any((root / "files").rglob("*")):
                    return self.send_json({"error": "Upload some files first."}, 400)
                opts = json.loads(self.body(1_000_000) or b"{}")
                scenario = "draft" if opts.get("scenario") == "draft" else "fresh"
                mode = opts.get("mode") if opts.get("mode") in ("auto", "ai", "local") else "auto"
                with LOCK:
                    if JOBS.get(pid, {}).get("state") == "running":
                        return self.send_json({"error": "Already analysing."}, 409)
                    JOBS[pid] = {"state": "running", "stage": "Starting", "started": time.time()}
                meta = read_json(root / "meta.json", {})
                meta.update(scenario=scenario, notes=str(opts.get("notes", ""))[:4000])
                write_json(root / "meta.json", meta)
                threading.Thread(target=run_job, args=(pid, scenario, meta["notes"], mode),
                                 daemon=True).start()
                return self.send_json({"ok": True})
            self.send_json({"error": "not found"}, 404)
        except (ValueError, json.JSONDecodeError) as e:
            self.send_json({"error": str(e)}, 400)

    def do_PUT(self):
        path, q = self.route()
        m = re.fullmatch(r"/api/projects/([a-f0-9]{12})/files", path)
        if not m:
            return self.send_json({"error": "not found"}, 404)
        try:
            root = project_dir(m.group(1))
            if not root.exists():
                return self.send_json({"error": "no such project"}, 404)
            rel = safe_rel(q.get("path", ""))
            data = self.body()
            target = root / "files" / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if rel.suffix.lower() == ".zip":
                tmp = root / ("upload-" + uuid.uuid4().hex + ".zip")
                tmp.write_bytes(data)
                try:
                    dest = root / "files" / rel.with_suffix("")
                    added = extract_zip(tmp, dest)
                finally:
                    tmp.unlink(missing_ok=True)
                return self.send_json({"saved": [(rel.with_suffix("") / a).as_posix() for a in added]})
            target.write_bytes(data)
            self.send_json({"saved": [rel.as_posix()]})
        except (ValueError, zipfile.BadZipFile) as e:
            self.send_json({"error": str(e)}, 400)

    def do_DELETE(self):
        path, q = self.route()
        m = re.fullmatch(r"/api/projects/([a-f0-9]{12})/files", path)
        if not m:
            return self.send_json({"error": "not found"}, 404)
        try:
            target = project_dir(m.group(1)) / "files" / safe_rel(q.get("path", ""))
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink(missing_ok=True)
            self.send_json({"ok": True})
        except ValueError as e:
            self.send_json({"error": str(e)}, 400)


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8765"))
    print(f"Paper Draft on http://{host}:{port}  (AI review: "
          f"{'on, ' + analyze.MODEL if analyze.have_credentials() else 'off - set ANTHROPIC_API_KEY'})")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
