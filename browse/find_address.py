#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["duckdb==2.0.0"]
# ///
"""
Every line of the records that may give an address, OCR misreadings included, with a link to
check them in the browser (browse/README.md).

    uv run browse/find_address.py "166 Lefferts pl"
    uv run browse/find_address.py "166 Lefferts pl" --people     # also trace who lived there
    python3 browse/find_address.py --self-test

It searches the address finder's records Parquet (data/space/records.parquet, which
space/build_parquet.py makes from data/browse.db) with the finder's own search (space/search.py),
so the two give the same lines: one copy of a volume loaded twice, the eval_holdout rows left
out. This file holds the readers both use.

A "contains" filter both misses and over-matches: it skips a misread line, and "6 Lefferts" is
in "56 Lefferts". This reads the word index's word list instead -- the street word's
spellings within --dist edits (Leflerts, Lefferta) and the number's look-alikes (I66, l6G) --
then reads every line holding one as number-then-street, in raw_line and the two resolved
address columns, rejoining a street the OCR split (Lef-ferts, Lef ferts). A line that ends on
the number is read on into the next line of its leaf.

Each line gets the best of these grades:
  exact     the number and the street as asked
  street    the number as asked, the street misspelled or split
  number    the number in look-alike characters (I66), the street within --dist
  wrapped   the number at the end of a line, the street at the start of the next
  near      one digit off (106, 165, 16): usually a real neighbour, sometimes a misread
and a note where the line names another street type (166 Lefferts av when asked for pl) or
direction (131 E 110th when asked for West), which is a different street, not a misreading. A
direction left out of a line is no difference. A numbered street (110th, 3d) matches by its digits
with look-alikes folded (11Oth), never by edits: 111th is another street. A near line whose name (SAME NAME) or surname (SURNAME)
is at the address in another volume is flagged, with a link to just those: the same household
one digit off is the likeliest misread.

--people looks up each person found at the address in every volume. A year whose line read the
address too badly to match shows up as that person at another address, or missing. A line that
is probably a namesake says why (search.Records.residents).
"""
from __future__ import annotations

import argparse
import collections
import re
import sys
import time
import urllib.parse
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "data" / "browse.db"
PARQUET = REPO / "data" / "space" / "records.parquet"
BASE = "http://127.0.0.1:8001/browse/records"
GRADES = ["exact", "street", "number", "wrapped", "near"]
# characters OCR reads for digits, folded to them (the FTS words are lowercased)
FOLD = str.maketrans({"i": "1", "l": "1", "I": "1", "|": "1", "!": "1", "]": "1", "o": "0",
                      "O": "0", "g": "6", "G": "6", "b": "6", "s": "5", "S": "5", "B": "8",
                      "z": "2", "Z": "2"})
FIELDS = ["raw_line", "address_resolved", "home_address_resolved"]
LINK_IDS = 150          # record ids per link: a longer URL is past the server's request-line limit
COMMON_SHARE = 0.25     # a spelling this common relative to the street word is another street
DIRECTIONS = {"w": "w", "west": "w", "e": "e", "east": "e", "n": "n", "north": "n", "s": "s",
              "south": "s"}


def lev(a: str, b: str, cap: int = 99) -> int:
    """Edit distance, giving up (cap + 1) once every path is past `cap`."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def street_type(word: str) -> str:
    """pl / av / st / ... from how a line spells it (pi and p1 are pl misread); '' if none."""
    w = re.sub(r"[^a-z0-9]", "", word.lower())
    if not w:
        return ""
    if w in ("pl", "pi", "p1", "place", "plc", "pi1") or (w[0] == "p" and len(w) <= 3):
        return "pl"
    if w in ("av", "ave", "avenue", "a") or (w[0] == "a" and w[1:2] == "v"):
        return "av"
    if w in ("st", "street", "s", "sl", "8t") or w.startswith("str"):
        return "st"
    for t in ("rd", "ct", "sq", "ter", "al", "la", "dr", "blvd", "road", "court", "square",
              "terrace", "alley", "lane", "drive"):
        if w == t:
            return t[:2]
    return ""


def parse(address: str):
    """'166 Lefferts pl' -> ('166', ['lefferts'], 'pl'); a direction leads the words, as one
    letter: '131 West 110th st' -> ('131', ['w', '110th'], 'st')"""
    toks = address.split()
    if len(toks) < 2 or not toks[0].isdigit():
        raise SystemExit(f'give a house number and a street: "166 Lefferts pl", not {address!r}')
    kind = street_type(toks[-1]) if len(toks) > 2 else ""
    words = [re.sub(r"[^a-z0-9]", "", t.lower()) for t in (toks[1:-1] if kind else toks[1:])]
    words = [w for w in words if w]
    if len(words) > 1 and words[0] in DIRECTIONS:
        words[0] = DIRECTIONS[words[0]]
    return toks[0], words, kind


def split_direction(words: list) -> tuple:
    """(direction, the street's own words): ('w', ['110th']) from ['w', '110th']"""
    if len(words) > 1 and words[0] in DIRECTIONS.values():
        return words[0], words[1:]
    return "", words


def anchor_of(words: list) -> str:
    """The word a line is matched on: the street's longest ('kalb' of De Kalb)."""
    return max(split_direction(words)[1], key=len)


def ordinal(word: str) -> str | None:
    """A numbered street's digits, look-alikes folded: '110th' and '11oth' -> '110'; None for a
    word that is not one. 110th and 111th are different streets, so these are never fuzzed."""
    m = re.fullmatch(r"([0-9ilogbsz|]+?)(st|nd|rd|th|d|h|t)?", word)
    if not m or not any(c.isdigit() for c in m.group(1)):
        return None
    f = m.group(1).translate(FOLD)
    return f if f.isdigit() else None


def as_number(tok: str) -> str | None:
    """A line's token as a house number, look-alikes folded ('I66' -> '166', 'h186' -> '186');
    None unless it holds a real digit."""
    t = tok.strip(".:;,'\"()")
    if len(t) > 1 and t[0] in "hr" and t[1:].translate(FOLD).isdigit():    # h166, hl66
        t = t[1:]
    if not any(c.isdigit() for c in t):
        return None
    f = t.translate(FOLD)
    return f if f.isdigit() and len(f) <= 5 else None


def street_dist(anchor: str, dist: int) -> int:
    """The edits allowed in the street word: `dist`, but 1 below eight letters -- two edits turn
    Forest into First and Fulton into Milton."""
    return min(dist, 1 if len(anchor) < 8 else 2 if len(anchor) < 12 else 3)


def match_tokens(toks: list, number: str, words: list, kind: str, dist: int, cut: int | None = None,
                 skip=frozenset()):
    """The best reading of number-then-street in `toks` as (grade, how, note, tail) or None;
    `note` names what makes it another street: another type (av for pl) or direction (E for W);
    `tail` is the three tokens after the street and its type, where a place marker goes. `cut`
    is where the second of two lines starts: only a reading across it counts (grade wrapped).
    `skip` is spellings that are other streets (other_streets). A direction in the line is
    optional: "131 110th" may be West 110th."""
    direction, street = split_direction(words)
    anchor = anchor_of(words)
    k = street.index(anchor)
    numbered = ordinal(anchor)
    dist = street_dist(anchor, dist)
    clean = lambda t: re.sub(r"[^a-z0-9]", "", t.lower())   # noqa: E731
    best = None
    for i, tok in enumerate(toks):
        if cut is not None and not cut - 2 <= i < cut:     # the number ends the first line
            continue
        n = as_number(tok)
        if n is None:
            continue
        raw = tok.strip(".:;,'\"()")
        if raw[:1] in ("h", "r") and raw[1:].translate(FOLD).isdigit():
            raw = raw[1:]
        if raw == number:
            ngrade = "exact"
        elif n == number:
            ngrade = "number"
        elif lev(n, number, 1) == 1:
            ngrade = "near"
        else:
            continue
        start, line_dir = i + 1, ""
        if start + 1 < len(toks) and clean(toks[start]) in DIRECTIONS:
            line_dir = DIRECTIONS[clean(toks[start])]
            start += 1
        j = start + k
        if j >= len(toks):
            continue
        options = [(clean(toks[j]), j)]
        if j + 1 < len(toks):
            options.append((clean(toks[j]) + clean(toks[j + 1]), j + 1))
        for s, end in options:
            if numbered:
                if ordinal(s) != numbered:
                    continue
                d = 0 if s == anchor else 1
            else:
                d = lev(s, anchor, dist)
                if d > dist or s in skip:
                    continue
                # a word rejoined from two is held to one edit unless the first part ends in a
                # hyphen: "John, N." is not Johnson
                if end > j and d > 1 and not toks[j].endswith("-"):
                    continue
            if cut is not None and end < cut:
                continue
            if cut is not None:
                grade = "wrapped" if ngrade != "near" else "near"
            elif ngrade == "exact":
                grade = "exact" if s == anchor and end == j else "street"
            else:
                grade = ngrade
            line_kind = street_type(toks[end + 1]) if end + 1 < len(toks) else ""
            # another direction is another street when one was asked for, or the street is
            # named (W Broadway); "131 110th st" asks for either side
            other_dir = line_dir and line_dir != direction and (direction or not numbered)
            note = " ".join(x for x in (
                line_dir.upper() if other_dir else "",
                line_kind if kind and line_kind and line_kind != kind else "") if x)
            after = end + 1 + (1 if line_kind else 0)
            tail = " ".join(toks[after:after + 3])      # where a place marker would be: "Bklyn"
            cand = (GRADES.index(grade), d, grade, f"{tok} {' '.join(toks[j:end + 1])}", note, tail)
            if best is None or cand[:2] < best[:2]:
                best = cand
    return best and best[2:]


def other_streets(streets: list, anchor: str) -> tuple:
    """(kept, dropped) of [(term, count)]: a spelling at least COMMON_SHARE as common as the
    street word itself is another street, not a misreading of it -- Classon for Clarkson,
    Monroe for Montrose, both two edits off. A numbered street's spellings all fold to its own
    digits, so none is dropped."""
    if ordinal(anchor):
        return streets, []
    own = max([n for t, n in streets if t == anchor], default=0)
    kept = [(t, n) for t, n in streets if t == anchor or n < COMMON_SHARE * own or own < 20]
    return kept, [s for s in streets if s not in kept]


def best_reading(r, number: str, words: list, kind: str, dist: int, skip=frozenset()):
    """The best grade any of a row's FIELDS gives, as match_tokens returns it, or None."""
    best = None
    for f in FIELDS:
        m = match_tokens((r[f] or "").split(), number, words, kind, dist, skip=skip)
        if m and (best is None or GRADES.index(m[0]) < GRADES.index(best[0])):
            best = m
    return best


def read_wrapped(r, next_raw: str, number: str, words: list, kind: str, dist: int,
                 skip=frozenset()):
    toks = (r["raw_line"] or "").split()
    return match_tokens(toks + (next_raw or "").split(), number, words, kind, dist, cut=len(toks),
                        skip=skip)


def links(base: str, ids: list) -> list:
    return [base + "?" + urllib.parse.urlencode({"record_id__in": ",".join(ids[i:i + LINK_IDS]),
                                                 "_sort": "year", "_size": "max"})
            for i in range(0, len(ids), LINK_IDS)]


def name_of(r) -> tuple:
    return tuple(re.sub(r"[^a-z ]", "", (r["name_resolved"] or "").lower()).split())


def residents_at(hits: list) -> set:
    """The names on the lines that give the address (every grade but near, same street type)."""
    return {name_of(h) for (g, _, n, *_), h in hits if g != "near" and not n and len(name_of(h)) >= 2}


def flag_of(grade: str, note: str, r, at: set) -> str:
    """OTHER STREET (<note>) for another street type or direction; for a near line, SAME NAME or
    SURNAME when that person, or their surname, is at the address in some other volume (`at`:
    residents_at) -- the same household one digit off is more likely a misread than a move."""
    if note:
        return f"OTHER STREET ({note})"
    if grade != "near" or len(name_of(r)) < 2:        # "119 Fulton" in the name field is no name
        return ""
    return ("SAME NAME" if name_of(r) in at
            else "SURNAME" if name_of(r)[0] in {n[0] for n in at} else "")


def report(res: dict, base: str, people: bool, dist: int):
    """Print a search.Records.find result: the spellings searched, each grade's lines with a link
    to them in the browser, and with --people each traced person's lines."""
    print(f"street words within {street_dist(res['anchor'], dist)} of {res['anchor']!r}: "
          + ", ".join(f"{t} ({n})" for t, n in sorted(res["streets"], key=lambda x: -x[1])[:40])
          + (" ..." if len(res["streets"]) > 40 else ""))
    if res["dropped"]:
        print("not searched, as common as another street: "
              + ", ".join(f"{t} ({n})" for t, n in res["dropped"]))
    print(f"number forms of {res['number']}: " + ", ".join(f"{t} ({n})" for t, n in res["numbers"]))
    by = collections.defaultdict(list)
    for h in res["hits"]:
        by[h["grade"]].append(h)
    for g in GRADES:
        if not by[g]:
            continue
        print(f"\n== {g}: {len(by[g])} ==")
        for h in by[g]:
            print(f"{h['year']} {h['record_id']:40} u={h['usable']} {h['how']!r:24} {h['flag']:9} "
                  f"{(h['raw_line'] or '')[:90]}")
        for url in links(base, [h["record_id"] for h in by[g]]):
            print(url)
        if g == "near":
            look = [h["record_id"] for h in by[g] if h["flag"]]
            if look:
                print(f"near lines whose name or surname is at the address elsewhere ({len(look)}):")
                for url in links(base, look):
                    print(url)
    if not people:
        return
    print("\n== the people at it, in every volume ==")
    for name, lines in res["people"].items():
        print(f"\n{name}")
        for p in lines:
            print(f"  {p['year']} {p['record_id']:40} {p['grade']:7} {p['left_out'] or '':24} "
                  f"{(p['raw_line'] or '')[:80]}")


def self_test():
    words = ["lefferts"]
    m = lambda s, cut=None: match_tokens(s.split(), "166", words, "pl", 2, cut)  # noqa: E731
    assert m("Crowell W. R. ins. h 166 Lefferts pl")[:1] == ("exact",)
    assert m("Cotte J h 166 Lef-ferts pl")[0] == "exact", "a hyphen within the word is no misreading"
    assert m("Cotte J h 166 Lef ferts pl")[0] == "street"
    assert m("Cotte J h I66 Leflerts pi")[0] == "number"
    assert m("Cotte J h186 Lefferts pl")[0] == "near"
    assert m("Cotte J h 6 Lefferts pl") is None, "two digits off is another house"
    assert m("Lemcke Albert h 166 Lefferts av")[2] == "av", "another street type is noted"
    assert m("Cotte J h 166 Lefferts")[2] == "", "no type in the line is no note"
    line, nxt = "Cotte Josephine L h 166".split(), "Lefferts pl".split()
    assert m(" ".join(line + nxt), cut=len(line))[0] == "wrapped"
    assert m("Jones h 166 Lefferts pl and 4 Main", cut=6) is None, "within one line is not a wrap"
    line = "Mills Abraham painter h 151 Lorimer".split()
    assert m(" ".join(line + '" Alex soapmkr h 166 Lefferts pl'.split()), cut=len(line)) is None, \
        "the address on the next line alone is not a wrap"
    assert match_tokens(
        "h 151 Classon av".split(), "151", ["clarkson"], "av", 2, skip={"classon"}) is None
    assert match_tokens("Archer h 32 John, N. Y.".split(), "32", ["johnson"], "av", 2) is None
    assert match_tokens("h 924 First av".split(), "924", ["forest"], "av", 2) is None, \
        "a six-letter street gets one edit"
    assert match_tokens("h 924 Forst av".split(), "924", ["forest"], "av", 2)[0] == "street"
    w110 = lambda s, cut=None: match_tokens(s.split(), "131", ["w", "110th"], "st", 2, cut)  # noqa
    assert parse("131 West 110th st") == ("131", ["w", "110th"], "st")
    assert parse("12 South st") == ("12", ["south"], "st"), "a one-word street is no direction"
    assert ordinal("110th") == ordinal("11oth") == ordinal("110") == "110" and ordinal("west") is None
    assert ordinal("21st") == "21" and ordinal("52d") == "52"
    assert w110("Smith John clerk h 131 W 110th")[0] == "exact"
    assert w110("Smith John h 131 West 110th st")[0] == "exact"
    assert w110("Smith John h 131 110th")[0] == "exact", "the direction may be left out"
    assert w110("Smith John h 131 W 11Oth")[0] == "street"
    assert w110("Smith John h 131 W 111th") is None, "111th is another street, never a misreading"
    assert w110("Smith John h 131 E 110th")[2] == "E", "East 110th is another street"
    assert w110("Smith John h 131 W 110th av")[2] == "av"
    assert match_tokens("Smith h 131 E 110th".split(), "131", ["110th"], "st", 2)[2] == "", \
        "no direction asked: either side"
    assert w110("Smith John h 131 Westervelt av") is None
    assert match_tokens("Jones h 12 W Broadway".split(), "12", ["broadway"], "", 2)[2] == "W", \
        "West Broadway is not Broadway"
    assert other_streets([("110th", 900), ("110", 30000)], "110th") == \
        ([("110th", 900), ("110", 30000)], [])
    assert other_streets([("clarkson", 400), ("classon", 3000), ("clarkon", 3)], "clarkson") == \
        ([("clarkson", 400), ("clarkon", 3)], [("classon", 3000)])
    assert parse("166 Lefferts pl") == ("166", ["lefferts"], "pl")
    assert parse("12 De Kalb av") == ("12", ["de", "kalb"], "av")
    assert m("h 166 Lefferts pl")[1] == "166 Lefferts"
    assert m("Jas mech eng 220 Bway h 166 Lefferts pl Bklyn")[3] == "Bklyn"
    assert m("Wm H banker 683 B'way Mhtn h 166 Lefferts pl")[3] == "", "Mhtn is the other address's"
    assert match_tokens("h 12 De Kalb av".split(), "12", ["de", "kalb"], "av", 1)[0] == "exact"
    assert as_number("h166") == "166" and as_number("lGG") is None and as_number("l6G") == "166"
    assert as_number("hl66") == "166" and m("Cotte J hl66 Lefferts pl")[0] == "number"
    print("self-test ok")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("address", nargs="?", help='a house number and a street: "166 Lefferts pl"')
    ap.add_argument("--dist", type=int, default=2,
                    help="edits allowed in the street word (default 2; 1 for a short word)")
    ap.add_argument("--people", action="store_true", help="trace each person found at it")
    ap.add_argument("--parquet", default=str(PARQUET),
                    help="the records (space/build_parquet.py), with records.words.parquet beside")
    ap.add_argument("--base", default=BASE, help="the records table's URL in the browser")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        self_test()
        return 0
    if not a.address:
        ap.error("give an address")
    parquet = Path(a.parquet)
    if not parquet.exists():
        raise SystemExit(f"{parquet} is missing: make it with `uv run space/build_parquet.py`")
    if DB.exists() and DB.stat().st_mtime > parquet.stat().st_mtime:
        print(f"note: {DB.name} is newer than {parquet.name}; lines loaded since are not searched "
              "(`uv run space/build_parquet.py`)", file=sys.stderr)
    sys.path.insert(0, str(REPO / "space"))
    import search                                 # DuckDB; the readers above need nothing
    t = time.time()
    res = search.Records(str(parquet), memory=False).find(a.address, a.dist, people=a.people)
    report(res, a.base, a.people, a.dist)
    print(f"\n{len(res['hits']):,} lines in {time.time() - t:.1f} s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
