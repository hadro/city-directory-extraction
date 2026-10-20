#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The surname carry before and after `strict` and `heads` (resolve_dittos, 2026-10-20).

    python3 results/carry_rules.py --out results/carry_rules.json
    python3 results/carry_rules.py --ids 1906BPL --examples 40

Runs resolve_cross_line three ways over exactly the sequence assemble_records.assemble builds
for every volume of a run (both roots of 4b-100k+guard by default): the old rule, `strict` alone,
and `strict` + the dropped surname headers put back (`heads`). Nothing is written to the records.

THE CHECK THAT NEEDS NO GOLD
----------------------------
No gold records the surname a ditto line inherits in these volumes (minneapolis_eval's
context.inherited_surname is a 230-line sample of another book). But a dropped header IS that
fact, printed: `ANDERSON` over a column says the dittos below it are Andersons. So at every
header that dropped_headers places, ask what the carry would have given its follower WITHOUT the
header -- under the old rule, and under `strict` alone. Agreement with the printed header
measures the gate independently of the header fix, at thousands of points. (Disagreement is not
all error: a header that begins a NEW block is preceded by the previous block's surname, and no
carry rule can know it -- so the old-vs-strict difference is the number to read, not either
level.)

The dispute rate (rows flagged cross_leaf or letter_conflict, PIPELINE.md #6) is reported too,
but it is the carry's own flag and not ground truth -- and it falls largely BY CONSTRUCTION here,
since `strict` admits only surnames inside their leaf's letters and a header sits on the leaf.

RESULT (2026-10-20, 4b-100k+guard, 44 volumes)
----------------------------------------------
                                   1906BPL     Brooklyn 1912    all 44
  agreement with printed header    47.8 -> 84.8%  17.0 -> 60.9%   41.3 -> 79.8%  (n = 1,802)
  dispute rate (by construction)   23.2 -> 6.6%   39.0 -> 5.5%    26.3 -> 6.4%
  ditto rows whose surname moves   33,349         16,515          50,128

Of the 50,128: 36,336 now take a header, 13,791 are carried past a line `strict` refused, 1 is
newly orphaned. The microfiche volumes print few dittos and move by 0-112 rows each.

Looked at on the page, not just counted: twelve changed rows drawn at random from the two big
volumes all came FROM junk (`millions—`, `Wallabout`, `Corner`, `Street.`, `Special`,
`Cortelyou`, a given name whose mark was dropped). Of the six whose page was read, four new
surnames were confirmed right (Friedman, Winkler, the SHAPIRO and ANDERSON headers), one could not
be read off the crop, and one was wrong in a way that led to dropping the follower test (ENNIS
over the OCR'd `iimnis Adam`; now right).

KNOWN COST: a real entry whose first letter the OCR lost (`rntzen And'w` = Arntzen, `llison`,
`fit Amant` = St Amant) is now refused as lowercase, so its dittos inherit the surname before
it -- plausible and wrong, where they used to carry the damaged one. 184 rows from 34 lines in
1906BPL, about half of them continuation lines where the change is a gain. A repair (the leaf's
letter + the fragment, where the volume spells that surname elsewhere) is not attempted.

Two first drafts of the letter test were measured and replaced. The LEAF'S OWN VOTE refused
every surname on 1906BPL leaf 20, an A page that votes J (`leaf_letter_ranges` has the story);
a VOLUME-WIDE sorted run refused the second alphabet of micro_IABROOKLYN_0036 (its dispute rate
rose 21.3 -> 33.8%; with the neighbouring-leaf span it falls to 8.6%).
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO / "postprocess"), str(REPO / "eval"), str(REPO / "data_prep")]
from assemble_records import Incomplete, dropped_headers, load_run  # noqa: E402
from entry_rate import is_entry  # noqa: E402
from resolve_dittos import classify_glued_marks, leaf_letter_ranges, resolve_cross_line  # noqa: E402

ROOTS = ("data/volumes_run1", "data/volumes_reocr")


def volume(ident: str, root: Path, run: str, examples: list, n_examples: int, rng) -> dict:
    pairs = load_run(root / ident, run)
    lines = [ln for ln, _ in pairs]
    seq = [(ln["context"]["leaf"], ln.get("raw_line") or "") for ln in lines]
    glued = tuple(m for m, d in classify_glued_marks(seq).items() if d["verdict"] == "DITTO")
    heads = dropped_headers(ident, lines)
    old = list(resolve_cross_line(seq, glued))
    tight = list(resolve_cross_line(seq, glued, strict=True))
    new = list(resolve_cross_line(seq, glued, heads=heads, strict=True))

    def rate(rows):
        res = [r for r in rows if r["status"] == "resolved"]
        return {"resolved": len(res), "orphan": sum(r["status"] == "orphan" for r in rows),
                "disputed": sum(1 for r in res if r["flags"]),
                "dispute_rate": round(sum(1 for r in res if r["flags"]) / len(res), 4)
                if res else None}

    applied = sum(1 for i in heads if new[i].get("header") == heads[i])
    agree = {"old": 0, "strict": 0, "n": 0}
    for i, h in heads.items():
        if new[i].get("header") != h:
            continue                                   # the gate refused this header
        agree["n"] += 1
        agree["old"] += old[i]["resolved"].lower() == h.lower()
        agree["strict"] += tight[i]["resolved"].lower() == h.lower()
    # Only a DITTO row's record changes: a line made transparent keeps its own name (assemble
    # uses the model's `name` for every not_ditto row), it just stops passing it on.
    changed = collections.Counter()
    for i, (o, n) in enumerate(zip(old, new)):
        if o["resolved"] == n["resolved"] or "resolved" not in (o["status"], n["status"]):
            continue
        cause = ("from a header" if n.get("header") else
                 "carried past an off-letter or lowercase line" if n["status"] == "resolved"
                 else n["status"])
        changed[cause] += 1
        if len(examples) < n_examples and rng.random() < 0.05:
            examples.append({"volume": ident, "row": i, "leaf": seq[i][0],
                             "raw_line": seq[i][1][:70], "old": o["resolved"],
                             "new": n["resolved"], "cause": cause})
    # what the gate turned away, by how far its letter falls outside the leaf's span -- the +/-1
    # bucket bounds the one real risk, a block's first surname where the span is drawn too tight
    ranges = leaf_letter_ranges(seq)
    refused = collections.Counter()
    for (leaf, raw), (_ln, rec), o, t in zip(seq, pairs, old, tight):
        if not (o["status"] == "not_ditto" and o["resolved"] and not t["resolved"]):
            continue
        sur, (lo, hi) = o["resolved"], ranges.get(leaf, ("A", "Z"))
        c = sur[0].upper()
        d = (ord(lo) - ord(c) if c < lo else ord(c) - ord(hi)) if sur[0].isupper() else None
        key = ("lowercase" if d is None else "letter +/-1" if d == 1 else "letter far")
        refused[key + (" / entry-shaped" if is_entry(rec) else " / not entry-shaped")] += 1
    return {"lines": len(seq), "glued": list(glued), "old": rate(old), "new": rate(new),
            "headers_placed": len(heads), "headers_applied": applied,
            "header_agreement": {"n": agree["n"],
                                 "old": round(agree["old"] / agree["n"], 4) if agree["n"] else None,
                                 "strict": round(agree["strict"] / agree["n"], 4)
                                 if agree["n"] else None},
            "setters_made_transparent": dict(refused),
            "ditto_surname_changed": dict(changed)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", default="4b-100k+guard")
    ap.add_argument("--ids", help="comma list (default: every volume of the run in both roots)")
    ap.add_argument("--examples", type=int, default=30)
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    rng = random.Random(20261020)
    report, examples = {"run": args.run, "volumes": {}}, []
    for root in map(lambda r: REPO / r, ROOTS):
        for d in sorted(p for p in root.iterdir() if p.is_dir()):
            if args.ids and d.name not in args.ids.split(","):
                continue
            if not any(d.glob(f"chunk_*.preds_{args.run}.txt")):
                continue
            try:
                report["volumes"][d.name] = volume(d.name, root, args.run, examples,
                                                   args.examples, rng)
            except Incomplete as e:
                print(f"{d.name}: INCOMPLETE {e}")
                continue
            v = report["volumes"][d.name]
            ha = v["header_agreement"]
            print(f"{d.name:28s} dispute {v['old']['dispute_rate']} -> {v['new']['dispute_rate']}"
                  f"  orphans {v['old']['orphan']} -> {v['new']['orphan']}"
                  f"  headers {v['headers_applied']}/{v['headers_placed']}"
                  f"  agree old {ha['old']} strict {ha['strict']}"
                  f"  ditto surnames changed {sum(v['ditto_surname_changed'].values()):,}")
    tot, changed, refused = collections.Counter(), collections.Counter(), collections.Counter()
    for v in report["volumes"].values():
        changed.update(v["ditto_surname_changed"])
        refused.update(v["setters_made_transparent"])
        for k in ("old", "strict"):
            tot[f"agree_{k}"] += round((v["header_agreement"][k] or 0)
                                       * v["header_agreement"]["n"])
        tot["agree_n"] += v["header_agreement"]["n"]
        for side in ("old", "new"):
            tot[f"{side}_resolved"] += v[side]["resolved"]
            tot[f"{side}_disputed"] += v[side]["disputed"]
            tot[f"{side}_orphan"] += v[side]["orphan"]
    n = tot["agree_n"]
    report["total"] = {
        "ditto_surname_changed": dict(changed),
        "setters_made_transparent": dict(refused),
        "header_agreement": {"n": int(n), "old": round(tot["agree_old"] / n, 4) if n else None,
                             "strict": round(tot["agree_strict"] / n, 4) if n else None},
        "dispute_rate": {"old": round(tot["old_disputed"] / tot["old_resolved"], 4),
                         "new": round(tot["new_disputed"] / tot["new_resolved"], 4)},
        "orphans": {"old": tot["old_orphan"], "new": tot["new_orphan"]}}
    report["examples"] = examples
    print(json.dumps(report["total"], indent=1))
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n",
                                  encoding="utf-8")
        print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
