#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Leading markers -- the Eastern District `E` and its kin -- before and after (2026-10-20).

    python3 results/lead_marks.py --out results/lead_marks.json
    python3 results/lead_marks.py --ids micro_IABROOKLYN_0040 --examples 20

Runs assemble_records.assemble twice over every volume of the run, with and without
`lead_marks`, and compares the rows. Nothing is written to the records.

The 1857-59 consolidated Brooklyn volumes print a small raised E before every Eastern District
resident ("Names marked thus (E) are persons residing in the Eastern District"). Nothing knew:
the model copied it into `name` (`E Cox L.`), so 26,356 records' name_resolved began `E `, and
where the OCR read the mark as a quote (`“Kleinschnitz George`) the line could not set the
surname carry at all. resolve_dittos.classify_lead_marks finds the marks per volume by what
follows them (a surname, inside its leaf's letters) and assemble_records strips them from
name_resolved into name_mark, and records district = Eastern.

Reported per volume: the MARKER verdicts, marked rows, rows given a district, rows whose
name_resolved changed (and how many of those are dittos, i.e. carry effects), and the leftovers
-- name_resolved still opening `E ` + capital, or a quote + capital -- before and after.

RESULT (2026-10-20, 4b-100k+guard, 44 volumes)
----------------------------------------------
  name_resolved opening `E ` + capital      26,356 -> 294   (0039 7,678 -> 65, 0040 7,642 -> 69,
                                                              0042 10,952 -> 76)
  name_resolved opening a quote + capital      613 -> 275   (the E volumes 353 -> 41; the rest
                                                              is 1906BPL's glued `“`, not a marker)
  district = Eastern                        31,530 records  (0039 7,970, 0040 8,030,
                                                              0042 11,227, 0036's section 4,303)
  name_resolved changed                     27,418, of which 132 dittos (carry); usable: 0 changed

Every mark read as the E was checked on a crop first: `E`, `Æ`, `©`, `€`, `®`, `"`, `“`. Three
drafts were measured and changed: a follower had to be lowercase after its capital (missed 431
`E ACKERMAN T. & J.` business lines in 0040), a mark could not stack (missed 359 `E *Bennett`),
and the column rule's digit reading `1` was pooled with `| I !` (in ABBYY's 1906BPL `1` is mostly
the ditto, 61 of 82, and pooling sank the class to 40% so its real `I` markers were lost).

Not done here: `*`, a MARKER in nearly every microfiche volume, is recorded in name_mark only.
The model puts it in race_designation on 0039 (as ogden1839's gold does) but DROPS it on 0035,
where 25.7% of lines carry it -- what it means there is not established.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO / "postprocess"), str(REPO / "eval"), str(REPO / "data_prep")]
from assemble_records import Incomplete, assemble, load_run  # noqa: E402

ROOTS = ("data/volumes_run1", "data/volumes_reocr")
E_LEFT = re.compile(r"^E\s+[A-Z]")
Q_LEFT = re.compile(r"^[\"“”'‘’]\s*[A-Z]")


def volume(ident, root, run, examples, n_examples):
    pairs = load_run(root / ident, run)
    before, _ = assemble(ident, pairs, lead_marks=False)
    after, summary = assemble(ident, pairs)
    changed = [(b, a) for b, a in zip(before, after) if b["name_resolved"] != a["name_resolved"]]
    for b, a in changed:
        if len(examples) < n_examples:
            examples.append({"record_id": a["record_id"], "raw_line": a["raw_line"][:70],
                             "before": b["name_resolved"], "after": a["name_resolved"],
                             "name_mark": a["name_mark"], "district": a["district"]})
    left = lambda rows, rx: sum(1 for r in rows if rx.match(r["name_resolved"] or ""))  # noqa
    return {"lines": len(after), "markers": summary["ditto"]["lead_marks"],
            "marked": summary["ditto"]["marked_lines"],
            "district_eastern": summary["ditto"]["district_eastern"],
            "name_resolved_changed": len(changed),
            "of_which_dittos": sum(1 for _b, a in changed if a["ditto_source"] or a["ditto_header"]),
            "usable_changed": sum(1 for b, a in zip(before, after) if b["usable"] != a["usable"]),
            "left_E": [left(before, E_LEFT), left(after, E_LEFT)],
            "left_quote": [left(before, Q_LEFT), left(after, Q_LEFT)]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", default="4b-100k+guard")
    ap.add_argument("--ids")
    ap.add_argument("--examples", type=int, default=40)
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    report, examples, tot = {"run": args.run, "volumes": {}}, [], collections.Counter()
    for root in (REPO / r for r in ROOTS):
        for d in sorted(p for p in root.iterdir() if p.is_dir()):
            if (args.ids and d.name not in args.ids.split(",")) or not any(
                    d.glob(f"chunk_*.preds_{args.run}.txt")):
                continue
            try:
                v = report["volumes"][d.name] = volume(d.name, root, args.run, examples,
                                                       args.examples)
            except Incomplete as e:
                print(f"{d.name}: INCOMPLETE {e}")
                continue
            for k in ("marked", "district_eastern", "name_resolved_changed", "of_which_dittos",
                      "usable_changed"):
                tot[k] += v[k]
            for k in ("left_E", "left_quote"):
                tot[k + "_before"] += v[k][0]
                tot[k + "_after"] += v[k][1]
            if v["marked"] or v["name_resolved_changed"]:
                print(f"{d.name:28s} markers {v['markers']}  marked {v['marked']:,}  eastern "
                      f"{v['district_eastern']:,}  name_resolved changed "
                      f"{v['name_resolved_changed']:,} ({v['of_which_dittos']} dittos)  "
                      f"'E ' left {v['left_E'][0]:,}->{v['left_E'][1]:,}  quote left "
                      f"{v['left_quote'][0]:,}->{v['left_quote'][1]:,}")
    report["total"], report["examples"] = dict(tot), examples
    print(json.dumps(report["total"], indent=1))
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n",
                                  encoding="utf-8")
        print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
