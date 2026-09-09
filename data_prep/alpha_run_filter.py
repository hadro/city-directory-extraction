#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Cut front matter, display ads and business-directory runs out of a volume's line JSONL by
ALPHABETICAL ORDER rather than by typography.

    python3 data_prep/alpha_run_filter.py --lines data/1906BPL_lines.jsonl        # report only
    python3 data_prep/alpha_run_filter.py --lines data/1906BPL_lines.jsonl --apply
    python3 data_prep/alpha_run_filter.py --self-test

Why this exists
---------------
`ia_volume_to_jsonl.py` filters LINES by shape -- height, width, character class. That cannot
see the failure that actually matters. Fed a page of law-office prose from an 1836 volume's
front matter, `2b-100k` emitted confident fabricated people:

    IN : | 'Shis state, entrusted to their care, will receive prompt
         name: "\" Shis"  address: "entrusted to their care"  home_address: "will receive prompt"

The model never refuses, so every non-entry that survives filtering becomes a fake person in
the output. That makes page-type detection a CORRECTNESS problem, not a cost problem. And no
line-level rule can catch it: "courts of law or equity in" is lowercase, ASCII, normal height,
normal width, sitting on a common left margin. It passes every shape test because it looks
exactly like an entry.

The signal, and why it is free
------------------------------
**A residential listing is sorted; prose, ads and business directories are not.** Take each
leaf's modal line-initial letter and the body of the volume is a monotonic A->Z walk. Anything
off that walk is not part of the alphabetical sequence.

Credit: this was proposed by the `sub-agent-csv-work` session. Independently reproduced here
from 1906BPL's line JSONL (a different derivation than theirs -- they read the hOCR directly):
all 25 letter blocks in correct order, no overlaps, across 1,254 leaves. The gaps between
blocks -- B->C, M->N, S->T -- are exactly the inserted ad and business-directory runs.

It needs no threshold, which is the whole point. `ia_volume_to_jsonl.py`'s `ad_score` was the
obvious alternative and it is blocked on a cutoff nobody has validated against pages a human
has looked at. Ordering has no such knob.

Robustness
----------
The naive longest non-decreasing RUN breaks on one stray OCR letter -- a misread `R` among the
Ks truncates the run there and discards the rest of the volume. The correct primitive is the
longest non-decreasing SUBSEQUENCE, which absorbs isolated noise because it is free to skip a
leaf and continue. Both were implemented; the run version cut 61% of 1906BPL and the
subsequence version cuts what the report below shows. That difference is the whole reason this
note exists.

What this does NOT establish
----------------------------
That every cut leaf is genuinely non-listing. Monotonicity proves the KEPT leaves form a sorted
sequence; it does not prove the dropped ones deserved it. A listing page whose modal letter is
misread drops out and takes real entries with it. So `--apply` is opt-in, the default is a
report, and `--dump-cut` writes a sample from every excised range for eyeballing.

RESOLVED, and recorded because the guess was wrong: 1906BPL's A block really does begin at leaf
9. `sub-agent-csv-work` read the pages -- leaves 9-38 are a sustained A run (share 0.50-0.87,
leaf 30 at 0.87) while leaves 0-8 have no dominant letter at all (all <= 0.33). The earlier
suspicion that leaf 9 was an abbreviations key or ad index was unfounded.

**An ad page can carry a high modal letter, so confidence does NOT mean "listing".** Ad copy is
full of business names, so a page of advertising often has one letter dominating just as a
listing page does -- their B/M/S "second alphabet" clusters (B also 137..162, M also 736..752,
S also 1029..1077) all spot-check as advertising rather than a second alphabetical sequence,
and leaf 130 here is prose at confidence 0.96. This is the deeper reason the confidence floor
below cannot work: the two classes overlap on the axis it measures.
"""
from __future__ import annotations

import argparse
import bisect
import collections
import json
import re
import string
import sys
from pathlib import Path

# A leaf needs at least this many alphabetic line-starts before its modal letter means anything.
# Below it, a plate with three OCR fragments would vote with the same weight as a full page.
MIN_ALPHA_LINES = 15

# Modal-letter agreement a leaf needs before its vote counts. DEFAULT 0.0 = no floor, and the
# measured reason is that a floor does not do what it looks like it should:
#
#   min-conf   cut on 1906BPL          what happens
#   0.0        78 leaves / 15,138 ln   finds the real ad runs (incl. the 8,127-line trade-ad run)
#   0.70        2 leaves /    312 ln   near-inert -- ad pages ABSTAIN instead of being cut, and
#   0.85        2 leaves /    312 ln   abstaining means kept, so the 8,127-line trade-ad run at
#                                      leaves 1218-1251 survives
#
# The floor cannot separate the two things that produce low confidence: an advertising page
# (scattered initials, should be cut) and a heavily-dittoed listing page (few real sort keys,
# must be kept). Raising it protects two leaves and loses the volume's largest genuine cut.
# So the knob is exposed for a conservative pass but is off by default, and `--apply` stays
# opt-in behind reading `--dump-cut`. Separating those two cases properly needs page labels
# that do not exist yet.
MIN_CONFIDENCE = 0.0

# A sortable surname: an ANCHORED capital plus two lowercase. See first_letter() for why each
# half is load-bearing. Credit: sub-agent-csv-work / detect_listing_bounds.py.
_SORT_KEY_RE = re.compile(r"([A-Za-z])[a-z]{2,}")


def first_letter(raw_line: str):
    """The letter a directory entry sorts under, or None if this line cannot cast a vote.

    **A DITTO LINE MUST ABSTAIN, and getting this wrong inverts the filter.** In a dense
    directory a run of entries sharing a surname prints that surname once and dittos the rest:

        Ackerman And'w J foreman h 460 Ralph av
        "        Ann C wid David h 518 Madison
        44       Anna costumes 760 B'way            <- 44 is ABBYY misreading the ditto mark

    A first draft stripped the ditto as leading junk and read the GIVEN name, so a whole page of
    Ackermans voted "A" no matter where it sat in the volume. Leaves 139-143 and 818-822 of
    1906BPL -- 1,724 lines of perfectly good entries -- were cut as out-of-order because of it.
    Ditto marks are pervasive in this corpus (the gold convention has them: `" Julius r 131 Av A`),
    so this is not an edge case.

    The rule is an ANCHORED capital followed by at least two lowercase letters. Anchoring kills
    the ditto (leading punctuation or an OCR digit never matches); the two-lowercase tail kills
    two further classes this volume is full of.

    That tail came from `sub-agent-csv-work`'s `detect_listing_bounds.py` and replaced a bare
    `raw_line[0].isupper()` here. I had claimed their version carried the ditto bug; it never
    did, and on 1906BPL theirs abstains on 4,097 lines mine wrongly counted:

        MAIN OFFICE, 1232 Fulton St.      ALL-CAPS ad banner -> must abstain
        W. E. Murdock, Boston.            initials-first ad copy -> must abstain
        H'y grocer 213 Prince             "Henry" -- a GIVEN name on a ditto entry whose
        Wm elk h 149% Division av         ditto mark the OCR dropped -> must abstain

    Those last two are the same failure as the ditto in a different costume, and they were the
    largest buckets (852 M, 643 W). The apostrophe-surname worry that argued against `{2,}`
    (O'Brien, O'Connor) does not appear in this volume's data at all -- every apostrophe hit was
    an abbreviated given name.
    """
    m = _SORT_KEY_RE.match(raw_line or "")
    return m.group(1).upper() if m else None


def leaf_letters(rows, min_confidence=MIN_CONFIDENCE):
    """{leaf: (modal_letter, confidence, n_alpha)} for leaves whose vote is worth trusting.

    A leaf only gets a vote if enough lines carry a sort key AND those keys agree. Measured on
    1906BPL, modal confidence is what separates a listing page from an interleaved ad page:
    real listing leaves run 0.87-0.92 (a directory page is one or two letters deep), while ad
    and mixed pages scatter across the alphabet at 0.43-0.57.

    Note that VOTER SHARE does not separate them and was tried first: leaf 200 is a genuine
    listing page where only 17% of lines carry a sort key (the rest are dittos), which is a
    LOWER share than the ad page at leaf 26 (28%). Share measures how dittoed a page is;
    confidence measures whether it is alphabetically coherent. Only the second is the question.
    """
    per = collections.defaultdict(list)
    for r in rows:
        ltr = first_letter(r["raw_line"])
        if ltr:
            per[r["context"]["leaf"]].append(ltr)
    out = {}
    for leaf, letters in per.items():
        if len(letters) < MIN_ALPHA_LINES:
            continue
        top, n = collections.Counter(letters).most_common(1)[0]
        conf = n / len(letters)
        if conf < min_confidence:            # incoherent -> abstain, do NOT cut
            continue
        out[leaf] = (top, conf, len(letters))
    return out


def longest_nondecreasing(seq):
    """Indices of a longest non-decreasing subsequence of `seq`. O(n log n).

    Subsequence, NOT run: a single misread letter in the middle of a sorted volume must cost one
    leaf, not the entire remainder. `bisect_right` is what makes it non-DEcreasing rather than
    strictly increasing -- a volume has many consecutive leaves under the same letter, and
    `bisect_left` would keep only one of them and discard the rest of the B's as out of order.
    """
    if not seq:
        return []
    tails, tail_idx, prev = [], [], [-1] * len(seq)
    for i, v in enumerate(seq):
        j = bisect.bisect_right(tails, v)
        if j == len(tails):
            tails.append(v)
            tail_idx.append(i)
        else:
            tails[j] = v
            tail_idx[j] = i
        prev[i] = tail_idx[j - 1] if j else -1
    out, k = [], tail_idx[-1]
    while k != -1:
        out.append(k)
        k = prev[k]
    return out[::-1]


def alpha_body(letters):
    """(kept_leaves:set, ordered [(leaf, letter)]) -- the leaves on the volume's A->Z walk."""
    ordered = sorted(letters.items())
    seq = [string.ascii_uppercase.index(v[0]) for _, v in ordered]
    keep_idx = longest_nondecreasing(seq)
    kept = {ordered[i][0] for i in keep_idx}
    return kept, [(ordered[i][0], ordered[i][1][0]) for i in keep_idx]


def cut_ranges(all_leaves, kept):
    """Contiguous runs of excluded leaves, as (start, end)."""
    out, run = [], []
    for leaf in sorted(all_leaves):
        if leaf in kept:
            if run:
                out.append((run[0], run[-1]))
                run = []
        else:
            run.append(leaf)
    if run:
        out.append((run[0], run[-1]))
    return out


def _self_test() -> int:
    assert first_letter("Kramer Aaron furs 56 Bond") == "K"
    assert first_letter("MacDonald John grocer") == "M"
    # every ditto form in this corpus must ABSTAIN, not vote its given name
    for ditto in ('" Julius r 131 Av A', "44 Geo cigars 611 Hart", "“ Anna wid Louis h 622 Marcy",
                  "*' A grocer 989 Myrtle av", "| 'Shis state, entrusted to their", ""):
        assert first_letter(ditto) is None, ditto
    # a dropped ditto leaves an abbreviated GIVEN name behind -- same failure, no punctuation
    for given in ("H'y grocer 213 Prince", "Wm elk h 149% Division av"):
        assert first_letter(given) is None, given
    # ALL-CAPS banners and initials-first ad copy carry no sort key either
    for ad in ("MAIN OFFICE, 1232 Fulton St.", "W. E. Murdock, Boston.", "ALL CAPS HEADING"):
        assert first_letter(ad) is None, ad

    # non-decreasing keeps every repeat of a letter; a lone spike costs one leaf, not the tail
    assert longest_nondecreasing([0, 0, 1, 1, 2]) == [0, 1, 2, 3, 4]
    got = longest_nondecreasing([0, 1, 17, 2, 3, 4])
    assert got == [0, 1, 3, 4, 5], got                          # the stray 17 is skipped
    assert longest_nondecreasing([]) == []

    # a run-based implementation would stop dead at the spike; this must not
    rows = []
    for leaf, ltr in [(1, "A"), (2, "B"), (3, "R"), (4, "C"), (5, "D")]:
        rows += [{"raw_line": f"{ltr}name {i} street", "context": {"leaf": leaf}}
                 for i in range(MIN_ALPHA_LINES)]
    letters = leaf_letters(rows)
    kept, walk = alpha_body(letters)
    assert kept == {1, 2, 4, 5}, kept
    assert cut_ranges(letters, kept) == [(3, 3)], cut_ranges(letters, kept)

    # a leaf with too few alphabetic starts abstains rather than voting
    thin = [{"raw_line": "Q x", "context": {"leaf": 9}}] * 3
    assert 9 not in leaf_letters(thin)
    print("self-test OK", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lines", help="a *_lines.jsonl from ia_volume_to_jsonl.py")
    ap.add_argument("--out", default=None, help="filtered JSONL (default <input>.alpha.jsonl)")
    ap.add_argument("--apply", action="store_true",
                    help="actually write the filtered file; without it this only reports")
    ap.add_argument("--dump-cut", default=None,
                    help="write sample lines from every excised range. READ THIS before --apply.")
    ap.add_argument("--min-confidence", type=float, default=MIN_CONFIDENCE,
                    help="modal-letter agreement a leaf needs before its vote counts "
                         f"(default {MIN_CONFIDENCE}); below it the leaf abstains and is KEPT")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)

    if a.self_test:
        return _self_test()
    if not a.lines:
        ap.error("--lines is required (or use --self-test)")

    rows = [json.loads(l) for l in open(a.lines, encoding="utf-8")]
    letters = leaf_letters(rows, a.min_confidence)
    kept, walk = alpha_body(letters)
    cuts = cut_ranges(letters, kept)

    all_leaves = {r["context"]["leaf"] for r in rows}
    scored = len(letters)
    unscored = len(all_leaves) - scored
    keep_rows = [r for r in rows
                 if r["context"]["leaf"] in kept or r["context"]["leaf"] not in letters]
    cut_rows = len(rows) - len(keep_rows)

    print(f"{a.lines}", file=sys.stderr)
    print(f"  {len(rows):,} lines over {len(all_leaves):,} leaves "
          f"({scored:,} leaves scored, {unscored:,} too thin to vote -- kept by default)",
          file=sys.stderr)
    print(f"  alphabetical walk: {len(kept):,} leaves, "
          f"{walk[0][1] if walk else '?'} -> {walk[-1][1] if walk else '?'}", file=sys.stderr)
    print(f"  would cut {len(cuts)} ranges / {scored - len(kept):,} leaves / "
          f"{cut_rows:,} lines ({100 * cut_rows / max(len(rows), 1):.1f}%)", file=sys.stderr)
    for s, e in sorted(cuts, key=lambda se: se[0] - se[1])[:12]:
        n = sum(1 for r in rows if s <= r["context"]["leaf"] <= e)
        print(f"      leaves {s:>5}-{e:<5} {e - s + 1:>4} leaves  {n:>6,} lines", file=sys.stderr)

    if a.dump_cut:
        with open(a.dump_cut, "w", encoding="utf-8") as fh:
            for s, e in cuts:
                fh.write(f"\n===== CUT leaves {s}-{e} =====\n")
                sample = [r for r in rows if s <= r["context"]["leaf"] <= e][:12]
                for r in sample:
                    fh.write(f"  {r['context']['leaf']}\t{r['raw_line']}\n")
        print(f"  samples from every cut range -> {a.dump_cut}", file=sys.stderr)

    if a.apply:
        out = Path(a.out) if a.out else Path(str(a.lines).replace(".jsonl", "") + ".alpha.jsonl")
        with open(out, "w", encoding="utf-8") as fh:
            for r in keep_rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"  wrote {len(keep_rows):,} lines -> {out}", file=sys.stderr)
    else:
        print("  (report only -- pass --apply to write, after reading --dump-cut)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
