# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Harvest REAL NYC occupation vocabulary from SAFE (non-eval) directory listing pages and
merge it into the synthetic generator's occupation pool.

Why: `synth_persons.py`'s `NYC_OCC` is ~50 hand-curated trade words. On real gold the model
*regularises* any occupation outside that pool to the nearest one it knows (measured v4 misses:
`tanyard`->`tailor`, `shoestore`->`shoemaker`, `weigher`->`weaver`, `porterhouse`->`porter`).
Same failure class as the ~54-surname pool that `harvest_names.py` fixed -- and the same fix:
fold in authentic terms harvested from real directories so the model learns to COPY, not snap.

Pipeline (reuses the TESTED extractor, no duplicated Gemini code):
    surya listing .txt  ->  pseudo-gold JSONL  ->  eval/gemini_baseline.py  ->  YAML preds
    ->  pool occupation_role values  ->  names/occupations_harvested.tsv
`synth_persons.py` loads that TSV and merges it into the NYC occupation sampling pool (weighted),
exactly like `surnames_harvested.tsv`.

LEAKAGE RULE (same as harvest_names.py): only pass volumes that are NOT in the eval panel or the
external eval sets. The safe set below is publishers/years with NO panel or external collision
(Longworth/Elliot/Hodge/Low/Long/Groot -- eval-blind publishers -- plus off-year Trow/Doggett).

Usage
-----
    # end-to-end (needs GEMINI_API_KEY; ~2k lines = pennies):
    python3 data_prep/harvest_occupations.py --surya-dirs ../directory-pipeline/output/nypl_longworth_1818_19_* ...
    # reuse an existing preds file (no Gemini):
    python3 data_prep/harvest_occupations.py --from-preds data/harvest_occ_preds.txt --lines data/harvest_lines.jsonl
    python3 data_prep/harvest_occupations.py --self-test        # offline: filter/clean/merge logic
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent
NAMES_DIR = REPO / "data_prep" / "names"
OCC_OUT = NAMES_DIR / "occupations_harvested.tsv"
GEMINI = REPO / "eval" / "gemini_baseline.py"

# dir name -> (publisher, directory_year); regex tolerant of the trailing 8-hex NYPL id
_DIR_RE = re.compile(r"nypl_([a-z]+)(?:_[a-z]+)*_(1[6789]\d\d)(?:_(\d\d))?_[0-9a-f]{8}$")

# lines that are never a person entry (page furniture / ad boilerplate / OCR junk)
_PAGE_NUM = re.compile(r"^\W*\d{1,4}\W*$")
_HAS_LOWER = re.compile(r"[a-z]")
_STREET_TOK = re.compile(r"\b(st|street|av|ave|avenue|lane|pl|place|road|rd|sq|square|"
                         r"row|slip|alley|wharf|dock|market|cor|corner)\b", re.I)


def parse_dir(d: str) -> "tuple[str, str]":
    m = _DIR_RE.search(Path(d).name)
    if not m:
        return "", ""
    pub, y, yy = m.groups()
    year = f"{y}/{yy}" if yy else y
    return pub, year


def gather_lines(dirs: "list[str]") -> "list[dict]":
    """Read *_surya.txt from each dir; yield candidate person-entry lines with context.
    Filters obvious non-entries (headers, page numbers, OCR garbage) -- Gemini drops the
    rest by returning an empty occupation."""
    out = []
    for d in dirs:
        pub, year = parse_dir(d)
        for txt in sorted(glob.glob(os.path.join(d, "*_surya.txt"))):
            image = Path(txt).name.replace("_surya.txt", ".jpg")
            for raw in open(txt, encoding="utf-8"):
                line = raw.strip()
                if len(line) < 8 or _PAGE_NUM.match(line):
                    continue
                if not _HAS_LOWER.search(line):            # ALL-CAPS header / running head
                    continue
                ascii_ratio = sum(c.isascii() for c in line) / len(line)
                if ascii_ratio < 0.85:                     # OCR garbage (九万主 etc.)
                    continue
                out.append({"publisher": pub, "year": year, "image": image, "raw_line": line})
    return out


def write_pseudo_gold(lines: "list[dict]", path: Path) -> None:
    """Minimal {raw_line, context, record} JSONL for gemini_baseline.py (record is a dummy;
    the extractor only reads raw_line + context)."""
    empty = {"name": "", "is_business": False, "spouse_name": "", "race_designation": "",
             "occupation_role": "", "employer": "", "address": "", "home_address": ""}
    with open(path, "w", encoding="utf-8") as fh:
        for ln in lines:
            fh.write(json.dumps({
                "raw_line": ln["raw_line"],
                "context": {"publisher": ln["publisher"] or "trow",
                            "directory_year": ln["year"] or "1850", "image": ln["image"]},
                "record": empty,
            }, ensure_ascii=False) + "\n")


def run_gemini(gold: Path, out: Path) -> None:
    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit("GEMINI_API_KEY not set (export it from ../directory-pipeline/.env).")
    cmd = ["uv", "run", str(GEMINI), "--gold", str(gold), "--out", str(out), "--target", "yaml"]
    print(f"  running: {' '.join(cmd)}", file=sys.stderr)
    subprocess.run(cmd, check=True)


def clean_occ(occ: str) -> str:
    """Normalise a predicted occupation_role into a poolable term, or '' to drop."""
    o = re.sub(r"\s+", " ", (occ or "").strip().strip(",;"))
    if not o or len(o) > 42:
        return ""
    if ":" in o:                                           # field-name leak from malformed YAML
        return ""
    if any(ch.isdigit() for ch in o):                      # address bled into the field
        return ""
    if _STREET_TOK.search(o) and "house" not in o.lower() and "store" not in o.lower():
        return ""                                           # street token but not a *-house/store trade
    if o.lower() in {"do", "do.", "none", "n/a", "the", "and"}:
        return ""
    if not _HAS_LOWER.search(o):
        return ""
    return o


def parse_preds(preds_path: Path) -> Counter:
    blocks = Path(preds_path).read_text(encoding="utf-8").split("\n\n")
    pool: Counter = Counter()
    for b in blocks:
        # Gemini emits YAML values either quoted ("painter") or bare (painter) -- accept both.
        m = re.search(r'^occupation_role:\s*(.*?)\s*$', b, re.M)
        if not m:
            continue
        occ = clean_occ(m.group(1).strip().strip('"'))
        if occ:
            pool[occ] += 1
    return pool


def merge_write(path: Path, counts: Counter) -> int:
    prev: Counter = Counter()
    if path.exists():
        for ln in open(path, encoding="utf-8"):
            n, c = ln.rstrip("\n").rsplit("\t", 1)
            prev[n] += int(c)
    prev.update(counts)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for n, c in prev.most_common():
            fh.write(f"{n}\t{c}\n")
    return len(prev)


def _self_test() -> int:
    assert parse_dir("nypl_longworth_1818_19_69fdfa80") == ("longworth", "1818/19")
    assert parse_dir("nypl_elliot_1812_e9592bb0") == ("elliot", "1812")
    assert parse_dir("nypl_low_buell_bull_1796_2dfca400") == ("low", "1796")
    # cleaning: keep real trades incl. compounds + *-house/store; drop addresses/junk
    for good in ["grocer", "cabinet maker", "wines & liquors", "boarding house",
                 "drygood store", "shagreen case maker", "tailor."]:
        assert clean_occ(good) == good, f"dropped a real trade: {good!r}"
    for bad in ["84 Bowery", "", "corner of Broadway", "do", "N/A", "x" * 50]:
        assert clean_occ(bad) == "", f"kept junk: {bad!r}"
    # parse_preds over a tiny YAML-preds fixture -- mix quoted and BARE values (Gemini emits both)
    import tempfile
    fixture = ('name: Clark John\noccupation_role: grocer\naddress: 12 Broad\n\n'
               'name: "Ross A"\noccupation_role: "84 Bowery"\naddress: ""\n\n'
               'name: Duke Wm\noccupation_role: cabinet maker\naddress: 15 Thames')
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(fixture); tmp = Path(f.name)
    pool = parse_preds(tmp)
    assert pool == Counter({"grocer": 1, "cabinet maker": 1}), dict(pool)
    print("self-test OK", file=sys.stderr)
    return 0


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--surya-dirs", nargs="*", default=[], help="pipeline output dirs w/ *_surya.txt")
    ap.add_argument("--lines-out", default=str(REPO / "data" / "harvest_lines.jsonl"))
    ap.add_argument("--preds-out", default=str(REPO / "data" / "harvest_occ_preds.txt"))
    ap.add_argument("--from-preds", help="skip Gemini; pool this existing preds file")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()

    if args.from_preds:
        pool = parse_preds(Path(args.from_preds))
    else:
        dirs = [d for pat in args.surya_dirs for d in glob.glob(pat) if os.path.isdir(d)]
        if not dirs:
            ap.error("no --surya-dirs matched (need dirs containing *_surya.txt)")
        lines = gather_lines(dirs)
        if not lines:
            ap.error("no candidate listing lines found in the given dirs")
        print(f"gathered {len(lines)} candidate lines from {len(dirs)} volume(s)", file=sys.stderr)
        write_pseudo_gold(lines, Path(args.lines_out))
        run_gemini(Path(args.lines_out), Path(args.preds_out))
        pool = parse_preds(Path(args.preds_out))

    total = merge_write(OCC_OUT, pool)
    print(f"harvested +{sum(pool.values())} occ mentions / {len(pool)} distinct this run",
          file=sys.stderr)
    print(f"  pool now: {total} distinct -> {OCC_OUT}", file=sys.stderr)
    print(f"  top: {', '.join(n for n, _ in pool.most_common(12))}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
