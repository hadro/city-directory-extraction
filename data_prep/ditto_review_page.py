#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
The ditto review queue as pictures: for each leading mark a volume's gate gave up, seeded-random
lines as the scan prints them, so a person can say whether the mark is the volume's ditto.

    python3 data_prep/ditto_review_page.py --ids trowsgeneraldire1915trow
        -> results/ditto_review_<id>.html
    python3 data_prep/ditto_review_page.py --ids a,b,c --out results/ditto_review_letters.html

WHY (2026-10-04). PIPELINE.md #1 asks a human to promote marks from `results/ditto_review_*.tsv`,
which carries one OCR'd sample line per mark. One line cannot show what was printed: Trow 1915's
`1` reads "1 Tine, Wyo." in the TSV. The verdict is about the glyph on the page, so this shows
the page.

Candidates are recomputed from the listing-scoped lines the corpus run reads
(data/survey_ocr/<id>_listing.jsonl.gz), at least MIN_LINES lines each and a name-follower ratio
of at least DITTO_MIN_FOLLOWER (a confirmation cannot override that ratio, so nothing below it is
promotable), in two kinds:
- marks ia_volume_to_jsonl.ditto_lead_candidates sent to review: punctuation and digits;
- LETTER-shaped tokens (`ii`, `n`, `it`), which the gate never considers. ABBYY-8 reads the
  1910s Trow and Brooklyn `"` that way on 1.05M run-set lines, and only a verdict can admit
  one, because `n` is also "near" in a wrapped address.
Marks already decided in data_prep/ditto_decisions.json are left out.

Each crop runs from the line above to the line itself, because a ditto repeats the line above's
surname: the reader checks both that the glyph is the volume's mark and that the entry belongs
under that surname. `given name next` is the share of a mark's lines whose second word is one
the volume prints after its admitted ditto at least GIVEN_MIN times: high for a ditto, low for
"n Fulton".
"""
from __future__ import annotations

import argparse
import collections
import gzip
import html
import json
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
OCR = REPO / "data" / "survey_ocr"
RESULTS = REPO / "results"
sys.path.insert(0, str(HERE))

from ia_volume_to_jsonl import (DITTO_MIN_FOLLOWER, NAME_FOLLOWER,  # noqa: E402
                                ditto_lead_candidates)
from iiif_frame import crop_url  # noqa: E402

IIIF = "https://iiif.archive.org/iiif"
SEED = 20261004
PER_MARK = 10
MIN_LINES = 100
GIVEN_MIN = 5
LETTERS = re.compile(r"^[a-z]{1,2}$")
DECISIONS = HERE / "ditto_decisions.json"


def crop(ident: str, row: dict) -> str:
    """The line and the one printed above it, with a margin for a mark the OCR clipped. Mapped
    through iiif_frame: Trow 1915 and 1917's images are camera frames, not the OCR'd page."""
    box = row["context"]["bbox"]
    w = (row["context"].get("page_size") or [box[2] + 100])[0]
    pad = (max(20, int(0.02 * w)), int(1.6 * (box[3] - box[1])), 20, 8)
    return crop_url(ident, row["context"]["leaf"], box, "!900,200", pad)


def decided(ident: str) -> set:
    if not DECISIONS.exists():
        return set()
    vol = json.loads(DECISIONS.read_text(encoding="utf-8"))["volumes"].get(ident) or {}
    return (set(vol.get("confirmed") or ()) | set(vol.get("rejected") or {})
            | set(vol.get("ambiguous") or {}))


def gate_ratios(ident: str) -> dict:
    """mark -> share of its lines with a capitalised word next, over every candidate line of
    the volume (data/survey_ocr/<id>_lines.jsonl.gz): what the sweep's gate measures."""
    lead, follow = collections.Counter(), collections.Counter()
    with gzip.open(OCR / f"{ident}_lines.jsonl.gz", "rt", encoding="utf-8") as fh:
        for line in fh:
            tk = json.loads(line)["raw_line"].split()
            if tk:
                lead[tk[0]] += 1
                follow[tk[0]] += len(tk) > 1 and bool(NAME_FOLLOWER.match(tk[1]))
    return {w: follow[w] / c for w, c in lead.items()}


def candidates(ident: str):
    """(rows, admitted, [(lines, mark, share, follower, given_next, kind)], scoped lines)."""
    rows = [json.loads(line) for line in
            gzip.open(OCR / f"{ident}_listing.jsonl.gz", "rt", encoding="utf-8")]
    texts = [r["raw_line"] for r in rows]
    admitted, review, _stats, n = ditto_lead_candidates(texts)
    lead, follow, second = collections.Counter(), collections.Counter(), collections.defaultdict(list)
    given = collections.Counter()
    for t in texts:
        tk = t.split()
        if not tk:
            continue
        lead[tk[0]] += 1
        if len(tk) > 1:
            second[tk[0]].append(tk[1])
            follow[tk[0]] += bool(NAME_FOLLOWER.match(tk[1]))
            if tk[0] == '"':
                given[tk[1]] += 1
    vocab = {w for w, c in given.items() if c >= GIVEN_MIN}
    gate = gate_ratios(ident)
    skip = decided(ident)
    out = []
    for w, c in lead.items():
        if c < MIN_LINES or w in skip or w in admitted:
            continue
        kind = "letters" if LETTERS.match(w) else "review" if w in review else None
        ratio = follow[w] / c
        # a verdict cannot admit a mark below the gate's own follower floor, which the sweep
        # measures over the volume's every candidate line, front matter and ads included: 1906BPL's
        # `*` and `1` read 75% and 67% on listing pages and 42% and 20% volume-wide (2026-10-05)
        if kind and ratio >= DITTO_MIN_FOLLOWER and gate.get(w, 0.0) >= DITTO_MIN_FOLLOWER:
            g = sum(s in vocab for s in second[w]) / c
            out.append((c, w, c / n, ratio, g, kind))
    out.sort(key=lambda x: (x[5] != "letters", -x[0]))
    return rows, admitted, out, n


CSS = """
body{font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0;color:#1d1d1f;
background:#fafafa} main{max-width:1100px;margin:0 auto;padding:24px 28px 60px}
h1{font-size:23px;margin:0 0 6px} h2{font-size:20px;margin:44px 0 4px;padding-top:16px;
border-top:3px solid #b8b8c4} h3{font-size:16px;margin:28px 0 4px;padding-top:10px;
border-top:1px solid #dcdce2} p{max-width:900px} .muted{color:#666}
code{font:12.5px ui-monospace,Menlo,monospace;background:#eef;padding:0 3px;border-radius:3px}
table{border-collapse:collapse;background:#fff;margin:8px 0}
th,td{border:1px solid #dcdce2;padding:4px 8px;font-size:13px;text-align:left}
td.n{text-align:right;font-variant-numeric:tabular-nums} th{background:#f0f0f4}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
figure{margin:0;background:#fff;border:1px solid #dcdce2;border-radius:6px;padding:6px}
figure img{max-width:100%;display:block;background:#f4f4f4;min-height:40px}
figcaption{font:12px ui-monospace,Menlo,monospace;color:#444;margin-top:4px;word-break:break-word}
"""


def gather(ident: str, min_lines: int) -> dict:
    rows, admitted, cands, n = candidates(ident)
    shown = [c for c in cands if c[0] >= min_lines]
    by_mark = {w: [] for _c, w, *_ in shown}
    for r in rows:
        toks = r["raw_line"].split(None, 1)
        if toks and toks[0] in by_mark and r["context"].get("bbox"):
            by_mark[toks[0]].append(r)
    return {"id": ident, "n": n, "admitted": admitted, "shown": shown, "rows": by_mark,
            "left": [c for c in cands if c[0] < min_lines]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ids", "--id", dest="ids", required=True, help="comma list of volumes")
    ap.add_argument("--min-lines", type=int, default=MIN_LINES,
                    help="show a mark in a volume only when it starts this many lines (marks "
                         f"from {MIN_LINES} up to this are counted as left out)")
    ap.add_argument("--per-mark", type=int, default=PER_MARK, help="crops per mark per volume")
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    ids = args.ids.split(",")
    rng = random.Random(SEED)
    vols = [gather(i, args.min_lines) for i in ids]
    # one section per mark, every volume it is a candidate in side by side: a mark is one OCR
    # reading, and seeing `ii` in six volumes at once is one look, not six
    marks = collections.defaultdict(list)
    for v in vols:
        for c, w, s, r, g, kind in v["shown"]:
            marks[w].append((v, c, s, r, g, kind))
    order = sorted(marks, key=lambda w: -sum(x[1] for x in marks[w]))
    title = f"Ditto review: {ids[0]}" if len(ids) == 1 else f"Ditto review: {len(ids)} volumes"
    out = [f"<!doctype html><html><head><meta charset='utf-8'><title>{title}</title>"
           f"<style>{CSS}</style></head><body><main>", f"<h1>{title}</h1>",
           f"<p class='muted'>Built by <code>data_prep/ditto_review_page.py</code> from the "
           f"listing-scoped lines the corpus run reads (seed {SEED}). Images load from "
           f"archive.org.</p>",
           "<p>Each mark below starts lines that reach the model with the mark still on them, so "
           "the model reads it as part of the name and the surname above is never carried down. "
           "Every crop shows the line and the one printed above it. <b>A mark is a ditto if, on "
           "the page, it is the volume's ditto sign and the entry belongs under the surname "
           "above.</b> Say yes or no per mark; name a volume where the answer differs. "
           "<b>Letter-shaped marks</b> are OCR readings of the printed <code>\"</code> the "
           "filter never considers. Look hardest at <code>n</code>, which is also \"near\" in a "
           "wrapped address (<code>n Fulton</code>), at <code>h</code>, the residence marker, and "
           "at single letters, which can be specks. <i>Given name next</i> is the share of a "
           "mark's lines whose next word the volume prints after its admitted ditto: high for a "
           "ditto, low for an address or a house number.</p>",
           "<table><tr><th>volume</th><th>scoped lines</th><th>already admitted</th>"
           "<th>marks here</th><th>lines</th><th>marks left out (lines)</th></tr>"]
    for v in vols:
        t = sum(c for c, *_ in v["shown"])
        lt = sum(c for c, *_ in v["left"])
        adm = " ".join(f"<code>{html.escape(m)}</code>" for m in sorted(v["admitted"])) or "none"
        out.append(f"<tr><td><code>{v['id']}</code></td><td class='n'>{v['n']:,}</td>"
                   f"<td>{adm}</td><td class='n'>{len(v['shown'])}</td>"
                   f"<td class='n'>{t:,} ({t / v['n']:.1%})</td>"
                   f"<td class='n'>{len(v['left'])} ({lt:,})</td></tr>")
    out.append("</table><table><tr><th>mark</th><th>kind</th><th>volumes</th><th>lines</th>"
               "<th>given name next</th></tr>")
    for i, w in enumerate(order):
        xs = marks[w]
        tot = sum(x[1] for x in xs)
        g = sum(x[1] * x[4] for x in xs) / tot
        out.append(f"<tr><td><a href='#m{i}'><code>{html.escape(w)}</code></a></td>"
                   f"<td>{xs[0][5]}</td><td class='n'>{len(xs)}</td><td class='n'>{tot:,}</td>"
                   f"<td class='n'>{g:.0%}</td></tr>")
    out.append("</table>")
    for i, w in enumerate(order):
        xs = marks[w]
        tot = sum(x[1] for x in xs)
        out.append(f"<h2 id='m{i}'><code>{html.escape(w)}</code> · {tot:,} lines in "
                   f"{len(xs)} volume{'s' if len(xs) > 1 else ''}</h2><table><tr><th>volume</th>"
                   f"<th>lines</th><th>capitalised word next</th><th>given name next</th></tr>")
        out += [f"<tr><td><code>{v['id']}</code></td><td class='n'>{c:,}</td>"
                f"<td class='n'>{r:.0%}</td><td class='n'>{g:.0%}</td></tr>"
                for v, c, s, r, g, kind in xs]
        out.append("</table><div class='grid'>")
        for v, *_ in xs:
            pool = v["rows"][w]
            for row in rng.sample(pool, min(args.per_mark, len(pool))):
                leaf = row["context"]["leaf"]
                page = f"{IIIF}/{v['id']}${leaf}/full/!2000,2000/0/default.jpg"
                out.append(f"<figure><a href='{page}'><img loading='lazy' "
                           f"src='{crop(v['id'], row)}'></a><figcaption>{v['id']} leaf {leaf}: "
                           f"{html.escape(row['raw_line'][:80])}</figcaption></figure>")
        out.append("</div>")
    out.append("</main></body></html>")
    path = Path(args.out).resolve() if args.out else RESULTS / f"ditto_review_{ids[0]}.html"
    path.write_text("\n".join(out), encoding="utf-8")
    for v in vols:
        t = sum(c for c, *_ in v["shown"])
        print(f"  {v['id']:30s} {len(v['shown']):3d} marks {t:9,d} lines ({t / v['n']:.1%}); "
              f"left out {len(v['left'])} ({sum(c for c, *_ in v['left']):,} lines)",
              file=sys.stderr)
    print(f"{len(order)} marks -> {path.relative_to(REPO)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
