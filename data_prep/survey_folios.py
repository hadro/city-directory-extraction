#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Leaf -> printed page from the page's own margins: the fallback `survey_census.py`'s docstring
has promised since 2026-09-12, for the ~98 volumes whose `_page_numbers.json` is sparse or empty.

    python3 data_prep/survey_folios.py --ident 1906BPL        # fit one volume, print segments
    python3 data_prep/survey_folios.py --calibrate            # score against IA's own numbers
    python3 data_prep/survey_folios.py --self-test

Reads the Phase 1 word dump (data/survey_ocr/<id>_words.jsonl.gz); no network.

HOW
---
1. Candidates. Every 1-4 digit token (surrounding punctuation stripped) in the top or bottom 25%
   of a leaf. 25% and not 10%: an ad band pushes the folio down the page -- 1897BPL leaf 302
   prints `262` as its first line, below a banner, and a 10% band read 0% of that volume's folios
   against 100% at 25%, with no loss on any other calibration volume.
2. Counting. Pages are counted over CONTENT leaves (pageindex chars >= 50), not all leaves. 68
   of 184 volumes interleave an empty leaf between every page -- the whole ABBYY-8 Trow and
   Brooklyn family among them -- and they are scanner artefacts, not lost text: on
   trowsgeneraldir1904p1trow the text leaves 411, 413, 417 print 151, `151!`, `1B4`, one
   page per text leaf. Counting all leaves would halve the slope on a third of the corpus.
   Why MISS is 0.1 and not higher: the ABBYY-8 OCR drops most folios (trowsgeneraldir1904p1trow
   leaves 401-700 expose one as a lone last line on 25 of ~150 pages), and at 0.3 a 150-leaf
   stretch with 25 reads scored below "unnumbered", so 16 Trow volumes fitted nothing at all.
   Swept 2026-09-22 against IA's read numbers on all 184 volumes (1904BPL excluded):

       MISS   read agree   inferred agree   listing leaves fitted   start/end claims
       0.30   99.42%       98.1%            59%                     51 / 78
       0.10   99.50%       98.0%            72%                     75 / 88
       0.05   99.53%       97.3%            78%                     82 / 101

   Agreement on READ leaves does not move, so the coverage costs nothing where it matters for
   the CSV; 0.1 takes most of it while `inferred` stays at 98%.
3. Fit. A printed number v on content leaf i proposes offset v - i. A Viterbi over content leaves
   picks a piecewise-constant offset (states: every offset proposed >= 3 times, plus "unnumbered"),
   scoring +1 where the leaf's candidates contain the fitted number, -MISS where they do not, 0 in
   the unnumbered state, and SWITCH to change state. So street numbers and phone numbers, which
   never line up across pages, cannot form a segment, and a volume that restarts its numbering
   (several alphabets) or skips an unnumbered plate just changes offset.
4. Attestation, per leaf -- the survey's founding rule, the same one survey_pagenumbers.py
   enforces on IA's `confidence: null`:

       read         this leaf's own margin prints the fitted number
       inferred     inside a fitted segment, but this leaf's margin does not show it
                    (a mangled folio, or a page that prints none). Never CSV-grade.

   A leaf outside every segment has no page at all, which is the true answer for unnumbered front
   matter.

WHAT THE CALIBRATION IS AND IS NOT
----------------------------------
IA derives `_page_numbers.json` from THIS SAME OCR, so agreement with it is a check on method,
not on data: two readers of one text. It is still the right check -- the fit is new, the
candidate rule is new -- but "two independent detectors agree" overstates it. And the
calibration turned up a case where IA's side is the wrong one: 1904BPL (tier A, volume
confidence 95.6) sets pageNumber = leafNum on 76% of its leaves at confidence 100, while its own
`ocr_value` for those leaves records the tokens it actually saw -- `['1904', '317', '3004']`, a year,
a street number and a phone number. So a disagreement is a finding about one of the two, not
automatically about this one.
"""
from __future__ import annotations

import argparse
import collections
import gzip
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))

OUT = REPO / "data" / "survey_ocr"
PN = REPO / "data" / "survey_pagenumbers"

NUM = re.compile(r"^[\W_]*(\d{1,4})[\W_]*$")
BAND = 0.25              # top/bottom share of the page searched for a folio
CONTENT_CHARS = 50       # pageindex chars for a leaf to count as a page
MIN_PROPOSALS = 3        # an offset must be proposed this often to become a state
MIN_SUPPORT = 3          # ...and a fitted segment must be read on this many leaves to survive
MISS = 0.1               # cost of a leaf whose margin does not show the fitted number
SWITCH = 2.5             # cost of changing offset (or entering/leaving "unnumbered")


EDGE_LINES = 1           # the top and bottom this-many lines are the running head / foot


def candidates(rec: dict, band: float = BAND) -> set:
    """Folio-shaped numbers where a folio is printed: a line that is ONLY a number, anywhere in
    the top or bottom `band`; or any number in the page's top or bottom EDGE_LINES lines.

    Not every number in the band. 1906BPL's top ad strip ends ~12% down and the listing starts
    right under it, so a 25% band swept in house numbers (`h 648 68th`) and the `44` ditto --
    twenty candidates a leaf -- and consecutive leaves lined up by chance into runs "reading"
    pages 0..8 inside the 1090s. A folio stands alone or sits in the running head; an address
    number does neither.
    """
    ps = rec.get("page_size")
    if not ps or not ps[1] or not rec["lines"]:
        return set()
    h = ps[1]
    by_y = sorted(rec["lines"], key=lambda ws: min(w[1] for w in ws))
    edge = {id(ws) for ws in by_y[:EDGE_LINES] + by_y[-EDGE_LINES:]}
    out = set()
    for ws in rec["lines"]:
        yc = (min(w[1] for w in ws) + max(w[3] for w in ws)) / 2 / h
        solo = len(ws) == 1 and (yc < band or yc > 1 - band)
        if not (solo or id(ws) in edge):
            continue
        for _x0, _y0, _x1, _y1, _conf, t in ws:
            m = NUM.match(t)
            if m:
                out.add(int(m.group(1)))
    return out


def folio_token(rec: dict, value: int):
    """(the printed token, "head"|"foot") for `value` on this leaf, as `candidates` found it --
    the verbatim quote a page claim cites."""
    h = (rec.get("page_size") or [0, 0])[1] or 1
    for ws in rec["lines"]:
        for _x0, y0, _x1, y1, _conf, t in ws:
            m = NUM.match(t)
            if m and int(m.group(1)) == value:
                return t, ("head" if (y0 + y1) / 2 / h < 0.5 else "foot")
    return None, None


def load(ident: str):
    """-> (content leaves in order, {leaf: candidate set})."""
    leaves, cands = [], {}
    with gzip.open(OUT / f"{ident}_words.jsonl.gz", "rt", encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            if rec["chars"] >= CONTENT_CHARS:
                leaves.append(rec["leaf"])
                cands[rec["leaf"]] = candidates(rec)
    return leaves, cands


def fit(leaves: list, cands: dict) -> dict:
    """-> {leaf: (page, "read"|"inferred")} for every leaf inside a supported segment."""
    n = len(leaves)
    props = collections.Counter(v - i for i, leaf in enumerate(leaves) for v in cands[leaf])
    states = [o for o, k in props.items() if k >= MIN_PROPOSALS]
    if not states or not n:
        return {}
    NONE = len(states)                       # the "unnumbered" state
    S = NONE + 1

    def emit(s, i):
        if s == NONE:
            return 0.0
        return 1.0 if (i + states[s]) in cands[leaves[i]] else -MISS

    score = [emit(s, 0) for s in range(S)]
    back = []
    for i in range(1, n):
        best = max(range(S), key=lambda s: score[s])
        new, bp = [0.0] * S, [0] * S
        for s in range(S):
            stay, jump = score[s], score[best] - SWITCH
            if stay >= jump:
                new[s], bp[s] = stay + emit(s, i), s
            else:
                new[s], bp[s] = jump + emit(s, i), best
        back.append(bp)
        score = new
    s = max(range(S), key=lambda k: score[k])
    path = [s]
    for bp in reversed(back):
        s = bp[s]
        path.append(s)
    path.reverse()

    # segments; drop those read on fewer than MIN_SUPPORT leaves
    out, i = {}, 0
    while i < n:
        j = i
        while j + 1 < n and path[j + 1] == path[i]:
            j += 1
        if path[i] != NONE:
            o = states[path[i]]
            reads = [k for k in range(i, j + 1) if (k + o) in cands[leaves[k]]]
            # A segment runs from its first READ leaf to its last, never past them. Staying in an
            # offset through a few unread leaves is cheaper than a switch, so without this the fit
            # extrapolates into unnumbered front matter -- and numbers a page that prints none,
            # which is the error survey_pagenumbers.py retracted from the CSV. Between two reads
            # a leaf is `inferred`; outside them it has no page.
            if len(reads) >= MIN_SUPPORT:
                for k in range(reads[0], reads[-1] + 1):
                    out[leaves[k]] = (k + o, "read" if k in reads else "inferred")
        i = j + 1
    return out


def segments(folios: dict) -> list:
    """Compact form for a sidecar: runs where the page advances by one per content leaf."""
    segs = []
    for leaf in sorted(folios):
        page, att = folios[leaf]
        if segs and page == segs[-1]["last_page"] + 1:
            s = segs[-1]
            s["last_leaf"], s["last_page"] = leaf, page
            s["leaves"] += 1
            s["read"] += att == "read"
        else:
            segs.append({"first_leaf": leaf, "last_leaf": leaf, "first_page": page,
                         "last_page": page, "leaves": 1, "read": int(att == "read")})
    return segs


# ==============================================================================================
def ia_read(ident: str) -> dict:
    """IA's own numbers where IA READ them at confidence >= 90 -- never its interpolations."""
    p = PN / f"{ident}.json"
    if not p.exists():
        return {}
    d = json.loads(p.read_text(encoding="utf-8"))
    out = {}
    for e in d.get("pages") or []:
        c = e.get("confidence")
        if isinstance(c, (int, float)) and c >= 90 and e.get("leafNum") is not None:
            try:
                out[int(e["leafNum"])] = int(str(e.get("pageNumber")).strip())
            except ValueError:
                pass
    return out


def compare(folios: dict, ia: dict) -> dict:
    both = [leaf for leaf in folios if leaf in ia]
    agree = sum(folios[leaf][0] == ia[leaf] for leaf in both)
    ia_is_leaf = sum(ia[leaf] == leaf for leaf in ia) / len(ia) if ia else None
    return {"ia_read_leaves": len(ia), "both": len(both), "agree": agree,
            "agree_rate": round(agree / len(both), 3) if both else None,
            "ia_page_equals_leaf": round(ia_is_leaf, 2) if ia_is_leaf is not None else None}


def calibrate(idents: list) -> int:
    tot = collections.Counter()
    for ident in idents:
        leaves, cands = load(ident)
        f = fit(leaves, cands)
        ia = ia_read(ident)
        if not ia:
            continue
        c = compare(f, ia)
        read = sum(a == "read" for _p, a in f.values())
        print(f"{ident:32} fitted {len(f):5} (read {read:5}) | IA read {c['ia_read_leaves']:5} "
              f"both {c['both']:5} agree {c['agree_rate']}  IA page==leaf {c['ia_page_equals_leaf']}")
        tot["both"] += c["both"]
        tot["agree"] += c["agree"]
    if tot["both"]:
        print(f"\nTOTAL agree {tot['agree']:,}/{tot['both']:,} = {tot['agree'] / tot['both']:.1%}")
    return 0


def _self_test() -> int:
    # a clean run: content leaves 0..19 print 11..30, two margins misread, one street number
    leaves = list(range(20))
    cands = {i: {i + 11} for i in leaves}
    cands[5], cands[9] = set(), {723}                 # a mangled folio, an ad's street number
    f = fit(leaves, cands)
    assert f[4] == (15, "read") and f[5] == (16, "inferred") and f[9] == (20, "inferred"), f
    # the numbering restarts (a second alphabet): a new segment, not a smear
    cands2 = {i: {i + 11} if i < 10 else {i - 9} for i in leaves}
    f2 = fit(leaves, cands2)
    assert f2[9] == (20, "read") and f2[10] == (1, "read"), (f2[9], f2[10])
    assert [(s["first_page"], s["last_page"]) for s in segments(f2)] == [(11, 20), (1, 10)]
    # unnumbered front matter: no candidates -> no page, never an extrapolated one
    cands3 = {i: (set() if i < 6 else {i - 5}) for i in leaves}
    f3 = fit(leaves, cands3)
    assert 0 not in f3 and 5 not in f3 and f3[6] == (1, "read"), f3
    # scattered noise alone never becomes a segment
    noise = {i: {100 + 7 * i} for i in leaves}
    assert fit(leaves, noise) == {}
    # candidates: only the margins, only number-shaped tokens
    rec = {"page_size": [1000, 1000], "lines": [
        [[0, 10, 50, 30, 90, "12"], [60, 10, 300, 30, 90, "BROOKLYN"]],  # running head
        [[0, 120, 50, 140, 90, "Abbott"], [60, 120, 90, 140, 90, "h"],
         [100, 120, 150, 140, 90, "648"]],                              # listing: an address
        [[0, 150, 50, 170, 90, "44"], [60, 150, 90, 170, 90, "Thos"]],  # a ditto, in the band
        [[0, 200, 50, 220, 90, "262"]],                                 # a lone number, in band
        [[0, 500, 50, 520, 90, "317"]],                                 # a lone number, mid-page
        [[0, 900, 50, 920, 90, "Zwing"], [60, 900, 90, 920, 90, "h"]],
        [[0, 960, 50, 980, 90, "—14—"]],                                # foot, with dashes
        [[0, 970, 50, 990, 90, "1896a"]]]}                              # not a number
    assert candidates(rec) == {12, 262, 14}, candidates(rec)
    print("self-test OK", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ident")
    ap.add_argument("--calibrate", nargs="*", default=None,
                    help="score against IA's read numbers (default: every volume that has them)")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()
    if args.calibrate is not None:
        ids = args.calibrate or sorted(p.name[:-len("_words.jsonl.gz")]
                                       for p in OUT.glob("*_words.jsonl.gz"))
        return calibrate(ids)
    if not args.ident:
        ap.error("--ident, --calibrate or --self-test")
    leaves, cands = load(args.ident)
    f = fit(leaves, cands)
    for s in segments(f):
        print(f"  leaves {s['first_leaf']:5}..{s['last_leaf']:<5} pages {s['first_page']:5}.."
              f"{s['last_page']:<5} ({s['leaves']} leaves, {s['read']} read)")
    print(compare(f, ia_read(args.ident)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
