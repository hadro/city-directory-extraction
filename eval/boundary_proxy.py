#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
A field-boundary instrument that needs no labels: how often a printed occupation goes missing.

    python3 eval/boundary_proxy.py --root data/volumes_run1 --run 4b-100k      # every volume
    python3 eval/boundary_proxy.py --root data/volumes_run1 --run 4b-100k --run 4b-100k+guard
    python3 eval/boundary_proxy.py --lines X.jsonl --preds Y.txt                # any paired file
    python3 eval/boundary_proxy.py --self-test

WHY (PIPELINE.md #2). `entry_rate` asks whether a line came back as a person. It cannot see
where the words went, and re-ingesting 1906BPL changed none of 500 rows' classification while the
name/occupation boundary moved. The pipeline had no instrument for field boundaries at all. This
is the proxy validated on the `44` ditto A/B (results/ab_ditto44_1906BPL_2b100k.json; the
analysis is results/ab_ditto44_1906BPL_2b100k_preds/analyze.py), made reusable:

    swallowed      the line prints an occupation token after the name, the record is not a
                   business, and `occupation_role` came back empty: the occupation went into
                   the name or the address, or was dropped

On run 1 (2026-09-28) that is 0.1-0.5% of such lines on four volumes and 1.7% on Smith 1856, where
the column-merged microfilm lines are the known fault (docs/PIPELINE.md stage 6). The cases read
as real. 290 of 1906BPL's 613 are `elk`, ABBYY's reading of `clk`, fused into the name:
`" Jos elk h 243 Hawthorne` came back named `" Josk`. Most of the rest are ad copy and
bank-officer lists, where the model is wrong on a line that is not an entry.

Two diagnostics ride beside it, NOT validated, for reading rather than citing:

    occ_in_name    `name` holds an occupation token after its first word
                   ("Smith John carpenter"). The first word is spared because Baker, Carpenter,
                   Mason and Taylor are surnames
    digit_in_name  `name` holds a digit: an address or house number pulled into the name

The rates are for comparing RUNS over the same lines (an A/B, a retrain, a changed ingest). As
absolutes they conflate the model with the lexicon, which misses occupations it has not seen and
counts a few words that are also streets or surnames.

THE LEXICON is built at run time, and its size and a hash go into the report:
- every hand-labelled `occupation_role` in data/*_eval.jsonl that is ONE word, kept where that
  word is an occupation at least OCC_RATIO times as often as it is a name or address token. So it
  spans 1786 to 1933: `cartman`, `grocer`, `shoemkr`, `bkpr`. Words that only occur inside a
  longer occupation are left out: first built from every token, the lexicon took in `city`,
  `office`, `law`, `eagle` and a surname (`merrill`), and ad copy dominated the flags.
- the 1906BPL pilot's hand list (results/ab_ditto44_1906BPL_2b100k_preds/occ_lexicon.json, 343
  tokens) and its five pre-registered OCR variants (`elk` is how ABBYY reads `clk`), minus any
  word the gold uses as a name or address OCC_RATIO times as often as an occupation.
- never the STATUS markers. `wid` / `widow` were 84% of all flags on 1906BPL and 88% on Doggett
  1845, and the gold itself disagrees about where they go: of 632 gold rows printing one, 298
  put it in `occupation_role` and 196 in `spouse_name` alone. `col'd` is a race designation.
Reading the gold's labels here is not leakage: nothing is scored against the gold.

Lines come from chunk files (`<root>/<volume>/chunk_NNN.jsonl` with `chunk_NNN.preds_<run>.txt`,
as hpc/35_volumes.sbatch writes them) or from one --lines/--preds pair. Records are YAML, one per
line, and a count mismatch is fatal: a misaligned record makes every rate below silently wrong.
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "eval"))
from evaluate import load_pred  # noqa: E402

PILOT = REPO / "results" / "ab_ditto44_1906BPL_2b100k_preds" / "occ_lexicon.json"
PILOT_OCR = {"elk", "eom", "lah", "earp", "tailoi"}   # pre-registered with the pilot
OCC_RATIO = 3
OCC_MIN = 2             # occurrences in gold occupation fields before a token counts
STOP = {"and", "the", "for", "with", "co", "cor", "near", "rear", "late", "est", "estate",
        "street", "st", "ave", "av", "road", "rd", "place", "pl", "office", "house", "rooms"}
STATUS = {"wid", "widow", "wido", "widower", "col'd", "colored", "coloured", "col’d"}
TOK = re.compile(r"[a-z][a-z’']+")
EXAMPLES = 8
TRIGGERS = 20


def tokens(s: str) -> list:
    return TOK.findall((s or "").lower())


def build_lexicon() -> set:
    whole, occ, other = collections.Counter(), collections.Counter(), collections.Counter()
    for path in sorted((REPO / "data").glob("*_eval.jsonl")):
        if path.name.startswith("iapanel_"):
            continue
        for line in path.open(encoding="utf-8"):
            if not line.strip():
                continue
            rec = json.loads(line).get("record") or {}
            toks = tokens(rec.get("occupation_role"))
            occ.update(toks)
            if len(toks) == 1 and len(toks[0]) >= 3:
                whole[toks[0]] += 1
            for f in ("name", "address", "home_address", "employer"):
                other.update(tokens(rec.get(f)))
    lex = {t for t, n in whole.items() if n >= OCC_MIN and n >= OCC_RATIO * other.get(t, 0)}
    if PILOT.exists():
        lex |= {t for t in json.loads(PILOT.read_text(encoding="utf-8"))
                if other.get(t, 0) < OCC_RATIO * max(occ.get(t, 0), 1)}
    return (lex | PILOT_OCR) - STOP - STATUS


WORD = re.compile(r"[a-z][a-z’']+|\d[\w/½]*")


def occupation_words(raw: str, lex: set) -> list:
    """Lexicon words in the line where an occupation can stand. The name is spared, because
    Miller, Mason, Carpenter and Turner are surnames: two words, or one after a ditto mark
    (`" John grocer`, Trow's glued `-Adolph`), which stands for the surname. A word right after
    a house number is a street: Doggett's "h. 6 Attorney" is Attorney Street."""
    raw = (raw or "").lower()
    words = WORD.findall(raw)
    skip = 1 if raw.lstrip()[:1] and not raw.lstrip()[0].isalnum() else 2
    return [w for i, w in enumerate(words)
            if i >= skip and w in lex and not words[i - 1][0].isdigit()]


def check(raw: str, rec: dict, lex: set) -> dict:
    """The three flags for one line and its record. A record the model calls a business is
    left out of `swallowed`: "Aachen & Munich Fire Ins Co" is a name, and a business entry
    leaves `occupation_role` empty by convention."""
    business = str(rec.get("is_business")).strip().lower() == "true"   # parsed YAML: 'False'
    has = bool(occupation_words(raw, lex)) and not business
    name_toks = tokens(rec.get("name"))
    return {"has_occ": has,
            "swallowed": has and not str(rec.get("occupation_role") or "").strip(),
            "occ_in_name": any(t in lex for t in name_toks[1:]),
            "digit_in_name": bool(re.search(r"\d", str(rec.get("name") or "")))}


def paired(lines_path: Path, preds_path: Path) -> list:
    lines = [json.loads(x) for x in lines_path.read_text(encoding="utf-8").splitlines() if x.strip()]
    preds = load_pred(str(preds_path), "yaml")
    if len(preds) != len(lines):
        raise SystemExit(f"{preds_path.name}: {len(preds)} records for {len(lines)} lines -- "
                         f"they must align 1:1")
    return list(zip(lines, preds))


def volume_rows(vdir: Path, run: str) -> list:
    out = []
    for c in sorted(vdir.glob("chunk_*.jsonl")):
        p = c.with_name(f"{c.stem}.preds_{run}.txt")
        if not p.exists():
            raise SystemExit(f"missing predictions {p}")
        out += paired(c, p)
    return out


def measure(rows: list, lex: set) -> dict:
    tally = collections.Counter()
    by_section = collections.defaultdict(collections.Counter)
    triggers = collections.Counter()
    examples = []
    for line, rec in rows:
        raw = line.get("raw_line") or ""
        f = check(raw, rec, lex)
        sec = (line.get("context") or {}).get("section") or "-"
        for k, v in f.items():
            tally[k] += v
            by_section[sec][k] += v
        tally["lines"] += 1
        by_section[sec]["lines"] += 1
        if f["swallowed"]:
            triggers.update(set(occupation_words(raw, lex)))
            if len(examples) < EXAMPLES:
                examples.append({"raw_line": raw[:100], "name": rec.get("name"),
                                 "address": rec.get("address")})

    def rates(t):
        return {"lines": t["lines"], "with_occupation": t["has_occ"],
                "swallowed": t["swallowed"],
                "swallow_rate": round(t["swallowed"] / t["has_occ"], 4) if t["has_occ"] else None,
                "occ_in_name": t["occ_in_name"], "digit_in_name": t["digit_in_name"]}
    return {**rates(tally), "by_section": {s: rates(t) for s, t in sorted(by_section.items())},
            "top_triggers": triggers.most_common(TRIGGERS), "examples": examples}


def git_rev() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
                              capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _self_test() -> int:
    lex = {"carpenter", "grocer", "clk"}
    f = check("Smith John, grocer, 12 Pine", {"name": "Smith John", "occupation_role": ""}, lex)
    assert f["has_occ"] and f["swallowed"]
    f = check("Smith John, grocer, 12 Pine", {"name": "Smith John", "occupation_role": "grocer"}, lex)
    assert not f["swallowed"]
    assert check("Carpenter Wm, clk", {"name": "Carpenter Wm", "occupation_role": "clk"},
                 lex)["occ_in_name"] is False, "a surname that is also a trade is spared"
    assert check("x", {"name": "Smith John carpenter"}, lex)["occ_in_name"]
    assert not check("Carpenter John, 12 Pine", {"name": "Carpenter John"}, lex)["has_occ"], \
        "a surname that is a trade is not an occupation"
    assert not check("Smith & Jones grocer 12 Pine", {"name": "Smith & Jones grocer",
                                                      "is_business": "True"}, lex)["swallowed"]
    assert check("Smith John, grocer", {"name": "Smith John", "is_business": "False"},
                 lex)["swallowed"], "load_pred returns the string 'False', which is truthy"
    assert occupation_words("Fletcher James H., h. 6 Carpenter", lex) == [], "a street"
    assert occupation_words('" John grocer 12 Pine', lex) == ["grocer"]
    assert check("x", {"name": "Smith 12"}, lex)["digit_in_name"]
    assert tokens("Rob’t O’Brien, 44 Pine") == ["rob’t", "o’brien", "pine"]
    m = measure([({"raw_line": "Smith John, grocer", "context": {"section": "listing"}},
                  {"name": "Smith John grocer", "occupation_role": ""}),
                 ({"raw_line": "Jones Wm, clk", "context": {"section": "listing"}},
                  {"name": "Jones Wm", "occupation_role": "clk"})], lex)
    assert m["with_occupation"] == 2 and m["swallowed"] == 1 and m["swallow_rate"] == 0.5
    lexicon = build_lexicon()
    assert {"grocer", "cartman", "clk"} <= lexicon, "era-spanning trades are in"
    assert not {"and", "street", "wid", "widow", "col'd", "merrill"} & lexicon
    print(f"self-test ok ({len(lexicon)} lexicon tokens)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", help="directory of <volume>/chunk_NNN.jsonl (hpc/prep_volumes.py)")
    ap.add_argument("--run", action="append", default=[],
                    help="prediction run name(s): chunk_NNN.preds_<run>.txt; repeat to compare")
    ap.add_argument("--lines", help="one JSONL of {raw_line, context}")
    ap.add_argument("--preds", help="its YAML predictions, one record per line")
    ap.add_argument("--out", help="write the report here (JSON)")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()

    lex = build_lexicon()
    report = {"derived": _dt.date.today().isoformat(), "code_at": git_rev(),
              "lexicon": {"tokens": len(lex), "sha1": hashlib.sha1(
                  "\n".join(sorted(lex)).encode()).hexdigest()[:12],
                  "occ_ratio": OCC_RATIO, "occ_min": OCC_MIN},
              "runs": {}}
    if args.lines:
        if not args.preds:
            ap.error("--lines needs --preds")
        report["runs"]["file"] = {Path(args.lines).name: measure(
            paired(Path(args.lines), Path(args.preds)), lex)}
    elif args.root and args.run:
        root = Path(args.root)
        vols = sorted(d for d in root.iterdir() if d.is_dir())
        for run in args.run:
            report["runs"][run] = {v.name: measure(volume_rows(v, run), lex) for v in vols
                                   if any(v.glob(f"chunk_*.preds_{run}.txt"))}
    else:
        ap.error("give --root and --run, or --lines and --preds")

    names = sorted({v for r in report["runs"].values() for v in r})
    print(f"lexicon {len(lex)} tokens; swallowed = occupation printed, occupation_role empty\n")
    print(f"{'volume':28s} " + " ".join(f"{r[:22]:>22s}" for r in report["runs"]))
    for v in names:
        cells = []
        for r in report["runs"].values():
            m = r.get(v)
            cells.append(f"{m['swallowed']:>7,d}/{m['with_occupation']:<8,d} {m['swallow_rate']:5.1%}"
                         if m and m["swallow_rate"] is not None else f"{'-':>22s}")
        print(f"{v[:28]:28s} " + " ".join(f"{c:>22s}" for c in cells))
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n",
                                  encoding="utf-8")
        print(f"\n-> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
