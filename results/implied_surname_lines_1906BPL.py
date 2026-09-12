#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Unmarked entries that lead with a GIVEN name, and the wrong surname they carry downstream.

    python3 results/implied_surname_lines_1906BPL.py \
        --lines data/1906BPL_lines.jsonl \
        --out results/implied_surname_lines_1906BPL.json

Found 2026-09-12 from an observation off the page images: long runs of lines that look like real
entries but start with the given name and carry no ditto indicator at all.

THE FINDING
-----------
A surname block prints the surname once and dittos the rest. Sometimes the mark is simply not
there -- the printer omitted it, or ABBYY dropped it -- and the entry begins at the given name:

    Geo C bookkpr h 1.18 McDonough          <- no mark
    Geo C elk h 31, Clifton pi              <- no mark
    " Geo C electrician h 118 McDonough     <- SAME block, mark present
    Geo D lumber ft Kent h 168 McDon-       <- no mark

Both forms on one page of one block, so this is a dropped mark, not a second convention.

Measured on 1906BPL's 199,012 kept lines:

    unmarked lines leading with a harvested given name        5,491
    ... accepted as a NEW SURNAME by surname_token() today    4,813   (87.7%)
    ditto lines downstream that inherit that wrong carry      8,017
    TOTAL lines carrying a wrong surname                     12,830   (6.45% of the volume)
    worst single run of inherited error                         137   consecutive lines

The entry itself is wrong, and then it poisons the carry for every ditto line until the next real
surname. That second part is the larger half.

WHY THE OBVIOUS SIGNAL DOES NOT WORK
------------------------------------
Alphabetical position was the first thing tried and it fails. Only 2,048 non-ditto lines disagree
with their leaf's modal sort letter, and that set is mostly advertising (`Telephone` 170, `Nos.`
58, `Riding` 45, `Watches,` 21). The reason is structural: entries inside a surname block are
sorted by GIVEN name, so `Jas`/`John`/`Jos` sitting under a `J` surname vote for the leaf's own
modal letter and look perfectly well-behaved.

`alpha_run_filter.first_letter` already abstains on `Wm` and `H'y`, the two forms whose
abbreviation leaves fewer than two lowercase letters after the capital. It cannot abstain on
`Jas`, `Geo`, `Thos`, `Chas`, `Jos`, `Edw'd`, `Rob't`, `Mich'l` -- all of them match the anchored
sort-key rule and vote as surnames. That is not a bug in the rule; the rule cannot see the
difference from shape alone. It needs a vocabulary.

THE DETECTOR, AND WHY IT SELF-CALIBRATES
----------------------------------------
A ditto line's SECOND token is a given name by construction -- the mark supplied the surname. The
volume hands over 134,142 of them, so the given-name vocabulary can be harvested from the book
itself rather than supplied from outside. Score each token by where it appears:

    ratio = n(given-name position) / (n(given-name position) + n(leading position))

Measured separation on 1906BPL, and the middle band is the evidence the score means something:

    ratio < 0.50     14 types   Telephone, Van, De, St, La, Le, Brooklyn   ad copy, surname prefixes
    0.50 - 0.90     292 types   Charlotte, Hamilton, Morgan, Stewart, Lewis, Lawrence, Isaac
    ratio >= 0.90   595 types   John, Wm, Jas, Geo, Thos, Jos, H'y, Chas, Edw'd, Frank

Nothing told the test that the middle band is the set of names that are genuinely BOTH given names
and surnames. It fell out of the counts, which is the reason to believe the ends.

**5,491 is a floor, not a ceiling.** At 0.90 the test declines to claim `Isaac` (0.88) and `Lewis`
(0.89), both of which are real cases in this volume. Raising recall means accepting the ambiguous
band, and nothing here establishes where that trade should sit.

PORTABILITY -- THE TWO HALVES TRAVEL DIFFERENTLY
------------------------------------------------
The MECHANISM needs the volume's dittos to be recognised, so it inherits the `--inventory`
calibration PIPELINE.md already requires before a production pass. It adds no new per-volume
convention dependence: if the marks are not identified, ditto resolution is already broken.

The OUTPUT transfers. `resolve_dittos.py` says the ditto glyphs are "a property of one OCR engine
on one book, not of the corpus" -- given-name vocabulary is the opposite, a property of the
language and the era, stable across publisher, engine and decade. So the harvested lexicon seeds
a volume that cannot harvest its own, which is the case this was asked about: a book that marks
repeats by indentation alone and prints no glyph at all.

Practical shape: harvest per volume where possible, union with a corpus-wide lexicon, and re-run
the ratio per volume so a token may be a given name in one book and a surname in another.

VALIDATED, AND THE RESULT CHANGED TWO THINGS
--------------------------------------------
`implied_surname_validation.py` runs this lexicon against the 21-volume panel gold. Read it before
using this detector; the short version:

- **It must be gated on whether the volume uses implied surnames at all.** Applied blind it throws
  242 false positives on rows whose gold surname IS the leading token (`Harvey Andrew`,
  `Dudley Charles` -- names that are both). Gated, that is 1. Blind application is the error, not
  the lexicon.
- **Recall is not measurable from the gold we hold**, and no recall number should be quoted. The
  panel holds 6 clean instances, all trow1913. 1906BPL, where the phenomenon is abundant, has no
  labelled gold -- and `data/1906BPL_sample500_eval.jsonl` cannot help: it is the A/B input sample
  and 0 of its 500 rows carry a name.
- **The production gate misses the Trow family.** Trow glues its dash (`-Adolph`), so nothing
  tokenises as a mark and both the gate and the harvest read 0.0% against a gold-implied share of
  58.8% / 97.9%. This detector is blocked on next-step #9 there.

WHAT IS STILL NOT ESTABLISHED
-----------------------------
- **One volume, one OCR engine, one publisher** for the 5,491 and the 6.45%. Same caveat the ditto
  glyph list carries.
- **The 0.90 threshold is chosen from this book**, from the separation printed above. It is not
  transferred from anywhere and should not be trusted on a new volume without re-running.
- **The overlap with next-step #6 is NOT measured.** A wrong carry running 137 lines is a
  plausible contributor to that 23.5% cross-line dispute rate, and this file does not claim it.
  That is a separate measurement.
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "postprocess"))

from resolve_dittos import is_ditto_lead, surname_token          # noqa: E402

# Name-shaped: a capital followed by letters/apostrophes/period. Kills the digit ditto forms
# (`4`, `41`, `14`) that the harvest otherwise picks up, and bare single initials.
NAMEY = re.compile(r"^[A-Z][A-Za-z’'.]*$")

MIN_COUNT = 5        # a token must appear this often in given-name position to be scored at all
MIN_RATIO = 0.90     # see the separation table in the docstring; chosen from this volume


def load(path):
    rows = []
    with open(path, encoding="utf-8") as fh:
        for ln in fh:
            if ln.strip():
                r = json.loads(ln)
                rows.append((r["context"]["leaf"], r["raw_line"]))
    return rows


def harvest(rows):
    """(given-position counts, leading-position counts) over the whole volume.

    A ditto line's second token is a given name because the mark supplied the surname; a non-ditto
    line's first token is whatever the pipeline currently reads as a surname. Tokens that are
    really given names pile up in the first and only appear in the second when the mark is missing
    -- which is the whole signal.
    """
    n_given, n_lead = Counter(), Counter()
    for _, raw in rows:
        toks = raw.split()
        if not toks:
            continue
        if is_ditto_lead(raw):
            if len(toks) >= 2:
                n_given[toks[1]] += 1
        else:
            n_lead[toks[0]] += 1
    return n_given, n_lead


def lexicon(n_given, n_lead, min_count, min_ratio):
    scored = {}
    for tok, n in n_given.items():
        if n < min_count or not NAMEY.match(tok) or len(tok) < 2:
            continue
        scored[tok] = n / (n + n_lead[tok])
    return {t for t, r in scored.items() if r >= min_ratio}, scored


def runs_of(idx):
    """Consecutive index runs, so 'long runs' is a measured shape rather than an impression."""
    if not idx:
        return []
    out, cur = [], [idx[0]]
    for a, b in zip(idx, idx[1:]):
        if b == a + 1:
            cur.append(b)
        else:
            out.append(cur)
            cur = [b]
    out.append(cur)
    return out


def measure(rows, min_count, min_ratio):
    n_given, n_lead = harvest(rows)
    given, scored = lexicon(n_given, n_lead, min_count, min_ratio)

    flagged = [i for i, (_, raw) in enumerate(rows)
               if raw.split() and not is_ditto_lead(raw) and raw.split()[0] in given]
    # The pipeline consequence: does today's code take the given name for a surname?
    taken = sum(1 for i in flagged if surname_token(rows[i][1]))

    # Blast radius. Only the LAST flagged line of a run has ditto followers, so this cannot
    # double-count a run's tail.
    blast, worst = 0, 0
    for i in flagged:
        j, n = i + 1, 0
        while j < len(rows) and is_ditto_lead(rows[j][1]):
            n += 1
            j += 1
        blast += n
        worst = max(worst, n)

    rns = runs_of(flagged)
    bands = {}
    for lo, hi in ((0.0, 0.5), (0.5, 0.9), (0.9, 0.95), (0.95, 1.01)):
        sel = [t for t, r in scored.items() if lo <= r < hi]
        bands[f"{lo:.2f}-{hi:.2f}"] = {
            "types": len(sel),
            "unmarked_lines": sum(n_lead[t] for t in sel),
            "examples": sorted(sel, key=lambda t: -n_lead[t])[:8],
        }

    longest = max(rns, key=len) if rns else []
    return {
        "n_lines": len(rows),
        "n_ditto_lead": sum(1 for _, r in rows if is_ditto_lead(r)),
        "min_count": min_count, "min_ratio": min_ratio,
        "lexicon_size": len(given),
        "n_flagged": len(flagged),
        "n_taken_as_surname_today": taken,
        "share_taken": round(taken / len(flagged), 4) if flagged else None,
        "n_ditto_inheriting_wrong_carry": blast,
        "n_total_wrong_surname": taken + blast,
        "share_of_volume_wrong": round((taken + blast) / len(rows), 4),
        "worst_inherited_run": worst,
        "n_runs": len(rns),
        "longest_run": len(longest),
        "lines_in_runs_ge_3": sum(len(r) for r in rns if len(r) >= 3),
        "ratio_bands": bands,
        "top_flagged_tokens": Counter(rows[i][1].split()[0]
                                      for i in flagged).most_common(20),
        "longest_run_sample": [rows[i][1][:80] for i in longest[:12]],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lines", default="data/1906BPL_lines.jsonl")
    ap.add_argument("--out", default="results/implied_surname_lines_1906BPL.json")
    ap.add_argument("--min-count", type=int, default=MIN_COUNT)
    ap.add_argument("--min-ratio", type=float, default=MIN_RATIO)
    args = ap.parse_args(argv)

    res = measure(load(args.lines), args.min_count, args.min_ratio)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(res, indent=2), encoding="utf-8")

    e = sys.stderr
    print(f"{args.lines}  {res['n_lines']:,} lines "
          f"({res['n_ditto_lead']:,} ditto-lead)", file=e)
    print(f"  given-name lexicon (ratio >= {res['min_ratio']}) "
          f"{res['lexicon_size']:,} types", file=e)
    print(f"  unmarked lines leading with one       {res['n_flagged']:6,}", file=e)
    print(f"  ... read as a NEW SURNAME today       {res['n_taken_as_surname_today']:6,}"
          f"   ({res['share_taken']:.1%})", file=e)
    print(f"  ditto lines inheriting a wrong carry  "
          f"{res['n_ditto_inheriting_wrong_carry']:6,}", file=e)
    print(f"  TOTAL lines with a wrong surname      {res['n_total_wrong_surname']:6,}"
          f"   ({res['share_of_volume_wrong']:.2%} of the volume)", file=e)
    print(f"  runs {res['n_runs']:,}, longest {res['longest_run']}, "
          f"worst inherited run {res['worst_inherited_run']}", file=e)
    print("  ratio bands:", file=e)
    for band, d in res["ratio_bands"].items():
        print(f"    {band}  {d['types']:>4} types  {d['unmarked_lines']:>6,} lines   "
              f"{', '.join(d['examples'][:6])}", file=e)
    print(f"  wrote {args.out}", file=e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
