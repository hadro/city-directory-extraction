#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
The ditto review queue as pictures: for each leading mark a volume's gate gave up, seeded-random
lines as the scan prints them, so a person can say whether the mark is the volume's ditto.

    python3 data_prep/ditto_review_page.py --id trowsgeneraldire1915trow
        -> results/ditto_review_<id>.html

WHY (2026-10-04). PIPELINE.md #1 asks a human to promote marks from `results/ditto_review_*.tsv`,
which carries one OCR'd sample line per mark. One line cannot show what was printed: Trow 1915's
`1` reads "1 Tine, Wyo." in the TSV. The verdict is about the glyph on the page, so this shows
the page.

Candidates are recomputed from the listing-scoped lines the corpus run reads
(data/survey_ocr/<id>_listing.jsonl.gz) with ia_volume_to_jsonl.ditto_lead_candidates: every
leading token the gate sent to review with a name-follower ratio of at least DITTO_MIN_FOLLOWER
(a human confirmation cannot override that ratio, so nothing below it is promotable) and at
least MIN_LINES lines. Each crop runs from the line above to the line itself, because a ditto
repeats the line above's surname: the reader checks both that the glyph is the volume's mark and
that the entry belongs under that surname.
"""
from __future__ import annotations

import argparse
import gzip
import html
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
OCR = REPO / "data" / "survey_ocr"
RESULTS = REPO / "results"
sys.path.insert(0, str(HERE))

from ia_volume_to_jsonl import DITTO_MIN_FOLLOWER, ditto_lead_candidates  # noqa: E402
from iiif_frame import crop_url  # noqa: E402

IIIF = "https://iiif.archive.org/iiif"
SEED = 20261004
PER_MARK = 10
MIN_LINES = 100


def crop(ident: str, row: dict) -> str:
    """The line and the one printed above it, with a margin for a mark the OCR clipped. Mapped
    through iiif_frame: Trow 1915 and 1917's images are camera frames, not the OCR'd page."""
    box = row["context"]["bbox"]
    w = (row["context"].get("page_size") or [box[2] + 100])[0]
    pad = (max(20, int(0.02 * w)), int(1.6 * (box[3] - box[1])), 20, 8)
    return crop_url(ident, row["context"]["leaf"], box, "!900,200", pad)


CSS = """
body{font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0;color:#1d1d1f;
background:#fafafa} main{max-width:1100px;margin:0 auto;padding:24px 28px 60px}
h1{font-size:23px;margin:0 0 6px} h2{font-size:18px;margin:34px 0 4px;padding-top:14px;
border-top:2px solid #d0d0d6} p{max-width:900px} .muted{color:#666}
code{font:12.5px ui-monospace,Menlo,monospace;background:#eef;padding:0 3px;border-radius:3px}
table{border-collapse:collapse;background:#fff;margin:8px 0}
th,td{border:1px solid #dcdce2;padding:4px 8px;font-size:13px;text-align:left}
td.n{text-align:right;font-variant-numeric:tabular-nums} th{background:#f0f0f4}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
figure{margin:0;background:#fff;border:1px solid #dcdce2;border-radius:6px;padding:6px}
figure img{max-width:100%;display:block;background:#f4f4f4;min-height:40px}
figcaption{font:12px ui-monospace,Menlo,monospace;color:#444;margin-top:4px;word-break:break-word}
"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--id", required=True)
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    ident = args.id
    rows = [json.loads(line) for line in
            gzip.open(OCR / f"{ident}_listing.jsonl.gz", "rt", encoding="utf-8")]
    texts = [r["raw_line"] for r in rows]
    admitted, review, _stats, n = ditto_lead_candidates(texts)
    cands = sorted(((c, w, s, r) for w, (c, s, r) in review.items()
                    if r >= DITTO_MIN_FOLLOWER and c >= MIN_LINES), reverse=True)
    by_mark = {w: [] for _c, w, _s, _r in cands}
    for r in rows:
        toks = r["raw_line"].split(None, 1)
        if toks and toks[0] in by_mark and r["context"].get("bbox"):
            by_mark[toks[0]].append(r)
    rng = random.Random(SEED)
    total = sum(c for c, *_ in cands)
    out = [f"<!doctype html><html><head><meta charset='utf-8'><title>Ditto review: {ident}"
           f"</title><style>{CSS}</style></head><body><main>",
           f"<h1>Ditto review: <code>{ident}</code></h1>",
           f"<p class='muted'>Built by <code>data_prep/ditto_review_page.py</code> from the "
           f"{n:,} listing-scoped lines the corpus run reads (seed {SEED}).</p>",
           "<p>Each mark below starts lines in this volume, and the gate left it out: either "
           "it is too rare, or it contains a digit, which the gate holds to a 5% floor because a "
           "leading number is usually a house number. Every crop shows the line and the one "
           "printed above it. <b>A mark is a ditto if, on the page, it is the volume's ditto "
           "sign and the entry belongs under the surname above.</b> Say yes or no per mark; "
           "a mark that is a ditto on most crops but something else on a few is still worth "
           "a yes if the something else is junk, and a no if it is a real entry.</p>",
           f"<p>Already admitted: {', '.join(f'<code>{html.escape(m)}</code>' for m in sorted(admitted)) or 'none'}"
           f" (normalized to <code>\"</code> before the model). The {len(cands)} marks here "
           f"start {total:,} lines ({total / n:.1%} of the volume).</p>",
           "<table><tr><th>mark</th><th>lines</th><th>share</th>"
           "<th>followed by a capitalised word</th></tr>"]
    out += [f"<tr><td><a href='#m{i}'><code>{html.escape(w)}</code></a></td>"
            f"<td class='n'>{c:,}</td><td class='n'>{s:.2%}</td><td class='n'>{r:.0%}</td></tr>"
            for i, (c, w, s, r) in enumerate(cands)]
    out.append("</table>")
    for i, (c, w, s, r) in enumerate(cands):
        pick = rng.sample(by_mark[w], min(PER_MARK, len(by_mark[w])))
        out.append(f"<h2 id='m{i}'><code>{html.escape(w)}</code> · {c:,} lines · "
                   f"{r:.0%} followed by a capitalised word</h2><div class='grid'>")
        for row in pick:
            leaf = row["context"]["leaf"]
            page = f"{IIIF}/{ident}${leaf}/full/!2000,2000/0/default.jpg"
            out.append(f"<figure><a href='{page}'><img loading='lazy' src='{crop(ident, row)}'>"
                       f"</a><figcaption>leaf {leaf}: {html.escape(row['raw_line'][:90])}"
                       f"</figcaption></figure>")
        out.append("</div>")
    out.append("</main></body></html>")
    path = Path(args.out or RESULTS / f"ditto_review_{ident}.html")
    path.write_text("\n".join(out), encoding="utf-8")
    print(f"{len(cands)} marks, {total:,} lines -> {path.relative_to(REPO)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
