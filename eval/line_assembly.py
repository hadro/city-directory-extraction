#!/usr/bin/env python3
"""
Diagnostics for the re-OCR import's line assembly (data_prep/reocr_pair.py), the tools behind
PIPELINE #31 and #32 (2026-10-23/24). Read-only: nothing here writes a dump, a sidecar or a panel.

    python3 eval/line_assembly.py page HEAD~3 trowsgeneraldire19091trow 97 "Kate B" "Paul R"
    python3 eval/line_assembly.py proxy trowsgeneraldire19091trow trowsgeneraldire19073trow
    python3 eval/line_assembly.py moved /tmp/dumps trowsgeneraldir1905p1trow
    python3 eval/line_assembly.py same data/survey_ocr/X_words.jsonl.gz /tmp/dumps/X_words.jsonl.gz
    python3 eval/line_assembly.py tables

`page REV VOL LEAF [PATTERN ...]` runs one page through the import's own path (better_layer where
the volume has a tesseract layer, then page_dump) under reocr_pair.py at git revision REV and under
the working tree, and prints the dump's lines that contain a PATTERN, with a neighbour either side:
source, the model's start flag, the box, the text. The REV copy is written into data_prep/ for the
run and deleted after: reocr_pair reads ditto_decisions.json beside itself, and a copy run from
anywhere else silently gets no confirmed ditto marks. Where the page's answers are is found from
the volume (data/reocr_tiers/<vol>, else the canary's data/reocr_books_halves); --root, --page-dir,
--alt-page-dir and --slug override, e.g. for the pilot: --root data/reocr_pilot --page-dir
data/reocr_pilot_pages_ia --slug lightonocr-3-1b-greedy-m2 --alt-page-dir -.

`proxy VOL ...`: the share of a volume's listing lines (data/survey_ocr/<vol>_listing.jsonl.gz, so
after the survey's wrap-joiner) in which a ditto dash opens a second entry mid-line: two entries
glued into one, PIPELINE #32 (a). 0.2-0.5% is the floor on Trow (dashes inside real entries).

`moved DIR VOL ...`: how many lines' start x differs between the production dump and a dump of the
same volume written to DIR (`reocr_pair.py dump ... --out-dir DIR`), with examples. A change meant
to touch a few lines that moves thousands is wrong somewhere (#32 (a)'s rejected versions).

`same A B`: whether two word dumps hold the same records (decompressed; gzip headers carry a
timestamp). A refactor meant to change nothing must say SAME on an IA-layer and a tesseract-layer
volume (PIPELINE #31).

`tables [VOL ...]`: per volume, the tiles LightOn answered in table mode and the column-header
lines it invented there ("Name, Address"), which untable keeps as lines (PIPELINE #32 (b), #27).
"""
from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import importlib
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
sys.path.insert(0, str(REPO / "data_prep"))
SLUG = "lightonocr-3-1b-greedy-vllm"
MID_DITTO = re.compile(r"\S\s+[—–]\s*[A-Z][a-z]")
HEADER_WORD = r"(name|names|occupation|address|details|residence|business|description|notes|" \
              r"location|info|information|street|number|trade)"
HEADER = re.compile(rf"^{HEADER_WORD}(, {HEADER_WORD})+$", re.I)


def volume_paths(vol: str, args) -> tuple:
    """(root, page_dir, alt_dir or None) for a volume's re-OCR answers."""
    if args.root:
        root, page_dir = Path(args.root), Path(args.page_dir or DATA / "reocr_books_records")
    elif (DATA / "reocr_tiers" / vol / "boxes.json").exists():
        root, page_dir = DATA / "reocr_tiers" / vol, DATA / "reocr_books_records"
    else:
        root, page_dir = DATA / "reocr_books_halves", DATA / "reocr_books"
    alt = args.alt_page_dir if args.alt_page_dir is not None else str(DATA / "reocr_books_tess")
    alt_dir = None if alt == "-" or not (Path(alt) / vol).exists() else Path(alt)
    return (root if root.is_absolute() else REPO / root,
            page_dir if page_dir.is_absolute() else REPO / page_dir,
            alt_dir if alt_dir is None or alt_dir.is_absolute() else REPO / alt_dir)


def dump_page(mod, root: Path, page_dir: Path, alt_dir, vol: str, leaf: int, slug: str) -> tuple:
    stem = f"{vol}_{leaf:04d}"
    tiles = {}
    for key, entry in json.loads((root / "boxes.json").read_text(encoding="utf-8")).items():
        v, fname = key.split("/")
        s, name = fname[:-4].rsplit("_c", 1)
        if v == vol and s == stem:
            tiles[f"c{name}"] = entry
    if not tiles:
        raise SystemExit(f"no tiles for {stem} in {root}/boxes.json")
    answers = {}
    for name in tiles:
        lines = mod.model_lines(root / vol / f"{stem}_{name}", slug, False)
        answers[name] = None if lines is None else (lines, False)
    marks = mod.confirmed_marks(vol)
    rec = mod.page_record(page_dir, vol, stem)
    layer, paired = "first", None
    alt_f = alt_dir / vol / f"{stem}.json" if alt_dir else None
    if alt_f and alt_f.exists():
        got = mod.better_layer(rec, json.loads(alt_f.read_text(encoding="utf-8")), tiles, answers, marks)
        new_rec, paired = got if isinstance(got, tuple) else (got, None)   # before b88ecda: a record
        layer = "alt" if new_rec is not rec else "first"
        rec = new_rec
    kw = {"paired": paired} if paired is not None else {}
    lines, sources, starts = mod.page_dump(rec, tiles, answers, with_starts=True, marks=marks, **kw)
    return lines, sources, starts, f"{layer}: {rec.get('engine', '?')}"


def page(args) -> int:
    rev = args.rev
    text = subprocess.run(["git", "show", f"{rev}:data_prep/reocr_pair.py"], cwd=REPO,
                          capture_output=True, text=True, check=True).stdout
    tag = re.sub(r"\W", "_", rev)
    tmp = REPO / "data_prep" / f"_reocr_pair_at_{tag}.py"
    tmp.write_text(text, encoding="utf-8")
    try:
        old = importlib.import_module(tmp.stem)
        new = importlib.import_module("reocr_pair")
        root, page_dir, alt_dir = volume_paths(args.vol, args)
        for label, mod in ((rev, old), ("working tree", new)):
            lines, sources, starts, layer = dump_page(mod, root, page_dir, alt_dir, args.vol, args.leaf, args.slug)
            texts = [" ".join(w[5] for w in ws) for ws in lines]
            print(f"===== {label}  ({layer}; {len(texts)} lines)")
            hits = [i for i, t in enumerate(texts) if not args.patterns or any(p in t for p in args.patterns)]
            for i in sorted({j for h in hits for j in range(max(0, h - 1), min(len(texts), h + 2))}):
                ws = lines[i]
                box = (min(w[0] for w in ws), min(w[1] for w in ws), max(w[2] for w in ws),
                       max(w[3] for w in ws)) if ws else None
                print(f"  {i:4d} {sources[i]:10s} start={int(starts[i])} {str(box):26s} {texts[i][:110]}")
    finally:
        tmp.unlink(missing_ok=True)
    return 0


def proxy(args) -> int:
    for vol in args.vols:
        n = hit = 0
        with gzip.open(DATA / "survey_ocr" / f"{vol}_listing.jsonl.gz", "rt", encoding="utf-8") as fh:
            for line in fh:
                t = json.loads(line)["raw_line"]
                n += 1
                hit += bool(MID_DITTO.search(t))
        print(f"{vol:28s} {n:8,d} listing lines  mid-line ditto {hit:6,d} ({100 * hit / max(n, 1):.2f}%)")
    return 0


def _replaced(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return {r["leaf"]: r for r in map(json.loads, fh) if "sources" in r}


def moved(args) -> int:
    for vol in args.vols:
        a, b = _replaced(DATA / "survey_ocr" / f"{vol}_words.jsonl.gz"), _replaced(Path(args.dir) / f"{vol}_words.jsonl.gz")
        n = m = 0
        examples = []
        for leaf, r in sorted(b.items()):
            if leaf not in a:
                continue
            for p, q in zip(a[leaf]["lines"], r["lines"]):
                if not p or not q:
                    continue
                n += 1
                x0, x1 = min(w[0] for w in p), min(w[0] for w in q)
                if x0 != x1:
                    m += 1
                    if len(examples) < args.examples:
                        examples.append((leaf, x0, x1, " ".join(w[5] for w in q)[:50]))
        print(f"{vol:28s} start moved on {m:,} of {n:,} lines")
        for e in examples:
            print(f"    leaf {e[0]}: x {e[1]} -> {e[2]}  {e[3]}")
    return 0


def _digest(path) -> tuple:
    h, n = hashlib.sha1(), 0
    with gzip.open(path, "rb") as fh:
        for line in fh:
            h.update(line)
            n += 1
    return h.hexdigest(), n


def same(args) -> int:
    a, b = _digest(args.a), _digest(args.b)
    print(("SAME" if a == b else "DIFF") + f"  {a[1]:,} vs {b[1]:,} records")
    return 0 if a == b else 1


def tables(args) -> int:
    import reocr_pair as rp
    vols = args.vols or sorted(p.name for p in (DATA / "reocr_tiers").iterdir() if (p / "boxes.json").exists())
    total, seen = collections.Counter(), collections.Counter()
    for vol in vols:
        c = collections.Counter()
        for f in (DATA / "reocr_tiers" / vol / vol).glob(f"*_{SLUG}.meta.json"):
            c["tiles"] += 1
            if not json.loads(f.read_text(encoding="utf-8")).get("table_mode"):
                continue
            c["table"] += 1
            stem = f.with_name(f.name[:-len(f"_{SLUG}.meta.json")])
            heads = [ln for ln in rp.model_lines(stem, SLUG, False) or [] if HEADER.match(ln.strip())]
            c["header"] += len(heads)
            seen.update(heads)
        if c["tiles"]:
            print(f"{vol:28s} tiles {c['tiles']:5d}  table mode {c['table']:4d} "
                  f"({100 * c['table'] / c['tiles']:4.1f}%)  header lines {c['header']}")
        total.update(c)
    print(f"ALL: {total['tiles']:,} tiles, {total['table']:,} in table mode, {total['header']} header lines")
    for line, k in seen.most_common(8):
        print(f"    {k:4d}  {line}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("page")
    p.add_argument("rev")
    p.add_argument("vol")
    p.add_argument("leaf", type=int)
    p.add_argument("patterns", nargs="*")
    p.add_argument("--root")
    p.add_argument("--page-dir")
    p.add_argument("--alt-page-dir", help="'-' for none")
    p.add_argument("--slug", default=SLUG)
    p = sub.add_parser("proxy")
    p.add_argument("vols", nargs="+")
    p = sub.add_parser("moved")
    p.add_argument("dir")
    p.add_argument("vols", nargs="+")
    p.add_argument("--examples", type=int, default=4)
    p = sub.add_parser("same")
    p.add_argument("a")
    p.add_argument("b")
    p = sub.add_parser("tables")
    p.add_argument("vols", nargs="*")
    args = ap.parse_args(argv)
    return {"page": page, "proxy": proxy, "moved": moved, "same": same, "tables": tables}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
