/* Paper Draft - upload + one-page overview */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const fmtN = (n) => (n ?? 0).toLocaleString();
const fmtBytes = (b) => b < 1024 ? b + " B" : b < 1048576 ? (b / 1024).toFixed(0) + " KB" : (b / 1048576).toFixed(1) + " MB";

const EXT = {
  data: "csv tsv json xlsx xls mat npy npz h5 hdf5 parquet dat log out xml yaml yml pkl",
  script: "py ipynb m r jl sh c cpp h f90 js ts java rs go sql do sas",
  figure: "png jpg jpeg svg tif tiff eps gif bmp webp",
  doc: "pdf docx doc tex md rst bib odt rtf txt zip",
};
function guessKind(name) {
  const e = name.split(".").pop().toLowerCase();
  if (e === "txt" && /(^|\/)(results?|outputs?|out|logs?|data)\//i.test(name)) return "data";
  if (/^(requirements\.txt|environment\.ya?ml|pyproject\.toml|dockerfile|makefile)$/i.test(name.split("/").pop())) return "script";
  for (const [k, v] of Object.entries(EXT)) if (v.split(" ").includes(e)) return k;
  return "other";
}
const KLABEL = {data: "Data", script: "Code", figure: "Fig", doc: "Doc", other: "File"};

const S = {pid: null, uploaded: [], status: null, project: null, scenario: "fresh", fileFilter: "all", gapFilter: "all", busy: 0};

async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}

/* ------------------------------------------------------------------ setup */
async function init() {
  S.status = await api("/api/status").catch(() => ({ai_available: false}));
  const pill = $("#aiPill");
  if (S.status.ai_available) {
    pill.classList.add("on");
    pill.querySelector("span").textContent = "AI review on";
    pill.title = "Model: " + S.status.model;
  } else {
    pill.querySelector("span").textContent = "Local scan only";
    pill.title = "Set ANTHROPIC_API_KEY on the server to turn on AI review";
    $("#useAi").checked = false;
    $("#useAi").disabled = true;
    $("#aiToggle").classList.add("off");
  }
  const m = location.pathname.match(/^\/p\/([a-f0-9]{12})$/);
  if (m) await loadProject(m[1]);
  else loadRecent();
}

async function loadRecent() {
  const {projects = []} = await api("/api/projects").catch(() => ({}));
  const done = projects.filter((p) => p.analysed).slice(0, 5);
  $("#recent").innerHTML = done.length ? "Recent: " + done.map((p) =>
    `<a href="/p/${esc(p.id)}">${esc(p.title || p.id)}</a>`).join("") : "";
}

async function loadProject(pid) {
  S.pid = pid;
  const p = await api(`/api/projects/${pid}`);
  S.project = p;
  S.uploaded = p.uploaded || [];
  if (p.meta?.scenario) setScenario(p.meta.scenario);
  if (p.meta?.notes) $("#notes").value = p.meta.notes;
  renderStaged();
  if (p.job?.state === "running") return poll();
  if (p.analysis) showDash(p);
}

function setScenario(v) {
  S.scenario = v;
  $$(".scen label").forEach((l) => {
    const inp = $("input", l);
    inp.checked = inp.value === v;
    l.classList.toggle("sel", inp.checked);
  });
}
$$(".scen input").forEach((i) => i.addEventListener("change", () => setScenario(i.value)));

/* ------------------------------------------------------------------ upload */
const drop = $("#drop");
drop.addEventListener("click", (e) => { if (e.target.id !== "pickFolder") $("#fileIn").click(); });
drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("#fileIn").click(); } });
$("#pickFolder").addEventListener("click", (e) => { e.stopPropagation(); $("#dirIn").click(); });
$("#fileIn").addEventListener("change", (e) => { addFiles([...e.target.files].map((f) => ({file: f, path: f.name}))); e.target.value = ""; });
$("#dirIn").addEventListener("change", (e) => { addFiles([...e.target.files].map((f) => ({file: f, path: f.webkitRelativePath || f.name}))); e.target.value = ""; });

let dragDepth = 0;
addEventListener("dragenter", (e) => { if (e.dataTransfer?.types.includes("Files")) { dragDepth++; $("#dropall").hidden = false; drop.classList.add("over"); } });
addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth = 0; $("#dropall").hidden = true; drop.classList.remove("over"); } });
addEventListener("dragover", (e) => e.preventDefault());
addEventListener("drop", async (e) => {
  e.preventDefault(); dragDepth = 0; $("#dropall").hidden = true; drop.classList.remove("over");
  const items = [...(e.dataTransfer.items || [])].map((it) => it.webkitGetAsEntry?.()).filter(Boolean);
  if (items.length) {
    const out = [];
    await Promise.all(items.map((en) => walk(en, "", out)));
    addFiles(out);
  } else addFiles([...e.dataTransfer.files].map((f) => ({file: f, path: f.name})));
});
function walk(entry, prefix, out) {
  return new Promise((res) => {
    if (entry.isFile) entry.file((f) => { out.push({file: f, path: prefix + f.name}); res(); }, res);
    else if (entry.isDirectory) {
      const rd = entry.createReader(), all = [];
      const read = () => rd.readEntries(async (ents) => {
        if (!ents.length) { await Promise.all(all.map((x) => walk(x, prefix + entry.name + "/", out))); res(); }
        else { all.push(...ents); read(); }
      }, res);
      read();
    } else res();
  });
}

const IGNORE = /(^|\/)(\.git|__pycache__|\.ipynb_checkpoints|node_modules|__MACOSX)(\/|$)|(^|\/)\.DS_Store$/;
async function addFiles(list) {
  list = list.filter((x) => !IGNORE.test(x.path));
  if (!list.length) return;
  hideAlert();
  if (!S.pid) {
    const {id} = await api("/api/projects", {method: "POST"});
    S.pid = id;
    history.replaceState(null, "", `/p/${id}`);
  }
  const pending = list.map((x) => ({...x, state: "busy"}));
  S.pendingList = (S.pendingList || []).concat(pending);
  renderStaged();
  let i = 0;
  const worker = async () => {
    while (i < pending.length) {
      const it = pending[i++];
      try {
        const r = await api(`/api/projects/${S.pid}/files?path=${encodeURIComponent(it.path)}`, {method: "PUT", body: it.file});
        S.uploaded = [...new Set(S.uploaded.concat(r.saved))].sort();
        it.state = "ok";
      } catch (err) { it.state = "bad"; it.error = err.message; }
      renderStaged();
    }
  };
  S.busy++;
  await Promise.all([worker(), worker(), worker(), worker()]);
  S.busy--;
  S.pendingList = S.pendingList.filter((x) => x.state !== "ok");
  renderStaged();
}

async function removeFile(path) {
  await api(`/api/projects/${S.pid}/files?path=${encodeURIComponent(path)}`, {method: "DELETE"}).catch(showAlert);
  S.uploaded = S.uploaded.filter((p) => p !== path);
  renderStaged();
}

function renderStaged() {
  const pend = (S.pendingList || []).filter((x) => x.state !== "ok");
  const all = S.uploaded;
  $("#staged").hidden = !all.length && !pend.length;
  const c = {data: 0, script: 0, figure: 0, doc: 0, other: 0};
  all.forEach((p) => c[guessKind(p)]++);
  $("#stagedSum").innerHTML = `<b>${all.length} file${all.length === 1 ? "" : "s"}</b>` +
    ["data", "script", "figure", "doc", "other"].filter((k) => c[k]).map((k) =>
      `<span class="tag k-${k}"><i></i>${c[k]} ${{data: "data", script: "code", figure: "figures", doc: "docs", other: "other"}[k]}</span>`).join("") +
    (pend.some((x) => x.state === "busy") ? ` <span>uploading ${pend.filter((x) => x.state === "busy").length}…</span>` : "");
  $("#stagedList").innerHTML =
    pend.map((x) => `<div class="up ${x.state}"><span class="dot"></span><span class="kb ${guessKind(x.path)}">${KLABEL[guessKind(x.path)]}</span>
      <span class="nm" title="${esc(x.path)}">${esc(x.path)}</span><span class="st">${x.state === "bad" ? esc(x.error) : "uploading"}</span></div>`).join("") +
    all.map((p) => `<div class="up ok"><span class="kb ${guessKind(p)}">${KLABEL[guessKind(p)]}</span>
      <span class="nm" title="${esc(p)}">${esc(p)}</span><button class="x" data-rm="${esc(p)}" title="Remove" aria-label="Remove ${esc(p)}">×</button></div>`).join("");
  $$("#stagedList [data-rm]").forEach((b) => b.addEventListener("click", () => removeFile(b.dataset.rm)));
  $("#goBtn").disabled = !all.length || S.busy > 0;
}

/* ------------------------------------------------------------------ analyze */
$("#goBtn").addEventListener("click", analyze);
$("#rerunBtn").addEventListener("click", () => { showUpload(); analyze(); });
$("#addBtn").addEventListener("click", () => { showUpload(); $("#fileIn").click(); });
$("#newBtn").addEventListener("click", () => { location.href = "/"; });

async function analyze() {
  hideAlert();
  const mode = $("#useAi").checked ? "ai" : "local";
  try {
    await api(`/api/projects/${S.pid}/analyze`, {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({scenario: S.scenario, notes: $("#notes").value, mode})});
  } catch (e) { return showAlert(e); }
  poll();
}

async function poll() {
  showUpload();
  $("#progress").hidden = false;
  $("#goBtn").disabled = true;
  const t0 = Date.now();
  const tick = setInterval(() => { $("#elapsed").textContent = Math.round((Date.now() - t0) / 1000) + " s"; }, 500);
  try {
    for (;;) {
      const p = await api(`/api/projects/${S.pid}`);
      $("#stage").textContent = p.job?.stage || "Working";
      if (p.job?.state === "error") throw new Error(p.job.error);
      if (p.job?.state !== "running" && p.analysis) { S.project = p; showDash(p); break; }
      await new Promise((r) => setTimeout(r, 1500));
    }
  } catch (e) { showAlert(e); }
  finally { clearInterval(tick); $("#progress").hidden = true; renderStaged(); }
}

function showAlert(e) { const a = $("#alert"); a.textContent = e.message || String(e); a.hidden = false; }
function hideAlert() { $("#alert").hidden = true; }

function showUpload() {
  $("#upload").hidden = false;
  $("#dash").hidden = true;
  setNav(false);
  if (S.project?.analysis) {
    $("#recent").innerHTML = `<a href="#overview" id="backDash">← Back to the overview</a>`;
    $("#backDash").addEventListener("click", (e) => { e.preventDefault(); showDash(S.project); });
  }
}

function setNav(on) {
  $$("#nav a").forEach((a, i) => { a.classList.toggle("dis", !on && i > 0); a.classList.toggle("on", on ? i === 1 : i === 0); });
}

/* ------------------------------------------------------------------ dashboard */
function showDash(p) {
  const A = p.analysis, R = A.review, M = p.manifest || {files: [], counts: {}};
  S.mode = A.mode;
  const files = Object.fromEntries((M.files || []).map((f) => [f.path, f]));
  $("#upload").hidden = true;
  $("#dash").hidden = false;
  setNav(true);
  scrollTo({top: 0});
  document.title = `${R.title_guess} — Paper Draft`;

  const fileLink = (path) => files[path]
    ? `<a class="fchip" href="/api/projects/${S.pid}/file?path=${encodeURIComponent(path)}" target="_blank" rel="noopener">${esc(path)}</a>`
    : `<span class="fchip">${esc(path)}</span>`;

  // summary card
  $("#sumChips").innerHTML = [
    A.mode === "ai" ? `<span class="chip">✧ AI review · ${esc(A.model)}</span>` : `<span class="chip gray">Local scan</span>`,
    `<span class="chip ${A.scenario === "draft" ? "rust" : "violet"}">${A.scenario === "draft" ? "Draft review" : "No draft yet"}</span>`,
    R.field && !/local scan/i.test(R.field) ? `<span class="chip gray">${esc(R.field)}</span>` : "",
    R.paper_type && !/local scan/i.test(R.paper_type) ? `<span class="chip gray">${esc(R.paper_type)}</span>` : "",
  ].join("");
  $("#title").textContent = R.title_guess;
  $("#oneLine").textContent = R.one_line_summary;
  $("#research").textContent = R.research_summary;
  $("#ring").innerHTML = ring(R.readiness);

  // tiles
  const c = M.counts || {};
  const figMain = R.figures.filter((f) => f.keep_for_paper === "main").length;
  const sev = (s) => R.gaps.filter((g) => g.severity === s).length;
  $("#tiles").innerHTML = [
    ["data", "Data files", c.data, c.data_rows ? `${fmtN(c.data_rows)} rows profiled` : "result tables and logs"],
    ["script", "Scripts", c.script, c.script_lines ? `${fmtN(c.script_lines)} lines of code` : "code and notebooks"],
    ["figure", "Figures", c.figure, figMain ? `${figMain} suggested for the main text` : "plots and images"],
    ["doc", "Documents", c.doc, (c.drafts || []).length ? `draft found: ${esc(c.drafts[0])}` : "no draft found"],
    ["gap", "Gaps", R.gaps.length, `${sev("critical")} critical · ${sev("important")} important`],
  ].map(([k, label, v, s]) => `<div class="tile ${k}"><div class="k">${label}</div><div class="v">${fmtN(v)}</div><div class="s">${s}</div></div>`).join("");

  // findings
  $("#findings").innerHTML = R.key_findings.length ? R.key_findings.map((f) =>
    `<li><div class="h"><b>${esc(f.finding)}</b><span class="str ${esc(f.strength)}">${esc(f.strength)}</span></div>
     <div class="ev">${f.evidence_files.map(fileLink).join("")}</div></li>`).join("")
    : `<li class="empty2">${A.mode === "ai" ? "No findings could be drawn from these files." : "Turn on AI review to have your results read and summarised."}</li>`;

  // gaps
  renderGaps(R, fileLink);

  // coverage
  $("#cov").innerHTML = R.coverage.map((s) => `<div class="sec ${esc(s.status)}" title="${esc(s.note)}">
    <span class="s">${esc(s.status)}</span><b>${esc(s.section)}</b><span class="n">${esc(s.note)}</span></div>`).join("");
  $("#covHint").textContent = A.scenario === "draft"
    ? "Each section of the paper, as found in your draft and backed by your files."
    : "How far your materials already cover each section of the paper.";

  // drafts
  $("#draftPanel").hidden = !R.draft_reviews.length;
  $("#drafts").innerHTML = R.draft_reviews.map((d) => `<div class="dr">
    <div class="ev" style="margin:.2rem 0 .4rem">${fileLink(d.path)}</div>
    <p class="ov">${esc(d.overall)}</p>
    <div class="cols3">
      <div class="g"><h4>Strengths</h4>${list(d.strengths)}</div>
      <div class="b"><h4>Weaknesses</h4>${list(d.weaknesses)}</div>
      <div class="a"><h4>Generic or AI-style signals</h4>${list(d.ai_style_signals)}</div>
    </div></div>`).join("");

  // figures
  $("#figCount").textContent = `${R.figures.length} figure${R.figures.length === 1 ? "" : "s"}`;
  const KEEP = {main: ["", "Main text"], supplementary: ["violet", "Supplementary"], drop: ["red", "Consider dropping"], unsure: ["gray", "Undecided"]};
  $("#figs").innerHTML = R.figures.length ? R.figures.map((f) => {
    const src = `/api/projects/${S.pid}/file?path=${encodeURIComponent(f.path)}`;
    const raster = /\.(png|jpe?g|gif|svg|webp|bmp)$/i.test(f.path);
    const [kc, kl] = KEEP[f.keep_for_paper] || KEEP.unsure;
    return `<div class="fig"><div class="th">${raster ? `<img src="${src}" alt="${esc(f.what_it_shows)}" loading="lazy" data-zoom="${src}">`
      : `<a href="${src}" target="_blank" rel="noopener" class="kind figure" style="text-decoration:none">${esc(f.path.split(".").pop().toUpperCase())}</a>`}</div>
      <div class="bd"><span class="nm">${esc(f.path)}</span>
        <div class="chips"><span class="chip ${kc}">${kl}</span>${f.produced_by && f.produced_by !== "unknown" ? `<span class="chip gray">from ${esc(f.produced_by)}</span>` : `<span class="chip amber">source script unknown</span>`}</div>
        <span>${esc(f.what_it_shows)}</span>
        ${f.suggested_caption ? `<span class="cap">“${esc(f.suggested_caption)}”</span>` : ""}
        ${f.quality_issues.map((q) => `<span class="iss">⚠ ${esc(q)}</span>`).join("")}
      </div></div>`;
  }).join("") : `<div class="empty2" style="border:0">No figures uploaded.</div>`;
  $$("#figs [data-zoom]").forEach((im) => im.addEventListener("click", () => zoom(im.dataset.zoom)));

  // connections
  const scripts = (M.files || []).filter((f) => f.kind === "script" && f.profile?.lines);
  $("#flow").innerHTML = scripts.length ? scripts.map((s) => {
    const reads = (M.files || []).filter((f) => f.read_by.includes(s.path)).map((f) => f.path);
    const writes = (M.files || []).filter((f) => f.produced_by.includes(s.path)).map((f) => f.path);
    const missing = s.profile.missing_refs || [];
    return `<div class="fl"><div class="col">${reads.map(fileLink).join("") || `<span class="none">no inputs found</span>`}
      ${missing.map((m) => `<span class="chip red" title="Referenced but not uploaded">missing: ${esc(m)}</span>`).join("")}</div>
      <span class="arr">→</span><span class="mid">${esc(s.path)}</span><span class="arr">→</span>
      <div class="col">${writes.map(fileLink).join("") || `<span class="none">no outputs found</span>`}</div></div>`;
  }).join("") : `<div class="mini">No scripts uploaded.</div>`;
  const orphanFig = (M.files || []).filter((f) => f.kind === "figure" && !f.produced_by.length);
  const unusedData = (M.files || []).filter((f) => f.kind === "data" && !f.read_by.length && !f.produced_by.length);
  $("#loose").innerHTML = [
    orphanFig.length && scripts.length ? `<b>Figures with no generating script:</b> ${orphanFig.map((f) => esc(f.path)).join(", ")}` : "",
    unusedData.length && scripts.length ? `<b>Data no script mentions:</b> ${unusedData.map((f) => esc(f.path)).join(", ")}` : "",
  ].filter(Boolean).join("<br>");

  // files table
  S.rows = (M.files || []).map((f) => ({f, ins: R.file_insights.find((x) => x.path === f.path)}));
  renderFiles(fileLink);

  // next steps etc.
  $("#steps").innerHTML = R.next_steps.map((s) => `<li>${esc(s)}</li>`).join("");
  $("#qs").innerHTML = R.questions_for_author.map((q) => `<li>${esc(q)}</li>`).join("");
  $("#checksPanel").hidden = !R.consistency_checks.length;
  $("#checks").innerHTML = R.consistency_checks.map((k) => `<li><div class="h"><span class="dot s-${esc(k.status)}" style="margin-top:.45rem"></span>
    <b>${esc(k.check)}</b></div><p>${esc(k.detail)}</p></li>`).join("");

  // footer
  $("#foot").textContent = A.mode === "ai"
    ? `AI review by ${A.model} · ${fmtN(A.usage?.input_tokens)} tokens read, ${fmtN(A.usage?.output_tokens)} written`
    : "Local scan — turn on AI review for a full reading.";
  $("#omitWrap").innerHTML = A.omitted?.length ? `<details class="omit"><summary>${A.omitted.length} item(s) not sent to the model in full</summary>
    <ul>${A.omitted.map((o) => `<li>${esc(o)}</li>`).join("")}</ul></details>` : "";
}

function list(arr) { return arr?.length ? `<ul>${arr.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : `<span>—</span>`; }

function ring(r) {
  const score = Math.max(0, Math.min(100, r.score | 0));
  const col = score >= 70 ? "var(--teal)" : score >= 40 ? "var(--amber)" : "var(--red)";
  const C = 2 * Math.PI * 52;
  return `<svg viewBox="0 0 120 120" role="img" aria-label="Readiness ${score} of 100">
    <circle cx="60" cy="60" r="52" fill="none" stroke="var(--bg2)" stroke-width="10"/>
    <circle cx="60" cy="60" r="52" fill="none" stroke="${col}" stroke-width="10" stroke-linecap="round"
      stroke-dasharray="${(C * score / 100).toFixed(1)} ${C.toFixed(1)}" transform="rotate(-90 60 60)"/>
    <text x="60" y="64" text-anchor="middle" font-family="Fraunces,Georgia,serif" font-size="30" font-weight="600" fill="var(--ink)">${score}</text>
    <text x="60" y="82" text-anchor="middle" font-family="Inter,sans-serif" font-size="9" font-weight="600" fill="var(--faint)" letter-spacing=".8">READINESS</text>
  </svg><div><div class="lbl">${esc(r.label)}</div><div class="why">${esc(r.rationale)}</div></div>`;
}

function renderGaps(R, fileLink) {
  const counts = {all: R.gaps.length};
  R.gaps.forEach((g) => { counts[g.severity] = (counts[g.severity] || 0) + 1; });
  const NAMES = {all: "All", critical: "Critical", important: "Important", nice_to_have: "Nice to have"};
  $("#gapFilter").innerHTML = Object.keys(NAMES).filter((k) => counts[k]).map((k) =>
    `<button class="stat ${k} ${S.gapFilter === k ? "on" : ""}" data-g="${k}">${k === "all" ? "" : "<i></i>"}${NAMES[k]} <b>${counts[k]}</b></button>`).join("");
  $$("#gapFilter [data-g]").forEach((b) => b.addEventListener("click", () => { S.gapFilter = b.dataset.g; renderGaps(R, fileLink); }));
  const shown = R.gaps.filter((g) => S.gapFilter === "all" || g.severity === S.gapFilter);
  $("#gapList").innerHTML = shown.length ? shown.map((g) => `<li><div class="h"><span class="sev ${esc(g.severity)}"></span>
    <b>${esc(g.item)}</b><span class="chip gray">${esc(g.category)}</span></div>
    <p>${esc(g.why_it_matters)}</p><div class="fix">${esc(g.how_to_fix)}</div></li>`).join("")
    : `<li class="empty2">Nothing missing at this level.</li>`;
}

function contents(f) {
  const p = f.profile || {};
  if (p.error) return `could not read: ${p.error}`;
  if (f.kind === "data") {
    if (p.rows != null) return `${fmtN(p.rows)} rows × ${p.column_count} cols` + (p.columns?.length ? ` · ${p.columns.slice(0, 5).map((c) => c.name).join(", ")}${p.columns.length > 5 ? "…" : ""}` : "");
    if (p.sheets) return p.sheets.map((s) => `${s.sheet}: ${fmtN(s.rows)} rows`).join(" · ");
    if (p.shape) return `array ${p.shape.join("×")} ${p.dtype}`;
    if (p.structure) return "JSON object";
    return p.note || fmtBytes(f.bytes);
  }
  if (f.kind === "script") return p.lines ? `${p.language}, ${fmtN(p.lines)} lines` + (p.imports?.length ? ` · ${p.imports.slice(0, 4).join(", ")}` : "") : "environment / config";
  if (f.kind === "figure") return p.width ? `${p.width}×${p.height} px` : fmtBytes(f.bytes);
  if (f.kind === "doc") return `${fmtN(p.words)} words` + (p.pages ? ` · ${p.pages} pages` : "") + (p.looks_like_paper ? " · looks like a paper" : "") + (p.bib_entries ? ` · ${p.bib_entries} references` : "");
  return fmtBytes(f.bytes);
}

function renderFiles(fileLink) {
  const rows = S.rows.filter(({f}) => S.fileFilter === "all" || f.kind === S.fileFilter);
  $("#fileCount").textContent = `${S.rows.length} files · ${fmtBytes(S.rows.reduce((a, {f}) => a + f.bytes, 0))}`;
  const STATUS = {good: "Good", needs_attention: "Needs attention", unclear: "Unclear"};
  $("#fileRows").innerHTML = rows.map(({f, ins}) => `<tr>
    <td class="path"><span class="kb ${f.kind}" style="margin-right:.45rem">${KLABEL[f.kind]}</span>${fileLink(f.path).replace('class="fchip"', 'class="fchip" style="background:none;padding:0;font-size:.8rem;color:var(--ink)"')}
      ${f.produced_by.length ? `<div class="sub2">made by ${f.produced_by.map(esc).join(", ")}</div>` : ""}
      ${f.read_by.length ? `<div class="sub2">read by ${f.read_by.map(esc).join(", ")}</div>` : ""}</td>
    <td>${esc(ins?.role || "—")}</td>
    <td>${esc(contents(f))}${ins?.summary && S.mode === "ai" ? `<div class="sub2">${esc(ins.summary)}</div>` : ""}</td>
    <td class="st">${ins ? `<span class="dot s-${esc(ins.status)}"></span>${STATUS[ins.status] || esc(ins.status)}` : "—"}</td>
    <td>${esc(ins?.note || "")}</td></tr>`).join("");
  $$("#fileSeg button").forEach((b) => {
    b.classList.toggle("on", b.dataset.k === S.fileFilter);
    b.onclick = () => { S.fileFilter = b.dataset.k; renderFiles(fileLink); };
  });
}

function zoom(src) {
  const lb = document.createElement("div");
  lb.className = "lightbox";
  lb.innerHTML = `<img src="${esc(src)}" alt="">`;
  lb.addEventListener("click", () => lb.remove());
  addEventListener("keydown", function k(e) { if (e.key === "Escape") { lb.remove(); removeEventListener("keydown", k); } });
  document.body.appendChild(lb);
}

// nav scroll-spy
addEventListener("scroll", () => {
  if ($("#dash").hidden) return;
  const ids = ["overview", "gaps", "figures", "files", "next"];
  let cur = "overview";
  for (const id of ids) { const el = document.getElementById(id); if (el && el.getBoundingClientRect().top < 140) cur = id; }
  $$("#nav a").forEach((a) => a.classList.toggle("on", a.getAttribute("href") === "#" + cur));
}, {passive: true});
$("#nav a[href='#upload']").addEventListener("click", (e) => { if (!$("#dash").hidden) { e.preventDefault(); showUpload(); scrollTo({top: 0}); } });

init();
