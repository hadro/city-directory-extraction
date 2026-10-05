#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Assemble a whole-volume run into records someone outside this repo can use (PIPELINE.md #13).

    python3 postprocess/assemble_records.py --root data/volumes_run1 --run 4b-100k+guard
    python3 postprocess/assemble_records.py --root data/volumes_run1 --run 4b-100k --ids 1906BPL
    python3 postprocess/assemble_records.py --self-test

Predictions used to land in a `.txt` and stop. This joins each one to everything the repo knows
about the line it came from, and writes one row per line to
data/records/<run>/<volume>.jsonl.gz and .csv.gz (gitignored), plus a summary to
results/records_<run>.json.

EVERY ROW CARRIES
    record_id           <volume>:<leaf>:<n>, n the line's order on its leaf. Stable across
                        re-runs of the same lines
    canvas, xywh        the IIIF canvas and the line's box on it (`#xywh=`); `crop` is the IIIF
                        image of just that line, upright. The hOCR's pixel space is the scan's on
                        182 of 184 volumes; Trow 1915 and 1917 OCR'd a cropped, turned page, and
                        data_prep/iiif_frame.py maps their boxes onto the camera image
    printed_page        the folio the survey's margin fit gives the leaf, and printed_page_how:
                        `read` off its margin, or `inferred` from the sequence around it
    section             the residential run the line came from (`listing`, `late_names`, ...)
    raw_line            what the model read, verbatim
    the 8 fields        what the model wrote, verbatim: the panel measures exactly this, so it
                        is never overwritten (the rule resolve_dittos.py and copy_guard.py keep)
    name_resolved       for a ditto-led line, the carried surname + the given names; else `name`
    home_address_resolved   resolve_dittos.annotate's within-line expansion (`h do`)
    address_resolved    the early volumes' slot grammar (`27 Ann do.` -> `27 Ann-street`,
                        resolve_dittos.resolve_address_run), with its status in address_ditto
    ditto_source        the record_id of the line the surname was carried from
    ditto_flags         resolve_dittos.resolve_cross_line's review flags: cross_leaf,
                        letter_conflict, orphan. Kept, never acted on: ~23% of 1906BPL's dittos
                        are disputed and the two checks overlap only 28%

AND WHAT IT KNOWS ABOUT THE LINE, AS FLAGS, NOT FILTERS
    role                start | runover | other | thin, from the box alone
                        (volume_run_report.layout_roles). A runover is the tail of the entry
                        above; the model makes a person of it anyway
    entry_shaped        entry_rate.is_entry on the record: a name and an address-like field
    non_entry_page      the leaf is in the survey's `non_entry_pages` (survey_adleaves.py): a
                        full-page ad, or a page whose OCR failed
    eval_holdout        gold / adjacent / volume: measurement lines, never to be published as
                        records or trained on

`usable` is the conservative export: entry-shaped, a start (or thin) line, on a listing page, not
held out. Nothing is dropped; a consumer filters on the flags.

The summary sets usable records against the volume's printed name count
(book_says.stated_name_count, survey_counts.py): on Doggett 1845 run 1's named start lines came
to 1.002 per printed name.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as _dt
import gzip
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO / "postprocess"), str(REPO / "eval"), str(REPO / "data_prep")]
from entry_rate import is_entry  # noqa: E402
from iiif_frame import crop_url, xywh as canvas_xywh  # noqa: E402
from evaluate import FIELDS, load_pred  # noqa: E402
from resolve_dittos import (annotate, classify_glued_marks, resolve_address_run,  # noqa: E402
                           resolve_cross_line)
from survey_folios import fit as fit_folios, load as load_folios  # noqa: E402
from volume_run_report import layout_roles  # noqa: E402

SIDECARS = REPO / "data_prep" / "survey"
OCR = REPO / "data" / "survey_ocr"
IIIF = "https://iiif.archive.org/iiif"
CSV_COLUMNS = (["record_id", "volume", "leaf", "printed_page", "printed_page_how", "section",
                "canvas", "xywh", "raw_line"] + FIELDS +
               ["name_resolved", "address_resolved", "address_ditto", "home_address_resolved",
                "ditto_source", "ditto_flags", "role", "entry_shaped", "non_entry_page",
                "eval_holdout", "usable"])


def load_run(vdir: Path, run: str) -> list:
    """[(line, record)] in volume order; a count mismatch is fatal, never truncated."""
    out = []
    for c in sorted(vdir.glob("chunk_*.jsonl")):
        lines = [json.loads(x) for x in c.read_text(encoding="utf-8").splitlines() if x.strip()]
        p = c.with_name(f"{c.stem}.preds_{run}.txt")
        if not p.exists():
            raise SystemExit(f"missing predictions {p}")
        preds = load_pred(str(p), "yaml")
        if len(preds) != len(lines):
            raise SystemExit(f"{p}: {len(preds)} records for {len(lines)} lines -- they must "
                             f"align 1:1")
        out += list(zip(lines, preds))
    return out


def printed_pages(ident: str) -> dict:
    """{leaf: (page, "read"|"inferred")} from the survey's margin fit (survey_folios.fit) over the
    volume's word dump: the same fit whose segments the sidecar stores, per leaf. The sidecar's
    segments cannot be unrolled, because they skip the unnumbered leaves inside them and do not
    say which. Calibrated at 99.5% (read) and 98.0% (inferred) against IA's read numbers."""
    try:
        leaves, cands = load_folios(ident)
    except FileNotFoundError:
        return {}
    return fit_folios(leaves, cands)


def strip_lead(name: str, lead: str) -> str:
    """The given names of a ditto-led name: the model's `name` less the mark it copied."""
    name = (name or "").strip()
    if lead and name.startswith(lead):
        return name[len(lead):].strip()
    return re.sub(r"^\W+", "", name).strip()


def assemble(ident: str, pairs: list) -> tuple:
    """-> (rows, summary) for one volume."""
    side = SIDECARS / f"ia_{ident}.json"
    doc = json.loads(side.read_text(encoding="utf-8")) if side.exists() else {}
    folios = printed_pages(ident)
    non_entry = set((doc.get("non_entry_pages") or {}).get("leaves") or [])
    lines = [ln for ln, _ in pairs]
    roles = layout_roles(lines) if all((ln.get("context") or {}).get("page_size")
                                       for ln in lines) else ["thin"] * len(lines)

    # record ids: order of the line on its leaf, in emission (reading) order
    per_leaf = collections.Counter()
    rids = []
    for ln in lines:
        leaf = ln["context"]["leaf"]
        rids.append(f"{ident}:{leaf}:{per_leaf[leaf]}")
        per_leaf[leaf] += 1

    # the surname carry over the whole volume, in reading order
    seq = [(ln["context"]["leaf"], ln.get("raw_line") or "") for ln in lines]
    glued = tuple(m for m, d in classify_glued_marks(seq).items() if d["verdict"] == "DITTO")
    carry = list(resolve_cross_line(seq, glued))
    addresses = list(resolve_address_run(rec.get("address") for _ln, rec in pairs))

    rows, last_surname = [], None
    for i, ((ln, rec), cr, role, (addr, addr_status)) in enumerate(
            zip(pairs, carry, roles, addresses)):
        ctx = ln.get("context") or {}
        leaf = ctx.get("leaf")
        if cr["status"] == "not_ditto" and cr["resolved"]:
            last_surname = rids[i]
        if cr["status"] == "resolved":
            given = strip_lead(rec.get("name"), cr["lead"])
            name_resolved = f"{cr['resolved']} {given}".strip()
            source = last_surname
        else:
            name_resolved = "" if cr["status"] == "orphan" else (rec.get("name") or "")
            source = None
        ann = annotate(rec)
        bbox = ctx.get("bbox")
        xywh = canvas_xywh(ident, leaf, bbox) if bbox and len(bbox) == 4 else None
        entry = is_entry(rec)
        held = ctx.get("eval_holdout")
        usable = bool(entry and role in ("start", "thin") and leaf not in non_entry and not held)
        rows.append({
            "record_id": rids[i], "volume": ident, "leaf": leaf,
            "printed_page": (folios.get(leaf) or (None, None))[0],
            "printed_page_how": (folios.get(leaf) or (None, None))[1],
            "section": ctx.get("section"),
            "canvas": f"{IIIF}/{ident}${leaf}/canvas", "xywh": xywh,
            "crop": crop_url(ident, leaf, bbox) if xywh else None,
            "raw_line": ln.get("raw_line"),
            **{f: rec.get(f, "") for f in FIELDS},
            "name_resolved": name_resolved,
            "address_resolved": addr, "address_ditto": addr_status,
            "home_address_resolved": ann["home_address_resolved"],
            "ditto_source": source, "ditto_flags": cr["flags"],
            "role": role, "entry_shaped": entry, "non_entry_page": leaf in non_entry,
            "eval_holdout": held, "usable": usable})

    stated = (doc.get("book_says") or {}).get("stated_name_count") or {}
    usable_n = sum(r["usable"] for r in rows)
    summary = {
        "rows": len(rows), "usable": usable_n,
        "named": sum(1 for r in rows if (r["name"] or "").strip()),
        "entry_shaped": sum(r["entry_shaped"] for r in rows),
        "roles": dict(collections.Counter(r["role"] for r in rows)),
        "non_entry_page_rows": sum(r["non_entry_page"] for r in rows),
        "eval_holdout_rows": sum(1 for r in rows if r["eval_holdout"]),
        "printed_page_known": sum(1 for r in rows if r["printed_page"] is not None),
        "ditto": {"carried": sum(1 for c in carry if c["status"] == "resolved"),
                  "orphan": sum(1 for c in carry if c["status"] == "orphan"),
                  "disputed": sum(1 for c in carry if c["status"] == "resolved" and c["flags"]),
                  "glued_marks": list(glued),
                  "address_slots": sum(1 for _a, st in addresses if st.startswith("resolved")),
                  "address_no_antecedent": sum(1 for _a, st in addresses
                                               if st == "no_antecedent")},
        "stated_name_count": stated.get("value"),
        "stated_approximate": bool(stated.get("approximate")),
        "usable_per_stated_name": round(usable_n / stated["value"], 3)
        if stated.get("value") else None}
    return rows, summary


def write(rows: list, out_dir: Path, ident: str):
    out_dir.mkdir(parents=True, exist_ok=True)
    with gzip.open(out_dir / f"{ident}.jsonl.gz", "wt", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    with gzip.open(out_dir / f"{ident}.csv.gz", "wt", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({**r, "ditto_flags": ",".join(r["ditto_flags"])})


def _self_test() -> int:
    assert strip_lead('" Wm H', '"') == "Wm H"
    assert strip_lead("44 John C", "44") == "John C"
    assert strip_lead("-Adolph", "-") == "Adolph"
    ctx = {"page_size": [1000, 1000]}
    pairs = [({"raw_line": "Smith John, grocer, 12 Pine",
               "context": {**ctx, "leaf": 5, "bbox": [100, 100, 600, 120]}},
              {"name": "Smith John", "occupation_role": "grocer", "address": "12 Pine"}),
             ({"raw_line": '" Wm, carman, 3 Oak, h do',
               "context": {**ctx, "leaf": 5, "bbox": [100, 130, 600, 150]}},
              {"name": '" Wm', "occupation_role": "carman", "address": "3 Oak",
               "home_address": "do"})]
    rows, s = assemble("no_such_volume", pairs)
    assert rows[0]["record_id"] == "no_such_volume:5:0" and rows[1]["record_id"].endswith(":5:1")
    assert rows[1]["name_resolved"] == "Smith Wm", rows[1]["name_resolved"]
    assert rows[1]["ditto_source"] == "no_such_volume:5:0"
    assert rows[1]["home_address_resolved"] == "3 Oak"
    assert rows[1]["address_resolved"] == "3 Oak" and rows[1]["address_ditto"] == "not_ditto"
    assert rows[0]["xywh"] == "100,100,500,20"
    assert rows[1]["name"] == '" Wm', "the model's field stays verbatim"
    assert s["ditto"]["carried"] == 1 and s["rows"] == 2
    print("self-test ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", help="chunk directories: <root>/<volume>/chunk_NNN.jsonl")
    ap.add_argument("--run", help="prediction run: chunk_NNN.preds_<run>.txt")
    ap.add_argument("--ids", help="comma list of volumes (default: every one with the run)")
    ap.add_argument("--out", default=str(REPO / "data" / "records"))
    ap.add_argument("--summary", help="default results/records_<run>.json")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()
    if not (args.root and args.run):
        ap.error("--root and --run are required")
    root = Path(args.root)
    vols = sorted(d.name for d in root.iterdir()
                  if d.is_dir() and any(d.glob(f"chunk_*.preds_{args.run}.txt")))
    if args.ids:
        vols = [v for v in vols if v in set(args.ids.split(","))]
    out_dir = Path(args.out) / args.run
    report = {"derived": _dt.date.today().isoformat(), "run": args.run, "root": args.root,
              "volumes": {}}
    for ident in vols:
        rows, summary = assemble(ident, load_run(root / ident, args.run))
        write(rows, out_dir, ident)
        report["volumes"][ident] = summary
        per = summary["usable_per_stated_name"]
        print(f"{ident:30s} {summary['rows']:8,d} rows  {summary['usable']:8,d} usable"
              f"{'' if per is None else f'  {per:.3f} per printed name'}")
    path = Path(args.summary or REPO / "results" / f"records_{args.run}.json")
    path.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(f"-> {out_dir}/<volume>.jsonl.gz, .csv.gz; summary {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
