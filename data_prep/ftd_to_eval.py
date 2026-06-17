# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Build a CROSS-LINGUAL TRANSFER eval set from the SODUCO "French Trade Directories
(19th c.) for Nested NER" dataset, mapped into this project's union schema.

The model is trained on English (Tulsa/NYC) directories; scoring it on French Paris
directories of the *same shape* (person/firm → activity → street + number) measures how
much of the structure-extraction skill transfers across language. Expect lower numbers
than English gold — that's the signal.

Source (open, CC): https://zenodo.org/records/8167628  ->  dataset_SODUCO_nested_ner.json
  curl -sL "https://zenodo.org/records/8167628/files/dataset_SODUCO_nested_ner.json?download=1" -o data/ftd.json

Each record has `text_ocr_{ref,pero,tess}` (clean ref vs two OCR engines) and a matching
`nested_ner_xml_{...}` with tags PER / ACT / SPAT(>LOC,CARDINAL) / TITRE / DESC / FT, e.g.
  <PER>Dufan et Clémendot</PER>, <ACT>pharmaciens</ACT>,
  <SPAT><LOC>r. de la Chaussée-d'Antin</LOC>, <CARDINAL>34</CARDINAL></SPAT>. <TITRE>(Elig.)</TITRE>

Mapping: PER -> name, ACT -> occupation_role, SPAT (inner text) -> address.
spouse/race/employer/home_address are unused (not present in this dialect).

Usage
-----
    python3 ftd_to_eval.py --in data/ftd.json --out data/ftd_eval.jsonl --limit 2000
    python3 ftd_to_eval.py --in data/ftd.json --ocr pero   # use a noisy-OCR variant
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

_BIZ_RE = re.compile(r"\bet\b|&|\bCie\b|\bfr[eè]res\b", re.IGNORECASE)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _tag(name: str, xml: str):
    return [re.sub(r"<[^>]+>", "", m) for m in re.findall(rf"<{name}>(.*?)</{name}>", xml, re.S)]


def to_record(e: dict, ocr: str) -> Optional[dict]:
    xml = e.get(f"nested_ner_xml_{ocr}") or ""
    text = e.get(f"text_ocr_{ocr}") or ""
    if not xml or not text:
        return None
    name = _norm(" ".join(_tag("PER", xml)))
    if not name:
        return None
    occ = ", ".join(_norm(a) for a in _tag("ACT", xml) if _norm(a))
    addr = "; ".join(_norm(s) for s in _tag("SPAT", xml) if _norm(s))
    if not addr and not occ:
        return None
    record = {
        "name": name, "is_business": bool(_BIZ_RE.search(name)), "spouse_name": "",
        "race_designation": "", "occupation_role": occ, "employer": "",
        "address": addr, "home_address": "",
    }
    return {
        "raw_line": _norm(text),
        "context": {"dialect": "ftd-fr", "alphabetical_range": "",
                    "directory_year": str(e.get("book", "")), "page": e.get("page")},
        "record": record,
    }


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="inp", required=True, help="dataset_SODUCO_nested_ner.json")
    ap.add_argument("--out", default=None, help="output .jsonl (default: stdout)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--ocr", choices=["ref", "pero", "tess"], default="ref",
                    help="ref = manually corrected gold; pero/tess = noisier OCR variants")
    args = ap.parse_args(argv)

    data = json.load(open(args.inp, encoding="utf-8"))
    out = open(args.out, "w", encoding="utf-8") if args.out else sys.stdout
    kept = 0
    samples = []
    try:
        for e in data:
            if args.ocr != "ref" and not e.get(f"has_valid_ner_xml_{args.ocr}", True):
                continue
            ex = to_record(e, args.ocr)
            if ex is None:
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
    print(f"kept={kept} ({args.ocr}) -> {args.out or 'stdout'}", file=sys.stderr)
    for s in samples:
        print(f"  IN : {s['raw_line']!r}", file=sys.stderr)
        print(f"  OUT: {'|'.join(str(s['record'][f]) for f in FIELDS)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
