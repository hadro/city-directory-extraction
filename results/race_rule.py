#!/usr/bin/env python3
"""PIPELINE #37: race_designation_resolved against the model's race_designation, volume by volume.

    python3 -I results/race_rule.py --out results/race_rule.json      # ~10 min, all three tiers
    python3 -I results/race_rule.py --ids micro_IABROOKLYN_0025 --examples 20

Reads the round-13 records on disk (each tier's summary names its volumes; data/records also holds
five stale run-1 files, which it skips) and applies assemble_records.race_resolved with the
sidecars' race_marker / star_meaning claims (data_prep/survey_race_markers.py) -- the same function
the assembly calls, so this is the before/after without re-assembling. Run it BEFORE re-assembly:
`district_added` compares against the district the records already carry.

Per volume, over usable rows: the model's count, the resolved count, and the difference split as
`kept`, `cleared` (model set, rule empty), `added` (rule set, model empty) and `changed`; rows given
district=Eastern by the star; and two residuals, the rows a better model could still change:
  text_unmarked   a textual volume's usable line whose raw text carries a "colored" form
                  (TEXT_IN_LINE), resolved empty
  star_unmarked   a `*` volume's usable line with a star somewhere in its raw text, resolved empty
"""
from __future__ import annotations

import argparse
import collections
import gzip
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO / "postprocess"), str(REPO / "eval"), str(REPO / "data_prep")]
from assemble_records import race_resolved, starred  # noqa: E402

TIERS = [("data/records/4b-100k+guard", "results/records_4b-100k+guard.json"),
         ("data/records_books_damaged/4b-100k+guard", "results/records_books_damaged.json"),
         ("data/records_books_first_clean/4b-100k+guard", "results/records_books_first_clean.json")]
# a "colored" form inside a printed line, as race_marker_recall.py looks for it, plus Lain's bare
# `col.` before an occupation (`Anderson Betsey, col. wid. laundress`)
TEXT_IN_LINE = re.compile(r"\((?:col'?d|col\.|col|colored|coloured|co'd|col d)\.?\)|\bcolou?red\b"
                          r"|,\s*col(?:'d)?\.\s", re.I)


def volume(path: Path, book: dict, examples: dict, n_examples: int) -> dict:
    form = (book.get("race_marker") or {}).get("value")
    star_east = (book.get("star_meaning") or {}).get("value") == "eastern_district"
    c = collections.Counter()
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            model = (r.get("race_designation") or "").strip()
            raw = r.get("raw_line") or ""
            new = race_resolved(model, r.get("name_mark"), raw, form)
            east = star_east and starred(r.get("name_mark"), raw) and r.get("district") != "Eastern"
            if not r.get("usable"):
                continue
            c["model_set"] += bool(model)
            c["resolved"] += bool(new)
            kind = ("kept" if model == new else "changed") if model and new else \
                "cleared" if model else "added" if new else None
            if kind:
                c[kind] += 1
            c["district_added"] += east
            if form and form != "*" and not new and TEXT_IN_LINE.search(raw):
                kind = "text_unmarked"
                c[kind] += 1
            if form == "*" and not new and "*" in raw:
                kind = "star_unmarked"
                c[kind] += 1
            if kind and kind != "kept" and len(examples[kind]) < n_examples:
                examples[kind].append({"record_id": r["record_id"], "raw_line": raw[:80],
                                       "model": model, "resolved": new,
                                       "name_mark": r.get("name_mark")})
    return {"form": form, "star_meaning": (book.get("star_meaning") or {}).get("value"), **c}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ids")
    ap.add_argument("--examples", type=int, default=15)
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    ids = set(args.ids.split(",")) if args.ids else None
    report, examples = {"volumes": {}}, collections.defaultdict(list)
    tot = collections.Counter()
    for d, summ in TIERS:
        for v in json.load(open(REPO / summ))["volumes"]:
            if ids and v not in ids:
                continue
            side = REPO / "data_prep" / "survey" / f"ia_{v}.json"
            book = (json.loads(side.read_text(encoding="utf-8")) if side.exists() else {}
                    ).get("book_says") or {}
            x = report["volumes"][v] = volume(REPO / d / f"{v}.jsonl.gz", book, examples,
                                              args.examples)
            tot.update({k: n for k, n in x.items() if isinstance(n, int)})
            if x.get("model_set") or x.get("resolved"):
                print(f"{v:30s} {str(x['form']):10s} {str(x['star_meaning']):16s} model "
                      f"{x.get('model_set', 0):6,d} -> {x.get('resolved', 0):6,d}  cleared "
                      f"{x.get('cleared', 0):5,d} added {x.get('added', 0):5,d} district+ "
                      f"{x.get('district_added', 0):6,d} residual {x.get('text_unmarked', 0)}"
                      f"/{x.get('star_unmarked', 0)}")
    marked = [v for v, x in report["volumes"].items() if x.get("resolved", 0) >= 5]
    report["total"] = dict(tot)
    report["volumes_with_5plus_marked"] = len(marked)
    report["by_form"] = {k: sum(x.get("resolved", 0) for x in report["volumes"].values()
                                if (x["form"] == "*") == (k == "star") and x["form"])
                         for k in ("star", "textual")}
    report["examples"] = examples
    print(json.dumps({k: report[k] for k in ("total", "volumes_with_5plus_marked", "by_form")},
                     indent=1))
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n",
                                  encoding="utf-8")
        print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
