#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The survey's only writer: merge `data_prep/survey/*.json` into master_directories.csv.

See docs/SURVEY_PLAN.md, "Writeback discipline". Nothing else in the survey touches the CSV.
Scripts and agents write per-volume sidecars; this merges them in one idempotent pass with a
diff report, so the result is a reviewable git diff rather than a concurrent-write mess.

Offline. No network, no IA calls -- everything it writes is already in the committed sidecars.

    python3 data_prep/apply_survey.py                 # diff report, writes nothing
    python3 data_prep/apply_survey.py --write         # commit the fills
    python3 data_prep/apply_survey.py --conflicts     # only the cells it refused to touch
    python3 data_prep/apply_survey.py --self-test     # offline

THREE RULES, and the second is the one that matters

1. **A sidecar fills an EMPTY cell. It never overwrites a full one.** A populated cell is prior
   human or agent work; the survey's job is to disagree out loud, not to win. Every collision is
   reported (`--conflicts`) and left on disk exactly as it was. That is the plan's conflict gate:
   when the page disagrees with the catalog it is more often an ad misread as a title page than a
   genuine catalog error, so the disagreement goes to a human, not into the column.

2. **A value is only written into a column that means the same thing.** Two Phase-0 results look
   ready and are NOT, and writing them would silently corrupt columns that are currently correct:

   * `key_page` -- the CSV column is a **printed page number** ("page of the abbreviations key",
     master_directories.README.md); the sidecar's `book_says.legend` carries a **leaf index**.
     Those are different units and differ by the page_offset, which drifts within a volume. On the
     6 volumes where the CSV and a sidecar both have a legend, `key_page + page_offset` reproduces
     the sidecar leaf exactly twice (1885BPL, brooklyndirector00ogde) and is off by one on three
     more -- which is the `leafNum - 1` trap the plan documents, not a rounding wobble. So the
     leaf is written to its own new `legend_leaf` column and `key_page` is left for Phase 2 to
     fill through `_page_numbers.json`.
   * `start_page` / `end_page` / `page_offset` -- `survey_report.py --gaps` counts 86 of these as
     "free, tier A/B", and that is a count of volumes whose **route** is free, not of values in
     hand. It is computed from `page_numbers.tier` alone. Phase 0 never looked for where the
     listings start; `detect_listing_bounds --from-jsonl` does, and it needs the Phase-1 OCR
     harvest first. There is nothing to write yet.

     CONDITIONAL since 2026-09-23 (see PAGE_METHOD below): Phase 2 now produces them, and they
     are written only from a claim that is `method: hocr-geometry`, `attestation: read` and
     `confidence: high`. Stricter than key_page's high-or-medium on purpose -- a medium page
     claim is a right number on a leaf that may not be the listing's edge (flagged bounds, a
     not-residential volume) or a short, weakly corroborated sequence.

3. **Idempotent.** Re-running writes nothing new: every fill from the last run now reads as
   `agree`. The CSV round-trips byte-identically through `csv` (CRLF, QUOTE_MINIMAL), so any diff
   this produces is a real change and not a reformat.

WHAT IT WRITES (measured over the 336 committed sidecars, 2026-09-20)

    new columns          volume_number 61 · legend_leaf 60 · legend_location 60
                         year_covered 42 · year_published 21
    existing, empty only publisher 3 · year 1

`year_covered` / `year_published` exist because volumes routinely disagree with themselves --
`micro_IABROOKLYN_0022` is CSV 1845 against a title page reading "for 1845 and 1846", and Trow
volumes were published the autumn before their nominal year. The CSV's single `year` stays the
human-facing summary and is never rewritten from these.

`legend_location` exists because **twice as many legends are inline as are on a dedicated page**
(40 vs 20). `key_page` assumes a page; 40 volumes do not have one, and for those the answer is
not a missing value but a different shape.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data_prep" / "master_directories.csv"
SIDECAR = ROOT / "data_prep" / "survey"
DECISIONS = ROOT / "data_prep" / "survey_decisions.json"
# Every cell this script has written. A page-column retraction requires the cell to be listed
# here with the same value: equality with an old claim is not proof of authorship, and on
# 2026-09-23 it would have cleared four HUMAN values (micro_IABROOKLYN_0005 start_page 5, rode 25,
# doggett1845 13, hearnes1852 page_offset 10) that merely equalled what the margin fit had said.
WRITTEN = ROOT / "data_prep" / "survey_written.json"


def load_written():
    """-> (doc, {(source, id, column): value})."""
    if not WRITTEN.exists():
        return {"written": []}, {}
    doc = json.loads(WRITTEN.read_text(encoding="utf-8"))
    return doc, {(w["source"], w["id"], w["column"]): str(w["value"]) for w in doc["written"]}

# Only `book-wins` writes. The rest retire a conflict from the queue without touching the cell,
# which is the point: "reviewed, the catalog was right" must be distinguishable from "not yet
# reviewed", and a regenerated queue cannot tell you which.
VERDICTS = {"book-wins", "catalog-wins", "both-right", "needs-image", "wontfix"}


def read_csv_raw() -> str:
    """Read with newline='' so the file's CRLF survives verbatim. `Path.read_text` grew a
    `newline` argument only in 3.13; this script targets 3.9."""
    with open(CSV_PATH, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def write_csv_raw(text: str) -> None:
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from survey_report import publisher_agrees, year_agrees  # noqa: E402  (same-dir sibling)

# New columns, appended to the header in this order. Each is a unit the CSV did not previously
# carry -- none of them redefines an existing column.
NEW_COLUMNS = ["volume_number", "year_covered", "year_published", "legend_leaf", "legend_location"]

# Columns this script must never write, and why. Enforced in `propose()` rather than left to
# reviewer memory -- rule 2 above.
#
# Empty since 2026-09-23. `start_page` / `end_page` / `page_offset` sat here from 2026-09-20
# ("needs phase 2") until Phase 2 produced them; they are now conditional on PAGE_METHOD. The
# mechanism stays -- the next column that must not be written from what the sidecars hold goes
# here, with its reason.
FORBIDDEN: dict = {}

# The conditional page columns. Only `survey_derive.py pages` writes these claims, and every one
# carries `method: hocr-geometry`. Three guards, all required:
#
#   method       a page claim from anywhere else is not this measurement
#   attestation  `read`: the cited leaf's own margin prints the number. `inferred` is the
#                sequence's guess for a leaf that prints none -- the same thing as IA's
#                interpolated folios, which were retracted from key_page on 2026-09-21.
#   confidence   `high` only. See the rule 2 note above for what `medium` means here.
#
# Before this was lifted, 10 randomly sampled high claims (seed 20260923) were opened at their
# IIIF images: 10/10 print the cited folio, and 10/10 cited leaves are the listing's true first
# or last page, the neighbouring leaf being a title page, a street directory, NAMES TOO LATE, or
# an ADDITIONAL NAMES supplement.
#
# `page_offset` is offered only alongside a qualifying start_page and from the SAME claim
# (start leaf - start page), so a row the survey fills always satisfies
# start_page + page_offset == the cited leaf. The 29 existing values are left alone by rule 1;
# where comparable they mostly differ (merceinscitydire00merc -5 vs -2), consistent with an anchor
# taken elsewhere in a volume whose offset drifts.
PAGE_METHOD = "hocr-geometry"
# ...and since 2026-09-23 also a page read by eye off the IIIF image (survey_readpackets.py
# --record-pages), under the same `read` + `high` guards. A read that found NO folio is recorded
# as `attestation: unprinted` with a null value, and so can never be written.
PAGE_METHODS = {PAGE_METHOD, "agent-read"}
PAGE_GRADE = {"high"}
PAGE_COLUMNS = ("start_page", "end_page")

# `key_page` was forbidden until 2026-09-21 and is now conditional, which is the honest form of
# the rule: the column was never the problem, the UNIT was. A leaf may not be written there; a
# printed page converted from one by `survey_pagenumbers.py` may. That converter is the only
# producer of `book_says.key_page`, and every claim it makes carries `method: ia-page-numbers`,
# so the two units cannot meet again by accident.
KEY_PAGE_METHOD = "ia-page-numbers"

# ... and a weak conversion is not CSV-grade. Two ways to be weak, and the second is the one that
# actually bit: a real but poor score (1869BPL scores the leaf 0 across 147 backward steps in 924
# leaves), or a number IA never read at all. `attestation: interpolated` marks the latter -- a
# folio IA filled in arithmetically between confident anchors, which on
# hearnesbrooklync1852unse asserts page 17 for a page that prints no folio whatsoever. Both stay
# in the sidecar with their grade and surface for review instead of landing in a column that
# reads as settled.
CSV_GRADE = {"high", "medium"}
INTERPOLATED = "interpolated"


def load_decisions():
    """-> {(source, id, column): decision}. Absent file is fine -- nothing has been decided yet."""
    if not DECISIONS.exists():
        return {}
    try:
        doc = json.loads(DECISIONS.read_text(encoding="utf-8"))
    except Exception as e:                               # noqa: BLE001 - loud, not silent
        print(f"unreadable {DECISIONS.name}: {e}", file=sys.stderr)
        return {}
    out = {}
    for d in doc.get("decisions") or []:
        verdict = d.get("verdict")
        if verdict not in VERDICTS:
            print(f"unknown verdict {verdict!r} on {d.get('id')}/{d.get('column')} -- ignored",
                  file=sys.stderr)
            continue
        if verdict == "book-wins" and not (d.get("reason") or "").strip():
            print(f"book-wins with no reason on {d.get('id')}/{d.get('column')} -- ignored",
                  file=sys.stderr)
            continue
        out[(d.get("source"), d.get("id"), d.get("column"))] = d
    return out


def page_claim_ok(claim) -> bool:
    return bool(claim and claim.get("value") is not None
                and claim.get("method") in PAGE_METHODS
                and claim.get("attestation") == "read"
                and claim.get("confidence") in PAGE_GRADE)


def propose(row: dict, doc: dict):
    """-> list of (column, new_value, citation_dict). What this sidecar offers for this row.

    Offers only. `classify()` decides what survives contact with the cell already there.
    """
    book = doc.get("book_says") or {}
    out = []

    for col in ("volume_number", "year_covered", "year_published"):
        claim = book.get(col)
        if claim and claim.get("value") is not None:
            out.append((col, str(claim["value"]), claim))

    legend = book.get("legend")
    if legend and legend.get("leaf") is not None:
        out.append(("legend_leaf", str(legend["leaf"]), legend))
        if legend.get("legend_location"):
            out.append(("legend_location", legend["legend_location"], legend))

    # The conditional `key_page`. Both guards are required: a claim that did not come from the
    # converter is a leaf wearing the wrong name, and a low-confidence conversion is not
    # CSV-grade. `legend.leaf` above can never route here -- it is a different claim.
    kp = book.get("key_page")
    if (kp and kp.get("value") is not None
            and kp.get("method") == KEY_PAGE_METHOD
            and kp.get("confidence") in CSV_GRADE
            and kp.get("attestation") != INTERPOLATED):
        out.append(("key_page", str(kp["value"]), kp))

    for col in PAGE_COLUMNS:
        pc = book.get(col)
        if page_claim_ok(pc):
            out.append((col, str(pc["value"]), pc))
            if col == "start_page" and pc.get("page_offset") is not None:
                out.append(("page_offset", str(pc["page_offset"]), pc))

    # `column_count` joined this list on 2026-09-22, when reading the listings turned up three
    # Trow volumes whose recorded value was wrong. It is only ever offered from an `agent-read`
    # claim -- a column count is a fact about the page's layout, and nothing in the hOCR text
    # channel can see it.
    cc = book.get("column_count")
    if cc and cc.get("value") is not None and cc.get("method") == "agent-read":
        out.append(("column_count", str(cc["value"]), cc))

    # Existing columns. Same offer; the empty-cell rule is what keeps them safe.
    #
    # `csv_label` exists because the two sides want different strings. A claim's `value` is what
    # the page actually says -- "Thomas Leslie, Henry R., & William J. Hearne" -- and truncating
    # that is the exact failure this queue was built to catch. But the CSV column is what groups
    # volumes into the ~20-30 publisher x era families the style profiles key on, and a unique
    # 43-character string groups with nothing. The column's own convention is already short and
    # already handles partnerships: `Trow/Wilson` on 27 rows, `Low/Buell/Bull`, `Hearnes` on 7.
    # So the page keeps its words and the column keeps its labels.
    for col in ("publisher", "year"):
        claim = book.get(col)
        if claim and claim.get("value") is not None:
            cell = claim.get("csv_label") if col == "publisher" else None
            out.append((col, str(cell if cell else claim["value"]), claim))

    assert not any(c in FORBIDDEN for c, _v, _cl in out), "rule 2 violated"
    return out


def retractable(row: dict, doc: dict, written=None):
    """-> [(column, value_to_clear, claim)]. Cells this tool wrote that it would no longer write.

    A survey claim can be DOWNGRADED after the fact -- `survey_pagenumbers.py` reclassified every
    `confidence: null` page number as interpolated rather than merely unscored, which moved 8
    cells below CSV grade after they had already landed. Rule 1 stops `propose()` from correcting
    them: it only fills empty cells, so a wrong value it wrote itself would sit there forever.

    The safety property is that this can only clear a cell it can PROVE it wrote: the sidecar must
    still hold a claim for that column, and the cell must match that claim's value exactly. A
    human-entered value cannot collide, because if it agreed with the claim there would be nothing
    to retract, and if it disagrees it is a conflict and is left alone. hearnesbrooklync1852unse
    is the worked example -- its `key_page=27` is a LEAF someone entered by hand, the claim says
    17, they differ, and retraction does not touch it.
    """
    book = doc.get("book_says") or {}
    out = []
    kp = book.get("key_page")
    if kp and kp.get("value") is not None:
        below_grade = (kp.get("confidence") not in CSV_GRADE
                       or kp.get("attestation") == INTERPOLATED)
        if below_grade and (row.get("key_page") or "").strip() == str(kp["value"]):
            out.append(("key_page", str(kp["value"]), kp))
    # The page columns, on a STRONGER proof than key_page's: besides matching a claim, the cell
    # must be in the written ledger with the same value (`written`, from survey_written.json).
    # `written=None` means "no ledger given" and retracts nothing from these columns.
    src, ident = doc.get("source"), doc.get("id")

    def ours(col, value):
        return written is not None and written.get((src, ident, col)) == str(value)

    for col in PAGE_COLUMNS:
        pc = book.get(col)
        if not pc or pc.get("method") not in PAGE_METHODS:
            continue
        if not page_claim_ok(pc):
            if (row.get(col) or "").strip() == str(pc.get("value")) and ours(col, pc["value"]):
                out.append((col, str(pc["value"]), pc))
            if (col == "start_page" and pc.get("page_offset") is not None
                    and (row.get("page_offset") or "").strip() == str(pc["page_offset"])
                    and ours("page_offset", pc["page_offset"])):
                out.append(("page_offset", str(pc["page_offset"]), pc))
        # ...and a cell written from the MARGIN FIT that an image read has since overruled
        # (2026-09-23: 8 of the 80 written edges were one page off -- a caption page the bounds
        # missed, or a listing that ran one page past the fit's last read). The read records
        # what the fit said in `margin_fit_said`; the cell is cleared only if it still holds
        # exactly that, so a human's value is never touched. If the read is itself CSV-grade,
        # propose() then fills the cleared cell with it on the same run.
        fit = pc.get("margin_fit_said") or {}
        if pc.get("method") == "agent-read" and fit.get("method") == PAGE_METHOD:
            if (str(fit.get("value")) != str(pc.get("value")) or not page_claim_ok(pc)) \
                    and (row.get(col) or "").strip() == str(fit.get("value")) \
                    and ours(col, fit.get("value")):
                out.append((col, str(fit["value"]), pc))
            if (col == "start_page" and fit.get("page_offset") is not None
                    and str(fit.get("page_offset")) != str(pc.get("page_offset"))
                    and (row.get("page_offset") or "").strip() == str(fit["page_offset"])
                    and ours("page_offset", fit["page_offset"])):
                out.append(("page_offset", str(fit["page_offset"]), pc))
    # the not-CSV-grade and overruled paths can name the same cell; clear it once
    seen, uniq = set(), []
    for c, v, cl in out:
        if (c, v) not in seen:
            seen.add((c, v))
            uniq.append((c, v, cl))
    return uniq


def unit_suspects(row: dict, doc: dict):
    """-> [(column, value, legend_leaf)] where a printed-page column appears to hold a LEAF.

    The generalisable form of the hearnesbrooklync1852unse finding. `key_page` holds a printed
    page; commit 94fe7fe put a leaf in it, and the row still reads as settled. Nothing else
    catches this: once the volume's own claim is below CSV grade it stops being proposed, so the
    bad cell stops appearing as a conflict too and would silently drop out of view.

    The test is simply whether the cell equals the legend LEAF, which is a printed page only by
    coincidence -- and a coincidence worth a second look anyway.
    """
    book = doc.get("book_says") or {}
    legend = book.get("legend") or {}
    leaf = legend.get("leaf")
    if leaf is None:
        return []
    cur = (row.get("key_page") or "").strip()
    if cur and cur == str(leaf):
        claim = book.get("key_page") or {}
        if str(claim.get("value") or "") != cur:
            return [("key_page", cur, leaf)]
    return []


def classify(col: str, current: str, proposed: str):
    """-> 'fill' | 'agree' | 'conflict'.

    `agree` is what makes the script idempotent AND what keeps the report honest: a cell the
    survey would have written anyway is not a silent no-op, it is a confirmation.
    """
    if not (current or "").strip():
        return "fill"
    if current.strip() == proposed.strip():
        return "agree"
    if col == "publisher":
        return "agree" if publisher_agrees(current, proposed) else "conflict"
    if col in ("year", "year_covered", "year_published"):
        try:
            return "agree" if year_agrees(current, int(proposed)) else "conflict"
        except (TypeError, ValueError):
            return "conflict"
    return "conflict"


def load_sidecars():
    docs = {}
    for p in sorted(SIDECAR.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:                                # noqa: BLE001 - report, don't die
            print(f"unreadable sidecar: {p}", file=sys.stderr)
            continue
        docs[(d.get("source"), d.get("id"))] = d
    return docs


def run(write: bool, show_conflicts: bool, retract: bool = False):
    raw = read_csv_raw()
    reader = csv.reader(io.StringIO(raw))
    header = next(reader)
    body = [r for r in reader]

    docs = load_sidecars()
    decisions = load_decisions()
    written_doc, written = load_written()
    newly_written, unwritten = [], set()
    out_header = header + [c for c in NEW_COLUMNS if c not in header]
    idx = {c: i for i, c in enumerate(out_header)}

    counts = Counter()
    conflicts = []
    decided = []
    retracted = []
    suspects = []
    rows_out = []
    matched = 0

    for r in body:
        row = r + [""] * (len(out_header) - len(r))
        rec = dict(zip(out_header, row))
        doc = docs.get((rec["source"], rec["id"]))
        if doc is None:
            counts["row without sidecar"] += 1
            rows_out.append(row)
            continue
        matched += 1
        for col, cur, leaf in unit_suspects(rec, doc):
            suspects.append((rec["source"], rec["id"], col, cur, leaf,
                             (doc.get("book_says") or {}).get("key_page") or {}))
        if retract:
            for col, value, claim in retractable(rec, doc, written):
                row[idx[col]] = ""
                counts[f"retracted: {col}"] += 1
                retracted.append((rec["source"], rec["id"], col, value, claim))
                unwritten.add((rec["source"], rec["id"], col))
            rec = dict(zip(out_header, row))
        for col, value, claim in propose(rec, doc):
            verdict = classify(col, row[idx[col]], value)
            if verdict == "conflict":
                d = decisions.get((rec["source"], rec["id"], col))
                if d is not None:
                    counts[f"decided ({d['verdict']}): {col}"] += 1
                    decided.append((rec["source"], rec["id"], col, row[idx[col]], value, d))
                    # The one path that overwrites a non-empty cell, and only ever by an
                    # explicit human verdict carrying a reason.
                    if d["verdict"] == "book-wins":
                        if row[idx[col]] != value:
                            newly_written.append((rec["source"], rec["id"], col, value,
                                                  row[idx[col]] or None))
                        row[idx[col]] = value
                    continue
                conflicts.append((rec["source"], rec["id"], col, row[idx[col]], value, claim))
            counts[f"{verdict}: {col}"] += 1
            if verdict == "fill":
                row[idx[col]] = value
                newly_written.append((rec["source"], rec["id"], col, value, None))
        rows_out.append(row)

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(out_header)
    w.writerows(rows_out)
    new_raw = buf.getvalue()

    print(f"csv rows {len(body)}  |  sidecars {len(docs)}  |  joined {matched}")
    print(f"new columns: {', '.join(c for c in NEW_COLUMNS if c not in header) or '(none)'}\n")

    fills = {k: n for k, n in counts.items() if k.startswith("fill")}
    print(f"fills ({sum(fills.values())}):")
    for k, n in sorted(fills.items(), key=lambda kv: -kv[1]):
        print(f"  {n:4d}  {k.split(': ', 1)[1]}")
    if retracted:
        print(f"\nretracted ({len(retracted)}) -- written by this tool, now below CSV grade:")
        for src, ident, col, value, claim in retracted:
            if claim.get("attestation") == INTERPOLATED:
                why = "IA interpolated it; the page prints no such folio"
            elif claim.get("method") == "agent-read" and claim.get("margin_fit_said"):
                why = (f"overruled by an image read: leaf {claim.get('leaf')} "
                       + (f"prints {claim['value']}" if claim.get("value") is not None
                          else f"prints no folio ({claim.get('attestation')})"))
            else:
                why = f"confidence {claim.get('confidence')}"
            print(f"  {src}/{ident[:34]:34} {col:10} cleared {value:>5}   ({why})")
            print(f"      still cited by leaf {claim.get('leaf')} in the sidecar")

    if suspects:
        print(f"\n⚠️  unit suspects ({len(suspects)}) -- a printed-page column holding a LEAF:")
        for src, ident, col, cur, leaf, claim in suspects:
            says = f"; this volume's own claim is {claim['value']}" if claim.get("value") else ""
            print(f"  {src}/{ident[:34]:34} {col}={cur} == legend_leaf {leaf}{says}")
            print(f"      not auto-corrected -- a human entered it; decide in "
                  f"{DECISIONS.name}")

    agrees = sum(n for k, n in counts.items() if k.startswith("agree"))
    print(f"\nconfirmations (cell already correct): {agrees}")
    print(f"conflicts UNDECIDED (left untouched): {len(conflicts)}")
    if decided:
        vd = Counter(d["verdict"] for *_x, d in decided)
        print(f"conflicts decided ({len(decided)}): "
              + ", ".join(f"{v} {n}" for v, n in vd.most_common()))

    if show_conflicts and decided:
        print("\ndecided, per survey_decisions.json:")
        for src, ident, col, cur, prop, d in decided:
            arrow = "-> WROTE book value" if d["verdict"] == "book-wins" else "-> kept csv"
            print(f"  {src}/{ident[:32]:32} {col:11} {d['verdict']:13} {arrow}")
            print(f"      {d.get('reason', '')[:100]}")

    if show_conflicts and conflicts:
        print("\ncells the survey refused to overwrite (UNDECIDED -- add to survey_decisions.json):")
        for src, ident, col, cur, prop, claim in conflicts:
            print(f"  {src}/{ident[:34]:34} {col:14} csv={cur[:28]!r:30} book={prop[:28]!r}")
            print(f"      leaf {claim.get('leaf')}  {claim.get('evidence_type')}  "
                  f"{(claim.get('quote') or '')[:70]!r}")
            if claim.get("image"):
                print(f"      {claim['image']}")

    changed = new_raw != raw
    if not write:
        print("\n(dry run -- nothing written; pass --write)" if changed
              else "\nno changes: the CSV already matches the sidecars")
        return 0
    if not changed:
        print("\nno changes: the CSV already matches the sidecars")
        return 0
    write_csv_raw(new_raw)
    print(f"\nwrote {CSV_PATH.relative_to(ROOT)}")
    keep = [w for w in written_doc["written"]
            if (w["source"], w["id"], w["column"]) not in unwritten]
    today = __import__("datetime").date.today().isoformat()
    for src, ident, col, value, replaced in newly_written:
        keep = [w for w in keep if (w["source"], w["id"], w["column"]) != (src, ident, col)]
        keep.append({"source": src, "id": ident, "column": col, "value": value,
                     "replaced": replaced, "date": today})
    written_doc["written"] = keep
    WRITTEN.write_text(json.dumps(written_doc, indent=1), encoding="utf-8")
    print(f"ledger {WRITTEN.relative_to(ROOT)}: +{len(newly_written)} written, "
          f"-{len(unwritten)} retracted, {len(keep)} cells on record")
    return 0


def self_test():
    # Rule 1: an empty cell fills, a full cell never gets overwritten by a different value.
    assert classify("volume_number", "", "83") == "fill"
    assert classify("volume_number", "83", "83") == "agree"
    assert classify("volume_number", "82", "83") == "conflict"
    assert classify("legend_location", "  ", "dedicated-page") == "fill"

    # Idempotency is exactly "a second run reads as agree", so it is worth asserting directly.
    assert classify("legend_leaf", "9", "9") == "agree"

    # The fuzzy comparators are shared with survey_report so a cell cannot be "agree" in one
    # tool and "conflict" in the other.
    assert classify("publisher", "Trow", "THE TROW CITY DIRECTORY COMPANY") == "agree"
    assert classify("publisher", "Smith", "CHARLES JENKINS") == "conflict", \
        "the 1857BPL finding must survive the merge"
    assert classify("year", "1845", "1846") == "agree", "one year of slack"
    assert classify("year", "1845", "1899") == "conflict"
    assert classify("year_covered", "1852/53", "1853") == "agree"
    assert classify("year", "1845", "not-a-year") == "conflict"

    # Rule 2, enforced rather than remembered: propose() must never offer a forbidden column.
    doc = {"book_says": {
        "volume_number": {"value": 83, "leaf": 1},
        "legend": {"leaf": 9, "legend_location": "dedicated-page"},
        "year_covered": {"value": 1906, "leaf": 1},
    }}
    offered = {c for c, _v, _cl in propose({}, doc)}
    assert offered == {"volume_number", "legend_leaf", "legend_location", "year_covered"}, offered
    assert not (offered & set(FORBIDDEN)), "start_page/end_page/page_offset must never be offered"
    assert "key_page" not in offered, "a legend LEAF must never route to key_page"

    # key_page is conditional, not forbidden. Both guards must hold.
    def kp(method, conf):
        return propose({}, {"book_says": {"key_page": {"value": 21, "leaf": 9,
                                                       "method": method, "confidence": conf}}})
    assert [c for c, _v, _cl in kp("ia-page-numbers", "high")] == ["key_page"]
    assert [c for c, _v, _cl in kp("ia-page-numbers", "medium")] == ["key_page"]
    assert kp("ia-page-numbers", "low") == [], "a low-confidence conversion is not CSV-grade"
    assert kp("hocr-text", "high") == [], "only the converter may produce a key_page"
    assert kp("agent-read", "high") == [], "an agent leaf-read is still not a printed page"

    # The page columns: conditional on method, attestation AND high confidence.
    def pg(method="hocr-geometry", att="read", conf="high", col="start_page"):
        claim = {"value": 561, "leaf": 9, "method": method, "attestation": att,
                 "confidence": conf, "page_offset": -552}
        return [(c, v) for c, v, _cl in propose({}, {"book_says": {col: claim}})]
    assert pg() == [("start_page", "561"), ("page_offset", "-552")], pg()
    assert pg(col="end_page") == [("end_page", "561")], "page_offset rides only on start_page"
    assert pg(conf="medium") == [], "medium is not CSV-grade for a page column"
    assert pg(att="inferred") == [], "a folio the leaf does not print is never written"
    assert pg(method="ia-page-numbers") == [], "only survey_derive.py pages produces these"
    assert pg(method="agent-read") == [("start_page", "561"), ("page_offset", "-552")], \
        "...or a read by eye, under the same guards"
    assert pg(method="agent-read", att="unprinted") == [], "a leaf that prints no folio"
    # ...and a downgraded page claim retracts exactly the cells it wrote, never a human's
    low = {"book_says": {"start_page": {"value": 561, "leaf": 9, "method": "hocr-geometry",
                                        "attestation": "read", "confidence": "low",
                                        "page_offset": -552}}}
    low["source"], low["id"] = "ia", "x"
    led = {("ia", "x", "start_page"): "561", ("ia", "x", "page_offset"): "-552"}
    got = [(c, v) for c, v, _cl in retractable({"start_page": "561", "page_offset": "-552"},
                                                low, led)]
    assert got == [("start_page", "561"), ("page_offset", "-552")], got
    assert retractable({"start_page": "561", "page_offset": "-552"}, low, {}) == [], \
        "equal to the claim but NOT in the ledger: a human's value, never cleared"
    assert retractable({"start_page": "561"}, low) == [], "no ledger, no page retraction"
    # a read that overrules the fit: 1908BPL, fit said 22 at leaf 10, the caption leaf 9 prints 21
    fixed = {"book_says": {"start_page": {
        "value": 21, "leaf": 9, "method": "agent-read", "attestation": "read",
        "confidence": "high", "page_offset": -12,
        "margin_fit_said": {"value": 22, "leaf": 10, "page_offset": -12,
                            "method": "hocr-geometry", "confidence": "high"}}}}
    fixed["source"], fixed["id"] = "ia", "1908BPL"
    led = {("ia", "1908BPL", "start_page"): "22", ("ia", "1908BPL", "page_offset"): "-12"}
    assert [(c, v) for c, v, _cl in retractable({"start_page": "22", "page_offset": "-12"},
                                                 fixed, led)] == [("start_page", "22")], \
        "the superseded page is cleared; an unchanged offset is not"
    assert [(c, v) for c, v, _cl in propose({}, fixed)] == [("start_page", "21"),
                                                             ("page_offset", "-12")]
    assert retractable({"start_page": "20"}, fixed, led) == [], "a different value is untouched"
    # ...and a read that finds NO folio clears the fit's value without replacing it
    gone = {"book_says": {"start_page": {
        "value": None, "leaf": 21, "method": "agent-read", "attestation": "unprinted",
        "confidence": "low",
        "margin_fit_said": {"value": 14, "leaf": 22, "page_offset": 8,
                            "method": "hocr-geometry", "confidence": "high"}}}}
    gone["source"], gone["id"] = "ia", "m25"
    led = {("ia", "m25", "start_page"): "14", ("ia", "m25", "page_offset"): "8"}
    got = [(c, v) for c, v, _cl in retractable({"start_page": "14", "page_offset": "8"}, gone, led)]
    assert got == [("start_page", "14"), ("page_offset", "8")], got
    # micro_IABROOKLYN_0005: a human's start_page 5 equals what the fit said, and is not ours
    assert retractable({"start_page": "14"}, gone, {}) == []
    assert propose({}, gone) == []

    # An interpolated folio is refused even at high confidence: IA never read it off the page.
    interp = {"book_says": {"key_page": {"value": 17, "leaf": 27, "method": "ia-page-numbers",
                                         "confidence": "high", "attestation": "interpolated"}}}
    assert propose({}, interp) == [], "an interpolated folio is never CSV-grade"

    # Retraction can only clear a cell it can PROVE it wrote -- the claim value must match.
    weak = {"book_says": {"key_page": {"value": 17, "leaf": 27, "method": "ia-page-numbers",
                                       "confidence": "low", "attestation": "interpolated"}}}
    assert [c for c, _v, _cl in retractable({"key_page": "17"}, weak)] == ["key_page"]
    # hearnesbrooklync1852unse: 27 is a LEAF a human entered; the claim says 17. Never touched.
    assert retractable({"key_page": "27"}, weak) == [], "a human-entered value must survive"
    assert retractable({"key_page": ""}, weak) == [], "nothing to retract from an empty cell"
    # A claim still at CSV grade is not retractable -- that would undo the good ones.
    good = {"book_says": {"key_page": {"value": 21, "leaf": 9, "method": "ia-page-numbers",
                                       "confidence": "high", "attestation": "read"}}}
    assert retractable({"key_page": "21"}, good) == [], "a CSV-grade claim stays"

    # The unit check keeps a known-bad cell visible after its claim drops below grade, which is
    # exactly when it would otherwise stop being reported as a conflict.
    hearne = {"book_says": {"legend": {"leaf": 27},
                            "key_page": {"value": 17, "leaf": 27, "method": "ia-page-numbers",
                                         "confidence": "low", "attestation": "interpolated"}}}
    assert [c for c, _v, _l in unit_suspects({"key_page": "27"}, hearne)] == ["key_page"]
    assert unit_suspects({"key_page": "17"}, hearne) == [], "the converted value is not a suspect"
    assert unit_suspects({"key_page": ""}, hearne) == []
    assert unit_suspects({"key_page": "27"}, {"book_says": {}}) == [], "no legend, no opinion"

    # A legend with no leaf is not a claim (the plan's citation rule) and yields no legend_leaf.
    assert not propose({}, {"book_says": {"legend": {"legend_location": "inline-at-listing-head"}}})

    # The decisions file must parse, and every verdict in it must be one this tool honours --
    # a typo'd verdict silently retiring a conflict is exactly the failure this guards.
    decs = load_decisions()
    assert all(d["verdict"] in VERDICTS for d in decs.values())
    assert all(d.get("reason") for d in decs.values() if d["verdict"] == "book-wins"), \
        "book-wins overwrites a human-entered cell; it must say why"
    if DECISIONS.exists():
        doc = json.loads(DECISIONS.read_text(encoding="utf-8"))
        for d in doc.get("decisions") or []:
            assert (d.get("source"), d.get("id"), d.get("column")) in decs, \
                f"decision dropped on load: {d.get('id')}/{d.get('column')}"

    # The CSV must round-trip byte-identically, or every run would produce a reformat diff that
    # buries the real change.
    raw = read_csv_raw()
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\r\n").writerows(csv.reader(io.StringIO(raw)))
    assert buf.getvalue() == raw, "csv dialect drift -- a merge would reformat the whole file"

    print("self-test OK", file=sys.stderr)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help="commit the fills (default: dry run)")
    ap.add_argument("--conflicts", action="store_true", help="show every refused cell with its citation")
    ap.add_argument("--retract", action="store_true",
                    help="also clear cells this tool wrote whose claim has since been downgraded")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    return run(args.write, args.conflicts, args.retract)


if __name__ == "__main__":
    raise SystemExit(main())
