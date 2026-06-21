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

CROP_MAXH = 70          # px: displayed/encoded height of each line strip
CROP_PAD = 6            # px padding around each bbox before cropping


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
    """Match this sample dir to a master row by identifier, then by id-in-dirname."""
    ident = meta.get("identifier") or ""
    if ident in master:
        return master[ident]
    name = d.name
    # longest id that appears in the dir slug wins (avoids short-id false hits)
    cands = [rid for rid in master if rid and rid in name]
    return master[max(cands, key=len)] if cands else None


def _manifest_meta(d: Path) -> dict:
    """Pull year/title/identifier from _sample_manifest.json (IIIF v3)."""
    mf = d / "_sample_manifest.json"
    meta = {"year": "", "title": "", "identifier": ""}
    if not mf.exists():
        return meta
    try:
        m = json.load(open(mf, encoding="utf-8"))
    except Exception:
        return meta
    label = m.get("label", {})
    for v in label.values():
        if v:
            meta["title"] = v[0]
            break
    for entry in m.get("metadata", []) or []:
        lab = next(iter(entry.get("label", {}).values()), [""])[0].lower()
        val = next(iter(entry.get("value", {}).values()), [""])[0]
        if lab == "date" and not meta["year"]:
            meta["year"] = val
        if lab == "identifier" and not meta["identifier"]:
            meta["identifier"] = val
    return meta


def _order_lines(lines: list, width: int, cols: int) -> list:
    """Column-bucket by bbox x-center, then top-to-bottom within a column."""
    if cols <= 1:
        return sorted(range(len(lines)), key=lambda i: lines[i]["bbox"][1])
    colw = width / cols

    def colidx(i):
        x1, _, x2, _ = lines[i]["bbox"]
        c = int(((x1 + x2) / 2) / colw)
        return max(0, min(cols - 1, c))

    return sorted(range(len(lines)), key=lambda i: (colidx(i), lines[i]["bbox"][1]))


def _crop_b64(img: Image.Image, bbox: list) -> str:
    x1, y1, x2, y2 = bbox
    W, H = img.size
    box = (max(0, x1 - CROP_PAD), max(0, y1 - CROP_PAD),
           min(W, x2 + CROP_PAD), min(H, y2 + CROP_PAD))
    crop = img.crop(box)
    if crop.height > CROP_MAXH:
        scale = CROP_MAXH / crop.height
        crop = crop.resize((max(1, int(crop.width * scale)), CROP_MAXH))
    if crop.mode != "RGB":
        crop = crop.convert("RGB")
    buf = io.BytesIO()
    crop.save(buf, format="JPEG", quality=78)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _collect(dirs: list, cols_override, min_conf: float, master: dict) -> list:
    """-> list of page dicts: {image, year, lines:[{raw,conf,crop}...]}."""
    pages = []
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
            if not width:
                width = img.size[0]
            order = _order_lines(lines, width, cols)
            rows = []
            for i in order:
                ln = lines[i]
                if (ln.get("confidence") or 0) < min_conf:
                    continue
                txt = (ln.get("text") or "").strip()
                if not txt:
                    continue
                rows.append({"raw": txt, "conf": round(ln.get("confidence") or 0, 3),
                             "crop": _crop_b64(img, ln["bbox"])})
            pages.append({"image": jpg.name, "year": meta["year"],
                          "title": meta["title"], "rows": rows})
            print(f"  + {jpg.name}: {len(rows)} lines", file=sys.stderr)
    return pages


def build_html(pages: list, dialect: str) -> str:
    payload = json.dumps({"pages": pages, "dialect": dialect, "fields": FIELDS})
    title = "City-directory gold editor"
    # NOTE: braces in the <script>/<style> are doubled for str.format.
    return _TEMPLATE.format(payload=payload, title=html.escape(title))


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>{title}</title>
<style>
  body {{ font: 13px/1.4 -apple-system, system-ui, sans-serif; margin: 0; background:#f4f4f4; color:#222; }}
  header {{ position: sticky; top:0; background:#1d2b3a; color:#fff; padding:10px 16px; z-index:10;
            display:flex; gap:16px; align-items:center; flex-wrap:wrap; }}
  header h1 {{ font-size:15px; margin:0; }}
  header .stat {{ font-size:12px; opacity:.85; }}
  button {{ font-size:13px; padding:6px 12px; border:0; border-radius:5px; cursor:pointer; }}
  .primary {{ background:#2e8b57; color:#fff; }}
  .pagehdr {{ background:#dce4ec; padding:6px 16px; font-weight:600; position:sticky; top:42px; }}
  table {{ border-collapse:collapse; width:100%; background:#fff; }}
  th, td {{ border:1px solid #e0e0e0; padding:3px 5px; vertical-align:middle; }}
  th {{ background:#f0f3f6; font-size:11px; position:sticky; top:74px; z-index:5; }}
  tr.lowconf td {{ background:#fff6e6; }}
  tr.skip td {{ opacity:.35; }}
  td img {{ display:block; max-height:64px; }}
  input[type=text] {{ width:100%; border:1px solid #ccc; border-radius:3px; padding:2px 4px; font:12px monospace; box-sizing:border-box; }}
  input.raw {{ background:#fafafa; }}
  .narrow {{ width:90px; }}
  .biz {{ text-align:center; }}
  .conf {{ font-size:10px; color:#888; text-align:center; }}
  td.cropc {{ min-width:240px; max-width:340px; }}
</style></head>
<body>
<header>
  <h1>{title}</h1>
  <span class="stat" id="stat"></span>
  <button class="primary" onclick="exportGold()">⬇ Export gold.jsonl</button>
  <button onclick="toggleAllSkip()">Toggle all skip</button>
  <span class="stat">dialect: <input type="text" id="dialect" style="width:70px" /></span>
</header>
<div id="root"></div>
<script>
const DATA = {payload};
const FIELDS = DATA.fields;
document.getElementById('dialect').value = DATA.dialect;

function el(tag, attrs, kids) {{
  const e = document.createElement(tag);
  for (const k in (attrs||{{}})) {{
    if (k === 'class') e.className = attrs[k];
    else if (k.startsWith('on')) e[k] = attrs[k];
    else e.setAttribute(k, attrs[k]);
  }}
  (kids||[]).forEach(c => e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c));
  return e;
}}

const root = document.getElementById('root');
DATA.pages.forEach((pg, pi) => {{
  root.appendChild(el('div', {{class:'pagehdr'}},
    [`${{pg.image}}  —  ${{pg.title||''}} (${{pg.year||'?'}})  ·  alpha-range: `]));
  const ar = el('input', {{type:'text', id:`ar_${{pi}}`, style:'width:90px'}});
  root.lastChild.appendChild(ar);

  const tbl = el('table');
  tbl.appendChild(el('tr', {{}}, [
    el('th', {{}}, ['skip']), el('th', {{}}, ['line image']), el('th', {{}}, ['raw_line']),
    ...FIELDS.map(f => el('th', {{}}, [f])), el('th', {{}}, ['conf'])
  ]));
  pg.rows.forEach((r, ri) => {{
    const tr = el('tr', {{class: r.conf < 0.7 ? 'lowconf' : ''}});
    tr.dataset.page = pi; tr.dataset.row = ri;
    const skip = el('input', {{type:'checkbox', onchange:(e)=>{{
      tr.classList.toggle('skip', e.target.checked); updateStat();
    }}}});
    tr.appendChild(el('td', {{class:'biz'}}, [skip]));
    tr.appendChild(el('td', {{class:'cropc'}},
      [el('img', {{src:'data:image/jpeg;base64,'+r.crop}})]));
    const raw = el('input', {{type:'text', class:'raw', value:r.raw}});
    tr.appendChild(el('td', {{}}, [raw]));
    FIELDS.forEach(f => {{
      const td = el('td', {{class: f==='is_business'?'biz':''}});
      if (f === 'is_business') td.appendChild(el('input', {{type:'checkbox'}}));
      else td.appendChild(el('input', {{type:'text', class:'narrow', 'data-f':f}}));
      tr.appendChild(td);
    }});
    tr.appendChild(el('td', {{class:'conf'}}, [String(r.conf)]));
    tbl.appendChild(tr);
  }});
  root.appendChild(tbl);
}});

function rowRecord(tr) {{
  const cells = tr.querySelectorAll('td');
  const rec = {{}};
  // cells: [skip, crop, raw, ...8 fields, conf]
  const raw = cells[2].querySelector('input').value.trim();
  FIELDS.forEach((f, i) => {{
    const inp = cells[3+i].querySelector('input');
    rec[f] = (f === 'is_business') ? inp.checked : inp.value.trim();
  }});
  return {{raw, rec}};
}}

function exportGold() {{
  const dialect = document.getElementById('dialect').value.trim();
  const lines = [];
  document.querySelectorAll('table tr[data-page]').forEach(tr => {{
    if (tr.classList.contains('skip')) return;
    const pi = +tr.dataset.page;
    const pg = DATA.pages[pi];
    const {{raw, rec}} = rowRecord(tr);
    if (!rec.name) return;   // a gold line needs at least a name
    lines.push(JSON.stringify({{
      raw_line: raw,
      context: {{
        dialect: dialect,
        alphabetical_range: document.getElementById('ar_'+pi).value.trim(),
        directory_year: String(pg.year||''),
        image: pg.image
      }},
      record: rec
    }}));
  }});
  const blob = new Blob([lines.join('\n')+'\n'], {{type:'application/jsonl'}});
  const a = el('a', {{href:URL.createObjectURL(blob), download:'gold.jsonl'}});
  document.body.appendChild(a); a.click(); a.remove();
  alert(`Exported ${{lines.length}} gold lines (rows with a name, not skipped).`);
}}

function toggleAllSkip() {{
  const boxes = document.querySelectorAll('table tr[data-page] td:first-child input');
  const target = ![...boxes].every(b => b.checked);
  boxes.forEach(b => {{ b.checked = target; b.dispatchEvent(new Event('change')); }});
}}

function updateStat() {{
  const all = document.querySelectorAll('table tr[data-page]').length;
  const skipped = document.querySelectorAll('table tr[data-page].skip').length;
  document.getElementById('stat').textContent =
    `${{DATA.pages.length}} pages · ${{all}} lines · ${{all-skipped}} active`;
}}
updateStat();
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
    args = ap.parse_args(argv)

    master = _load_master(Path(args.master))
    pages = _collect(args.dirs, args.cols, args.min_conf, master)
    if not pages:
        return "no OCR'd pages found — run run_surya_ocr.py on the dir(s) first."
    Path(args.out).write_text(build_html(pages, args.dialect), encoding="utf-8")
    total = sum(len(p["rows"]) for p in pages)
    print(f"\nwrote {args.out}  ({len(pages)} pages, {total} candidate lines)", file=sys.stderr)
    print("Open it in a browser, correct fields, click Export.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
