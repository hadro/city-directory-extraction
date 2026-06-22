# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Validate gold JSONL exported by make_gold_tool.py BEFORE it joins the eval panel.

Two classes of finding:
  ERROR    — would break eval/evaluate.py or is structurally invalid. Fix before use.
  WARNING  — likely a transcription/splitting mistake worth a human glance.

It also prints coverage stats (field fill-rates, business ratio, lines/image) so you
can see whether the sample is balanced before investing more hand-labeling.

Checks
------
ERRORS
  * line not valid JSON / missing raw_line|context|record
  * record missing one of the 8 FIELDS, extra unknown field, is_business not bool
  * empty `name` (a gold line must have a name)
  * a field contains "|"  -> breaks the pipe serialization evaluate.py scores on
  * raw_line / any field contains a newline
  * context missing dialect|directory_year|image
WARNINGS
  * field text whose tokens don't appear in raw_line (transcription drift / typo)
  * occupation_role that looks like an address (has "h /r /bds " or a street number)
  * address with no digit AND no street/residence token (likely mis-split)
  * is_business=False but name looks like a firm (& Co / Bros / Mfg / Works / Sons)
  * directory_year not a 4-digit year; dialect not in the known set
  * duplicate (image, raw_line) rows
  * image file not found under --images root (if given)
  * year/​col mismatch vs master_directories.csv (if --master resolvable via image)

Usage
-----
    python3 data_prep/validate_gold.py data/gold_lain_1876.jsonl
    python3 data_prep/validate_gold.py data/*.jsonl --images ../directory-pipeline/output --strict
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

FIELDS = ["name", "is_business", "spouse_name", "race_designation",
          "occupation_role", "employer", "address", "home_address"]
KNOWN_DIALECTS = {"nyc", "tulsa", "minneapolis", "ftd-fr", "nyu"}

# residence/street tokens common in NYC-style directories (h=house, r=resides, bds=boards…);
# include full street-type words, hyphenated forms (Bowery-lane), and ditto (do = number repeated)
ADDR_TOK = re.compile(
    r"\b(h|r|bds|b|res|rear|cor|c|n|s|e|w|av|ave|avenue|st|street|pl|place|ter|terrace|"
    r"rd|road|sq|square|la|lane|ct|court|row|slip|wharf|al|alley|do)\b\.?", re.I)
FIRM_RE = re.compile(r"&|\bco\b|\bbros\b|\bbro\b|\bsons\b|\bmfg\b|\bworks\b|\b& co\b|\bcompany\b", re.I)
OCC_AS_ADDR = re.compile(r"\b(h|r|bds)\s+\d|\b\d+\s+[A-Z]")
WORD = re.compile(r"[A-Za-z0-9]+")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _tokens(s: str) -> set:
    return {w.lower() for w in WORD.findall(s or "")}


class Report:
    def __init__(self):
        self.errors = []
        self.warnings = []

    def err(self, where, msg):
        self.errors.append(f"{where}: {msg}")

    def warn(self, where, msg):
        self.warnings.append(f"{where}: {msg}")


def check_record(rec: dict, raw: str, where: str, rep: Report):
    keys = set(rec)
    for f in FIELDS:
        if f not in keys:
            rep.err(where, f"record missing field {f!r}")
    for extra in keys - set(FIELDS):
        rep.err(where, f"record has unknown field {extra!r}")
    if not isinstance(rec.get("is_business"), bool):
        rep.err(where, f"is_business must be bool, got {type(rec.get('is_business')).__name__}")
    if not _norm(str(rec.get("name", ""))):
        rep.err(where, "empty name")
    for f in FIELDS:
        v = rec.get(f)
        if isinstance(v, str):
            if "|" in v:
                rep.err(where, f"{f} contains '|' (breaks pipe scoring): {v!r}")
            if "\n" in v:
                rep.err(where, f"{f} contains newline")

    # --- content warnings ---
    raw_tok = _tokens(raw)
    for f in ("name", "occupation_role", "address", "employer", "spouse_name"):
        v = _norm(str(rec.get(f, "")))
        if not v:
            continue
        miss = _tokens(v) - raw_tok
        # ignore pure-punct/short residence flags; flag only real word drift
        miss = {m for m in miss if len(m) > 1}
        if miss:
            rep.warn(where, f"{f} tokens not in raw_line (typo/drift?): {sorted(miss)}")
    occ = _norm(str(rec.get("occupation_role", "")))
    if occ and OCC_AS_ADDR.search(occ):
        rep.warn(where, f"occupation_role looks like an address: {occ!r}")
    addr = _norm(str(rec.get("address", "")))
    if addr and not any(ch.isdigit() for ch in addr) and not ADDR_TOK.search(addr):
        rep.warn(where, f"address has no number or street token: {addr!r}")
    # home_address is only for a SECOND address; a lone address belongs in `address`
    if _norm(str(rec.get("home_address", ""))) and not addr:
        rep.warn(where, "home_address set but address empty — a single address belongs in `address`")
    name = _norm(str(rec.get("name", "")))
    if name and FIRM_RE.search(name) and not rec.get("is_business"):
        rep.warn(where, f"name looks like a firm but is_business=False: {name!r}")


def check_context(ctx: dict, where: str, rep: Report):
    for k in ("dialect", "directory_year", "image"):
        if k not in ctx:
            rep.err(where, f"context missing {k!r}")
    dy = str(ctx.get("directory_year", ""))
    if dy and not re.search(r"\b(1[789]\d\d|20\d\d)\b", dy):
        rep.warn(where, f"directory_year not a 4-digit year: {dy!r}")
    dia = ctx.get("dialect", "")
    if dia and dia not in KNOWN_DIALECTS:
        rep.warn(where, f"unusual dialect {dia!r} (known: {sorted(KNOWN_DIALECTS)})")


def load_master(path: Path):
    if not path or not path.exists():
        return {}
    import csv
    idx = {}
    for r in csv.DictReader(open(path, encoding="utf-8")):
        rid = (r.get("id") or "").strip()
        if rid:
            idx[rid] = r
    return idx


def master_row_for_image(image: str, master: dict):
    cands = [rid for rid in master if rid and rid in (image or "")]
    return master[max(cands, key=len)] if cands else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", help="gold .jsonl file(s) / globs")
    ap.add_argument("--images", default="", help="root to verify context.image exists under")
    ap.add_argument("--master", default=str(Path(__file__).resolve().parent / "master_directories.csv"))
    ap.add_argument("--strict", action="store_true", help="exit 1 if any ERROR")
    args = ap.parse_args(argv)

    paths = [Path(p) for g in args.files for p in glob.glob(g)] or [Path(p) for p in args.files]
    master = load_master(Path(args.master)) if args.master else {}
    rep = Report()
    seen = set()
    fill = Counter()
    n = biz = 0
    per_image = Counter()

    for path in paths:
        if not path.exists():
            rep.err(str(path), "file not found")
            continue
        for i, raw_line in enumerate(open(path, encoding="utf-8"), 1):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            where = f"{path.name}:{i}"
            try:
                obj = json.loads(raw_line)
            except json.JSONDecodeError as e:
                rep.err(where, f"invalid JSON: {e}")
                continue
            for k in ("raw_line", "context", "record"):
                if k not in obj:
                    rep.err(where, f"missing top-level {k!r}")
            if "record" not in obj or "context" not in obj:
                continue
            n += 1
            raw = obj.get("raw_line", "")
            rec, ctx = obj["record"], obj["context"]
            check_record(rec, raw, where, rep)
            check_context(ctx, where, rep)

            if rec.get("is_business") is True:
                biz += 1
            for f in FIELDS:
                v = rec.get(f)
                if (v is True) or (isinstance(v, str) and v.strip()):
                    fill[f] += 1

            img = ctx.get("image", "")
            per_image[img] += 1
            key = (img, _norm(raw))
            if key in seen:
                rep.warn(where, f"duplicate (image, raw_line): {raw!r}")
            seen.add(key)

            if args.images and img:
                hits = list(Path(args.images).rglob(img))
                if not hits:
                    rep.warn(where, f"image not found under {args.images}: {img}")
            if master:
                row = master_row_for_image(img, master)
                if row:
                    my = str(ctx.get("directory_year", ""))
                    if row.get("year") and my and row["year"][:4] != my[:4]:
                        rep.warn(where, f"year {my} != master {row['year']} for {row['id']}")

    # ---- report ----
    out = sys.stdout
    print("=" * 60, file=out)
    print(f"GOLD VALIDATION — {n} lines across {len(paths)} file(s)", file=out)
    print("=" * 60, file=out)
    if n:
        print(f"\nbusiness rows: {biz} ({biz/n:.0%})   |   lines/image: "
              f"{n/max(1,len(per_image)):.1f} over {len(per_image)} images", file=out)
        print("field fill-rate:", file=out)
        for f in FIELDS:
            print(f"  {f:18s} {fill[f]:4d}  {fill[f]/n:5.0%}", file=out)
        thin = [img for img, c in per_image.items() if c < 5]
        if thin:
            print(f"\n{len(thin)} image(s) with <5 gold lines (likely under-labeled)", file=out)

    print(f"\nERRORS: {len(rep.errors)}", file=out)
    for e in rep.errors[:200]:
        print(f"  ✗ {e}", file=out)
    print(f"\nWARNINGS: {len(rep.warnings)}", file=out)
    for w in rep.warnings[:200]:
        print(f"  ⚠ {w}", file=out)
    if len(rep.warnings) > 200:
        print(f"  … +{len(rep.warnings)-200} more", file=out)

    if args.strict and rep.errors:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
