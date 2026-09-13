#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Do dropped surname headers explain the 23.5% cross-line dispute rate? No — 2.6% of it.

    python3 results/header_orphan_dispute_share_1906BPL.py \
        --lines data/1906BPL_lines.jsonl \
        --out   results/header_orphan_dispute_share_1906BPL.json

Run 2026-09-13. PIPELINE.md next-step #6 recorded the mechanism and said explicitly that the
magnitude was NOT measured and had to be before anyone wrote a fix. This is that measurement, and
it says do not write the fix for this reason.

THE MECHANISM IS REAL
---------------------
A dense directory prints a shared surname once as an ALL-CAPS header and dittos every entry under
it. Every such header is dropped at ingest -- `short` under 8 chars, or `allcaps`
(results/surname_headers_dropped_1906BPL.py) -- and `resolve_dittos.py` reads the kept-line JSONL,
so it never sees one. At a block boundary the nearest preceding kept line belongs to the PREVIOUS
surname, so the carry gets a confidently wrong antecedent rather than none.

Measured, on the whole volume:

    ditto rows immediately after a dropped header    1,392   58.0% disputed
    every other ditto row                          132,750   23.2% disputed

**2.5x the dispute rate.** The mechanism is not speculative.

THE MAGNITUDE IS NOT
--------------------
Those rows are 1.0% of the volume's 134,142 ditto-lead rows, so they carry **807 of 31,564
disputes = 2.6%**. Repairing every one of them moves the headline dispute rate from 23.5% to about
22.9%.

So: **surname headers are not why the cross-line carry disputes 23.5% of its rows**, and a fix
justified on that basis would be justified wrongly. PIPELINE.md #6's own prescription -- detect a
column break within a leaf from the bbox x-coordinate and reset the carry there -- remains
untouched by this result and is still where the 23.5% has to come from.

WHAT IS STILL WORTH FIXING, ON DIFFERENT GROUNDS
------------------------------------------------
1,392 rows get a wrong surname more than half the time. That is a correctness defect on those rows
and worth repairing on its own merits; it is simply not a dispute-rate story. The detection needs
no new idea -- ALL-CAPS alphabetic followed by a ditto-lead line is the follower test the
per-volume glyph gate already applies.

WHAT THIS DOES NOT SETTLE
-------------------------
- One volume. On a book whose headers are longer than 8 characters the `short` rule would not fire
  and only `allcaps` would, so the population differs.
- "Disputed" is `resolve_cross_line`'s own flag, not ground truth. It marks rows whose antecedent
  crossed a leaf or conflicts with the leaf's modal letter. A header-orphaned row can be silently
  wrong WITHOUT being flagged, so 58.0% is a floor on how badly those rows do, not an estimate.
- The reverse also holds volume-wide: the 23.5% is a review-queue rate, not an error rate.
"""

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "data_prep"))
sys.path.insert(0, str(ROOT / "postprocess"))

from ia_volume_to_jsonl import (Item, hocr_lines, join_wraps, page_geometry,   # noqa: E402
                                text_reject, geom_reject)
from resolve_dittos import resolve_cross_line                                   # noqa: E402

# A single ALL-CAPS word. Loose on length on purpose: ABBYY mangles these (APPGEGATE for
# APPLEGATE) and a header stays a header when misread.
HEADER = re.compile(r"^[A-Z][A-Z'’]{2,14}$")


def orphaned_boxes(item, n_leaves):
    """{(leaf, bbox)} for kept lines whose immediate predecessor was a dropped surname header.

    Reconstructs the ingest sequence rather than inferring it: join wrapped lines first, then run
    the same text and geometry rejects, so "immediately before" means what it means in the run
    that produced the JSONL.
    """
    out, n_headers = set(), 0
    for leaf in range(n_leaves):
        markup = item.hocr_page(leaf)
        if not markup:
            continue
        raw = hocr_lines(markup)
        if not raw:
            continue
        med_h_raw = statistics.median([b[3] - b[1] for b, _ in raw]) or 1.0
        lines, _ = join_wraps(raw, med_h_raw)
        med_h, med_w, _ = page_geometry(lines)
        pending = False
        for box, text, height in lines:
            why = text_reject(text) or geom_reject(box, height, med_h, med_w)
            if why is None:
                if pending:
                    out.add((leaf, tuple(box)))
                pending = False
            else:
                pending = bool(HEADER.match(text.strip()))
                n_headers += pending
    return out, n_headers


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lines", default="data/1906BPL_lines.jsonl")
    ap.add_argument("--ident", default="1906BPL")
    ap.add_argument("--cache", default="data/ia_cache")
    ap.add_argument("--out", default="results/header_orphan_dispute_share_1906BPL.json")
    args = ap.parse_args(argv)

    item = Item(args.ident, Path(args.cache))
    item.prefetch_hocr()
    orphaned, n_headers = orphaned_boxes(item, len(item.index))

    rows, meta = [], []
    for ln in Path(args.lines).read_text(encoding="utf-8").splitlines():
        if ln.strip():
            r = json.loads(ln)
            c = r["context"]
            rows.append((c["leaf"], r["raw_line"]))
            meta.append((c["leaf"], tuple(c["bbox"])))
    # Same stable sort resolve_dittos.cross_line_report uses: in-leaf emission order survives.
    order = sorted(range(len(rows)), key=lambda i: rows[i][0])
    rows = [rows[i] for i in order]
    meta = [meta[i] for i in order]

    pairs = [(m, x) for m, x in zip(meta, resolve_cross_line(rows))
             if x["status"] in ("resolved", "orphan")]
    disputed = [(m, x) for m, x in pairs if x["flags"]]
    orph = [1 for m, _ in pairs if m in orphaned]
    orph_disp = [1 for m, _ in disputed if m in orphaned]

    n_o, n_od = len(orph), len(orph_disp)
    n_r, n_rd = len(pairs) - n_o, len(disputed) - n_od
    res = {
        "ident": args.ident, "lines": args.lines,
        "dropped_surname_headers": n_headers,
        "kept_lines_following_one": len(orphaned),
        "ditto_rows": len(pairs), "disputed": len(disputed),
        "dispute_rate": round(len(disputed) / len(pairs), 4),
        "header_orphaned": {"n": n_o, "disputed": n_od,
                            "rate": round(n_od / n_o, 4) if n_o else None},
        "other": {"n": n_r, "disputed": n_rd,
                  "rate": round(n_rd / n_r, 4) if n_r else None},
        "share_of_all_disputes": round(n_od / len(disputed), 4) if disputed else None,
        "dispute_rate_if_all_repaired": round((len(disputed) - n_od) / len(pairs), 4),
    }
    Path(args.out).write_text(json.dumps(res, indent=2), encoding="utf-8")

    e = sys.stderr
    print(f"{res['dropped_surname_headers']:,} dropped surname headers; "
          f"{res['kept_lines_following_one']:,} kept lines follow one", file=e)
    print(f"{res['ditto_rows']:,} ditto rows, {res['disputed']:,} disputed "
          f"({res['dispute_rate']:.1%})\n", file=e)
    print(f"{'':36}{'n':>9}{'disputed':>11}{'rate':>8}", file=e)
    print(f"{'ditto after a dropped header':36}{n_o:>9,}{n_od:>11,}"
          f"{res['header_orphaned']['rate']:>8.1%}", file=e)
    print(f"{'every other ditto':36}{n_r:>9,}{n_rd:>11,}{res['other']['rate']:>8.1%}", file=e)
    print(f"\nshare of ALL disputes they account for: {res['share_of_all_disputes']:.1%}", file=e)
    print(f"repairing every one moves the rate {res['dispute_rate']:.1%} -> "
          f"{res['dispute_rate_if_all_repaired']:.1%}", file=e)
    print(f"wrote {args.out}", file=e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
