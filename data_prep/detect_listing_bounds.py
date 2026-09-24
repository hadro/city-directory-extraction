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

A volume is NOT one A->Z run, and since 2026-09-22 it is not modelled as one. `alphabets()`
segments the voting leaves into ascending alphabets (a Viterbi with a restart cost), and the
largest is the listing. That handles the three shapes the single-run model got wrong across the
184-volume corpus -- a PART covering a stretch of the alphabet (Trow p1 = A..H), stray leaves,
and two alphabets in one binding (1856BPL's two districts) -- and it reports every alphabet as a
section. See `alphabets`, `trim_edges` and `merge_interludes` for the measured cases each one
exists for. The segmented bounds are reproduced from the word dumps of survey_harvest.py with
`--from-dump`, identical to reading the hOCR.

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
import gzip
import json
import re
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from ia_volume_to_jsonl import Item, hocr_lines, words_to_lines   # noqa: E402

REPO = HERE.parent
LETTERS = [chr(c) for c in range(ord("A"), ord("Z") + 1)]

# A word-shaped leading token: at least 3 letters, so page numbers, initials and stray marks do
# not vote. The surname is the first word of a directory entry, which is what carries the sort.
#
# The alternation admits O'Brien / D'Ambra while still abstaining on H'y and W'm. That is not a
# special case, it is the same rule: a surname capitalises after the apostrophe, an abbreviated
# GIVEN name does not, and the abbreviated given names are the ditto failure in disguise --
# they appear where OCR dropped the ditto mark, so voting them would score the wrong column.
# BOTH apostrophe characters, because this corpus is 4:1 CURLY: of 55 apostrophe-surname lines in
# 1906BPL, 44 use ’ and 11 use '. A straight-only class catches 20% of them and looks like it
# works, because the obvious test cases (O'Brien, D'Ambra) are the ones a person types straight.
FIRST_WORD_RE = re.compile(r"([A-Za-z])(?:[a-z]{2,}|['’][A-Z][a-z])")


def leaf_letters_from_jsonl(path, min_lines):
    """Same signal, read from an already-built *_lines.jsonl instead of the hOCR.

    Cheaper when the file exists, and usually cleaner. ia_volume_to_jsonl.py has already fetched
    and parsed the hOCR, so re-doing it here is pure waste -- and its text/geometry filters have
    already dropped the ALL-CAPS banners and display type that would otherwise vote.

    Measured on 1906BPL: 199,012 lines over 1,237 leaves in 0.8 s, no network, reproducing the
    hOCR bounds exactly (leaves 9..1215, 25/26 letters, zero violations) with fewer spurious gaps
    (6 vs 10) because the banners never got a vote.

    The two sources are NOT guaranteed identical, and on the thin tier they are not. On
    micro_IABROOKLYN_0013 (tesseract-on-microfilm, ~100 content leaves) the JSONL reads the start
    as leaf 14 against the hOCR's 18, and swaps which sparse letters clear the threshold. With so
    few lines per leaf, dropping a handful moves the modal share across the line either way.
    Prefer this path, but on a thin volume check the other before trusting a boundary.

    Superseded for the corpus survey (2026-09-22). Run over all 184 IA volumes, the two sources
    agreed within 2 leaves on 167; on every disagreement opened by eye (1897BPL, where this path
    stopped the listing at leaf 1002 in the middle of M; micro_IABROOKLYN_0037 and _0042;
    trowsgeneraldire19142trow) the hOCR path was the closer. survey_derive.py therefore reads
    the word dump (`leaf_letters_from_dump`) and keeps this path as a cross-check only.
    """
    votes = collections.defaultdict(list)
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            m = FIRST_WORD_RE.match(row.get("raw_line", "").strip())
            if m:
                votes[row.get("context", {}).get("leaf")].append(m.group(1).upper())

    return {leaf: m for leaf, seen in votes.items()
            if leaf is not None and (m := modal(seen, min_lines))}


def modal(firsts, min_lines):
    """(modal_letter, share, n_lines) over a leaf's sort keys, or None below `min_lines`."""
    if len(firsts) < min_lines:
        return None
    letter, n = collections.Counter(firsts).most_common(1)[0]
    return letter, n / len(firsts), len(firsts)


def sort_keys(texts):
    out = []
    for text in texts:
        m = FIRST_WORD_RE.match(text.strip())
        if m:
            out.append(m.group(1).upper())
    return out


def leaf_letters_from_dump(path, min_chars, min_lines):
    """Same signal, from a survey_harvest.py word dump (data/survey_ocr/<id>_words.jsonl.gz).

    This IS the hOCR path, not an approximation of it: the dump records every hOCR word, and
    `words_to_lines` is exactly what `hocr_lines` returns, so the result is identical to reading
    the hOCR -- with no network and no 21.7 GB cache. The min_chars gate reads the same pageindex
    census, stored in each dump record as `chars`.
    """
    out = {}
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            if rec["chars"] < min_chars or not rec["lines"]:
                continue
            m = modal(sort_keys(t for _b, t in words_to_lines(rec["lines"])), min_lines)
            if m:
                out[rec["leaf"]] = m
    return out


def leaf_letters(item, idx, min_chars, min_lines):
    """-> {leaf: (modal_letter, share, n_lines)} for every leaf with enough text."""
    out = {}
    for leaf in range(len(idx)):
        if idx[leaf][1] - idx[leaf][0] < min_chars:
            continue
        markup = item.hocr_page(leaf)
        if not markup:
            continue
        m = modal(sort_keys(t for _b, t in hocr_lines(markup)), min_lines)
        if m:
            out[leaf] = m
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


RESTART_COST = 8         # leaves a new alphabet must be worth before it counts as a section
EDGE_GAP = 10            # an alphabet's end cluster this far from the rest, and...
EDGE_MIN = 3             # ...smaller than this, is not part of it
MIN_REL_LINES = 0.25     # a leaf votes only with this share of the volume's median voting lines


def alphabets(letters, min_share=0.40, restart_cost=RESTART_COST):
    """Split a volume's letter-voting leaves into ascending alphabets.

    -> [sorted leaf list, ...], one per alphabet, in volume order.

    `blocks`/`analyse` model a volume as ONE A->Z run, and the corpus is not like that. Measured
    over all 184 IA volumes on 2026-09-22, the single-run model produced a listing whose end came
    BEFORE its start on 17 of them, because three shapes are common:

      * a PART covers a stretch of the alphabet -- trowsgeneraldir1904p1trow runs A->H, and two
        stray T leaves in its front matter made T the "last letter";
      * single stray leaves -- a lone B inside 1904p1's A run, an S inside 1907p2's N run;
      * TWO alphabets in one binding -- 1856BPL runs A->Y over leaves 65-389, then A->Z again
        over 405-581, and the single-run model returned 65..581.

    So this is a Viterbi over the voting leaves in leaf order. Each leaf is either included in
    the current alphabet (only if its letter is >= the last one included), skipped, or opens a
    new alphabet at a cost of `restart_cost` leaves. A stray leaf costs 1 to skip and so is
    skipped; a real second alphabet is worth far more than 8 leaves and so opens a section. Maximises
    the number of included leaves, so it keeps the longest coherent structure the votes support.
    """
    strong = {k: v for k, v in letters.items() if v[1] >= min_share and "A" <= v[0] <= "Z"}
    if not strong:
        return []
    # Front-matter ad pages vote with a handful of lines; listing pages vote with a column's worth.
    # 1867BPL leaves 2-4 ("BROOKLYN DIRECTORY ADVERTISER. ... GUTTENTAG & MYERS") voted A on
    # 14-28 lines and sat close enough to the A block that trim_edges could not separate them; the
    # listing pages vote on 90-160. Relative, so the thin microfilm tier scales with itself.
    floor = MIN_REL_LINES * statistics.median(v[2] for v in strong.values())
    seq = [(leaf, ord(v[0]) - 65) for leaf, v in sorted(strong.items()) if v[2] >= floor]
    if not seq:
        return []
    NEG = float("-inf")
    # state 0..25 = the last included letter; 26 = nothing included yet
    score = [NEG] * 26 + [0.0]
    back = []                                   # per element: {state: (prev_state, action)}
    for _leaf, x in seq:
        new = score[:]                          # skip: every state carries over unchanged
        bp = {st: (st, "skip") for st in range(27)}
        best_prev = max(range(26), key=lambda st: score[st])
        cands = []
        if score[26] > NEG:
            cands.append((score[26] + 1, 26, "start"))
        cont = max((st for st in range(x + 1)), key=lambda st: score[st])
        if score[cont] > NEG:
            cands.append((score[cont] + 1, cont, "include"))
        if score[best_prev] > NEG:
            # the epsilon breaks ties AGAINST a restart: brooklynnewyorkc1904geor has eight
            # one-leaf ad votes (A C E F G J M R, leaves 665-681) between S and S, worth exactly
            # the cost of a restart, and the tie split one alphabet in two
            cands.append((score[best_prev] + 1 - restart_cost - 1e-6, best_prev, "restart"))
        if cands:
            val, prev, act = max(cands, key=lambda c: c[0])
            if val > new[x]:
                new[x] = val
                bp[x] = (prev, act)
        back.append(bp)
        score = new
    # trace back from the best final state
    st = max(range(27), key=lambda s_: score[s_])
    runs, cur = [], []
    for i in range(len(seq) - 1, -1, -1):
        prev, act = back[i][st]
        if act != "skip":
            cur.append(seq[i][0])
            if act in ("start", "restart"):
                runs.append(sorted(cur))
                cur = []
        st = prev
    runs = [r for r in (trim_edges(r) for r in reversed(runs)) if r]
    # ...but a listing ENDS partway down a page, so its last leaf is short by nature and the
    # floor cuts it: 1862BPL leaf 508 ("Zyla Bobert, gardener", 20 votes) and 1867BPL leaf 657
    # ("Zwergius Julius", 14) are the true final pages, and gating them moved both ends back a
    # page. So after segmenting, an alphabet's end may reach any directly following leaf (within
    # 2, i.e. across one blank verso) that continues its letter order, gated or not.
    order = sorted(strong)
    for r in runs:
        while True:
            last = r[-1]
            nxt = next((k for k in order if k > last), None)
            if nxt is None or nxt - last > 2 or strong[nxt][0] < letters[last][0]:
                break
            r.append(nxt)
    return merge_interludes(runs, letters)


def merge_interludes(runs, letters, edge_gap=EDGE_GAP):
    """Rejoin an alphabet that a short interlude split in two.

    brooklyncitydire1848teal runs A..M to leaf 164, then its Mc section -- "MAC | M'Cage James
    ... Caig James" -- where the OCR splits off the M' and the names vote the letter AFTER the
    Mc: C, D, G, K, L over leaves 165-176. Then N resumes at 177. Keeping that interlude was worth
    more than a restart costs, so the listing became A..M plus a second "A..Z".

    A real second alphabet follows a COMPLETE one (1856BPL's Eastern District starts after the
    Western ends at Y). So: when an alphabet stops before W, and the next begins within
    `edge_gap` leaves and later passes the letter the first stopped at, the second's continuation
    is the first's, and its lead-in is an interlude (left as skipped votes inside the span).
    """
    if not runs:
        return runs
    out = [runs[0]]
    for r in runs[1:]:
        prev = out[-1]
        stop = letters[prev[-1]][0]
        if stop < "W" and r[0] - prev[-1] <= edge_gap and letters[r[-1]][0] > stop:
            j = next(k for k, leaf in enumerate(r) if letters[leaf][0] >= stop)
            out[-1] = prev + r[j:]
        else:
            out.append(r)
    return out


def trim_edges(run, edge_gap=EDGE_GAP, edge_min=EDGE_MIN):
    """Drop small clusters sitting apart at either end of an alphabet.

    Ascending order alone cannot reject a stray leaf that happens to carry the alphabet's FIRST
    letter. 1856BPL leaves 12 and 29 are front-matter ad pages ("BROOKLYN DIRECTORY
    ADVERTISER. ... FRANCIS D. NORRIS,") that vote A, and A is where the listing begins, so the
    segmentation took them in and the listing "started" at leaf 12 instead of 65. They are singletons 13-23
    leaves apart; the listing is dense. So: split at gaps over `edge_gap` and shed end clusters
    smaller than `edge_min`, repeatedly. Interior clusters are untouched -- an ad run inside the
    listing is a gap, not an edge.
    """
    parts = clusters(run, edge_gap)
    while len(parts) > 1 and len(parts[0]) < edge_min:
        parts.pop(0)
    while len(parts) > 1 and len(parts[-1]) < edge_min:
        parts.pop()
    return [x for p in parts for x in p]


# ---- edge extension ----------------------------------------------------------------------
# The letter vote misses a listing's OUTERMOST pages, and it misses them systematically: a caption
# page ("TROW GENERAL DIRECTORY ... ABBREVIATIONS", then the first A entries) or a last page that
# is half advertising carries too few entry lines to vote. Measured against 292 listing edges read
# off the page images on 2026-09-23: 16 of 142 starts were late (the Trow p1 caption page every
# year 1903-1914, 1908BPL, 1911p1...) and 4 of 150 ends early. Extending each edge outward across
# pages that still read as listing corrects them. 57 extension steps were opened at their IIIF
# images: 54 right, and the 3 wrong were all a TITLE-and-abbreviations page (1922/23 p1 leaf 185,
# 1917 leaves 210-211) taken for a caption page -- which is what CAPTION_SHARE exists to refuse.
EDGE_KEY_RE = re.compile(r"^[*\u2022\"'`]*([A-Z])(?:[a-z']+|\s[A-Z&]\b|&|\.)")
EXTEND_GAP = 3           # the next page may be this many leaves away (blank versos between)
EXTEND_MIN = 5           # a page needs this many lines keyed on the edge letter...
EXTEND_SHARE = 0.25      # ...making up this share of its keyed lines
# ...or, at a START only, be a caption page ("DIRECTORY" in its first 12 lines) above this share.
# The margin is narrow and measured: title pages 0.049-0.083, the weakest real caption page
# (trowsgeneraldir1905p1trow leaf 117, 5 of 50) 0.100.
CAPTION_SHARE = 0.09


def edge_page(lines):
    """-> (keys, is_caption) for one page's line texts. The key admits what FIRST_WORD_RE
    refuses and a listing's first page is full of: corporate names (`A A Automatic Mfg Co`,
    `A&B`) and initials. ALL-CAPS lines never key -- they are headings and banners."""
    keys = [m.group(1) for t in lines if (m := EDGE_KEY_RE.match(t.strip())) and not t.isupper()]
    return keys, any("DIRECTORY" in t.upper() for t in lines[:12])


def extend_edges(start, end, first_letter, last_letter, pages):
    """-> (start, end, added_at_start, added_at_end). `pages` = {leaf: [line texts]} for the
    TEXT leaves around both edges (blank leaves omitted)."""
    def listingish(leaf, letter, at_start):
        keys, caption = edge_page(pages[leaf])
        k = keys.count(letter)
        share = k / max(len(keys), 1)
        # caption first: a caption page is where the listing BEGINS, however well it scores
        if at_start and caption and k >= EXTEND_MIN and share >= CAPTION_SHARE:
            return "caption"
        if k >= EXTEND_MIN and share >= EXTEND_SHARE:
            return "listing"
        return None

    added = {"start": [], "end": []}
    leaves = sorted(pages)
    for side, edge, letter in (("start", start, first_letter), ("end", end, last_letter)):
        cur = edge
        while True:
            nxt = ([x for x in leaves if x < cur][-1:] if side == "start"
                   else [x for x in leaves if x > cur][:1])
            if not nxt or abs(nxt[0] - cur) > EXTEND_GAP:
                break
            kind = listingish(nxt[0], letter, side == "start")
            if not kind:
                break
            cur = nxt[0]
            added[side].append(cur)
            if kind == "caption":          # nothing before a caption page is the listing
                break
        if side == "start":
            start = cur
        else:
            end = cur
    return start, end, added["start"], added["end"]


def detect(letters, n_leaves, source, min_share=0.40, gap=6, interior="keep", params=None):
    """-> (result, block_map, kept) for a {leaf: (letter, share, n)} map, or (None, ...) when no
    alphabetical structure was found. The whole analysis, with no printing -- `main` and
    survey_derive.py both call this, so the CLI and the corpus survey cannot drift apart.

    The volume is first split into ascending `alphabets`; the largest is the listing, and the
    letter blocks, gaps and violations are computed inside it alone. Every alphabet is reported
    under `sections`, so a second alphabet (a business or street directory, a second town) is
    inventoried rather than either swallowed or discarded."""
    runs = alphabets(letters, min_share)
    if not runs:
        return None, {}, []
    main = max(runs, key=len)
    lo, hi = main[0], main[-1]
    member = set(main)
    # Blocks see only the listing's own voting leaves: a stray leaf inside the span that the
    # segmentation skipped is exactly an out-of-order vote, and letting it form a block would
    # re-create the violations the segmentation exists to remove.
    block_map = blocks({k: v for k, v in letters.items() if k in member}, min_share, gap)
    _s, _e, present, violations, gaps = analyse(block_map)
    if _s is None:
        return None, block_map, []
    # The listing's bounds are the section's, not the first and last letter blocks'. A block
    # is a letter's LARGEST cluster at `gap` leaves of slack, and on a volume with blank versos
    # that slack is three pages: trowsgeneraldir1904p1trow's last H listings (leaves 1183-1195,
    # "Harrison --Teresa G h 161 E 61st" under an ad band) fell outside H's block, and the
    # listing ended at 1181.
    start, end = lo, hi
    if interior == "drop":
        kept = sorted({leaf for L in present for leaf in block_map[L]["leaves"]})
    else:
        kept = sorted({leaf for L in present
                       for leaf in range(block_map[L]["span"][0], block_map[L]["span"][1] + 1)})
    missing = [L for L in LETTERS if L not in block_map]
    result = {"source": source, "leaves": n_leaves,
              "start_leaf": start, "end_leaf": end,
              "kept_leaves": len(kept),
              "letters_present": present, "missing_letters": missing,
              "blocks": {L: {"start_leaf": b["span"][0], "end_leaf": b["span"][1],
                             "leaves": b["n"], "alternates": b["alts"]}
                         for L, b in block_map.items()},
              "order_violations": violations,
              "gaps": [{"between": [a, b], "start_leaf": lo, "end_leaf": hi, "leaves": n}
                       for a, b, lo, hi, n in gaps],
              "ambiguous_letters": [L for L in present if block_map[L]["alts"]],
              "sections": [{"start_leaf": r[0], "end_leaf": r[-1], "voting_leaves": len(r),
                            "first_letter": letters[r[0]][0], "last_letter": letters[r[-1]][0],
                            "letters": "".join(sorted({letters[x][0] for x in r})),
                            "is_listing": r is main}
                           for r in runs],
              "skipped_votes": sorted(k for k, v in letters.items()
                                      if lo <= k <= hi and k not in member
                                      and v[1] >= min_share),
              "params": dict(params or {}, min_share=min_share, gap=gap,
                             restart_cost=RESTART_COST)}
    return result, block_map, kept


def _self_test():
    """Offline; no network, no cache. Pins the two things measurement actually corrected here:
    the ditto forms must abstain, and a letter's block must be its member leaves rather than its
    span (interior ad pages sat inside the O block until that was fixed)."""
    # Ditto marks vote the GIVEN name if the sort key is not anchored. These exact lines are the
    # ones the parallel session hit on 1906BPL.
    def key(line):
        m = FIRST_WORD_RE.match(line.strip())
        return m.group(1).upper() if m else None

    assert key("Ackerman And'w J foreman h 460 Ralph av") == "A", "a real surname must vote"
    assert key('"        Ann C wid David h 518 Madison') is None, "ditto mark must abstain"
    assert key("44       Anna costumes 760 B'way") is None, "OCR'd ditto must abstain"
    assert key('" Julius r 131 Av A') is None, "gold-convention ditto must abstain"
    assert key("do. Ann C wid") is None, "'do.' ditto must abstain"
    assert key("MAIN OFFICE, 1232 Fulton St.") is None, "ALL-CAPS banner must abstain"
    assert key("W. E. Murdock, Boston.") is None, "initials-first ad copy must abstain"
    # Both apostrophe characters on BOTH sides of the distinction. The corpus is 4:1 curly, so a
    # straight-only test passes while missing 80% of the real cases -- which is exactly what the
    # first version of this test did, because a person typing an example types it straight.
    assert key("O'Brien Michael lab h 12 Pine") == "O", "straight-quote surname must vote"
    assert key("O’Brien Michael lab h 12 Pine") == "O", "CURLY-quote surname must vote"
    assert key("D'Ambra Luigi lab h 44 Union") == "D", "straight D'-surname must vote"
    assert key("D’Addio Luigi lab h 44 Union") == "D", "curly D’-surname must vote"
    assert key("H'y grocer 213 Prince") is None, "abbreviated GIVEN name must abstain"
    assert key("H’y grocer 213 Prince") is None, "curly abbreviation must abstain too"
    assert key("Wm elk h 149 Division av") is None, "so must Wm -- the ditto in another costume"

    assert clusters([1, 2, 3, 20, 21], 6) == [[1, 2, 3], [20, 21]], "gap must split runs"
    assert clusters([1, 5, 9], 6) == [[1, 5, 9]], "gaps within tolerance must not split"
    assert clusters([], 6) == [], "empty input must not raise"

    # A block keeps its members, not its span: leaf 5 voted B, leaf 6 did not, leaf 7 voted B.
    letters = {5: ("B", 0.9, 40), 6: ("Z", 0.1, 30), 7: ("B", 0.9, 40)}
    bm = blocks(letters, 0.40, 6)
    assert bm["B"]["leaves"] == [5, 7], "a non-voting interior leaf must not join the block"
    assert bm["B"]["span"] == (5, 7), "the span still reports the outer bound"
    assert "Z" not in bm, "a leaf below min_share must not form a block"

    # Ordering and gap bookkeeping.
    bm2 = blocks({1: ("A", .9, 9), 2: ("A", .9, 9), 9: ("B", .9, 9)}, 0.40, 6)
    start, end, present, viol, gaps = analyse(bm2)
    assert (start, end) == (1, 9) and present == ["A", "B"], "bounds span first to last letter"
    assert viol == [], "A before B is not a violation"
    assert gaps == [("A", "B", 3, 8, 6)], "the run between blocks must be reported as a gap"

    back = analyse(blocks({1: ("B", .9, 9), 9: ("A", .9, 9)}, 0.40, 6))
    assert back[3] == [("A", "B")], "B starting before A must be flagged as a violation"

    # ---- alphabets(): the segmentation that replaced the single-run model -------------------
    def run(lo, n, first="A", step=2, lines=90):
        """n voting leaves from `lo`, `step` apart, two per letter from `first` on."""
        return {lo + k * step: (chr(ord(first) + k // 2), 0.9, lines) for k in range(n)}

    one = run(100, 40)
    assert alphabets(one) == [sorted(one)], "one clean alphabet is one section"
    # a PART: H..Q only, plus two stray T leaves in the front matter (trowsgeneraldir1904p1trow)
    part = {**run(100, 20, "H"), 25: ("T", 0.9, 90), 65: ("T", 0.9, 90)}
    got = alphabets(part)
    assert len(got) == 1 and got[0][0] == 100, got
    # a stray leaf inside a run is skipped, not a restart
    stray = {**one, 121: ("B", 0.9, 90)}
    assert alphabets(stray) == [sorted(one)], "a lone out-of-order leaf is skipped"
    # TWO alphabets (1856BPL): both are sections, in volume order
    two = {**run(100, 40), **run(300, 30)}
    got = alphabets(two)
    assert [(g[0], len(g)) for g in got] == [(100, 40), (300, 30)], got
    # front-matter ads voting the FIRST letter pass ascending order; trim_edges sheds them
    ads = {**one, 12: ("A", 0.9, 90), 29: ("A", 0.9, 90)}
    assert alphabets(ads)[0][0] == 100, "isolated leading singletons are trimmed"
    # ...and ads voting on a handful of lines are gated out even when adjacent (1867BPL)
    thin = {**one, 94: ("A", 0.9, 14), 96: ("A", 0.9, 20)}
    assert alphabets(thin)[0][0] == 100, "a few-line vote does not open the listing"
    # but a short FINAL page is the listing's real end and must survive (1862BPL leaf 508)
    tail = {**one, 180: ("Z", 0.9, 20)}
    assert alphabets(tail)[0][-1] == 180, "a short last page still ends the listing"

    # the Mc interlude (brooklyncitydire1848teal): A..M, then Mc names voting C..L, then N..Z
    mc = {**run(100, 26), **{152 + k: (L, 0.9, 90) for k, L in enumerate("CDGKL" * 2)},
          **run(170, 26, "N")}
    got = alphabets(mc)
    assert len(got) == 1 and got[0][0] == 100 and got[0][-1] == 220, [(g[0], g[-1]) for g in got]
    # ...but a COMPLETE alphabet followed by another stays two (1856BPL's two districts)
    assert len(alphabets(two)) == 2

    # extend_edges: a caption page before the first voting leaf, a short tail page after
    body = ["Abbott John h 12 Pine"] * 20
    pages = {7: ["TROW GENERAL DIRECTORY", "ABBREVIATIONS"] + ["x y"] * 40 + ["Aaron A h 1 B"] * 6,
             5: ["POLK'S TROW'S NEW YORK CITY DIRECTORY", "LIST OF ABBREVIATIONS"]
                + ["Alley al", "Avenue av"] * 3 + ["Bway Broadway"] * 100,    # a TITLE page
             9: body, 11: body,
             13: ["Zabel J h 4 Oak"] * 8 + ["PIANOS", "Kindling wood"] * 3,
             15: ["INDEX TO ADVERTISEMENTS"] + ["Smith & Co page 4"] * 30}
    got = extend_edges(9, 11, "A", "Z", pages)
    assert got == (7, 13, [7], [13]), got
    title_only = {k: v for k, v in pages.items() if k != 7}
    assert extend_edges(9, 11, "A", "Z", title_only)[0] == 9, \
        "a title-and-abbreviations page is refused (share under CAPTION_SHARE)"
    assert extend_edges(9, 11, "A", "Z", {9: body, 11: body, 30: body})[1] == 11, \
        "too far away to be the next page"

    res, _bm, _k = detect(two, 500, "test")
    assert (res["start_leaf"], res["end_leaf"]) == (100, 178), res["start_leaf"]
    assert [s["is_listing"] for s in res["sections"]] == [True, False]

    print("self-test OK", file=sys.stderr)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    if "--self-test" in (argv if argv is not None else sys.argv[1:]):
        return _self_test()
    ap.add_argument("--self-test", action="store_true", help="offline; no network, no cache")
    ap.add_argument("--ident", required=True, help="IA identifier")
    ap.add_argument("--from-jsonl", nargs="?", const="auto", default=None,
                    help="read an existing data/<ident>_lines.jsonl instead of the hOCR. Bare "
                         "flag looks for the default path. Faster, needs no network, and gets "
                         "the benefit of the ingest's own filters -- prefer it when the file "
                         "exists.")
    ap.add_argument("--from-dump", nargs="?", const="auto", default=None,
                    help="read a survey_harvest.py word dump (default "
                         "data/survey_ocr/<ident>_words.jsonl.gz). Identical to reading the "
                         "hOCR, with no network.")
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

    if args.from_dump:
        path = Path(args.from_dump) if args.from_dump != "auto" \
            else REPO / "data" / "survey_ocr" / f"{args.ident}_words.jsonl.gz"
        if not path.exists():
            ap.error(f"no word dump at {path} -- run survey_harvest.py --ids {args.ident}")
        print(f"{args.ident}: reading {path}", file=sys.stderr)
        letters = leaf_letters_from_dump(path, args.min_chars, args.min_lines)
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            n_leaves = sum(1 for _ in fh)
        source = str(path)
    elif args.from_jsonl:
        path = Path(args.from_jsonl) if args.from_jsonl != "auto" \
            else REPO / "data" / f"{args.ident}_lines.jsonl"
        if not path.exists():
            ap.error(f"no lines JSONL at {path} -- build it with ia_volume_to_jsonl.py, or drop "
                     f"--from-jsonl to read the hOCR")
        print(f"{args.ident}: reading {path}", file=sys.stderr)
        letters = leaf_letters_from_jsonl(path, args.min_lines)
        n_leaves = (max(letters) + 1) if letters else 0     # the JSONL knows only what it kept
        source = str(path)
    else:
        item = Item(args.ident, Path(args.cache))
        idx = item.index
        print(f"{args.ident}: {len(idx)} leaves", file=sys.stderr)
        letters = leaf_letters(item, idx, args.min_chars, args.min_lines)
        n_leaves = len(idx)
        source = "hocr"
    print(f"  {len(letters)} leaves with a readable modal letter", file=sys.stderr)
    if args.verbose:
        for leaf, (L, share, n) in sorted(letters.items()):
            print(f"    {leaf:5d}  {L}  {share:.2f}  ({n} lines)", file=sys.stderr)

    params = {"min_chars": args.min_chars, "min_lines": args.min_lines}
    result, block_map, kept = detect(letters, n_leaves, source, args.min_share, args.gap,
                                     args.interior, params)
    if result is None:
        print("no alphabetical structure found -- not a sorted listing, or the OCR is too poor",
              file=sys.stderr)
        return 1
    result = {"ident": args.ident, **result}
    start, end = result["start_leaf"], result["end_leaf"]
    present, missing = result["letters_present"], result["missing_letters"]
    violations = [tuple(v) for v in result["order_violations"]]
    gaps = [(g["between"][0], g["between"][1], g["start_leaf"], g["end_leaf"], g["leaves"])
            for g in result["gaps"]]
    if args.emit_leaves:
        print(",".join(str(x) for x in kept))
        return 0

    print(f"\nletter   leaves        n   note")
    for L in present:
        b = block_map[L]
        alts = "  AMBIGUOUS: also " + ", ".join(f"{lo}..{hi} ({k})" for lo, hi, k in b["alts"]) \
            if b["alts"] else ""
        print(f"  {L}   {b['span'][0]:5d}..{b['span'][1]:<5d} {b['n']:4d}{alts}")

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

    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=1), encoding="utf-8")
        print(f"\nwrote {args.json}")
    print(f"\nsweep just the listing:\n"
          f"  python3 data_prep/ia_volume_to_jsonl.py --ident {args.ident} "
          f"--leaves {start}-{end}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
