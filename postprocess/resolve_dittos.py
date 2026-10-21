#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Resolve ditto marks in extracted records -- WITHIN-LINE channel only (step 1 of 3).

    python3 postprocess/resolve_dittos.py --records data/polk1933bk_eval.jsonl
    python3 postprocess/resolve_dittos.py --preds data/preds_2b-100k_1906BPL_sample500.txt
    python3 postprocess/resolve_dittos.py --self-test          # offline, stdlib only

The model emits dittos VERBATIM by contract (conventions 11/12 in GROUND_TRUTH_HANDOFF.md), and
that contract is load-bearing: it governs synth_persons.py, all 21 gold volumes and evaluate.py
at once, so resolution has to happen downstream or the panel stops being a measuring stick.
This is the downstream step. It NEVER overwrites a field -- it adds `*_resolved` alongside.

THREE SCOPES, AND ONLY ONE OF THEM IS LINE-LOCAL
------------------------------------------------
Measured across every `data/*_eval.jsonl` in this repo:

  scope                          example              antecedent                   needs order?
  within-line  address->home     `h do`, `h910 do`    the SAME record's `address`  NO   <- HERE
  cross-line   name prefix       `" Jos`, `44 John C` previous entry's surname     yes
  cross-line   address slots     `71 do. do.`         previous line's address      yes

Only the within-line channel is deterministic from one record. It needs no reading order, no
leaf/column boundary handling, no interaction with alpha_run_filter, and it cannot orphan -- so
it is separated from the sequential pass deliberately, not incidentally. The cross-line channels
carry a ~23% dispute rate against an independent check (see the module for step 3); this one does
not, and merging them would hide that difference behind a single accuracy number.

THE FORM INVENTORY IS DRAWN FROM THE CORPUS, NOT FROM MEMORY
------------------------------------------------------------
Every `home_address` ditto in the corpus, by grep rather than by recall:

    x16  home_address='do'      address='3 1-2 Jaggar ave'   `... laundry, 3 1-2 Jaggar ave, h do`
    x1   home_address='910 do'  address='908, 6th av'        `" Mary E (wid Chas E) dairy 908, 6th av h910 do`

Two forms, and the second one matters more than its count: `910 do` is a PARTIAL ditto -- house
number given, street inherited -- so a resolver that only handles the full copy silently drops
the case where the answer is not simply the other field.

**The grep also caught a false positive, which is the point of running it.** `\bdo\b` matches
`12 Do-minick` (nyu_eval: `Drummond Samuel, druggist, 52 Reade, h. 12 Do-minick`) -- Dominick
Street, hyphenated across a column break. A hyphen is a word boundary, so the naive pattern reads
a real address as a ditto and replaces it with a different street entirely. DITTO_TOKEN below
requires the token to be free-standing and not glued to a hyphen. This is the same discipline the
curly-apostrophe post-mortem in HANDOFF.md arrived at: grep the corpus for the character class you
just wrote, before trusting it.

WHAT IS NOT HERE
----------------
The Duncan/early-volume address dittos are a positional SLOT GRAMMAR, not a suffix rule, and they
are cross-line -- so they belong to step 3. Recorded here because the shape was mis-read once:

    13 Warren do.     do. = the street TYPE        ("13 Warren street")
    30 do.            do. = street NAME + type     (inherits "Warren street")
    71 do. do.        TWO independent slots        (row 53 of duncan1794, after "73 Roosevelt-street")
    do.               the ENTIRE address           (row 51, after "Bowery-lane")

`71 do. do.` is the decisive case: one `do.` cannot mean two things, so the slots resolve
separately and a single "strip the trailing do." rule is wrong on 44 of duncan1794's 58 rows.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import collections
from collections import Counter

FIELDS = ["name", "is_business", "spouse_name", "race_designation",
          "occupation_role", "employer", "address", "home_address"]

# A free-standing ditto word. The ANCHORS are what matter: the pattern is matched against the
# whole stripped field, never searched inside it, so `12 Do-minick` / `14 Dover` / `9 Dodge av`
# cannot match. A `\bdo\b` SEARCH does match `Do-minick`, because a hyphen is a word boundary --
# that is the false positive the corpus grep turned up, and anchoring is the fix.
# Trailing period optional; the corpus prints both `do` and `do.`.
DITTO_TOKEN = re.compile(r"^do\.?$", re.IGNORECASE)

# `910 do` -- a house number, then the ditto. The number keeps its printed form, including the
# fraction and hyphen shapes this corpus uses (`3 1-2`, `18-06`, `10-54`).
NUM_DITTO = re.compile(r"^(?P<num>\d+(?:[ -]\d+)*)\s+do\.?$", re.IGNORECASE)

# Leading house number to strip when inheriting only the STREET half of an address.
# Mirrors the shapes above, plus the optional comma Polk prints (`908, 6th av`).
LEADING_NUM = re.compile(r"^\d+(?:[ -]\d+)*\s*,?\s+")


def street_part(address: str) -> str:
    """The street half of an address -- what a partial ditto (`910 do`) inherits.

    `908, 6th av` -> `6th av`;  `633 E169th` -> `E169th`;  `3 1-2 Jaggar ave` -> `Jaggar ave`.
    An address with no leading number is already all street (`Bowery-lane`), so it passes through.
    """
    return LEADING_NUM.sub("", address.strip()).strip()


def resolve_within_line(rec: dict) -> tuple:
    """Resolve `home_address` against this record's own `address`.

    Returns `(resolved_value, status)`. Status is one of:
      not_ditto      -- the field is absent or is a real address; nothing to do
      resolved       -- full copy (`do` -> the address)
      resolved_part  -- partial (`910 do` -> `910` + the address's street half)
      no_antecedent  -- it IS a ditto, but `address` is empty, so it cannot be resolved

    `no_antecedent` is reported rather than guessed. A ditto with nothing to point at is a real
    signal -- usually a dropped or mis-parsed sibling field -- and inventing a value would put a
    confident wrong address on the record, which is the failure mode this whole pipeline is
    trying not to have.
    """
    home = (rec.get("home_address") or "").strip()
    addr = (rec.get("address") or "").strip()
    if not home:
        return "", "not_ditto"

    if DITTO_TOKEN.match(home):
        return (addr, "resolved") if addr else ("", "no_antecedent")

    m = NUM_DITTO.match(home)
    if m:
        street = street_part(addr)
        if not street:
            return "", "no_antecedent"
        return f"{m.group('num')} {street}", "resolved_part"

    return home, "not_ditto"


def annotate(rec: dict) -> dict:
    """Non-destructive: copy the record, add the resolution and its provenance.

    `home_address` keeps the model's verbatim output. `home_address_resolved` is the expansion,
    and `ditto_status` says how it got there -- so a wrong resolution is inspectable rather than
    baked in. Records that carry no ditto get the fields too (resolved == verbatim), so a
    consumer never has to branch on presence.
    """
    out = dict(rec)
    value, status = resolve_within_line(rec)
    out["home_address_resolved"] = value
    out["ditto_status"] = status
    out["ditto_scope"] = "within_line" if status.startswith("resolved") else ""
    return out


# --------------------------------------------------------------------------------------------
# CROSS-LINE: the name channel (step 3)
#
# 67% of 1906BPL's 199,012 lines are ditto-lead -- only 50,225 carry a surname of their own. So
# this pass decides the `name` field for two thirds of a dense volume, and a wrong antecedent
# poisons a whole run (mean 7.1 rows, p90 15, max 180).
#
# READING ORDER: use hOCR EMISSION order, do not reconstruct columns. Measured on 1906BPL, the
# surname sequence in emission order is 93.6% alphabetically non-decreasing within a leaf, and the
# 6.4% backward jumps run ~2.6 per leaf -- about what legitimate column wraps predict on a
# multi-column page. Emission order IS reading order here. This is also the finding HANDOFF #2
# arrived at from the other side: column detection from hOCR line boxes actively fails, because
# wrapped-line indents make left edges multi-modal. Sorting by leaf is stable, so within-leaf
# emission order survives.
#
# THE CARRY IS NOT FREE, AND THE NUMBERS SAY SO. Walking back to the nearest surname-shaped line
# finds an antecedent for 84.9% of dittos within the leaf and 100% if the carry crosses leaves --
# but "found" is not "correct". Two independent checks each dispute ~20k of the 133,781 dittos:
#
#     cross-leaf carry (structural, page boundary)          20,257
#     carried surname != the leaf's own modal letter        20,179
#     overlap                                                8,953   <- only 28% of the union
#
# They are NOT the same rows. That is the whole reason both are computed: ~31.5k rows (23% of all
# dittos) are disputed by at least one check, and either check alone would miss about half of it.
# Nothing here silently picks a winner -- disputed rows are flagged and the caller decides.

try:                                                   # single source of truth for the sort key
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "data_prep"))
    from alpha_run_filter import first_letter as _first_letter
except Exception:                                      # pragma: no cover - fallback keeps this runnable
    _SORT_KEY_RE = re.compile(r"([A-Za-z])(?:[a-z]{2,}|['’][A-Z][a-z])")

    def _first_letter(raw_line: str):
        w = raw_line.split()[0] if raw_line.split() else ""
        m = _SORT_KEY_RE.match(w)
        return m.group(1).upper() if m else None


def surname_token(raw_line: str):
    """The leading token if it is a real sortable surname, else None.

    Delegates the decision to `alpha_run_filter.first_letter`, which is the anchored rule this
    project already paid for twice: it abstains on `"`, `44` and `do.`, AND on the abbreviated
    given names (`H'y`, `Wm`) that appear where OCR dropped the ditto mark entirely -- 664 lines
    of 1906BPL. Re-deriving it here would mean re-deriving both bugs.
    """
    if _first_letter(raw_line) is None:
        return None
    return raw_line.split()[0]


# Ditto leaders, drawn by grep from 1906BPL's 199,012 lines rather than from memory. Counts:
#   44 (84,053)  “ (44,230)  " (2,478)  ** (1,221)  * (417)  '* (316)  *' (279)
#   — (254)  ‘ (199)  4‘ (133)  ” (91)  4 (1,386)  41 (519)  14 (510)
# `44` is ABBYY's reading of `"` and is the single most common leading token in the book.
# `**` is a FOURTH rendering and appears in none of this repo's existing ditto lists -- it was
# found only by dumping the distribution (`** Edwin eom'l trav h 588 11th` is a real entry).
#
# THE DIGIT FORMS ARE DELIBERATELY NOT DEFAULTED ON except 44. `4`, `41` and `14` are also real
# house numbers, and a line may legitimately begin with one. `44` earns its place on frequency
# (42% of all lines) and because `44 Anna costumes 760 B'way` is documented in two other modules
# as an OCR'd ditto. Use --inventory on a NEW volume before trusting any of this: the forms are a
# property of one OCR engine on one book, not of the corpus.
DITTO_LEADERS = re.compile(r"^(?:44|[\"“”'‘’]+|\*+|['’]\*|\*['’]|4['‘]|〃|—|-|do\.?)$", re.IGNORECASE)


# A mark GLUED to the token after it: Trow prints `-Adolph`, Polk sometimes `"Thos`. Nothing
# tokenises as a mark, so `is_ditto_lead` cannot see it and the whole ditto machinery reads the
# volume as having no dittos at all -- trow1913 measures 0.0% ditto-lead against a gold-implied
# share of 97.9%.
GLUED_MARK = re.compile(r"^(?P<mark>[-\"“”'‘’*〃—«]+)\s*(?P<rest>\S.*)$")


def split_glued_mark(raw_line: str, marks=()):
    """('-', 'Adolph A salesman...') when the line opens with a glued mark in `marks`, else None.

    `marks` is PER VOLUME and empty by default, so nothing changes for a caller that does not opt
    in. That default is not timidity: the same character means different things in different
    books, and `classify_glued_marks` below is how you find out which. Splitting blind corrupts
    ogden1839 (see there).
    """
    if not marks:
        return None
    m = GLUED_MARK.match(raw_line or "")
    if not m or m.group("mark") not in marks:
        return None
    return m.group("mark"), m.group("rest")


def is_ditto_lead(raw_line: str, glued=()) -> bool:
    """Does this line open with a ditto mark? `glued` opts in to marks printed without a space.

    Default `glued=()` reproduces every number recorded before 2026-09-12 exactly.
    """
    toks = raw_line.split()
    if toks and DITTO_LEADERS.match(toks[0]):
        return True
    return split_glued_mark(raw_line, glued) is not None


def classify_glued_marks(rows, min_n=3):
    """Per volume, is a glued leading mark a DITTO or a semantic MARKER? Measured, not assumed.

    `rows` = [(leaf, raw_line), ...]. Returns {mark: {...}} with the evidence and a verdict.

    The discriminator is alphabetical coherence, which costs nothing because `first_letter` is
    already the anchored sort-key rule. Take the leaf's modal letter from lines that carry NO
    leading mark, then ask what the token after the mark does:

      a DITTO is followed by a GIVEN name, which does not sort -- so its initial disagrees with
      the leaf's modal letter, and counting it would scatter the page across the alphabet;
      a MARKER is followed by the SURNAME itself, which IS the sort key -- so it agrees.

    Measured on the panel gold, and the separation is total:

        ogden1839    *   n=7   follower matches modal 100%  -> MARKER   (gold: real surname)
        polk1933si   "   n=6                            0%  -> DITTO    (gold: ditto)
        trow1907     -   n=41                          12%  -> DITTO    (gold: ditto)
        trow1913     -   n=87                          15%  -> DITTO    (gold: ditto)

    ogden1839's `*` is a RACE DESIGNATION -- gold records `race_designation: '*'` and
    `name: 'Simmons Aaron'` -- and `*` is in DITTO_LEADERS. So a blind glued-split would both
    destroy the marker and promote a surname to a given name, on 7 of 7 rows. That volume is the
    reason this function exists and the reason `marks` defaults to empty.

    A token-level test was tried first and rejected at 78.2%: requiring the follower to be a known
    given name fails on Trow's orthography (`Edwd`/`Robt`/`Alfd` where 1906BPL prints `Edw'd`/
    `Rob't`) and on business continuations (`-Paper Co`, `-& Co`), which are dittos with no given
    name in them at all. Coherence needs no lexicon and so has neither failure.

    **It DOES need the given names to span the alphabet, so run it over a volume, never a window.**
    Inside one surname block the given names are sorted and contiguous, so a short slice of
    `-Adolph`/`-Anna`/`-Arnold` under `Aarons` votes A three times, matches the modal letter and
    reads as MARKER. At leaf scale a page spans several blocks and the followers scatter -- which
    is why the real volumes land at 12-15% and the self-test pins both behaviours.
    """
    votes = {}
    for leaf, raw in rows:
        if GLUED_MARK.match(raw or ""):
            continue                                   # a marked line cannot vote for the modal
        letter = _first_letter(raw)
        if letter:
            votes.setdefault(leaf, Counter())[letter] += 1
    modal = {lf: c.most_common(1)[0][0] for lf, c in votes.items() if c}

    seen = {}
    for leaf, raw in rows:
        m = GLUED_MARK.match(raw or "")
        if not m or leaf not in modal:
            continue
        d = seen.setdefault(m.group("mark"), {"n": 0, "follower_is_sort_key": 0, "examples": []})
        d["n"] += 1
        d["follower_is_sort_key"] += (_first_letter(m.group("rest")) == modal[leaf])
        if len(d["examples"]) < 5:
            d["examples"].append(raw[:60])
    out = {}
    for mark, d in seen.items():
        if d["n"] < min_n:
            d["verdict"] = "UNDECIDED"                 # too few to call; report, do not guess
        else:
            share = d["follower_is_sort_key"] / d["n"]
            d["share_follower_is_sort_key"] = round(share, 3)
            d["verdict"] = "MARKER" if share >= 0.5 else "DITTO"
        out[mark] = d
    return out


def inventory(rows, top=30):
    """Report the leading-token distribution for a volume, split by the sort-key rule.

    Run this on any new volume BEFORE a production pass. The ditto glyphs above are what one OCR
    engine produced on one book; a different engine or era prints different garbage, and the cost
    of guessing is a whole run of records attributed to the wrong surname. This is the cheap
    version of the habit the HANDOFF post-mortems keep arriving at: look at the actual characters
    before writing the character class.
    """
    counts = {}
    for raw in rows:
        toks = raw.split()
        tok = toks[0] if toks else ""
        key = "<SURNAME-SHAPED>" if surname_token(raw) else tok
        counts[key] = counts.get(key, 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])[:top]


def modal_letters(rows):
    """Per-leaf dominant sort letter, and whether the leaf legitimately spans more than one.

    A leaf that straddles a letter transition (end of A, start of B) will hold dittos under the
    minority letter perfectly correctly, so `multi` exists to stop those being reported as errors.
    Threshold 0.15 for the runner-up share; below that a second letter is noise, not a transition.
    """
    counts, out = {}, {}
    for leaf, raw in rows:
        letter = _first_letter(raw)
        if letter:
            counts.setdefault(leaf, {})
            counts[leaf][letter] = counts[leaf].get(letter, 0) + 1
    for leaf, c in counts.items():
        ordered = sorted(c.values(), reverse=True)
        share = ordered[1] / sum(ordered) if len(ordered) > 1 else 0.0
        out[leaf] = (max(c, key=c.get), share > 0.15)
    return out


LETTER_WINDOW = 3            # voting leaves either side that set a leaf's letter span


def leaf_letter_ranges(rows, k=LETTER_WINDOW) -> dict:
    """{leaf: (lo, hi)}: the letters a surname on the leaf may begin with, from the NEIGHBOURING
    leaves' votes rather than the leaf's own.

    The leaf's own vote is not safe. 1906BPL leaf 20 is an A page holding most of the Allen
    block, and so many of its lines lost their ditto mark and lead with a given name that it
    votes J (42 `Jas foreman`-style lines to 4 surnames) -- gating on that refused Alleman,
    Allemania and Allen, and the whole page inherited `Allegretti`.

    Nor is ONE sorted run per volume: micro_IABROOKLYN_0036 has two alphabets (the listing, then
    the Eastern District's own A-W) and 0031 carries a sorted 20-leaf insert between its M and N
    leaves, and a volume-wide longest non-decreasing run refused every surname in the second.

    So: each leaf takes the votes (alpha_run_filter.leaf_letters) of the `k` nearest voting leaves
    either side and its own, drops the single lowest and highest of them, and spans what is left.
    A stray J leaf among A's gets (A, A); a leaf where C ends and D begins gets (C, D), so the D
    block's first surname still sets the carry; at a restart the span widens, which fails open --
    more lines may set the carry, as before this rule existed, never fewer than they should.
    """
    import bisect
    try:
        from alpha_run_filter import leaf_letters
    except ImportError:                                # pragma: no cover
        return {}
    votes = leaf_letters([{"raw_line": raw or "", "context": {"leaf": leaf}} for leaf, raw in rows])
    voting = sorted(votes)
    out = {}
    for leaf in {lf for lf, _ in rows}:
        i = bisect.bisect_left(voting, leaf)
        own = i < len(voting) and voting[i] == leaf
        window = voting[max(0, i - k): i + k + (1 if own else 0)]
        letters = sorted(votes[lf][0] for lf in window)
        if len(letters) >= 5:
            letters = letters[1:-1]
        out[leaf] = (letters[0], letters[-1]) if letters else ("A", "Z")
    return out


# A LEADING MARK before the name: 1-3 punctuation characters, one capital standing alone (no
# full stop -- `J. Smith` is an initial), or a one- or two-digit number. Glued or spaced. What
# follows starts with a capital, in either case after it: `E ACKERMAN T. & J. boiler works` is
# 431 of micro_IABROOKLYN_0040's Eastern District lines.
LEAD_MARK = re.compile(r"^(?P<mark>[^\sA-Za-z0-9]{1,3}|[A-Z](?![.\w])|\d{1,2})\s*"
                       r"(?P<rest>(?:[^\sA-Za-z0-9]{1,3}\s*)?[A-Z][A-Za-z].*)$", re.S)

# One printed column rule, read by the OCR as any of these -- `| Cahill Robert J.` (0042),
# `I Darla Dommic` (1906BPL), `! Eichler Albert C`, all checked on the page. Judged as ONE mark,
# since each reading alone can fall under min_n -- the scatter PIPELINE.md #18 describes for
# dittos. NOT the digits, although `1 Christian John J.` (0040) and `1 Darling Byron S` (1906BPL)
# are the rule too: in an ABBYY volume `1`/`11` are mostly readings of the DITTO (61 of 1906BPL's
# 82 `1` lines go on with a given name), and pooled they sank its rule class to 40% coherent. A
# digit is judged alone, per volume, as the DITTO_LEADERS note above says it must be.
RULE_GLYPHS = frozenset("|I!][")


def _mark_class(mark: str) -> str:
    return "column rule" if mark and set(mark) <= RULE_GLYPHS else mark


def classify_lead_marks(rows, ranges=None, min_n=20, min_share=0.85) -> dict:
    """Per volume, which leading marks sit before the SURNAME (a marker) rather than a given name.

    The same alphabetical-coherence test as classify_glued_marks, on the follower: a marker is
    followed by the sort key, so it lies inside its leaf's letters; a ditto is followed by a given
    name, so it scatters. Measured over the 44 whole-volume runs on 2026-10-20 the two ends are far
    apart -- 1906BPL's ditto `"` 8% coherent, Brooklyn 1912's `—` 6%, and the markers ~100%:
    the Eastern District `E` of micro_IABROOKLYN_0039/0040/0042 (14.8 / 15.1 / 20.4% of their
    lines), its misreadings `Æ` and `"` (`ÆArron Louis`, `"Bridge Margaret` on the page), the
    column rule read as `|` or `1`, and the `*` of nearly every microfiche volume. `min_n` keeps a
    handful of stray lines from becoming a convention. -> {mark: {"n", "coherent", "verdict"}}.
    """
    ranges = ranges if ranges is not None else leaf_letter_ranges(rows)
    by_class, members = {}, collections.defaultdict(collections.Counter)
    for leaf, raw in rows:
        m = LEAD_MARK.match(raw or "")
        sur = surname_token(m.group("rest")) if m else None
        if not sur:
            continue
        key = _mark_class(m.group("mark"))
        members[key][m.group("mark")] += 1
        d = by_class.setdefault(key, {"n": 0, "coherent": 0})
        lo, hi = ranges.get(leaf, ("A", "Z"))
        d["n"] += 1
        d["coherent"] += lo <= sur[0].upper() <= hi
    out = {}
    for key, d in by_class.items():
        share = d["coherent"] / d["n"]
        verdict = "MARKER" if d["n"] >= min_n and share >= min_share else "UNDECIDED"
        for mark, n in members[key].items():
            out[mark] = {"n": n, "class": key, "class_n": d["n"], "share": round(share, 3),
                         "verdict": verdict}
    return out


def split_lead_mark(raw_line: str, marks=()):
    """('E', 'Cox L. carman ...') when the line opens with one of the volume's `marks`. Marks
    can stack -- 359 of micro_IABROOKLYN_0040's lines open `E *Bennett William J.`, the
    Eastern District mark and the race designation -- and then come back joined by a space."""
    if not marks:
        return None
    found, rest = [], raw_line or ""
    for _ in range(2):
        m = LEAD_MARK.match(rest)
        if not m or m.group("mark") not in marks:
            break
        found.append(m.group("mark"))
        rest = m.group("rest")
    return (" ".join(found), rest) if found else None


def can_set_carry(sur: str, leaf, ranges) -> bool:
    """May this surname-shaped lead become the carry? The `strict` rule (2026-10-20).

    `surname_token` alone lets any line whose first word looks sortable reset the carry, and on a
    page that interleaves advertising that is most of the error: 25,601 records across the 44
    whole-volume runs carried a surname from a line that is not an entry -- 1906BPL's
    `" Harry engineer` came out `millions— Harry` from the ad `millions— Try them.`, and
    `French and American, all flavors.` handed `French` to 856 dittos. Two tests, both cheap:

      a CAPITAL lead. `alpha_run_filter._SORT_KEY_RE` opens `[A-Za-z]` although first_letter's
      docstring says "anchored capital"; it is left alone there because it also drives listing
      bounds. For the carry, `until Withdrawn.` (9,166 records carried a lowercase surname)
      must not count.
      the LEAF'S LETTERS (leaf_letter_ranges): a directory is sorted, so a surname outside the
      span its neighbours set is ad copy, a legend, a street continuation, or a given name whose
      ditto mark the OCR dropped (`Geo A J realestate` on an A page, `Jas foreman` under Allen).

    A line that fails is TRANSPARENT -- the carry runs on past it, which is right for an ad set
    between two entries of one block. Not used: `entry_shaped` (it would block 1,057 real
    surname lines of micro_IABROOKLYN_0039 such as `Abbott Moses, keeper city hall.`) and the
    layout role (0039 has 1,252 real entries labelled runover).
    """
    if not sur or not sur[0].isupper():
        return False
    lo, hi = ranges.get(leaf, ("A", "Z"))
    return lo <= sur[0].upper() <= hi


def resolve_cross_line(rows, glued=(), heads=None, strict=False, markers=()):
    """Sequential surname carry over `rows` = [(leaf, raw_line), ...] in reading order.

    `glued` is the per-volume set of marks printed without a space (Trow's `-`), empty by default
    so every number recorded before 2026-09-12 reproduces. Get it from `classify_glued_marks`,
    never by assumption -- ogden1839's `*` is a race designation, not a ditto.

    `heads` {row index: surname} puts back the surname block headers ingest drops (`ANDERSON`
    over a column, `ACME` over its dittos): the carry becomes that surname just before the row.
    `strict` gates which lines may set the carry (`can_set_carry`). Both default off, so every
    number recorded before 2026-10-20 reproduces; assemble_records.py turns both on. A row
    resolved from a header says so in `header` (and has no source line to point at).

    `markers` (classify_lead_marks' MARKER verdicts) lets a line that opens with a marker --
    `E Cox L.`, `“Kleinschnitz George` -- set the carry from the surname after it, and says
    which mark in `mark`. Without it those lines can never set the carry (first_letter anchors at
    position 0), so a ditto under an Eastern District entry inherited the surname before it. A
    marker that is also a ditto glyph (`"`) is read as a marker only where what follows lies
    inside the leaf's letters; otherwise the line is still a ditto.

    Yields one dict per row: the verbatim leading token, the resolved surname, and FLAGS. It
    never drops a row and never silently picks between candidates.

    Flags, any of which may be set together:
      cross_leaf      the antecedent came from a previous leaf -- a page boundary was crossed
      letter_conflict the carried surname disagrees with this leaf's own modal letter, on a leaf
                      that does not legitimately span two letters
      orphan          no antecedent exists yet (nothing to carry); resolved is left empty

    Callers should treat `cross_leaf` and `letter_conflict` as review queues, not as errors --
    on 1906BPL they are 15.1% and 15.1% of dittos respectively and overlap only 28%, so together
    they cover ~23% of dittos. That is the honest precision of a carry on this volume, and it is
    the number to drive down with better column handling, not to hide.
    """
    modal = modal_letters(rows)
    ranges = leaf_letter_ranges(rows) if (strict or markers) else {}
    heads = heads or {}
    prev, prev_leaf, prev_header = None, None, None
    for i, (leaf, raw) in enumerate(rows):
        if i in heads and (not strict or can_set_carry(heads[i], leaf, ranges)):
            prev, prev_leaf, prev_header = heads[i], leaf, heads[i]
        # The glued test runs FIRST so an opted-in mark is never re-read as something else.
        # Without it a Trow line is INERT rather than wrong: `first_letter` anchors at position 0,
        # the dash is not a letter, so surname_token abstains and is_ditto_lead sees no mark --
        # the row falls through as not_ditto with an empty resolution and the carry is untouched.
        # Measured on trow1913's 93 gold rows: 0 surnames carried without `glued`, 86 with it.
        gl = split_glued_mark(raw, glued)
        mk = None if gl else split_lead_mark(raw, markers)
        if mk:
            sur = surname_token(mk[1])
            if is_ditto_lead(raw) and not (sur and can_set_carry(sur, leaf, ranges)):
                mk = None                              # a ditto after all: fall through
            elif not sur or (strict and not can_set_carry(sur, leaf, ranges)):
                # still the marker's line (`E ACKERMAN T. & J.`, `E De Barr John`), but nothing
                # here may set the carry
                yield {"leaf": leaf, "raw_line": raw, "lead": mk[0], "resolved": "",
                       "status": "not_ditto", "flags": [], "mark": mk[0]}
                continue
            else:
                prev, prev_leaf, prev_header = sur, leaf, None
                yield {"leaf": leaf, "raw_line": raw, "lead": mk[0], "resolved": sur,
                       "status": "not_ditto", "flags": [], "mark": mk[0]}
                continue
        sur = None if gl else surname_token(raw)
        if sur is not None and strict and not can_set_carry(sur, leaf, ranges):
            yield {"leaf": leaf, "raw_line": raw, "lead": sur, "resolved": "",
                   "status": "not_ditto", "flags": []}
            continue
        if sur is not None:
            prev, prev_leaf, prev_header = sur, leaf, None
            yield {"leaf": leaf, "raw_line": raw, "lead": sur, "resolved": sur,
                   "status": "not_ditto", "flags": []}
            continue
        if not gl and not is_ditto_lead(raw):
            yield {"leaf": leaf, "raw_line": raw, "lead": raw.split()[0] if raw.split() else "",
                   "resolved": "", "status": "not_ditto", "flags": []}
            continue

        lead = gl[0] if gl else raw.split()[0]
        flags = []
        if prev is None:
            yield {"leaf": leaf, "raw_line": raw, "lead": lead, "resolved": "",
                   "status": "orphan", "flags": ["orphan"]}
            continue
        if prev_leaf != leaf:
            flags.append("cross_leaf")
        m = modal.get(leaf)
        if m and not m[1] and prev[0].upper() != m[0]:
            flags.append("letter_conflict")
        out = {"leaf": leaf, "raw_line": raw, "lead": lead, "resolved": prev,
               "status": "resolved", "flags": flags}
        if prev_header:
            out["header"] = prev_header
        yield out


# --------------------------------------------------------------------------------------------
# CROSS-LINE: the address channel, the early volumes' SLOT GRAMMAR (PIPELINE.md #8)
#
# Duncan 1794 prints a street type once and dittos it after (the table in the module docstring).
# Each address resolves against the previous line's RESOLVED address, because the type carries
# down a chain: `71 Dey-street.`, then `27 Ann do.` -> `27 Ann-street`, then `11 Rector do.` ->
# `11 Rector-street`. 45 of duncan1794's 58 gold rows sit in such chains. The slots:
#
#     do.              the whole previous address                  (row 51, after `Bowery-lane`)
#     71 do. do.       number; the NAME slot and the TYPE slot      (row 53 -> `71 Roosevelt-street`)
#     30 do.           number; the previous street, name and type   (row 39 -> `30 Warren-street`)
#     27 Ann do.       number and name; the previous street's TYPE  (row 1  -> `27 Ann-street`)
#
# An address with no ditto is its own antecedent. A slot with nothing to fill it is
# `no_antecedent`, never a guess: a type cannot be inherited from `Broadway`.

STREET_TYPES = ("street|lane|slip|alley|road|square|place|row|court|wharf|market|walk|avenue|"
                "dock|yard")
STREET_RX = re.compile(r"^(?:\d+[.,]?\s+)?(?P<name>.+?)(?P<join>[- ])(?P<type>" + STREET_TYPES +
                       r")\.?$", re.IGNORECASE)
SLOT_TWO = re.compile(r"^(?P<num>\d+)[.,]?\s+do\.?\s+do\.?$", re.IGNORECASE)
SLOT_TYPE = re.compile(r"^(?:(?P<num>\d+)[.,]?\s+)?(?P<name>[A-Z][\w'’]*(?:\s[A-Z][\w'’]*)*)"
                       r"\s+do\.?$")


def resolve_address_slot(address: str, prev: str) -> tuple:
    """(resolved, status) for one `address` against the previous line's resolved address.
    Status: not_ditto | resolved_full | resolved_two_slots | resolved_street | resolved_type |
    no_antecedent."""
    a, prev = (address or "").strip(), (prev or "").strip()
    if not a:
        return "", "not_ditto"
    street = STREET_RX.match(prev) if prev else None
    if DITTO_TOKEN.match(a):
        return (prev, "resolved_full") if prev else ("", "no_antecedent")
    m = SLOT_TWO.match(a)
    if m:
        return ((f"{m['num']} {street['name']}{street['join']}{street['type']}",
                 "resolved_two_slots") if street else ("", "no_antecedent"))
    m = NUM_DITTO.match(a)
    if m:
        rest = street_part(prev).rstrip(".")
        return (f"{m['num']} {rest}", "resolved_street") if rest else ("", "no_antecedent")
    m = SLOT_TYPE.match(a)
    if m:
        if not street:
            return "", "no_antecedent"
        num = f"{m['num']} " if m["num"] else ""
        return f"{num}{m['name']}{street['join']}{street['type']}", "resolved_type"
    return a, "not_ditto"


def resolve_address_run(addresses):
    """Yield (resolved, status) for a volume's addresses in reading order, each resolved against
    the last one that resolved. Leaves the model's `address` alone: this is `address_resolved`."""
    prev = ""
    for a in addresses:
        val, status = resolve_address_slot(a, prev)
        if val:
            prev = val
        yield val, status


# --------------------------------------------------------------------------------------------
# loaders -- mirror eval/evaluate.py so the same files work here without conversion


def parse_yaml_block(block: str) -> dict:
    """Minimal `key: "value"` reader for a qwen_predict.py YAML block.

    Deliberately first-key-wins on duplicates, the mirror of evaluate.py's fix: a runaway
    completion emits a truncated SECOND copy of the record, and last-key-wins silently let that
    copy overwrite correct values (HANDOFF: it cost ~12 points of EM and read as a model
    regression). Nothing here should re-introduce that.
    """
    rec = {f: "" for f in FIELDS}
    seen = set()
    for line in block.splitlines():
        m = re.match(r'^\s*([a-z_]+):\s*"(.*)"\s*$', line)
        if not m:
            continue
        key, val = m.group(1), m.group(2)
        if key in rec and key not in seen:
            rec[key] = val.replace('\\"', '"')
            seen.add(key)
    return rec


def load_records(records_path=None, preds_path=None) -> list:
    if records_path:
        return [json.loads(ln)["record"] for ln in open(records_path, encoding="utf-8") if ln.strip()]
    text = open(preds_path, encoding="utf-8").read()
    return [parse_yaml_block(b) for b in re.split(r"\n\s*\n", text) if b.strip()]


# --------------------------------------------------------------------------------------------


def self_test() -> int:
    """Cases drawn from the corpus, NOT invented.

    The HANDOFF post-mortem on the apostrophe regex is explicit about why: a test written from
    imagination confirms the imagined case. `Do-minick` and `910 do` are here because grepping
    the eval files turned them up; neither would have occurred to me.
    """
    fails = []

    def check(label, got, want):
        if got != want:
            fails.append(f"  {label}\n     got  {got!r}\n     want {want!r}")

    # full copy -- boyd1890, the x16 form
    check("full copy",
          resolve_within_line({"address": "3 1-2 Jaggar ave", "home_address": "do"}),
          ("3 1-2 Jaggar ave", "resolved"))
    # polk1925 / polk1933bk / queens1933 all take this path
    check("full copy (polk)",
          resolve_within_line({"address": "633 E169th", "home_address": "do"}),
          ("633 E169th", "resolved"))
    # partial -- polk1917, `h910 do` against `908, 6th av`
    check("partial ditto",
          resolve_within_line({"address": "908, 6th av", "home_address": "910 do"}),
          ("910 6th av", "resolved_part"))
    # THE FALSE POSITIVE the grep caught. Dominick St, hyphenated across a column break.
    check("Do-minick is NOT a ditto",
          resolve_within_line({"address": "52 Reade", "home_address": "12 Do-minick"}),
          ("12 Do-minick", "not_ditto"))
    # ordinary streets that start with the letters d-o must survive untouched
    for street in ("14 Dover", "9 Dodge av", "22 Dougherty"):
        check(f"{street} untouched",
              resolve_within_line({"address": "1 Main", "home_address": street}),
              (street, "not_ditto"))
    # a ditto with nothing to point at is reported, never invented
    check("no antecedent",
          resolve_within_line({"address": "", "home_address": "do"}),
          ("", "no_antecedent"))
    check("no antecedent (partial)",
          resolve_within_line({"address": "", "home_address": "910 do"}),
          ("", "no_antecedent"))
    # empty field
    check("empty", resolve_within_line({"address": "1 Main", "home_address": ""}), ("", "not_ditto"))
    # street_part shapes seen in the corpus
    check("street_part fraction", street_part("3 1-2 Jaggar ave"), "Jaggar ave")
    check("street_part comma", street_part("908, 6th av"), "6th av")
    check("street_part hyphen no", street_part("18-06 Stephen av Rdgwd"), "Stephen av Rdgwd")
    check("street_part no number", street_part("Bowery-lane"), "Bowery-lane")
    # annotate is non-destructive
    a = annotate({"address": "633 E169th", "home_address": "do"})
    check("verbatim preserved", a["home_address"], "do")
    check("resolved added", a["home_address_resolved"], "633 E169th")

    # ---- cross-line, name channel. Lines lifted from 1906BPL and from the assertions in
    # detect_listing_bounds.py, so the two modules cannot drift apart silently.
    check("surname passes", surname_token("Ackerman And'w J foreman h 460 Ralph av"), "Ackerman")
    check("curly apostrophe surname", surname_token("D’Ambra Jos lab h 12 Union"), "D’Ambra")
    for line in ('"        Ann C wid David h 518 Madison',
                 "44       Anna costumes 760 B'way",
                 "do. Ann C wid",
                 "H'y grocer 213 Prince",
                 "Wm elk h 149 Division av"):
        check(f"abstains: {line[:18]}", surname_token(line), None)
    # the four OCR renderings of the same mark, all real lines from the volume
    for line in ('44 John C elk h Webster av n E 3d', '“ Jas W ins h 576 10th',
                 '** Edwin eom’l trav h 588 11th', '" Julius r 131 Av A'):
        check(f"ditto lead: {line[:14]}", is_ditto_lead(line), True)
    check("real entry is not a ditto lead", is_ditto_lead("Ackerman Jos lab h 12 Union"), False)
    check("house number is not a ditto lead", is_ditto_lead("140 Broadway, Borough of Manhattan"), False)

    # --- glued marks (Trow `-Adolph`, Polk `"Thos`). Opt-in: the default must not move. ---
    check("glued mark invisible by default", is_ditto_lead("-Adolph A salesman h68 Lenox av"), False)
    check("glued mark seen when opted in",
          is_ditto_lead("-Adolph A salesman h68 Lenox av", glued=("-",)), True)
    check("glued split", split_glued_mark('"Thos trackmn r69 Swan', ('"',)),
          ('"', "Thos trackmn r69 Swan"))
    check("a mark not in the volume's set stays glued",
          split_glued_mark("*Simmons Aaron, 171 Corcord", ("-",)), None)
    # A glued mark makes the line INERT, not wrong: first_letter anchors at position 0, the dash
    # is not a letter, so the sort key abstains -- and with no mark token there is no ditto
    # either. The row carries nothing and poisons nothing. On trow1913's 93 gold rows that is 0
    # surnames carried; with glued=('-',) it is 86.
    check("glued dash abstains from the sort key",
          surname_token("-Adolph A salesman h68 Lenox av"), None)
    trow = [(1, "Aarons Isaac clothing 27 Ave A"),
            (1, "-Adolph A salesman h68 Lenox av"),
            (1, "-Anna wid Isidor h68 Lenox av")]
    check("inert without the opt-in", [r["status"] for r in resolve_cross_line(trow)],
          ["not_ditto", "not_ditto", "not_ditto"])
    got = list(resolve_cross_line(trow, glued=("-",)))
    check("trow row0 anchors", got[0]["resolved"], "Aarons")
    check("trow glued ditto resolves", (got[1]["status"], got[1]["resolved"]),
          ("resolved", "Aarons"))
    check("trow second glued ditto resolves", got[2]["resolved"], "Aarons")

    # THE REGRESSION THIS DESIGN EXISTS FOR: ogden1839 prints `*` as a RACE DESIGNATION and the
    # surname follows it directly. Gold: race_designation='*', name='Simmons Aaron'. Splitting it
    # as a ditto would destroy the marker AND promote a surname to a given name, 7 of 7 rows.
    ogden = [(1, "Sands Wm. 102 Sands"),
             (1, "*Simmons Aaron, 171 Corcord"),
             (1, "*Simmons James, Weeksville, Bedford")]
    verdicts = classify_glued_marks(ogden, min_n=2)
    check("ogden `*` classified MARKER, not ditto", verdicts["*"]["verdict"], "MARKER")
    # Given names must SPAN the alphabet for the test to work. A contiguous slice of one surname
    # block does not -- `-Adolph`/`-Anna`/`-Arnold` under `Aarons` all vote A and read as MARKER.
    # That is the documented small-sample failure, not a bug; a real leaf spans several blocks.
    trow_v = classify_glued_marks(
        [(1, "Aarons Isaac clothing 27 Ave A"), (1, "Abbott Chas grocer 12 Main"),
         (1, "-Benj B oils 170 W65th"), (1, "-Fred L rugs 303 5th av"),
         (1, "-Maude E h 2333 Bway")], min_n=2)
    check("trow `-` classified DITTO", trow_v["-"]["verdict"], "DITTO")
    narrow = classify_glued_marks(
        [(1, "Aarons Isaac clothing 27 Ave A"), (1, "-Adolph A salesman h68 Lenox av"),
         (1, "-Anna wid Isidor h68 Lenox av")], min_n=2)
    check("a one-block window is NOT enough to classify", narrow["-"]["verdict"], "MARKER")

    seq = [(1, "Ackerman And'w J foreman h 460 Ralph av"),
           (1, '"        Ann C wid David h 518 Madison'),
           (1, "44       Anna costumes 760 B'way"),
           (2, '44 Bertha dressmaker h 9 Grand')]        # carries across the leaf boundary
    got = list(resolve_cross_line(seq))
    check("row0 anchors", (got[0]["status"], got[0]["resolved"]), ("not_ditto", "Ackerman"))
    check("row1 resolves", (got[1]["status"], got[1]["resolved"], got[1]["flags"]),
          ("resolved", "Ackerman", []))
    check("row2 resolves", (got[2]["resolved"], got[2]["flags"]), ("Ackerman", []))
    check("row3 flags cross_leaf", (got[3]["resolved"], got[3]["flags"]),
          ("Ackerman", ["cross_leaf"]))
    # a ditto with nothing before it is an orphan, never a guess
    orph = list(resolve_cross_line([(1, '" Ann C wid David h 518 Madison')]))
    check("orphan", (orph[0]["status"], orph[0]["resolved"]), ("orphan", ""))

    # `strict`: ad copy between two entries of one block is transparent to the carry. The real
    # 1906BPL shape -- leaf 51's bank notice, leaf 26's ad above leaf 27's dittos.
    # (a leaf votes only with alpha_run_filter.MIN_ALPHA_LINES sortable lines, as a real page has)
    a_page = [f"A{s} Wm clk h {n} Hicks" for n, s in enumerate(
        ("aron", "bel", "cker", "dams", "ldridge", "llen", "lvord", "mes", "nders", "ndrews",
         "nthony", "pplegate", "rcher", "rmstrong", "rnold", "shley"))]
    ads = [(5, s) for s in a_page] + [
           (5, "Abbott Geo grocer 9 Fulton"),
           (5, "until Withdrawn."),                       # lowercase: was the carry
           (5, "French and American, all flavors."),      # off-letter on an A leaf: was the carry
           (5, '" Harry engineer h 26 3d')]
    loose = list(resolve_cross_line(ads))
    check("loose: the ad is the carry", loose[-1]["resolved"], "French")
    tight = list(resolve_cross_line(ads, strict=True))
    check("strict: the carry runs past both ad lines",
          (tight[-1]["resolved"], tight[-3]["resolved"], tight[-2]["resolved"]), ("Abbott", "", ""))
    check("strict leaves the ad rows not_ditto", [tight[-3]["status"], tight[-2]["status"]],
          ["not_ditto", "not_ditto"])
    # ...but a real surname still sets it, and a two-letter leaf lets both letters through
    two = [(7, "Baker Ann h 1 Main"), (7, "Bell Jos h 2 Main"), (7, "Carr Wm h 3 Main"),
           (7, "Cole Jas h 4 Main"), (7, '" Mary h 5 Main')]
    check("strict on a two-letter leaf", list(resolve_cross_line(two, strict=True))[4]["resolved"],
          "Cole")
    # THE REGRESSION THE RANGES EXIST FOR (1906BPL leaf 20): an A page whose Allen block lost its
    # ditto marks votes J on its given names. Its own vote would refuse `Allen`; the run of
    # leaves around it says A, so Allen sets the carry and `Jas foreman` does not.
    allen = ([(lf, s) for lf in (16, 17, 18, 19) for s in a_page]
             + [(20, "Allegretti Jos h 1 Pine"), (20, "Allen Abram h 131")]
             + [(20, f"Jas {w} h {n} High") for n, w in enumerate(
                 ("foreman", "machinist", "printer", "salesman", "tailor", "clk", "carpr", "mason",
                  "painter", "porter", "grocer", "baker", "barber", "cooper", "driver", "agt"))]
             + [(20, '" Arthur W painter h 1176 Madison')]
             + [(lf, s) for lf in (21, 22, 23) for s in a_page])
    got = list(resolve_cross_line(allen, strict=True))
    check("leaf 20: its neighbours' letters, not its own vote",
          got[4 * len(a_page) + 18]["resolved"], "Allen")
    check("leaf 20's own vote was J", modal_letters(allen)[20][0], "J")
    # a second alphabet (0036's Eastern District): the restart widens the span, never blocks it
    restart = ([(lf, s) for lf in range(1, 6) for s in [f"W{t} Jas h 1 Main" for t in (
        "ade", "agner", "alker", "allace", "alsh", "ard", "arner", "arren", "atson", "eaver",
        "ebb", "eber", "ells", "elsh", "est", "hite")]] + [(lf, s) for lf in range(6, 11)
                                                          for s in a_page])
    rng = leaf_letter_ranges(restart)
    check("past a restart the new run's own letter is allowed", rng[8], ("A", "A"))
    check("at the seam the span is wide, not wrong", rng[6][0] <= "A" and rng[6][1] >= "W", True)
    # `markers`: the Eastern District E (0039/0040/0042) and its misreadings, measured not assumed
    c_page = [f"C{s} Wm h {n} Main" for n, s in enumerate(
        ("able", "ain", "ald", "alder", "all", "amp", "ane", "arr", "arter", "ase", "ass", "ole",
         "ook", "ox", "rane", "ross"))]
    east = ([(lf, s) for lf in (1, 2, 3) for s in c_page]
            + [(2, f"E C{s} Jas, carman, h. {n} Grand") for n, s in enumerate(
                ("able", "ain", "ald", "alder", "all", "amp", "ane", "arr", "arter", "ase",
                 "ass", "ole", "ook", "ox", "rane", "ross", "uff", "urtis", "ady", "elk"))]
            + [(2, "“Coxe George, lager beer, Graham av."), (2, '" Mary wid h 3 Main')])
    verdicts = classify_lead_marks(east)
    check("E is a MARKER", verdicts["E"]["verdict"], "MARKER")
    check("too few `“` to call", verdicts["“"]["verdict"], "UNDECIDED")
    got = list(resolve_cross_line(east, strict=True, markers=("E", "“", '"')))
    e_row = len(c_page) * 3                     # the first E line
    check("an E line sets the carry from its surname", (got[e_row]["resolved"],
                                                        got[e_row]["mark"]), ("Cable", "E"))
    check("a glued quote is the E misread", (got[-2]["resolved"], got[-2]["mark"]),
          ("Coxe", "“"))
    check("a spaced quote before an off-letter given name is still a ditto",
          (got[-1]["status"], got[-1]["resolved"]), ("resolved", "Coxe"))
    check("no markers, no change", [g.get("mark") for g in resolve_cross_line(east)][e_row],
          None)
    # the column rule's readings are judged together: 12 `|` + 12 `I` clear min_n only as one;
    # a digit is never pooled (in an ABBYY volume it is usually the ditto)
    rule = ([(lf, s) for lf in (1, 2, 3) for s in c_page]
            + [(2, f"{g} C{s} Wm h {n} Main") for g in ("|", "I", "1") for n, s in enumerate(
                ("able", "ain", "ald", "alder", "all", "amp", "ane", "arr", "arter", "ase", "ass",
                 "ole"))])
    rv = classify_lead_marks(rule)
    check("column rule pooled", (rv["|"]["verdict"], rv["I"]["verdict"], rv["I"]["class"]),
          ("MARKER", "MARKER", "column rule"))
    check("a digit is judged alone", (rv["1"]["class"], rv["1"]["verdict"]), ("1", "UNDECIDED"))
    caps = list(resolve_cross_line(east + [(2, "E ACKERMAN T. & J. boiler works, 9 Grand")],
                                   strict=True, markers=("E",)))
    stacked = list(resolve_cross_line(east + [(2, "E *Cotter William J. seaman, h. N. 8th")],
                                      strict=True, markers=("E", "*")))
    check("stacked marks: E and the race designation", (stacked[-1]["mark"],
                                                        stacked[-1]["resolved"]), ("E *", "Cotter"))
    check("an E before an ALL-CAPS business is still the mark",
          (caps[-1]["mark"], caps[-1]["resolved"], caps[-1]["status"]), ("E", "", "not_ditto"))

    # `heads`: the dropped ALL-CAPS header becomes the carry just before its follower
    hd = [(27, "Abbott Geo grocer 9 Fulton"), (27, "Allen Jas mason h 3 Court"),
          (27, '" Harry engineer h 26 3d'), (27, '" Hedwig physician h 1544 Bergen')]
    got = list(resolve_cross_line(hd, heads={2: "Anderson"}, strict=True))
    check("header carries", [(g["resolved"], g.get("header")) for g in got[2:]],
          [("Anderson", "Anderson"), ("Anderson", "Anderson")])
    check("a header changes nothing above it", got[1].get("header"), None)
    got = list(resolve_cross_line(hd + [(27, "Archer Wm h 7 Pine"), (27, '" Ann h 8 Pine')],
                                  heads={2: "Anderson"}))
    check("the next real surname ends the header's run", (got[5]["resolved"], got[5].get("header")),
          ("Archer", None))

    # the address slot grammar, on duncan1794's gold addresses in their printed order
    duncan = ["71 Dey-street.", "27 Ann do.", "11 Rector do.", "30 Ferry-street", "Mott do.",
              "13 Warren-street.", "13 do", "13 Warren do.", "30 do.", "19 Water do.", "169 do.",
              "Bowery-lane", "do.", "73 Roosevelt-street.", "71 do. do.", "31 James's do."]
    got = list(resolve_address_run(duncan))
    check("type slot", got[1], ("27 Ann-street", "resolved_type"))
    check("type carries down the chain", got[2], ("11 Rector-street", "resolved_type"))
    check("type slot, no number", got[4], ("Mott-street", "resolved_type"))
    check("number + street", got[6], ("13 Warren-street", "resolved_street"))
    check("number + street, after a resolved one", got[8], ("30 Warren-street", "resolved_street"))
    check("169 do.", got[10], ("169 Water-street", "resolved_street"))
    check("do. = the whole address", got[12], ("Bowery-lane", "resolved_full"))
    check("two slots", got[14], ("71 Roosevelt-street", "resolved_two_slots"))
    check("a possessive name", got[15], ("31 James's-street", "resolved_type"))
    check("no type to inherit", resolve_address_slot("27 Ann do.", "Broadway"),
          ("", "no_antecedent"))
    check("Do-minick is a street", resolve_address_slot("12 Do-minick", "71 Dey-street"),
          ("12 Do-minick", "not_ditto"))

    if fails:
        print("SELF-TEST FAILED\n" + "\n".join(fails), file=sys.stderr)
        return 1
    print("self-test OK")
    return 0


def cross_line_report(lines_path: str, want_inventory: bool, out_path=None, glued=()) -> int:
    """Run the name carry over a whole volume and report what it did, honestly.

    Prints the two dispute rates side by side rather than a single accuracy number, because on
    1906BPL they disagree about which rows are wrong (28% overlap) and an aggregate would hide
    that. Nothing is written back into a record here -- this stage produces a review queue.
    """
    rows = []
    with open(lines_path, encoding="utf-8") as fh:
        for ln in fh:
            if ln.strip():
                r = json.loads(ln)
                rows.append((r["context"]["leaf"], r["raw_line"]))
    rows.sort(key=lambda lr: lr[0])                    # stable: emission order survives in-leaf

    if want_inventory:
        print(f"{len(rows):,} lines — leading-token distribution:\n")
        for tok, n in inventory([r for _, r in rows]):
            mark = "  <- ditto?" if tok != "<SURNAME-SHAPED>" and DITTO_LEADERS.match(tok) else ""
            print(f"  {n:>8,}  {tok!r}{mark}")
        gl = classify_glued_marks(rows)
        print("\nGLUED leading marks (printed with no space, so nothing tokenises as a mark):")
        if not gl:
            print("  none")
        for mk, d in sorted(gl.items(), key=lambda kv: -kv[1]["n"]):
            share = d.get("share_follower_is_sort_key")
            print(f"  {mk!r:>6}  n={d['n']:<6} follower is the sort key "
                  f"{'--' if share is None else format(share, '.0%'):>4}  -> {d['verdict']}")
            for ex in d["examples"][:2]:
                print(f"          {ex!r}")
        if any(d["verdict"] == "DITTO" for d in gl.values()):
            marks = " ".join(m for m, d in gl.items() if d["verdict"] == "DITTO")
            print(f"\n  re-run with --glued-marks '{marks}' to carry these. A MARKER verdict "
                  "means the\n  follower IS the surname (ogden1839's `*` is a race designation) "
                  "-- do not pass it.")
        return 0

    res = list(resolve_cross_line(rows, glued))
    dittos = [r for r in res if r["status"] in ("resolved", "orphan")]
    cross = [r for r in dittos if "cross_leaf" in r["flags"]]
    conflict = [r for r in dittos if "letter_conflict" in r["flags"]]
    both = [r for r in dittos if len(r["flags"]) >= 2 and "orphan" not in r["flags"]]
    orphan = [r for r in dittos if r["status"] == "orphan"]
    disputed = [r for r in dittos if r["flags"]]

    print(f"{len(rows):,} lines, {len(dittos):,} ditto-lead ({len(dittos)/len(rows):.1%})")
    print(f"  carried to an antecedent : {len(dittos)-len(orphan):,}")
    print(f"  orphan (no antecedent)   : {len(orphan):,}")
    print(f"\n  DISPUTED by at least one check : {len(disputed):,} ({len(disputed)/len(dittos):.1%} of dittos)")
    print(f"    cross_leaf     : {len(cross):,}")
    print(f"    letter_conflict: {len(conflict):,}")
    print(f"    both           : {len(both):,}   <- the two checks are NOT redundant")
    print("\n  sample of clean resolutions:")
    for r in [x for x in dittos if not x["flags"]][:5]:
        print(f"    leaf {r['leaf']:<5} {r['lead']!r:6} -> {r['resolved']!r:14} {r['raw_line'][:44]!r}")
    print("\n  sample of DISPUTED (review queue):")
    for r in disputed[:5]:
        print(f"    leaf {r['leaf']:<5} {r['lead']!r:6} -> {r['resolved']!r:14} {','.join(r['flags'])}")
        print(f"       {r['raw_line'][:66]!r}")

    if out_path:
        with open(out_path, "w", encoding="utf-8") as fh:
            for r in res:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"\nwrote {out_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--records", help="JSONL with a `record` key (any data/*_eval.jsonl)")
    ap.add_argument("--preds", help="qwen_predict.py YAML predictions")
    ap.add_argument("--lines", help="a *_lines.jsonl (raw_line + context.leaf) for the CROSS-LINE pass")
    ap.add_argument("--glued-marks", default="",
                    help="space- or comma-separated marks this volume glues to the next token "
                         "(Trow: '-'). Run --inventory FIRST: a mark the classifier calls MARKER "
                         "is not a ditto and must not be passed here.")
    ap.add_argument("--inventory", action="store_true",
                    help="with --lines: dump the leading-token distribution and exit. Run this on "
                         "any new volume before trusting DITTO_LEADERS.")
    ap.add_argument("--out", help="write annotated records as JSONL")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    if args.lines:
        glued = tuple(m for m in re.split(r"[,\s]+", args.glued_marks) if m)
        return cross_line_report(args.lines, args.inventory, args.out, glued)
    if not (args.records or args.preds):
        ap.error("need --records, --preds, --lines or --self-test")

    recs = load_records(args.records, args.preds)
    ann = [annotate(r) for r in recs]

    counts = {}
    for a in ann:
        counts[a["ditto_status"]] = counts.get(a["ditto_status"], 0) + 1
    total = len(ann)
    print(f"{total:,} records")
    for status in ("resolved", "resolved_part", "no_antecedent", "not_ditto"):
        n = counts.get(status, 0)
        if n:
            print(f"  {status:<14} {n:>7,}  ({n/total:.2%})")

    shown = 0
    for a in ann:
        if a["ditto_status"].startswith("resolved") and shown < 8:
            print(f"    {a.get('name','')!r:22} address={a.get('address','')!r} "
                  f"home={a['home_address']!r} -> {a['home_address_resolved']!r}")
            shown += 1

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            for a in ann:
                fh.write(json.dumps(a, ensure_ascii=False) + "\n")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
