#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Can the band rule run on the thin tier now that it has been re-OCR'd? (PAGE_TYPE_CLASSIFIER)

    python3 results/band_structure_after_reocr.py --out results/band_structure_after_reocr.json
    python3 results/band_structure_after_reocr.py --ids micro_IABROOKLYN_0013

WHY. Phase 1 of docs/PAGE_TYPE_CLASSIFIER.md shipped a rule instead of a model: take the extent
of the ditto-lead lines that survive `text_reject`, expand by 0.015 of page height at each end,
and the band between is the listing body. On 1906BPL it admitted zero advertising lines across
239 labelled leaves.

Phase 2 then found the rule could not run on the thin tier AT ALL -- 0 of 108
`micro_IABROOKLYN_0013` leaves carried the 20 filter-surviving ditto lines it needs, because an
1836 directory is thin enough to print every surname in full. That mattered because fabrication
runs 30.1% on the thin tier against 5.6% on the dense one: the cheap rule fixed the tier that
was already fine and could not touch the one that needed it. Phase 2's conclusion was that a
learned classifier is the right instrument there.

**That measurement was taken on tesseract-on-microfilm, and those 39 volumes have since been
re-OCR'd by LightOnOCR (PIPELINE #27).** 0013 is one of them. So the premise of the "learned
model" conclusion has to be re-measured before anything is built on it -- which is cheap,
because BOTH dumps are still on disk: IA's as `<id>_words.ia.jsonl.gz` and the re-OCR as
`<id>_words.jsonl.gz`. This runs the same measurement over each and reports the pair.

WHAT IT MEASURES, per volume and per dump, over the volume's listing leaves:
  * `gate_leaves` -- leaves with >= 20 ditto-lead lines that survive `text_reject`. This is the
    rule's precondition; phase 2's finding was that it is 0 on the thin tier.
  * the ditto-lead share by decile of page height -- whether there is a band at all, or the
    flat 0.2% phase 2 found.
  * `lead_tokens` -- the commonest leading tokens, which is how phase 2 saw that the volume
    simply has no ditto convention (`Smith` 37, `Van` 29, not a mark).

A ditto mark is the volume's own, as the survey's per-volume gate admitted it (the sidecar's
`ditto_marks`), plus the shapes that gate looks at. A volume whose gate admits nothing has no
mark by construction, and that is a finding, not a gap.

This measures WHERE THE BODY IS, not what the strips contain -- the same limit phase 0 recorded.
"""
from __future__ import annotations

import argparse
import collections
import gzip
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "data_prep"))
from ia_volume_to_jsonl import DITTO_SHAPE, text_reject, words_to_lines  # noqa: E402

SIDECARS = REPO / "data_prep" / "survey"
OCR = REPO / "data" / "survey_ocr"
GATE_MIN = 20            # ditto lines a leaf needs before the band rule will read it (phase 1)
DECILES = 10


def ditto_marks(ident: str) -> set:
    doc = json.loads((SIDECARS / f"ia_{ident}.json").read_text(encoding="utf-8"))
    return set(((doc.get("harvest") or {}).get("filtered") or {}).get("ditto_marks") or [])


def listing_span(ident: str):
    doc = json.loads((SIDECARS / f"ia_{ident}.json").read_text(encoding="utf-8"))
    lst = doc.get("listing") or {}
    return lst.get("start_leaf"), lst.get("end_leaf")


def is_ditto(tok: str, marks: set) -> bool:
    """The volume's own admitted mark, or a mark-shaped token that is not a number."""
    return tok in marks or (bool(DITTO_SHAPE.match(tok)) and not any(c.isdigit() for c in tok))


def measure(path: Path, marks: set, span) -> dict:
    lo, hi = span
    bands = [{"lo": i / DECILES, "hi": (i + 1) / DECILES, "ditto": 0, "all": 0}
             for i in range(DECILES)]
    leads = collections.Counter()
    gate_leaves = n_leaves = n_lines = n_ditto = 0
    if not path.exists():
        return {"present": False}
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for raw in fh:
            rec = json.loads(raw)
            leaf, size = rec["leaf"], rec.get("page_size")
            if lo is not None and not (lo <= leaf <= hi):
                continue
            if not rec.get("lines") or not size or not size[1]:
                continue
            n_leaves += 1
            per_leaf = 0
            for box, text in words_to_lines(rec["lines"]):
                if text_reject(text) is not None:       # the rule reads the SURVIVING lines
                    continue
                tok = text.split()[0] if text.split() else ""
                d = is_ditto(tok, marks)
                k = min(DECILES - 1, max(0, int(DECILES * ((box[1] + box[3]) / 2) / size[1])))
                bands[k]["all"] += 1
                bands[k]["ditto"] += d
                n_lines += 1
                n_ditto += d
                per_leaf += d
                if not d:
                    leads[tok] += 1
            gate_leaves += per_leaf >= GATE_MIN
    for b in bands:
        b["share"] = round(b["ditto"] / b["all"], 4) if b["all"] else None
    return {"present": True, "leaves": n_leaves, "gate_leaves": gate_leaves,
            "gate_share": round(gate_leaves / n_leaves, 3) if n_leaves else None,
            "lines": n_lines, "ditto_lines": n_ditto,
            "ditto_share": round(n_ditto / n_lines, 4) if n_lines else None,
            "bands": bands, "lead_tokens": leads.most_common(6)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ids", default=None, help="comma list (default: every re-OCR'd volume)")
    ap.add_argument("--out", default="results/band_structure_after_reocr.json")
    args = ap.parse_args(argv)

    if args.ids:
        ids = args.ids.split(",")
    else:
        boxes = json.loads((REPO / "data/reocr_halves/boxes.json").read_text(encoding="utf-8"))
        ids = sorted({k.split("/")[0] for k in boxes})

    out = {}
    print(f"{'volume':30s} {'marks':8s} | {'IA: gate leaves':>15s} {'ditto%':>7s} | "
          f"{'reocr: gate':>11s} {'ditto%':>7s}")
    for ident in ids:
        marks, span = ditto_marks(ident), listing_span(ident)
        before = measure(OCR / f"{ident}_words.ia.jsonl.gz", marks, span)
        after = measure(OCR / f"{ident}_words.jsonl.gz", marks, span)
        out[ident] = {"ditto_marks": sorted(marks), "listing": span,
                      "ia": before, "reocr": after}
        f = lambda r, k: (r.get(k) if r.get("present") else None)
        print(f"{ident:30s} {','.join(marks) or '-':8s} | "
              f"{str(f(before,'gate_leaves')):>7s}/{str(f(before,'leaves')):<7s} "
              f"{(f(before,'ditto_share') or 0):>6.1%} | "
              f"{str(f(after,'gate_leaves')):>4s}/{str(f(after,'leaves')):<6s} "
              f"{(f(after,'ditto_share') or 0):>6.1%}", flush=True)
    Path(args.out).write_text(json.dumps(out, indent=1), encoding="utf-8")
    tot = lambda k, d: sum((v[d].get(k) or 0) for v in out.values() if v[d].get("present"))
    print(f"\nleaves clearing the {GATE_MIN}-ditto gate: IA {tot('gate_leaves','ia'):,} of "
          f"{tot('leaves','ia'):,}  ->  re-OCR {tot('gate_leaves','reocr'):,} of "
          f"{tot('leaves','reocr'):,}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
