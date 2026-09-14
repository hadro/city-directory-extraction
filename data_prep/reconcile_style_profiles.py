#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Do the style cards and the pipeline agree about a volume's ditto convention?

    python3 data_prep/reconcile_style_profiles.py data/*_lines.jsonl
    python3 data_prep/reconcile_style_profiles.py --self-test        # offline

Two INDEPENDENT derivations of the same fact exist in this repo and have never been compared:

  * `data_prep/style_profiles/*.md` + `style_profiles.json` -- a human read the actual printed
    page during visual sampling (sessions 1-4, 2026-06/19-21) and wrote down `markers.ditto`.
  * `ia_volume_to_jsonl.ditto_lead_candidates` -- the ingest infers it at run time from the
    frequency and name-follower ratio of mark-shaped leading tokens, deliberately knowing nothing
    about the publisher.

When two independent derivations disagree, one of them is wrong and you want to know which. This
prints the disagreements. It CHANGES NOTHING -- it is an instrument, like `--dump-dropped` and
`FIGURE_AUDIT.md`, and exists because this project's recurring failure is trusting a number
without building the thing that could contradict it.

WHY THE CARDS ARE NOT WIRED INTO THE FILTERS, and should not be
---------------------------------------------------------------
Tempting and wrong. The ingest's rules are self-calibrating against each page's own distribution,
which is what lets ONE setting span an 1786 single-column folio and a 1933 six-column Polk
(`page_geometry`, `leaf_bands`, `body_width`). A card is per publisher x era, a specific volume can
depart from its family, and 17 cards cover 449 catalog rows. `leaf_bands` reading "the volume's OWN
admitted ditto set, never a hard-coded glyph" is a deliberate stance.

What the cards ARE good for is exactly this: an outside check on what the self-calibration decided,
and a PRECONDITION for opt-in rules. `--deep-indent-gate` is the live example -- it is safe on
1906BPL and destroys real wraps on 1856BPL, and the distinguishing fact is not a threshold but
whether the volume has a ditto convention at all. Smith 1856 has none, so a shallow indent there is
always a real wrap. The card says the same thing without needing to run anything.

VERDICTS
--------
  agree            card and run name the same mark (or both say "no ditto")
  run-only         card records no ditto, the run admitted one -- card gap, or a false admission
  card-only        card records a mark the run did NOT admit -- the valuable one: either an OCR
                   corruption the run saw under another spelling (check `also admitted`), or a
                   genuine blind spot
  UNREPRESENTABLE  the card's mark cannot match `DITTO_SHAPE` at any frequency, so the ingest is
                   structurally blind to it and it never even reaches the review queue. Known:
                   Longworth (`do.`) and Boyd (`do`) print a WORD ditto. Measured on the cached
                   1798 Longworth, `do`-variants lead 7 of 13,280 lines (0.05%), so the gap is real
                   but currently unexercised -- do NOT widen DITTO_SHAPE until a volume that
                   actually uses it is in hand.
  no card          no profile matches this publisher x year. The common case: 9 profiles in the
                   JSON, 17 markdown cards, 449 catalog rows.

Reads the ORIGINAL pre-normalization text, reconstructing it from `context.raw_line_original`
where the ingest rewrote a line, so it reproduces the run's own decision rather than re-deriving
from an already-normalized file.

WHAT THE FIRST RUN FOUND (2026-09-13, 5 volumes, results/reconcile_style_profiles.json)
---------------------------------------------------------------------------------------
    1906BPL      upington    205,590   card '"'    run '"' '**' '44' '“'       agree
    1856BPL      smith        61,439   -           run (none)                  no card
    trow1915     trow      1,484,446   card '—'    run ',,' '..' '11' '„'      card-only
    longworth98  longworth    12,002   card 'do.'  run (none)                  UNREPRESENTABLE
    micro13      trow          2,889   -           run (none)                  no card

**1906BPL agrees, and that is the load-bearing result**, because it is the volume every published
figure rests on: a human reading the page and a frequency inference that knows nothing about the
publisher name the same mark. `44` is ABBYY's misreading of that `"`, which the card is what tells
you -- the run can only report 42% frequency, not what the glyph IS.

**Trow disagreed, and the card was over-generalized rather than wrong.** Its `—` and its glued
`-Michl` form were observed on the 1890s volume it sampled. On Trow 1915 the ditto is a SEPARATE
token in a low-double-quote family (`,,` `..` `„` `11` `.1` `,1`); a leading em-dash leads 97 of
1.48M lines, all advertising. The defect is the card's `year_range` [1859, 1922] projecting one
volume across 63 years. This also falsified a claim in `normalize_ditto_lead`'s docstring that "a
Trow volume gets no benefit from this" -- 1915 got 128,911 lines (8.7%) normalized.

**And it exposed a real mechanism: the ditto convention FRAGMENTS across OCR variants, and each
variant is gated independently.** On 1906BPL the dominant reading `44` is 41.5% and sails through.
On Trow the same printed mark scatters six ways and only four clear their floors; `.1` (0.72% of
lines, 98% name-followed) and `,1` (0.24%, 99%) miss the 5% DIGIT gate solely because they contain
a digit. `--ditto-marks .1,,1` recovers 21,289 lines. A per-variant gate is the wrong shape for a
convention that OCR shatters -- but fixing it means summing variants that are the same mark, which
needs a volume where that grouping can be checked, not a guess.

**`micro_IABROOKLYN_0013` is tagged `publisher=trow` and is an 1836/37 Brooklyn volume.** That is
`tag_publisher`'s documented fallback for an out-of-vocabulary publisher, and it matched no card
here only because the YEAR missed. A fallback tag plus a wide-enough `year_range` would have
compared a volume against a card for a publisher it has nothing to do with. Match on the CATALOG
publisher, never the trained tag, if this is ever wired into anything that decides.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROFILES = REPO / "data_prep" / "style_profiles" / "style_profiles.json"
sys.path.insert(0, str(REPO / "data_prep"))

from ia_volume_to_jsonl import (DITTO_SHAPE, ditto_lead_candidates,  # noqa: E402
                                _TAG_ALIASES)


def publisher_token(display: str) -> str:
    """'Upington (George Upington)' -> 'upington'. The cards spell it for humans."""
    raw = (display or "").strip().lower()
    first = re.split(r"[\s(/&,]+", raw)[0] if raw else ""
    first = re.sub(r"['’]s$|s['’]$|['’]$", "", first)
    return _TAG_ALIASES.get(first, first)


def load_profiles(path: Path = PROFILES):
    """{publisher_token: [(year_lo, year_hi, profile_key, ditto_marker)]}"""
    if not path.exists():
        return {}
    profiles = json.loads(path.read_text(encoding="utf-8")).get("profiles", {})
    out = {}
    for key, p in profiles.items():
        lo, hi = (p.get("year_range") or [0, 9999])[:2]
        tok = publisher_token(p.get("publisher", ""))
        out.setdefault(tok, []).append((lo, hi, key, (p.get("markers") or {}).get("ditto")))
    return out


def match_profile(index, publisher: str, year):
    """The card covering this publisher x year, or None. Year must fall in the card's range."""
    try:
        y = int(str(year)[:4])
    except (TypeError, ValueError):
        y = None
    cands = index.get((publisher or "").strip().lower(), [])
    for lo, hi, key, ditto in cands:
        if y is not None and lo <= y <= hi:
            return key, ditto
    return None


def originals(path: Path):
    """(pre-normalization lines, publisher, year) from an ingest JSONL.

    `raw_line` is what the model was fed; `context.raw_line_original` is stored ONLY when the
    ingest changed something. Preferring the latter reconstructs exactly what
    `ditto_lead_candidates` saw, so this reproduces the run's decision instead of re-deriving it
    from text the run already rewrote.
    """
    lines, pub, year = [], "", ""
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            if not raw.strip():
                continue
            row = json.loads(raw)
            ctx = row.get("context") or {}
            pub = pub or (ctx.get("publisher") or "")
            year = year or (ctx.get("directory_year") or "")
            lines.append(ctx.get("raw_line_original") or row.get("raw_line") or "")
    return lines, pub, year


def verdict(card_ditto, admitted):
    """(verdict, note) comparing one card's marker against what the run admitted."""
    card = (card_ditto or "").strip()
    if not card:
        return ("agree" if not admitted else "run-only",
                "card records no ditto" if not admitted else
                "card records NO ditto but the run admitted one")
    if not DITTO_SHAPE.match(card):
        return ("UNREPRESENTABLE",
                f"{card!r} is a WORD ditto -- DITTO_SHAPE cannot match it at any frequency, so the "
                f"ingest is structurally blind and it never reaches the review queue")
    if card in admitted:
        return "agree", f"both name {card!r}"
    if admitted:
        return ("card-only",
                f"card says {card!r}; the run admitted {sorted(admitted)} instead -- is one an OCR "
                f"reading of {card!r}?")
    return "card-only", f"card says {card!r}; the run admitted NOTHING"


def report(paths, out_fh=sys.stdout):
    index = load_profiles()
    rows = []
    for p in paths:
        lines, pub, year = originals(Path(p))
        admitted, review, stats, n = ditto_lead_candidates(lines)
        m = match_profile(index, pub, year)
        if m is None:
            v, note, card = "no card", f"no profile covers {pub!r} x {year}", None
        else:
            card_key, card = m
            v, note = verdict(card, admitted)
            note = f"[{card_key}] {note}"
        rows.append({"file": Path(p).name, "publisher": pub, "year": year, "lines": n,
                     "card_ditto": card, "admitted": sorted(admitted),
                     "top_review": sorted(review.items(), key=lambda kv: -kv[1][0])[:4],
                     "verdict": v, "note": note})

    w = max([len(r["file"]) for r in rows] + [18])
    print(f"{'volume':<{w}}  {'publisher':<11} {'lines':>9}  {'card':<8} {'run admitted':<26} verdict",
          file=out_fh)
    print("-" * (w + 78), file=out_fh)
    for r in rows:
        adm = ", ".join(repr(a) for a in r["admitted"]) or "(none)"
        print(f"{r['file']:<{w}}  {r['publisher'][:11]:<11} {r['lines']:>9,}  "
              f"{repr(r['card_ditto'])[:8] if r['card_ditto'] is not None else '-':<8} "
              f"{adm[:26]:<26} {r['verdict']}", file=out_fh)
    print(file=out_fh)
    for r in rows:
        if r["verdict"] == "agree":
            continue
        print(f"  {r['file']} — {r['verdict'].upper()}\n      {r['note']}", file=out_fh)
        if r["top_review"]:
            q = ", ".join(f"{t!r} {c:,} ({s:.2%}/{f:.0%})" for t, (c, s, f) in r["top_review"])
            print(f"      nearest misses in the review queue: {q}", file=out_fh)
    return rows


def _self_test() -> int:
    assert publisher_token("Upington (George Upington)") == "upington"
    assert publisher_token("Trow") == "trow"
    assert publisher_token("Hearne's") == "hearne"
    assert publisher_token("") == ""

    idx = {"upington": [(1902, 1912, "upington_brooklyn_1900s", '"')],
           "smith": [(1850, 1860, "smith_card", None)]}
    assert match_profile(idx, "upington", "1906")[1] == '"'
    assert match_profile(idx, "upington", 1899) is None, "year outside the card's range must miss"
    assert match_profile(idx, "nobody", "1906") is None

    # the four verdicts that matter, each anchored on a real volume from this repo
    assert verdict('"', {'"', "44"})[0] == "agree"            # upington / 1906BPL
    assert verdict(None, set())[0] == "agree"                 # hearne 1850s / 1856BPL: no ditto
    assert verdict(None, {"44"})[0] == "run-only"
    assert verdict("—", {",,", "11"})[0] == "card-only"       # trow: card vs OCR readings
    assert verdict("—", set())[0] == "card-only"
    # Longworth/Boyd print a WORD ditto, which DITTO_SHAPE can never match
    assert verdict("do.", set())[0] == "UNREPRESENTABLE"
    assert verdict("do", {"44"})[0] == "UNREPRESENTABLE"
    assert not DITTO_SHAPE.match("do.") and DITTO_SHAPE.match("—")

    print("self-test OK", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("lines", nargs="*", help="ingest JSONL files (data/*_lines.jsonl)")
    ap.add_argument("--json", default=None, help="also write the rows here")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()
    if not args.lines:
        ap.error("give at least one data/*_lines.jsonl (or --self-test)")
    rows = report(args.lines)
    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nwrote {args.json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
