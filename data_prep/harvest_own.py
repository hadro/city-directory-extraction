# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Build an IN-DOMAIN eval set from our own pipeline output for the Tulsa city directory:
pair each extracted entry's structured fields with the REAL OCR text of its source
line(s), recovered from the aligned JSON.

This is the realest test we have — actual historical OCR (with its real errors) of the
exact collection the model targets. Labels come from the pipeline's Gemini extraction, so
treat this as a strong **in-domain reference / silver** set (and a Gemini-agreement
baseline) until the rows are hand-reviewed; then it's gold.

How the join works (verified): `extract_entries` stamped each entry with the
`canvas_fragment` of its source aligned line, so an entry's `#xywh=...` matches an aligned
line's `#xywh=...` exactly. Multi-line entries are rebuilt by taking every aligned line from
an entry's headline down to the next entry's headline (reading order within a single
left/right column image).

Usage
-----
    python3 harvest_own.py --dir ../directory-pipeline/output/tulsa_1921 --out data/tulsa_eval.jsonl
    python3 harvest_own.py --dir ../directory-pipeline/output/tulsa_1922 --out data/tulsa22_eval.jsonl --limit 1000
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re
import sys
from typing import Optional

# Must match data_prep/synth_persons.py FIELDS
FIELDS = ["name", "is_business", "spouse_name", "race_designation",
          "occupation_role", "employer", "address", "home_address"]
# Two source schemas are supported: Tulsa (name, spouse_name, race_designation,
# occupation_role, employer, address) and Lain-1897 (surname, given_name, occupation, address).


def _xywh(cf: str) -> Optional[str]:
    m = re.search(r"#xywh=([\d.,]+)", cf or "")
    return m.group(1) if m else None


def _truthy(s) -> bool:
    return str(s).strip().lower() in ("true", "1", "yes")


def _despace(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _recoverable(raw: str, rec: dict) -> bool:
    """Is the gold answer actually present in the recovered OCR line? Gemini was multimodal
    and sometimes completed truncated/hyphen-split text the OCR line lacks ('Jack-' ->
    'Jackson av'); scoring a text-only model on those is unfair. Tolerant of spacing/hyphens."""
    r = _despace(raw)
    return all(_despace(rec[f]) in r for f in ("name", "address") if rec[f])


def _entry_name(r: dict) -> str:
    n = (r.get("name") or "").strip()                      # Tulsa schema
    return n or f"{(r.get('surname') or '').strip()} {(r.get('given_name') or '').strip()}".strip()  # Lain schema


def _entry_record(r: dict) -> dict:
    return {
        "name": _entry_name(r),
        "is_business": _truthy(r.get("is_business")),
        "spouse_name": (r.get("spouse_name") or "").strip(),
        "race_designation": (r.get("race_designation") or "").strip(),
        "occupation_role": (r.get("occupation_role") or r.get("occupation") or "").strip(),
        "employer": (r.get("employer") or "").strip(),
        "address": (r.get("address") or "").strip(),
        "home_address": "",
    }


def _is_person_row(r: dict) -> bool:
    # alphabetical name/business listings only — skip street-directory and empty rows
    return bool(_entry_name(r)
                and (r.get("address") or "").strip()
                and not (r.get("occupant_name") or "").strip()
                and not (r.get("street_name") or "").strip()
                and not _truthy(r.get("is_advertisement")))


def _pick_entries_csv(d: str, explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    cands = sorted(glob.glob(os.path.join(d, "entries_*.csv")))
    # prefer a plain entries_<model>.csv over _v1/_fixed/_bak/_geocoded variants
    plain = [c for c in cands if re.search(r"entries_[^/]*\.csv$", os.path.basename(c))
             and not re.search(r"_(v\d+|fixed|bak|geocoded|cleaned)", os.path.basename(c))]
    chosen = (plain or cands)
    if not chosen:
        sys.exit(f"no entries_*.csv found in {d}")
    return chosen[0]


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", required=True, help="pipeline output dir, e.g. ../directory-pipeline/output/tulsa_1921")
    ap.add_argument("--entries", default=None, help="explicit entries CSV (else auto-detect)")
    ap.add_argument("--out", default=None, help="output .jsonl (default: stdout)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--year", default=None, help="directory_year (else inferred from --dir)")
    ap.add_argument("--keep-unrecoverable", action="store_true",
                    help="keep rows whose gold name/address isn't present in the recovered OCR "
                         "line (default: drop them so the eval is fair to a text-only model)")
    args = ap.parse_args(argv)

    year = args.year or (re.search(r"(\d{4})", os.path.basename(args.dir.rstrip("/"))) or [None, ""])[1]
    csv_path = _pick_entries_csv(args.dir, args.entries)

    # group qualifying entries by source image
    by_img: dict = {}
    with open(csv_path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if _is_person_row(r) and _xywh(r.get("canvas_fragment", "")):
                by_img.setdefault(r["image"], []).append(r)

    out = open(args.out, "w", encoding="utf-8") if args.out else sys.stdout
    kept = no_aligned = no_match = unrecoverable = 0
    samples = []
    try:
        for img, ers in by_img.items():
            stem = img.rsplit(".", 1)[0]
            cand = glob.glob(os.path.join(args.dir, f"{glob.escape(stem)}_*_aligned.json"))
            if not cand:
                no_aligned += len(ers)
                continue
            lines = (json.load(open(cand[0], encoding="utf-8")).get("lines")) or []
            texts = [(ln.get("gemini_text") or "") for ln in lines]
            key2idx = {_xywh(ln.get("canvas_fragment", "")): i for i, ln in enumerate(lines)}

            ents = []
            for r in ers:
                idx = key2idx.get(_xywh(r["canvas_fragment"]))
                if idx is None:
                    no_match += 1
                else:
                    ents.append((idx, r))
            ents.sort(key=lambda t: t[0])
            starts = [i for i, _ in ents]

            for j, (idx, r) in enumerate(ents):
                end = starts[j + 1] if j + 1 < len(starts) else len(lines)
                raw = " ".join(t for t in texts[idx:end] if t).strip()
                if not raw:
                    continue
                record = _entry_record(r)
                if not args.keep_unrecoverable and not _recoverable(raw, record):
                    unrecoverable += 1
                    continue
                ex = {
                    "raw_line": raw,
                    "context": {"dialect": "tulsa",
                                "alphabetical_range": (r.get("alphabetical_range") or "").strip(),
                                "directory_year": year, "image": img},
                    "record": record,
                }
                out.write(json.dumps(ex, ensure_ascii=False) + "\n")
                kept += 1
                if len(samples) < 4:
                    samples.append(ex)
                if args.limit and kept >= args.limit:
                    raise StopIteration
    except StopIteration:
        pass
    finally:
        if args.out:
            out.close()

    print(f"kept={kept}  (dropped: unrecoverable={unrecoverable}, no_aligned_file={no_aligned}, "
          f"xywh_unmatched={no_match})  from {os.path.basename(csv_path)} -> {args.out or 'stdout'}",
          file=sys.stderr)
    for s in samples:
        print(f"  IN : {s['raw_line']!r}", file=sys.stderr)
        print(f"  OUT: {'|'.join(str(s['record'][f]) for f in FIELDS)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
