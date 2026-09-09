#!/usr/bin/env python3
"""Find where a volume's residential listing starts and ends, from the hOCR alone.

Why this exists: ia_volume_to_jsonl.py sweeps every leaf with enough text, so front matter,
display advertising and the business/street directories get swept as if they were entries. The
model does not refuse them -- fed a page of prose it emits confident fake person records -- so the
junk lands in the output looking exactly like data. `start_page`/`end_page` in
master_directories.csv are the fields for this and are blank for 291 of 291 IA rows.

The signal is free and already local. A residential listing is *alphabetically sorted*; front
matter, ads and prose are not. So per leaf take the modal first letter of each line's first word,
keep the leaves where one letter dominates, and the listing is the stretch where those letters run
A -> Z. This is ordering, not typography, which is the point: it needs no tuned threshold on font
size or column width, and prose pages fall outside the run by construction rather than by scoring.

Measured on the cached 1906BPL (1,254 leaves): all 25 letter blocks land in correct A->Z order,
zero violations, listing at leaves 9..1215 (X absent, as expected for surnames).

Ad runs surface two ways, and BOTH are reported rather than absorbed:

  * as gaps between letter blocks -- leaves inside the listing's span belonging to no letter.
    The three largest in 1906BPL (M->N 88 leaves, S->T 58, B->C 39) were spot-checked and are
    display advertising.
  * as a second cluster of an already-placed letter. Counterintuitive but measured: ad copy is
    full of business names, so a page of ads can carry a dominant letter of its own (leaf 145,
    inside B's second cluster, is a full-page bath-house and trust-company spread). These are
    printed as AMBIGUOUS and never merged into the letter's block.

Interior ad pages are a harder problem and this tool does NOT solve them. Measured on 1906BPL:
genuine listing leaf 13 carries a sort key on 34% of its lines; ad leaf 819 carries one on 38%.
The ad page scores HIGHER. So no threshold on modal share separates them at leaf granularity,
and --interior drop buys precision (384 ad leaves excluded instead of 199) by also dropping ~172
genuine listing leaves. Default is `keep`, because contiguous spans are what start_page/end_page
mean; take the precision cut knowingly or, better, cut interior ads at LINE level instead --
data_prep/alpha_run_filter.py does that, and the two compose.

Credit where due: the ditto-vote defect and the two negative results below were found by the
parallel session that wrote alpha_run_filter.py, and re-measured here.

Two things that look like they should work and do not:

  * a confidence floor. Modal confidence does separate listing (0.87-0.92) from ads (0.43-0.57),
    but a floor makes an ad page ABSTAIN, and abstaining means kept.
  * voter share, as above -- ad pages can out-score listing pages.

Ditto marks are the trap in the sort key itself. A run of entries sharing a surname prints it
once and dittos the rest, and ABBYY reads the ditto as `44`:

    Ackerman And'w J foreman h 460 Ralph av
    "        Ann C wid David h 518 Madison
    44       Anna costumes 760 B'way

Voting the first *word* would score those given names and read a clean listing page as
out-of-order. FIRST_WORD_RE is anchored and demands a leading letter, so `"`, `44` and `do.` all
abstain -- verified against these exact lines.

    python3 data_prep/detect_listing_bounds.py --ident 1906BPL
    python3 data_prep/detect_listing_bounds.py --ident 1906BPL --json bounds.json
    python3 data_prep/detect_listing_bounds.py --ident 1906BPL --verbose   # per-leaf letters

Two things it deliberately does NOT do. It reports leaves, not printed pages: `start_page` is a
printed number, `--leaves` takes leaf indices, and `page_offset` is filled for 9% of IA rows and
is known to drift within a volume (1884BPL: +54 at p.402 -> +82 at p.984), so converting here
would invent precision. And it never silently picks between two candidate boundaries -- an
ambiguous edge is printed as AMBIGUOUS for a human or a cheap subagent to settle with one page
read.
"""

import argparse
import collections
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from ia_volume_to_jsonl import Item, hocr_lines          # noqa: E402

REPO = HERE.parent
LETTERS = [chr(c) for c in range(ord("A"), ord("Z") + 1)]

# A word-shaped leading token: at least 3 letters, so page numbers, initials and stray marks
# do not vote. The surname is the first word of a directory entry, which is what carries the sort.
FIRST_WORD_RE = re.compile(r"([A-Za-z])[a-z]{2,}")


def leaf_letters(item, idx, min_chars, min_lines):
    """-> {leaf: (modal_letter, share, n_lines)} for every leaf with enough text."""
    out = {}
    for leaf in range(len(idx)):
        if idx[leaf][1] - idx[leaf][0] < min_chars:
            continue
        markup = item.hocr_page(leaf)
        if not markup:
            continue
        firsts = []
        for _box, text in hocr_lines(markup):
            m = FIRST_WORD_RE.match(text.strip())
            if m:
                firsts.append(m.group(1).upper())
        if len(firsts) < min_lines:
            continue
        counts = collections.Counter(firsts)
        letter, n = counts.most_common(1)[0]
        out[leaf] = (letter, n / len(firsts), len(firsts))
    return out


def clusters(leaves, gap):
    """Split a sorted leaf list into runs, breaking where the gap exceeds `gap`."""
    if not leaves:
        return []
    runs, cur = [], [leaves[0]]
    for a, b in zip(leaves, leaves[1:]):
        if b - a <= gap:
            cur.append(b)
        else:
            runs.append(cur)
            cur = [b]
    runs.append(cur)
    return runs


def blocks(letters, min_share, gap):
    """-> {letter: {"span": (lo, hi), "n": k, "alts": [(lo, hi, k), ...]}}

    `alts` are the letter's other clusters. A letter with a second cluster nearly as big as the
    first is the ambiguous case: usually a street or business directory repeating the alphabet.
    """
    strong = collections.defaultdict(list)
    for leaf, (letter, share, _n) in sorted(letters.items()):
        if share >= min_share:
            strong[letter].append(leaf)

    out = {}
    for letter, leaves in strong.items():
        runs = sorted(clusters(leaves, gap), key=len, reverse=True)
        best = runs[0]
        # Keep the member leaves, not just the span. A letter's block routinely has ad pages
        # sitting INSIDE it (1906BPL leaf 819 is a trust-company spread between two O leaves),
        # and filling the span back in would sweep exactly what this tool exists to exclude.
        out[letter] = {"span": (best[0], best[-1]), "n": len(best), "leaves": best,
                       "alts": [(r[0], r[-1], len(r)) for r in runs[1:] if len(r) >= 3]}
    return out


def analyse(block_map):
    """-> (start, end, ordered_letters, violations, gaps). Pure bookkeeping over the blocks."""
    present = [L for L in LETTERS if L in block_map]
    if not present:
        return None, None, [], [], []

    violations = []
    for a, b in zip(present, present[1:]):
        if block_map[b]["span"][0] < block_map[a]["span"][0]:
            violations.append((a, b))

    gaps = []
    for a, b in zip(present, present[1:]):
        lo, hi = block_map[a]["span"][1], block_map[b]["span"][0]
        if hi - lo > 1:
            gaps.append((a, b, lo + 1, hi - 1, hi - lo - 1))

    return block_map[present[0]]["span"][0], block_map[present[-1]]["span"][1], present, violations, gaps


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ident", required=True, help="IA identifier")
    ap.add_argument("--cache", default=str(REPO / "data" / "ia_cache"))
    ap.add_argument("--min-chars", type=int, default=400,
                    help="skip leaves whose pageindex census is below this")
    ap.add_argument("--min-lines", type=int, default=5,
                    help="skip leaves with fewer word-shaped lines than this")
    ap.add_argument("--min-share", type=float, default=0.40,
                    help="a leaf 'belongs' to a letter when it starts this fraction of its lines")
    ap.add_argument("--gap", type=int, default=6,
                    help="leaves of slack inside one letter's block (ad pages, plates)")
    ap.add_argument("--json", default=None, help="write the result as JSON")
    ap.add_argument("--interior", choices=["keep", "drop"], default="keep",
                    help="leaves that sit INSIDE a letter block but did not vote for it. "
                         "keep (default) = contiguous spans, which is what start_page/end_page "
                         "mean. drop = only the leaves that voted, which excludes interior ad "
                         "pages but also drops genuine listing pages -- see the module docstring; "
                         "modal share does not separate the two.")
    ap.add_argument("--emit-leaves", action="store_true",
                    help="print ONLY the kept leaves as a comma list on stdout, for "
                         "ia_volume_to_jsonl.py --leaves. Excludes the interior ad runs, which "
                         "a plain start-end range would sweep.")
    ap.add_argument("--verbose", action="store_true", help="print the per-leaf modal letters")
    args = ap.parse_args(argv)

    item = Item(args.ident, Path(args.cache))
    idx = item.index
    print(f"{args.ident}: {len(idx)} leaves", file=sys.stderr)

    letters = leaf_letters(item, idx, args.min_chars, args.min_lines)
    print(f"  {len(letters)} leaves with a readable modal letter", file=sys.stderr)
    if args.verbose:
        for leaf, (L, share, n) in sorted(letters.items()):
            print(f"    {leaf:5d}  {L}  {share:.2f}  ({n} lines)", file=sys.stderr)

    block_map = blocks(letters, args.min_share, args.gap)
    start, end, present, violations, gaps = analyse(block_map)
    if start is None:
        print("no alphabetical structure found -- not a sorted listing, or the OCR is too poor",
              file=sys.stderr)
        return 1

    if args.interior == "drop":
        kept = sorted({leaf for L in present for leaf in block_map[L]["leaves"]})
    else:
        kept = sorted({leaf for L in present
                       for leaf in range(block_map[L]["span"][0], block_map[L]["span"][1] + 1)})
    if args.emit_leaves:
        print(",".join(str(x) for x in kept))
        return 0

    print(f"\nletter   leaves        n   note")
    for L in present:
        b = block_map[L]
        alts = "  AMBIGUOUS: also " + ", ".join(f"{lo}..{hi} ({k})" for lo, hi, k in b["alts"]) \
            if b["alts"] else ""
        print(f"  {L}   {b['span'][0]:5d}..{b['span'][1]:<5d} {b['n']:4d}{alts}")

    missing = [L for L in LETTERS if L not in block_map]
    print(f"\nlisting: leaves {start}..{end}  ({len(present)}/26 letters"
          + (f", missing {''.join(missing)}" if missing else "") + ")")

    if violations:
        print("\nORDER VIOLATIONS -- these letters start before the letter that precedes them.")
        print("The volume may hold two interleaved alphabets (residential + business), or the")
        print("blocks are mis-detected. Do not trust the bounds until this is explained:")
        for a, b in violations:
            print(f"  {b} starts at {block_map[b]['span'][0]}, before {a} at "
                  f"{block_map[a]['span'][0]}")

    if gaps:
        print(f"\nGAPS between letter blocks ({len(gaps)}) -- candidate ad runs or inserted")
        print("sections. These leaves sit inside the listing's span but belong to no letter:")
        for a, b, lo, hi, n in sorted(gaps, key=lambda g: -g[4]):
            print(f"  {a}->{b}   leaves {lo}..{hi}   ({n} leaves)")

    ambiguous = [L for L in present if block_map[L]["alts"]]
    if ambiguous:
        print(f"\nAMBIGUOUS EDGES ({len(ambiguous)}) -- letters with a second sizable cluster,")
        print("usually a street or business directory repeating the alphabet. One page read")
        print("settles each; this tool will not guess between them.")

    swept = end - start + 1
    dropped = swept - len(kept)
    what = ("leaves excluded -- ad runs BETWEEN letter blocks"
            if args.interior == "keep" else
            "leaves excluded -- ad runs plus every non-voting leaf inside a block, so this "
            "number includes genuine listing pages")
    print(f"\n{len(kept)} leaves in the letter blocks, vs {swept} in a plain {start}-{end} range: "
          f"{dropped} {what} ({100 * dropped // swept}%).")

    result = {"ident": args.ident, "leaves": len(idx), "start_leaf": start, "end_leaf": end,
              "kept_leaves": len(kept),
              "letters_present": present, "missing_letters": missing,
              "blocks": {L: {"start_leaf": b["span"][0], "end_leaf": b["span"][1],
                             "leaves": b["n"], "alternates": b["alts"]}
                         for L, b in block_map.items()},
              "order_violations": violations,
              "gaps": [{"between": [a, b], "start_leaf": lo, "end_leaf": hi, "leaves": n}
                       for a, b, lo, hi, n in gaps],
              "ambiguous_letters": ambiguous,
              "params": {"min_chars": args.min_chars, "min_lines": args.min_lines,
                         "min_share": args.min_share, "gap": args.gap}}
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=1), encoding="utf-8")
        print(f"\nwrote {args.json}")
    print(f"\nsweep just the listing:\n"
          f"  python3 data_prep/ia_volume_to_jsonl.py --ident {args.ident} "
          f"--leaves {start}-{end}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
