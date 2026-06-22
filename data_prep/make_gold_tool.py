# /// script
# requires-python = ">=3.9"
# dependencies = ["pillow"]
# ///
"""
Build a self-contained HTML tool for hand-creating GOLD ground-truth eval lines
from sampled directory pages.

Input  : one or more sampled volume dirs (../directory-pipeline/output/<slug>/)
         that have been OCR'd with Surya (run_surya_ocr.py -> {stem}_surya.json).
Output : a single .html file (no server, no deps) that shows, per OCR'd line:
             [ cropped line image ] [ raw_line (editable) ] [ 8 field cells ]
         ordered column-then-top-to-bottom, low-confidence lines tinted.
         An "Export gold.jsonl" button downloads JSONL in the EXACT schema that
         eval/evaluate.py consumes (see data/lain_eval.jsonl):
             {"raw_line", "context":{dialect,alphabetical_range,directory_year,image},
              "record":{name,is_business,spouse_name,race_designation,
                        occupation_role,employer,address,home_address}}

The line crops are base64-embedded so the .html is fully portable.

Why Surya: it gives line-level bboxes (not just page text), so each gold row is
verified against its own sliced line image rather than hunting the full page.
raw_line is pre-filled for free; the 8-field split stays human (true gold, no
parser anchoring).

Usage
-----
    PY=/Users/joshhadro/github/directory-pipeline/.venv/bin/python   # has pillow
    $PY data_prep/make_gold_tool.py \
        ../directory-pipeline/output/ia_lain_1884_1884bpl \
        -o gold_lain_1884.html --cols 2 --dialect nyc

    # then: run surya first if not done -
    $PY ../directory-pipeline/pipeline/run_surya_ocr.py ../directory-pipeline/output/<slug>
"""
from __future__ import annotations

import argparse
import base64
import html
import io
import json
import sys
from pathlib import Path
from typing import Optional

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow required: use the directory-pipeline venv "
             "(.venv/bin/python has pillow), or `pip install pillow`.")

# Must match data_prep/synth_persons.py FIELDS / eval/evaluate.py FIELDS
FIELDS = ["name", "is_business", "spouse_name", "race_designation",
          "occupation_role", "employer", "address", "home_address"]

CROP_MAXH = 170         # px: cap on encoded crop height (downscale only above this)
CROP_PAD_X = 8          # px horizontal padding around the bbox
CROP_PAD_TOP = 8        # px context above the line
CROP_EXTEND_BELOW = 1.05  # extend below by this * line-height to catch wrapped continuations


def _iiif_text(v) -> str:
    """Flatten an IIIF label/value: v2 plain string, or v3 {lang:[str]} / lists."""
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        for vals in v.values():
            if isinstance(vals, list) and vals:
                return str(vals[0])
            if isinstance(vals, str):
                return vals
        return ""
    if isinstance(v, list) and v:
        return _iiif_text(v[0])
    return ""


def _load_master(path: Path) -> dict:
    """id -> row, for auto-resolving column_count / year from the manifest identifier."""
    if not path.exists():
        return {}
    import csv
    idx = {}
    for r in csv.DictReader(open(path, encoding="utf-8")):
        rid = (r.get("id") or "").strip()
        if rid:
            idx[rid] = r
    return idx


def _master_row(d: Path, meta: dict, master: dict):
    """Match this sample dir to a master row. Search a haystack of the IIIF identifier,
    the manifest top-level id URL (carries the full NYPL UUID / IA slug / LoC id), and
    the dir slug — longest matching id wins (avoids short-id false hits)."""
    hay = " ".join([meta.get("identifier", ""), meta.get("manifest_id", ""), d.name]).lower()
    cands = [rid for rid in master if rid and rid.lower() in hay]
    return master[max(cands, key=len)] if cands else None


def _manifest_meta(d: Path) -> dict:
    """Pull year/title/identifier from _sample_manifest.json (IIIF v3)."""
    mf = d / "_sample_manifest.json"
    meta = {"year": "", "title": "", "identifier": "", "manifest_id": ""}
    if not mf.exists():
        return meta
    try:
        m = json.load(open(mf, encoding="utf-8"))
    except Exception:
        return meta
    meta["manifest_id"] = str(m.get("id") or m.get("@id") or "")
    meta["title"] = _iiif_text(m.get("label"))
    for entry in m.get("metadata", []) or []:
        lab = _iiif_text(entry.get("label")).lower()
        val = _iiif_text(entry.get("value"))
        if lab == "date" and not meta["year"]:
            meta["year"] = val
        if lab == "identifier" and not meta["identifier"]:
            meta["identifier"] = val
    return meta


def _colidx(bbox: list, width: int, cols: int) -> int:
    if cols <= 1 or not width:
        return 0
    x1, _, x2, _ = bbox
    return max(0, min(cols - 1, int(((x1 + x2) / 2) / (width / cols))))


def _order_lines(lines: list, width: int, cols: int) -> list:
    """Column-bucket by bbox x-center, then top-to-bottom within a column."""
    if cols <= 1:
        return sorted(range(len(lines)), key=lambda i: lines[i]["bbox"][1])
    return sorted(range(len(lines)),
                  key=lambda i: (_colidx(lines[i]["bbox"], width, cols), lines[i]["bbox"][1]))


def _crop_b64(img: Image.Image, bbox: list) -> str:
    x1, y1, x2, y2 = bbox
    W, H = img.size
    lh = max(1, y2 - y1)
    box = (max(0, x1 - CROP_PAD_X), max(0, y1 - CROP_PAD_TOP),
           min(W, x2 + CROP_PAD_X), min(H, int(y2 + lh * CROP_EXTEND_BELOW)))
    crop = img.crop(box)
    if crop.height > CROP_MAXH:
        scale = CROP_MAXH / crop.height
        crop = crop.resize((max(1, int(crop.width * scale)), CROP_MAXH))
    if crop.mode != "RGB":
        crop = crop.convert("RGB")
    buf = io.BytesIO()
    crop.save(buf, format="JPEG", quality=78)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _collect(dirs: list, cols_override, min_conf: float, master: dict, max_lines: int = 0) -> list:
    """-> list of page dicts: {image, year, lines:[{raw,conf,crop}...]}.
    max_lines caps total candidate lines across the volume (0 = all)."""
    pages = []
    taken = 0
    for d in dirs:
        d = Path(d)
        meta = _manifest_meta(d)
        row = _master_row(d, meta, master)
        if cols_override:
            cols, src = cols_override, "--cols"
        elif row and (row.get("column_count") or "").strip().isdigit():
            cols, src = int(row["column_count"]), f"master({row['id']})"
        else:
            cols, src = 1, "default"
        if row and not meta["year"]:
            meta["year"] = row.get("year") or ""
        print(f"  {d.name}: cols={cols} [{src}]", file=sys.stderr)
        sjsons = sorted(d.glob("*_surya.json"))
        if not sjsons:
            print(f"  ! no *_surya.json in {d} (run run_surya_ocr.py first)", file=sys.stderr)
            continue
        for sj in sjsons:
            stem = sj.name[:-len("_surya.json")]
            jpg = next((d / f"{stem}{ext}" for ext in (".jpg", ".jpeg", ".JPG")
                        if (d / f"{stem}{ext}").exists()), None)
            if jpg is None:
                print(f"  ! no image for {sj.name}", file=sys.stderr)
                continue
            data = json.load(open(sj, encoding="utf-8"))
            width = data.get("image_width") or 0
            lines = data.get("lines", [])
            img = Image.open(jpg)
            from PIL import ImageStat
            if ImageStat.Stat(img.convert("L")).stddev[0] < 7:   # blank verso — skip
                print(f"  ~ {jpg.name}: blank page, skipped", file=sys.stderr)
                continue
            if not width:
                width = img.size[0]
            order = _order_lines(lines, width, cols)
            rows = []
            for i in order:
                if max_lines and taken >= max_lines:
                    break
                ln = lines[i]
                if (ln.get("confidence") or 0) < min_conf:
                    continue
                txt = (ln.get("text") or "").strip()
                if not txt:
                    continue
                rows.append({"raw": txt, "conf": round(ln.get("confidence") or 0, 3),
                             "col": _colidx(ln["bbox"], width, cols),
                             "crop": _crop_b64(img, ln["bbox"])})
                taken += 1
            if rows:
                pages.append({"image": jpg.name, "year": meta["year"],
                              "title": meta["title"], "rows": rows})
                print(f"  + {jpg.name}: {len(rows)} lines", file=sys.stderr)
            if max_lines and taken >= max_lines:
                break
    return pages


def build_html(pages: list, dialect: str) -> str:
    payload = json.dumps({"pages": pages, "dialect": dialect, "fields": FIELDS})
    title = "City-directory gold editor"
    # token replacement (not str.format) so JS/CSS braces stay literal
    return _TEMPLATE.replace("__TITLE__", html.escape(title)).replace("__PAYLOAD__", payload)


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>__TITLE__</title>
<style>
  body { font: 13px/1.45 -apple-system, system-ui, sans-serif; margin: 0; background:#eef1f4; color:#222; }
  header { position: sticky; top:0; background:#1d2b3a; color:#fff; padding:9px 16px; z-index:20;
           display:flex; gap:14px; align-items:center; flex-wrap:wrap; }
  header h1 { font-size:14px; margin:0; font-weight:600; }
  header .stat { font-size:12px; opacity:.85; }
  header input[type=text] { border:0; border-radius:4px; padding:3px 6px; font:12px monospace; }
  button { font-size:13px; padding:6px 11px; border:0; border-radius:5px; cursor:pointer; background:#3a4a5c; color:#fff; }
  button:hover { filter:brightness(1.12); }
  button.primary { background:#2e8b57; }
  button.ghost { background:#e7ebef; color:#33414f; }
  .filebtn { font-size:13px; padding:6px 11px; border-radius:5px; cursor:pointer; background:#e7ebef; color:#33414f; }
  .filebtn:hover { filter:brightness(1.06); }
  .filebtn input { display:none; }
  #saved { color:#9fe0b5; font-size:11px; }
  .nocrop { color:#b08; font-size:11px; font-style:italic; }
  #conv { max-width:1080px; margin:12px auto 0; background:#fffdf3; border:1px solid #e9e2c5;
          border-radius:7px; padding:8px 14px; font-size:12px; }
  #conv summary { cursor:pointer; font-weight:600; color:#6b5d20; }
  #conv summary .hint { font-weight:400; color:#a99; font-size:11px; }
  #conv ul { margin:8px 0 4px; padding-left:18px; }
  #conv li { margin:3px 0; line-height:1.5; }
  #conv code { background:#f1edda; border-radius:3px; padding:0 4px; font:11px monospace; }
  #root { padding:14px 16px 80px; max-width:1080px; margin:0 auto; }
  .pagehdr { font-weight:600; color:#33414f; margin:18px 0 8px; padding-bottom:5px;
             border-bottom:2px solid #cdd6df; display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
  .pagehdr .sub { font-weight:400; font-size:12px; color:#7a8794; }
  .card { background:#fff; border:1px solid #dfe4e9; border-radius:7px; padding:9px 11px;
          margin:0 0 9px; box-shadow:0 1px 2px rgba(0,0,0,.04); }
  .card.skip { opacity:.4; }
  .card.lowconf { border-left:4px solid #f0ad4e; }
  /* line crop: its own full-width row, scrolls horizontally — never under the fields */
  .strip { overflow-x:auto; overflow-y:hidden; background:#fcfbf6; border:1px solid #ece8da;
           border-radius:4px; padding:5px 6px; margin-bottom:8px; }
  .strip img { display:block; height:auto; max-height:92px; width:auto; max-width:none; }
  .metarow { display:flex; gap:14px; align-items:center; font-size:11px; color:#94a0ac; margin-bottom:7px; }
  .metarow label { color:#5a6b7b; cursor:pointer; user-select:none; }
  .rawrow input { width:100%; font:13px/1.3 monospace; padding:5px 7px; border:1px solid #cfd6dd;
                  border-radius:4px; box-sizing:border-box; background:#fafbfc; margin-bottom:8px; }
  .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:7px 12px; }
  .fc { display:flex; flex-direction:column; gap:2px; }
  .fc label { font-size:10px; text-transform:uppercase; letter-spacing:.04em; color:#6a7886; }
  .fc input[type=text] { font:12px monospace; padding:4px 6px; border:1px solid #ccd3da;
                         border-radius:3px; box-sizing:border-box; }
  .fc.biz { flex-direction:row; align-items:center; gap:7px; padding-top:14px; }
  .fc.biz label { font-size:11px; text-transform:none; }
  /* focus mode */
  .focusbar { position:sticky; top:40px; z-index:15; background:#e9eef3; border:1px solid #d3dce4;
              border-radius:7px; padding:9px 12px; margin-bottom:12px; display:flex; gap:14px;
              align-items:center; flex-wrap:wrap; }
  .focusbar .count { font-weight:600; font-size:13px; min-width:120px; }
  .bar { height:6px; background:#cfd8e0; border-radius:3px; flex:1; min-width:140px; overflow:hidden; }
  .bar > i { display:block; height:100%; background:#2e8b57; transition:width .12s; }
  .keys { font-size:11px; color:#566; }
  kbd { background:#fff; border:1px solid #b9c2cb; border-bottom-width:2px; border-radius:3px;
        padding:0 4px; font:11px monospace; }
  body.focus .card { max-width:880px; margin:0 auto 9px; }
  body.focus .card .strip img { max-height:130px; }
  .ctx { max-width:880px; margin:0 auto; opacity:.5; }
  .ctx .strip img { height:40px; }
  .ctx .lbl { font-size:10px; color:#8a96a2; margin:0 4px 2px; }
</style></head>
<body>
<header>
  <h1>__TITLE__</h1>
  <button id="modeBtn" class="ghost" onclick="setMode(mode==='list'?'focus':'list')"></button>
  <span class="stat" id="stat"></span>
  <span class="stat">dialect <input type="text" id="dialect" style="width:64px" /></span>
  <button class="ghost" onclick="toggleAllSkip()">Toggle all skip</button>
  <label class="filebtn">⬆ Import<input type="file" id="importFile" accept=".jsonl,.json,.txt" /></label>
  <button class="primary" onclick="exportGold()">⬇ Export gold.jsonl</button>
  <span class="stat" id="saved"></span>
</header>
<details id="conv">
  <summary>Transcription conventions <span class="hint">(click to collapse)</span></summary>
  <ul>
    <li><b>Verbatim.</b> Type each field as printed — don't expand abbreviations
        (<code>insur</code> stays <code>insur</code>, not "insurance"). Keep
        <code>h</code> / <code>r</code> / <code>bds</code> / <code>wid.</code> / <code>clk.</code> as-is.</li>
    <li><b>No delimiter commas.</b> The line's separating commas aren't field content.
        <code>Gibson Thomas, clk. h 38 Prospect</code> →
        name <code>Gibson Thomas</code>, occupation <code>clk.</code>, address <code>h 38 Prospect</code>.
        A trailing comma scores as wrong.</li>
    <li><b>Fractions as ASCII.</b> Write <code>1/2</code>, not the <code>½</code> glyph
        (e.g. <code>870 1/2 De Kalb av</code>). Fix the raw_line too if OCR misread it.</li>
    <li><b>Titles/honorifics go in <code>name</code></b>, verbatim — <code>Rev.</code>,
        <code>Dr.</code>, <code>Capt.</code>, <code>Mrs.</code>, <code>Miss</code>
        (e.g. <code>Gibert Lyman (Rev.)</code>). Don't expand to an occupation.</li>
    <li><b>Role vs employer.</b> The job word → <code>occupation_role</code>; an
        institution/company worked <i>at</i> → <code>employer</code> (both verbatim).
        <code>Scudder Ephraim, c. h. clk. h 76 Nassau</code> → occupation <code>clk.</code>,
        employer <code>c. h.</code>, address <code>h 76 Nassau</code>.</li>
    <li><b>address vs home_address.</b> The listed address → <code>address</code>, keeping its
        <code>h</code>/<code>r</code>/<code>bds</code> prefix. Use <code>home_address</code> ONLY for
        a <i>second</i>, separate <code>h.</code> home when the entry lists both a work address and a
        home. A lone <code>h 449 Clason av</code> goes in <code>address</code>, not home_address.</li>
    <li><b>Wrapped entries are one record.</b> Join a continuation line into the entry
        (raw_line + the right field) and <b>skip</b> the leftover fragment card —
        e.g. <code>… h 343</code> + <code>Kosciusko</code> → address <code>h 343 Kosciusko</code>.</li>
    <li><b>Spacing &amp; case don't matter</b> — fields are trimmed on export and the scorer
        ignores extra spaces, case, and trailing periods. Just don't add commas.</li>
    <li><b>Skip non-entries</b> — page numbers, running heads (<code>GIB-GIF</code>), ads.
        A gold line needs a <code>name</code>; nameless / skipped rows are excluded on export.</li>
  </ul>
</details>
<div id="root"></div>
<script>
const DATA = __PAYLOAD__;
const PAGES = DATA.pages;
const FIELDS = DATA.fields;

// ---- state ----
const entries = [];
PAGES.forEach((pg, pi) => pg.rows.forEach((r, ri) => entries.push({
  pi, ri, col: r.col || 0, raw: r.raw, conf: r.conf, crop: r.crop, skip: false,
  rec: Object.fromEntries(FIELDS.map(f => [f, f === 'is_business' ? false : '']))
})));
const arState = {};           // page index -> alphabetical_range
let dialect = DATA.dialect;
let mode = 'list';
let cursor = 0;
let ctxOn = false;

// ---- dom helper ----
function el(tag, attrs, kids) {
  const e = document.createElement(tag);
  for (const k in (attrs||{})) {
    if (k === 'class') e.className = attrs[k];
    else if (k.startsWith('on')) e[k] = attrs[k];
    else e.setAttribute(k, attrs[k]);
  }
  (kids||[]).forEach(c => e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c));
  return e;
}
const root = document.getElementById('root');
const dialectInput = document.getElementById('dialect');
dialectInput.value = dialect;
dialectInput.oninput = () => { dialect = dialectInput.value; scheduleSave(); };

// ---- card (shared by both modes) ----
function card(en) {
  const wrap = el('div', {class: 'card' + (en.skip ? ' skip' : '') + (en.conf < 0.7 ? ' lowconf' : '')});

  const strip = el('div', {class: 'strip'});
  if (en.crop) strip.appendChild(el('img', {src: 'data:image/jpeg;base64,' + en.crop}));
  else strip.appendChild(el('span', {class: 'nocrop'}, ['(imported — no line image)']));
  wrap.appendChild(strip);

  const skipBox = el('input', {type: 'checkbox'});
  skipBox.checked = en.skip;
  skipBox.onchange = () => { en.skip = skipBox.checked; wrap.classList.toggle('skip', en.skip); updateStat(); };
  wrap.appendChild(el('div', {class: 'metarow'}, [
    el('label', {}, [skipBox, ' skip (not an entry)']),
    `conf ${en.conf}`,
    `${PAGES[en.pi].image}`
  ]));

  const raw = el('input', {type: 'text', value: en.raw});
  raw.oninput = () => en.raw = raw.value;
  wrap.appendChild(el('div', {class: 'rawrow'}, [raw]));

  const grid = el('div', {class: 'grid'});
  FIELDS.forEach(f => {
    if (f === 'is_business') {
      const cb = el('input', {type: 'checkbox'});
      cb.checked = en.rec[f];
      cb.onchange = () => en.rec[f] = cb.checked;
      grid.appendChild(el('div', {class: 'fc biz'}, [cb, el('label', {}, [f])]));
    } else {
      const inp = el('input', {type: 'text', value: en.rec[f]});
      inp.oninput = () => en.rec[f] = inp.value;
      const cell = el('div', {class: 'fc'}, [el('label', {}, [f]), inp]);
      if (f === 'name') inp.dataset.name = '1';
      grid.appendChild(cell);
    }
  });
  wrap.appendChild(grid);
  return wrap;
}

function pageHeader(pi) {
  const pg = PAGES[pi];
  const ar = el('input', {type: 'text', placeholder: 'A–B', style: 'width:90px', value: arState[pi] || ''});
  ar.oninput = () => arState[pi] = ar.value;
  return el('div', {class: 'pagehdr'}, [
    `${pg.title || pg.image}`,
    el('span', {class: 'sub'}, [`${pg.image} · ${pg.year || '?'} · alpha-range:`]),
    ar
  ]);
}

function ctxCrop(en, label) {
  if (!en.crop) return el('div', {class: 'ctx'}, []);
  const strip = el('div', {class: 'strip'});
  strip.appendChild(el('img', {src: 'data:image/jpeg;base64,' + en.crop}));
  return el('div', {class: 'ctx'}, [el('div', {class: 'lbl'}, [label]), strip]);
}

// ---- render ----
function render() {
  root.innerHTML = '';
  document.body.classList.toggle('focus', mode === 'focus');
  document.getElementById('modeBtn').textContent = mode === 'list' ? '⊟ Focus mode' : '☰ List mode';
  if (mode === 'list') {
    let pi = -1;
    entries.forEach(en => {
      if (en.pi !== pi) { pi = en.pi; root.appendChild(pageHeader(pi)); }
      root.appendChild(card(en));
    });
  } else {
    cursor = Math.max(0, Math.min(cursor, entries.length - 1));
    const en = entries[cursor];
    root.appendChild(focusBar(en));
    if (ctxOn && cursor > 0) root.appendChild(ctxCrop(entries[cursor - 1], '↑ previous line'));
    root.appendChild(card(en));
    if (ctxOn && cursor < entries.length - 1) root.appendChild(ctxCrop(entries[cursor + 1], '↓ next line'));
    setTimeout(() => { const n = root.querySelector('input[data-name]'); if (n) n.focus(); }, 0);
  }
  updateStat();
}

function focusBar(en) {
  const pct = entries.length ? Math.round((cursor + 1) / entries.length * 100) : 0;
  const ar = el('input', {type: 'text', placeholder: 'A–B', style: 'width:80px', value: arState[en.pi] || ''});
  ar.oninput = () => arState[en.pi] = ar.value;
  const ctxBox = el('input', {type: 'checkbox'});
  ctxBox.checked = ctxOn;
  ctxBox.onchange = () => { ctxOn = ctxBox.checked; render(); };
  const npages = new Set(entries.map(e => e.pi)).size;
  return el('div', {class: 'focusbar'}, [
    el('span', {class: 'count'}, [`${cursor + 1} / ${entries.length}  ·  p${en.pi + 1} c${en.col + 1}`]),
    el('div', {class: 'bar'}, [el('i', {style: `width:${pct}%`})]),
    el('button', {class: 'ghost', onclick: () => go(-1)}, ['◀ prev']),
    el('button', {class: 'ghost', onclick: () => go(1)}, ['next ▶']),
    el('button', {class: 'ghost', onclick: () => { en.skip = !en.skip; go(1); }}, ['skip ▶']),
    el('button', {class: 'ghost', onclick: () => jumpTo(nextColStart())}, ['↦ col']),
    el('button', {class: 'ghost', onclick: () => jumpTo(nextPageStart())},
       [npages > 1 ? '↦ page' : '↦ page (1 only)']),
    el('label', {class: 'keys'}, [ctxBox, ' context']),
    el('span', {style: 'font-size:12px;color:#5a6b7b'}, ['alpha:']), ar,
    el('span', {class: 'keys'}, ['  ', kbd('↵'), ' next · ', kbd('⇧↵'), ' prev · ', kbd('Esc'), ' skip · ', kbd('⌘/⌃B'), ' biz'])
  ]);
}
function kbd(t) { return el('kbd', {}, [t]); }

function go(delta) {
  cursor = Math.max(0, Math.min(cursor + delta, entries.length - 1));
  render();
  scheduleSave();
}

function jumpTo(i) { if (i >= 0) { cursor = i; render(); scheduleSave(); } }
function nextColStart() {                       // first entry of the next column (or next page)
  const c = entries[cursor];
  for (let i = cursor + 1; i < entries.length; i++)
    if (entries[i].pi !== c.pi || entries[i].col !== c.col) return i;
  return -1;
}
function nextPageStart() {
  const c = entries[cursor];
  for (let i = cursor + 1; i < entries.length; i++) if (entries[i].pi !== c.pi) return i;
  return -1;
}

function setMode(m) {
  if (m === 'focus') {            // jump focus to the first not-yet-touched entry
    const first = entries.findIndex(e => !e.skip && !e.rec.name.trim());
    cursor = first >= 0 ? first : 0;
  }
  mode = m;
  render();
}

// Mac-safe: Enter/Shift+Enter/Esc work inside inputs and don't collide with the OS;
// use e.code (physical key) for the modifier combo since Option/Alt rewrites e.key.
document.addEventListener('keydown', e => {
  if (mode !== 'focus') return;
  const mod = e.ctrlKey || e.metaKey;
  if (e.code === 'Enter' && e.shiftKey) { e.preventDefault(); go(-1); }       // prev
  else if (e.code === 'Enter' && !mod) { e.preventDefault(); go(1); }          // next
  else if (e.code === 'Escape') { e.preventDefault(); entries[cursor].skip = true; go(1); }  // skip + next
  else if (mod && e.code === 'KeyB') { e.preventDefault(); const en = entries[cursor]; en.rec.is_business = !en.rec.is_business; render(); scheduleSave(); }  // toggle biz
});

// ---- export / bulk / stats ----
function exportGold() {
  const lines = [];
  entries.forEach(en => {
    if (en.skip || !en.rec.name.trim()) return;   // a gold line needs a name
    const rec = {};
    FIELDS.forEach(f => rec[f] = (f === 'is_business') ? en.rec[f] : String(en.rec[f]).trim());
    lines.push(JSON.stringify({
      raw_line: en.raw.trim(),
      context: {
        dialect: dialect.trim(),
        alphabetical_range: (arState[en.pi] || '').trim(),
        directory_year: String(PAGES[en.pi].year || ''),
        image: PAGES[en.pi].image
      },
      record: rec
    }));
  });
  const blob = new Blob([lines.join('\n') + '\n'], {type: 'application/jsonl'});
  const a = el('a', {href: URL.createObjectURL(blob), download: 'gold.jsonl'});
  document.body.appendChild(a); a.click(); a.remove();
  alert(`Exported ${lines.length} gold lines (not skipped, has a name).`);
}

function toggleAllSkip() {
  const target = !entries.every(e => e.skip);
  entries.forEach(e => e.skip = target);
  render();
  scheduleSave();
}

function updateStat() {
  const total = entries.length;
  const skipped = entries.filter(e => e.skip).length;
  const ready = entries.filter(e => !e.skip && e.rec.name.trim()).length;
  document.getElementById('stat').textContent =
    `${PAGES.length} pages · ${total} lines · ${skipped} skipped · ${ready} ready`;
}

// ---- persistence: autosave to localStorage, keyed per volume ----
const STORE_KEY = 'goldtool:' + (PAGES[0] ? PAGES[0].image : 'x') + ':' + entries.length;
let saveTimer = null;
function fieldsFrom(r) {
  const o = {};
  FIELDS.forEach(f => o[f] = (f === 'is_business') ? !!(r && r[f]) : ((r && r[f]) || ''));
  return o;
}
function setSaved(msg) { const s = document.getElementById('saved'); if (s) s.textContent = msg; }
function save() {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify({
      v: 1, dialect, cursor, mode, ar: arState,
      entries: entries.map(e => ({ raw: e.raw, skip: e.skip, rec: e.rec, pi: e.pi }))
    }));
    setSaved('saved ✓');
  } catch (err) { setSaved('autosave off (storage blocked)'); }
}
function scheduleSave() { clearTimeout(saveTimer); saveTimer = setTimeout(save, 400); }
function restore() {
  try {
    const d = JSON.parse(localStorage.getItem(STORE_KEY) || 'null');
    if (!d || !d.entries) return false;
    d.entries.forEach((s, i) => {
      if (i < entries.length) { entries[i].raw = s.raw; entries[i].skip = !!s.skip; entries[i].rec = fieldsFrom(s.rec); }
      else entries.push({ pi: s.pi || 0, ri: -1, raw: s.raw || '', conf: 1, crop: '', skip: !!s.skip, rec: fieldsFrom(s.rec) });
    });
    Object.assign(arState, d.ar || {});
    if (d.dialect) { dialect = d.dialect; dialectInput.value = dialect; }
    if (typeof d.cursor === 'number') cursor = d.cursor;
    if (d.mode) mode = d.mode;
    return true;
  } catch (err) { return false; }
}

// ---- import a gold.jsonl: fuzzy-match each record back onto its entry ----
function toks(s) { return new Set(String(s || '').toLowerCase().match(/[a-z0-9]+/g) || []); }
function jac(a, b) { if (!a.size || !b.size) return 0; let n = 0; a.forEach(x => { if (b.has(x)) n++; }); return n / (a.size + b.size - n); }
function importGold(text) {
  const recs = text.split(/\r?\n/).map(l => l.trim()).filter(Boolean)
    .map(l => { try { return JSON.parse(l); } catch (e) { return null; } }).filter(Boolean);
  const N = entries.length, claimed = new Set();          // match only against original OCR entries
  let matched = 0, added = 0;
  recs.forEach(g => {
    if (!g.record) return;
    const img = g.context && g.context.image, gt = toks(g.raw_line || '');
    let best = -1, bs = 0;
    for (let i = 0; i < N; i++) {
      if (claimed.has(i)) continue;
      if (img && PAGES[entries[i].pi].image !== img) continue;
      const s = jac(gt, toks(entries[i].raw));
      if (s > bs) { bs = s; best = i; }
    }
    let pi;
    if (best >= 0 && bs >= 0.2) {
      const en = entries[best]; claimed.add(best); pi = en.pi;
      en.raw = g.raw_line || en.raw; en.rec = fieldsFrom(g.record); en.skip = false; matched++;
    } else {
      pi = Math.max(0, PAGES.findIndex(p => p.image === img));
      entries.push({ pi, ri: -1, raw: g.raw_line || '', conf: 1, crop: '', skip: false, rec: fieldsFrom(g.record) });
      added++;
    }
    if (g.context && g.context.alphabetical_range) arState[pi] = g.context.alphabetical_range;
    if (g.context && g.context.dialect) { dialect = g.context.dialect; dialectInput.value = dialect; }
  });
  save(); render();
  alert(`Imported ${matched} matched + ${added} added (no crop) = ${matched + added} record(s).`);
}
document.getElementById('importFile').addEventListener('change', ev => {
  const f = ev.target.files[0]; if (!f) return;
  const rd = new FileReader();
  rd.onload = () => importGold(String(rd.result));
  rd.readAsText(f);
  ev.target.value = '';
});

// ---- startup ----
const restored = restore();
render();
root.addEventListener('input', scheduleSave);
root.addEventListener('change', scheduleSave);
if (restored) setSaved('restored from autosave ✓');
</script>
</body></html>
"""


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dirs", nargs="+", help="sampled volume dir(s) with *_surya.json")
    ap.add_argument("-o", "--out", default="gold_tool.html", help="output HTML")
    ap.add_argument("--cols", type=int, default=0,
                    help="override column count (default: auto from master_directories.csv)")
    ap.add_argument("--master", default=str(Path(__file__).resolve().parent / "master_directories.csv"),
                    help="master CSV used to auto-resolve column_count / year")
    ap.add_argument("--dialect", default="nyc", help="context.dialect (default nyc)")
    ap.add_argument("--min-conf", type=float, default=0.0,
                    help="drop OCR lines below this confidence")
    ap.add_argument("--max-lines", type=int, default=0,
                    help="cap total candidate lines across the volume (0 = all; e.g. 40 std / 100 deep)")
    args = ap.parse_args(argv)

    master = _load_master(Path(args.master))
    pages = _collect(args.dirs, args.cols, args.min_conf, master, args.max_lines)
    if not pages:
        return "no OCR'd pages found — run run_surya_ocr.py on the dir(s) first."
    Path(args.out).write_text(build_html(pages, args.dialect), encoding="utf-8")
    total = sum(len(p["rows"]) for p in pages)
    print(f"\nwrote {args.out}  ({len(pages)} pages, {total} candidate lines)", file=sys.stderr)
    print("Open it in a browser, correct fields, click Export.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
