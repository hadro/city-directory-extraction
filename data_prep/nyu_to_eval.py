# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Build a real-gold NYC evaluation set from the NYU "NYC Directories Extracted Persons
Entries, 1850-1890" NDJSON, mapped into this project's union schema so it can be scored
against a model with eval/evaluate.py exactly like the synthetic data.

Each NYU record pairs `complete_entry` (the raw OCR line) with `labeled_entry` (CRF parse,
AS PRINTED) and `corrected_entry` (cleaned + per-token confidence scores 1-15). We take the
**labeled** (verbatim) values as the target — matching a verbatim extractor and the synthetic
targets — and use the **corrected** scores only as a quality gate. Output rows look like
synth_persons.py: {raw_line, context, record}.

Field mapping (NYU -> union schema):
  name            <- labeled_entry.subjects (joined)
  occupation_role <- labeled_entry.occupations (joined with ", ")
  address         <- first labeled location WITHOUT an "h" label (primary/work/combined)
  home_address    <- labeled location WITH an "h" label (the separate home, if any)
  spouse_name     <- "wid <Name>" parsed from complete_entry when labeled_widow == 1
  race_designation<- the col'd/colored/col token from complete_entry when labeled_black == 1
  employer        <- "" (NYC directories fold employer into the occupation list)
  is_business     <- False (NYU is a persons dataset; no business flag)

Get the data (CC-BY-SA-NC 4.0 — EVAL ONLY, do not train on it):
  smallest year (1850, ~70 MB):
  https://archive.nyu.edu/bitstream/2451/61521/43/1850.4adf9ec0-317a-0134-03ad-00505686a51c.ndjson

Usage
-----
    python3 nyu_to_eval.py --in data/1850.ndjson --out data/nyu_eval.jsonl --limit 2000
    python3 nyu_to_eval.py --in data/1850.ndjson --out data/nyu_eval.jsonl --min-score 8
    python3 nyu_to_eval.py --in data/1850.ndjson --use-corrected   # cleaned targets instead
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Optional

# Must match data_prep/synth_persons.py FIELDS
FIELDS = ["name", "is_business", "spouse_name", "race_designation",
          "occupation_role", "employer", "address", "home_address"]

_WID_RE = re.compile(r"\bwid(?:ow)?\b\.?\s+(?:of\s+)?([A-Z][A-Za-z'.\- ]*?)(?=[,.]|\s+(?:h\.|r\.|\d)|$)")
_COL_RE = re.compile(r"\b(col'd|colored|col)\b", re.IGNORECASE)
# NYU is a persons dataset with no business flag; infer obvious firms so they don't
# penalize the (Tulsa-trained) is_business field at eval time.
_BIZ_RE = re.compile(r"\s&\s|\b(?:Co|Bros|Sons)\.?$")


def _looks_business(name: str) -> bool:
    if not name:
        return False
    if _BIZ_RE.search(name):
        return True
    return name.isupper() and " " in name


def _alpha_range(name: str) -> str:
    m = re.search(r"[A-Za-z]{3}", name)
    return m.group(0).upper() if m else name[:3].upper()


def _locations(block: dict):
    """Return (primary_address, home_address) from a labeled/corrected entry block."""
    home, primary = "", ""
    for loc in (block.get("locations") or []):
        val = (loc.get("value") or "").strip()
        if not val:
            continue
        labels = loc.get("labels") or ([loc["label"]] if loc.get("label") else [])
        if "h" in labels and not home:
            home = val
        elif not primary:
            primary = val
    if not primary and home:          # only a home address present -> treat as primary
        primary, home = home, ""
    return primary, home


def _scores_ok(corrected: dict, min_score: int) -> bool:
    if min_score <= 0:
        return True
    if not corrected:
        return False
    for key in ("occupations", "locations"):
        for item in (corrected.get(key) or []):
            try:
                if int(item.get("score", 0)) < min_score:
                    return False
            except (TypeError, ValueError):
                return False
    return True


def to_record(rec: dict, use_corrected: bool) -> Optional[dict]:
    labeled = rec.get("labeled_entry") or {}
    corrected = rec.get("corrected_entry") or {}
    src = corrected if use_corrected else labeled

    subjects = labeled.get("subjects") or corrected.get("subjects") or []
    name = " ".join(s.strip() for s in subjects if s).strip()
    if not name:
        return None

    if use_corrected:
        occs = [o.get("value", "") for o in (corrected.get("occupations") or [])]
    else:
        occs = labeled.get("occupations") or []
    occupation_role = ", ".join(o.strip() for o in occs if o).strip()

    address, home_address = _locations(src)

    complete = rec.get("complete_entry") or ""
    spouse = ""
    if str(rec.get("labeled_widow", "0")) == "1":
        m = _WID_RE.search(complete)
        spouse = ("wid " + m.group(1).strip()) if m else "wid"
    race = ""
    if str(rec.get("labeled_black", "0")) == "1":
        m = _COL_RE.search(complete)
        race = m.group(1) if m else "col"

    record = {
        "name": name, "is_business": _looks_business(name), "spouse_name": spouse,
        "race_designation": race, "occupation_role": occupation_role,
        "employer": "", "address": address, "home_address": home_address,
    }
    return {
        "raw_line": complete,
        # publisher: the eval slice is the 1850 file, NYPL uuid 4adf9ec0-317a-0134-03ad-… =
        # "Doggett's, Manhattan, 1850/51" in master_directories.csv (not Trow — Trow starts 1852/53)
        "context": {"publisher": "doggett", "alphabetical_range": _alpha_range(name),
                    "directory_year": rec.get("directory_year", "")},
        "record": record,
    }


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="inp", required=True, help="NYU NDJSON file")
    ap.add_argument("--out", default=None, help="output .jsonl (default: stdout)")
    ap.add_argument("--limit", type=int, default=0, help="max qualifying rows (0 = all)")
    ap.add_argument("--min-score", type=int, default=15,
                    help="require all corrected occ/loc scores >= this (15 = hand-confirmed; 0 = no gate)")
    ap.add_argument("--use-corrected", action="store_true",
                    help="emit cleaned/corrected values instead of verbatim labeled values")
    args = ap.parse_args(argv)

    out = open(args.out, "w", encoding="utf-8") if args.out else sys.stdout
    seen = kept = bad = 0
    samples = []
    try:
        with open(args.inp, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                seen += 1
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    bad += 1            # tolerate a truncated final line (ranged download)
                    continue
                if str(rec.get("low_entry_caution", "0")) == "1":
                    continue
                if not _scores_ok(rec.get("corrected_entry") or {}, args.min_score):
                    continue
                ex = to_record(rec, args.use_corrected)
                if ex is None or not ex["record"]["address"]:
                    continue
                out.write(json.dumps(ex, ensure_ascii=False) + "\n")
                kept += 1
                if len(samples) < 3:
                    samples.append(ex)
                if args.limit and kept >= args.limit:
                    break
    finally:
        if args.out:
            out.close()
    print(f"read={seen} kept={kept} json_errors={bad} -> {args.out or 'stdout'}", file=sys.stderr)
    for s in samples:
        print(f"  e.g. IN: {s['raw_line']!r}", file=sys.stderr)
        print(f"       OUT: {'|'.join(str(s['record'][f]) for f in FIELDS)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
