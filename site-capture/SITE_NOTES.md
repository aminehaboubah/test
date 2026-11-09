# Paper Parse — site walkthrough, layout & formatting record

Captured 2026-11-09 from the ngrok-hosted instance (Python `BaseHTTP` server behind ngrok),
signed in as the `admin` account. Screenshots are in `screens/`, raw HTML in `html/`,
extracted page text in `*-text.txt`. Only read-only views were opened (no uploads,
re-processing, deletes, password changes or AI reviewer runs). Opening the LaTeX editor
auto-triggers one compile (`POST /api/docs/{id}/latex/compile`), which is the page's own
on-load behaviour.

---

## 1. What the site does

**Paper Parse** ("every paper, perfectly structured") is a self-hosted ("runs locally / on
your machine") tool that converts scientific papers between formats while keeping their
structure:

- **Input:** PDF (born-digital or scanned/OCR, one or two columns), Word `.docx`
  (with Word equations or typed math), LaTeX `.tex` or a zipped LaTeX project.
- **Internal model:** every file is parsed into one structured document made of *blocks*
  (headings, paragraphs, lists, equations, tables, figures, theorems, footnotes, references).
- **Output:** PDF (typeset with LaTeX), LaTeX `.zip` (main.tex + figures), Word `.docx`
  (native equations), with a column choice (as source / single / double) and a journal
  template (plain article, IEEE conference, ACM sigconf, Springer LNCS, Elsevier).
- **Reader:** an HTML reading view with outline, search, themes, figure zoom, the original
  PDF page beside the text, in-place editing, versions, comments.
- **LaTeX editor:** Overleaf-style editor with live PDF preview, SyncTeX ("Find in PDF"),
  file tree, outline, problems panel, history; two-way synced with the reader.
- **AI features (optional):**
  - *AI review* toggle at upload: models check headings, clear figure debris, compare pages
    with the result (stated: Claude Haiku and Gemini Flash; pages are sent to Anthropic and
    OpenAI under their API terms).
  - *Assistant* chat in the reader/editor (attach files, snip part of the PDF, @ context).
  - *Reviewer* panel with four checks: **Claims**, **Paper** (numbers/terms/figures/captions),
    **Grammar**, **Flow**.
  - Selectable "AI model for LaTeX edits" (default: "Terra plans: Gemini writes, Haiku reads,
    DeepSeek builds").
  - *Memory*: corrections and preferences reused across documents.
- **Usage page:** cost/token accounting per assistant reply, reviewer check and conversion.
- Parsing stack (footer): PDFs via Docling, with MinerU for doubtful formulas; Word and LaTeX
  parsed directly.

Current data in this instance: 830 documents (816 ready, 14 failed); $17.91 spent over 30 days.

---

## 2. Site map / routes

| Route | Page |
|---|---|
| `/` | Marketing landing page + Sign-in modal |
| `/app` | "Your space" dashboard: upload, document list, how-it-works, memory |
| `/app/usage` | Usage & costs |
| `/docs/{id}/paper.html` | Reader (`#report` anchor opens the "to check" report) |
| `/docs/{id}/latex` | LaTeX editor |
| `/static/*` | Hashed JS/CSS bundles (reader-main, reader-pdf, reader-assist, reader-review, reader-edits, reader-snip, reviewer, edits_panel, snip) |

API seen: `GET /api/me`, `POST /api/login {name,password}`, `GET /api/docs`, `GET /api/memory`,
`GET /api/settings`, `GET /api/usage`, `GET /docs/{id}/version.json`, `comments.json`,
`blocks.edit.json`, `latex/project.json`, `latex/file?path=main.tex`, `latex/pdf`,
`POST /api/docs/{id}/latex/compile`. Doc ids are a slug of the filename + 6-hex suffix
(e.g. `2610-37400v1-pdf-69bc60`).

---

## 3. Design system (shared across pages)

**Feel:** warm, editorial, paper-like. Off-white/cream background, deep-teal primary, rust
accent, serif display headings with a clean sans for UI. Generous whitespace, rounded cards
with soft shadows, thin warm-grey rules.

### Colour tokens (`:root`, light)
| Token | Value | Use |
|---|---|---|
| `--bg` | `#f8f6f1` | page background (cream) |
| `--bg2` | `#efebe3` | secondary surface / segmented controls |
| `--card` | `#ffffff` | cards |
| `--ink` | `#1c1917` | body text |
| `--muted` | `#5f5750` | secondary text |
| `--faint` | `#948b81` | captions, meta |
| `--rule` / `--rule2` | `#e6e0d6` / `#d9d1c4` | borders/dividers |
| `--teal` / `--teal-d` | `#0f5c5c` / `#0b4545` | primary buttons, links, brand |
| `--teal-l` / `--teal-m` | `#e8f2ef` / `#bfd9d2` | active nav pill, tints |
| `--rust` / `--rust-l` | `#b45309` / `#fdf1e3` | accent ("Parse" in logo, section eyebrows, highlight) |
| `--red` / `--red-l` | `#b42318` / `#fdecea` | failed state |
| `--amber` / `--amber-l` | `#a15c07` / `#fff5e0` | warnings ("N to check"), LaTeX sync banner |
| `--shadow` | `0 1px 2px rgba(28,25,23,.05), 0 4px 16px rgba(28,25,23,.06)` | cards |
| `--r` | `14px` | card radius |

Dark mode via `prefers-color-scheme` (landing: bg `#141311`, teal becomes `#4fb3a5`, rust
`#e08a3c`). The reader additionally has `data-theme` = light / dark / sepia (`#f4ecd8`) / auto.

File-type colours (icons/chips): **PDF** rust-red, **DOCX** blue (`#2b5797`-ish), **TEX** teal-green.

Reader toolbar category colours: Write = violet, Assistant = lavender, Comments = blue text,
Reviewer = crimson/pink, View = teal, Versions = amber/orange, Paper = blue.

### Typography
- **Serif (display & reading):** `Fraunces` → Iowan Old Style / Palatino / Georgia. Used for
  h1/h2, card titles, logo word "Paper Parse", big stats, and the whole reader body
  (`font: 1.06rem/1.72 var(--serif)`, justified, hyphenated).
- **Sans (UI):** `Inter` 400/500/600/700 → system-ui. Navigation, buttons, labels, meta.
- **Mono:** editor code (LaTeX source).
- Italic serif in teal/ink for emphasis words ("*perfectly*", "*clean, editable*").
- Eyebrow labels: tiny uppercase, letter-spaced, rust colour, preceded by a short rule
  (e.g. "— FEATURES").
- Section-date headers in the list: small uppercase, letter-spaced, faint ("SATURDAY, NOVEMBER 7").
- Math rendered with **KaTeX 0.16.11** (CDN).

### Components
- **Buttons:** primary = solid teal, white text, ~8–10px radius, trailing "→" arrow
  (e.g. "Open your space →"); secondary = white with rule border; small icon-leading
  buttons (book icon "Open", pencil "LaTeX", download "Export"); "⋯" kebab for more.
- **Pills/chips:** rounded-full; status chips with coloured dot ("● Ready 816", "● Failed 14");
  format chips ("● PDF", "● Word .docx", "● LaTeX .tex", "● LaTeX project .zip");
  "New" badge chip in hero.
- **Segmented controls:** grey track with white selected segment (All/PDF/Word/LaTeX;
  Today/7 days/30 days/All; Outline/PDF; Reader/LaTeX where selected = solid teal).
- **Cards:** white, 14px radius, 1px rule border, soft shadow, ~20–24px padding.
- **Toggle switch:** pill toggle ("AI review — better structure for PDFs" + "?" help bubble).
- **Tooltips:** dark near-black rounded box with white text.
- **Modals:** centred white card (~400px wide, ~24px radius), background blurred + dimmed.
- **Icons:** thin-stroke line icons (Lucide-style).

---

## 4. Page-by-page layout

### 4.1 Landing `/` — `screens/01-landing.png`, `01b-landing-hero.png`
Centered container ~1150px max width.

1. **Sticky top bar** (translucent cream, becomes solid on scroll): left logo (teal rounded
   square with document icon + "Paper" in ink serif + "Parse" in rust serif); nav links
   Features · Formats · How it works · Quality; right: "Sign in" (secondary) and
   "Open your space →" (primary).
2. **Hero** (two columns, soft radial peach/teal gradient wash):
   - Left: "New · LaTeX editor with a live PDF" chip; giant serif H1 on three lines
     "Every paper, / *perfectly* (italic, peach highlighter underlay) / structured." (last
     line teal); paragraph; CTA pair "Open your space →" / "See how it works"; trust ticks
     "🔒 Runs on your machine ✓ No account in the cloud ✓ Open formats in, open formats out".
   - Right: illustration of a grey source PDF morphing (teal circular → button) into a
     "reader" window card showing a sample paper (title, authors, section "1 Lagrangian and
     conventions", an equation with number (1.1), a booktabs-style table). Floating badges:
     "HTML Reader view" (purple tag), "DOCX Word equations" (blue), "TEX Compiles cleanly" (teal).
3. **"Tested on" logo strip** — white band: TESTED ON · IEEE · ACM · Springer LNCS ·
   Elsevier · REVTeX · APA 7 · NeurIPS · ICML · amsart (grey serif wordmarks).
4. **Features** (`#features`) — eyebrow + H2 "Everything a paper is made of, kept" + lead;
   3×2 grid of cards, each with a tinted icon tile, bold title, description:
   Real equations · Faithful structure · Tables & figures · Any format to any format ·
   Read, correct, write · Optional AI review (last two use rust-tinted icons).
5. **Formats** (`#formats`) — H2 "One document model, every way in and out"; one large card:
   "YOU BRING" column (PDF / Word / LaTeX rows with coloured type badges) → centre teal
   tile "one structured document" → "YOU GET" column (PDF typeset with LaTeX / LaTeX .zip
   with figures / Word native equations).
6. **How it works** (`#how`) — H2 "From file to finished paper in three steps"; three cards,
   each with a grey icon well, big faint numeral 1/2/3 in the corner: Drop your files ·
   Read and fix · Export anywhere.
7. **Quality** (`#quality`) — H2 "Measured, not promised"; four stats with left teal rule:
   **0.99** average round-trip score · **100%** test formulas rendered · **29** journal and
   field templates tested · **6** export formats from one model; footnote source line.
8. **CTA banner** — full-width dark teal gradient rounded panel: serif "Bring your first
   paper", sub-line, white button "Open your space →".
9. **Footer** — thin rule; "© Paper Parse · runs locally" left; links right.

Sections fade/slide in on scroll (initial `opacity:0`).

### 4.2 Sign-in modal — `screens/02-signin-modal.png`
Over blurred landing. Logo tile, serif "Sign in", "Continue to your space.", fields
**Name** and **Password** (cream-filled inputs, teal focus ring), full-width teal
"Sign in →" button, "×" close. Posts to `/api/login`, then redirects to `/app`.

### 4.3 Dashboard `/app` ("Your space") — `screens/03-app.png`, `09-app-mobile.png`
- **Top bar:** logo | "Your space" label | nav pills Convert (active teal-tint) · Documents ·
  How it works · Memory · Usage (anchors scroll-spy the page) | right: avatar circle "A" +
  "admin ⌄" → **account menu** (`04-account-menu.png`): "Signed in as admin", Change password,
  "AI model for LaTeX edits" select + help text, Usage and costs, Paper Parse home, Log out.
- **Hero:** centered chip "✧ PDF · WORD · LATEX", serif H1 "Turn any paper into a /
  *clean, editable* document", sub-text.
- **Drop zone:** large white card with dashed border; teal icon tile (upload arrow);
  "Drop papers here or <u>browse files</u>"; privacy/OCR note; format chips.
- Under it: **AI review** toggle (left) and "⚙ Advanced" (right) → reveals
  "Word engine: built-in (recommended)" select (`05-advanced.png`).
- **Your documents:** serif H2 + count; status filter pills (All 830 / ● Ready 816 /
  ● Failed 14); toolbar: search input (with "/" shortcut hint), type segmented
  (All · PDF · Word · LaTeX), sort select (Newest first / Oldest first / Name A–Z),
  "↻ Re-process…" bulk button.
  - List grouped by **date headers**. Each row = white rounded card: coloured file-type
    icon (PDF/DOCX/TEX dog-eared page), filename (semibold), meta line "single column ·
    144 blocks · 7:43 PM" + optional "✧ AI review" (teal) + optional "⚠ N to check"
    (amber, links to `#report`). Right side: **Open** (primary), **LaTeX**, **Export**, **⋯**.
  - **Export** expands the card inline (`06-export-menu.png`): "EXPORT AS" three option
    tiles (PDF typeset with LaTeX / LaTeX .zip main.tex + figures / Word .docx with
    equations; selected = teal border + tint), Columns select ("as in the source"),
    Template select ("plain article"), primary "Download".
  - **⋯** menu: Re-process… · Delete.
  - Paginated: "Show more (800 left)" (30 per page).
- **How it works:** three cards (1. Convert, 2. Read and correct, 3. Export) with detail.
- **Memory:** collapsible bar "ⓘ Memory — corrections and preferences reused across
  documents"; inside, add form (type select e.g. *correction*, key, value).
- **Footer:** "Runs locally on your machine." and parser credits.
- **Mobile:** nav collapses to logo + avatar; everything single column, chips wrap.

### 4.4 Usage `/app/usage` — `screens/10-usage.png`
- Narrower top bar (Documents · Memory · Usage active).
- Serif H1 "Usage" + description.
- Filter row: range segmented (Today / 7 days / **30 days** / All), document select,
  type select (Text edit, LaTeX edit, Figure, Answer, Reviewer, Conversion, Reader fix,
  Outline upkeep…), "Download CSV" right.
- **4 KPI cards:** SPENT $17.91 (539 records · 6506 calls) · PER ASSISTANT REPLY $0.035 ·
  TOKENS 87M (in / cached / written / out) · EDITS APPLIED 183 of 263. Uppercase small
  label, large serif number, muted sub-line.
- **By type** card: table TYPE · RECORDS · CALLS · TOKENS IN · CACHED · OUT · COST (bold) ·
  AVG · SHARE (teal horizontal bar on beige track). Right-aligned numerals.
- **Records** table: long log (time, document, type chip, the suggestion/prompt excerpt,
  applied/ignored status, model, tokens, cost), "Show more".

### 4.5 Reader `/docs/{id}/paper.html` — `screens/11-reader.png`, `11b-reader-full.png`, `14-r-*.png`
- **Toolbar** (~53px, cream, bottom rule), left→right: "← Your space"; Reader/LaTeX
  segmented (Reader solid teal); truncated title "Assessing…"; search pill
  ("Search ⇧/"); colour-coded category buttons: **Write ⌄** (violet, expands to show
  **Assistant** and **Comments**), **Reviewer** (crimson), **View ⌄** (teal),
  **Versions ⌄** (amber → History, Re-read LaTeX), **Paper ⌄** (blue → Idea flow, Sections,
  Assets, Report); **Export ▾** (white) → popover "CONVERT TO": Columns (as source /
  single / double), Template (article / IEEE conference / ACM sigconf / Springer LNCS /
  Elsevier), buttons PDF · LaTeX (zip) · Word.
- **Left rail** (~300px, collapsible «): Outline/PDF segmented; italic small-caps group
  labels OUTLINE ▾ / FIGURES ▾ / TABLES ▾; indented section links (sans, muted).
  "PDF" tab shows the original page images.
- **Main column** (~690px measure, centered): serif title (large, bold), authors, justified
  hyphenated serif body at 1.06rem/1.72; italic run-in "*Abstract*—", "*Index Terms*—";
  section headings in caps serif with rule underneath; small faint page markers in the
  left gutter ("p. 1"), clickable to open the original PDF page; figures with captions,
  KaTeX equations with numbers, booktabs tables, numbered citations linking to references.
- **Right side panels** slide in (~480px) and push the text: e.g. **Reviewer**
  (`14-r-reviewer.png`) — header with icon, "Run all", ×; 2×2 grid of check cards
  (Claims / Paper / Grammar / Flow, each "Not run yet"; selected has crimson border);
  crimson CTA "Check the claims". Assistant and Comments panels follow the same pattern.

### 4.6 LaTeX editor `/docs/{id}/latex` — `screens/13-latex-editor.png`
Full-viewport app layout, three panes:
- **Top bar:** logo tile; breadcrumb "Your space / **2610-37400v1-pdf.pdf**";
  Reader/LaTeX segmented (LaTeX active); sidebar toggle; status "● Compiled · 0.9 s";
  "☑ Auto" checkbox; primary **▶ Compile** with `Ctrl S` kbd badge; History; Assistant
  (lavender); Reviewer (crimson outline); Download.
- **Amber banner:** "This LaTeX is **synced with the reader**: what you save here changes
  the document, and edits made in the reader appear here. Only the parts you change are
  rewritten."
- **Left sidebar (~240px):** FILES (+ new file) — `main.tex` with TEX badge and MAIN tag
  (selected teal-tint row), `figs/*.png` with IMG badges; OUTLINE — section tree (Abstract
  in italic).
- **Centre editor:** tab "main.tex"; icon buttons fold all / unfold all / search;
  monospace source on cream; bottom **Problems** bar with red/amber/grey counters
  (0 · 0 · 18) and "compiled in 0.9 s ⌄".
- **Right PDF preview:** zoom − / Fit / +, hint "Select text: copy, source or AI ·
  Ctrl-click: go to source", "→ Find in PDF" (SyncTeX). (Rendered blank in the headless
  capture.)
- Assistant drawer: chat selector (This chat / earlier chats), New chat, "@ Add context",
  attach files, Snip (mark up part of the PDF), Send. Reviewer drawer with "Run all".

---

## 5. Files in this folder
- `screens/` — 01 landing (full + hero), 02 sign-in modal, 03 dashboard full page,
  04 account menu, 05 advanced options, 06 inline export panel, 07 row "⋯" menu,
  08 memory panel, 09 dashboard at phone width, 10 usage, 11 reader (viewport + full page),
  12 reader `#report`, 13 LaTeX editor, 14-r-* reader toolbar states (write, view,
  versions, paper, reviewer, export).
- `html/` — saved DOM of landing, app, usage, reader, latex pages.
- `landing-text.txt`, `app-text.txt`, `usage-text.txt`, `reader-text.txt`, `latex-text.txt` — visible text.
- `app-root-tokens.txt` — CSS custom properties of the app.
