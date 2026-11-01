#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Every line in data/browse.db that may give an address, OCR misreadings included, with a link to
check them in the browser (browse/README.md).

    python3 browse/find_address.py "166 Lefferts pl"
    python3 browse/find_address.py "166 Lefferts pl" --people     # also trace who lived there
    python3 browse/find_address.py --self-test

A "contains" filter both misses and over-matches: it skips a misread line, and "6 Lefferts" is
in "56 Lefferts". This reads the full-text index's word list instead -- the street word's
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
and a note where the line names another street type (166 Lefferts av when asked for pl), which
is a different street, not a misreading. A near line whose name (SAME NAME) or surname (SURNAME)
is at the address in another volume is flagged, with a link to just those: the same household
one digit off is the likeliest misread.

--people looks up each person found at the address in every volume. A year whose line read the
address too badly to match shows up as that person at another address, or missing.

Reads the database only; Datasette can keep serving it.
"""
from __future__ import annotations

import argparse
import collections
import re
import sqlite3
import sys
import urllib.parse
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "data" / "browse.db"
BASE = "http://127.0.0.1:8001/browse/records"
GRADES = ["exact", "street", "number", "wrapped", "near"]
# characters OCR reads for digits, folded to them (the FTS words are lowercased)
FOLD = str.maketrans({"i": "1", "l": "1", "I": "1", "|": "1", "!": "1", "]": "1", "o": "0",
                      "O": "0", "g": "6", "G": "6", "b": "6", "s": "5", "S": "5", "B": "8",
                      "z": "2", "Z": "2"})
FIELDS = ["raw_line", "address_resolved", "home_address_resolved"]
LINK_IDS = 150          # record ids per link: a longer URL is past the server's request-line limit


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
    """'166 Lefferts pl' -> ('166', ['lefferts'], 'pl')"""
    toks = address.split()
    if len(toks) < 2 or not toks[0].isdigit():
        raise SystemExit(f'give a house number and a street: "166 Lefferts pl", not {address!r}')
    kind = street_type(toks[-1]) if len(toks) > 2 else ""
    words = [re.sub(r"[^a-z]", "", t.lower()) for t in (toks[1:-1] if kind else toks[1:])]
    return toks[0], [w for w in words if w], kind


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


def match_tokens(toks: list, number: str, words: list, kind: str, dist: int, cut: int | None = None):
    """The best reading of number-then-street in `toks` as (grade, how, type) or None. `cut` is
    where the second of two lines starts: only a reading across it counts (grade wrapped)."""
    anchor = max(words, key=len)
    k = words.index(anchor)
    best = None
    for i, tok in enumerate(toks):
        if cut is not None and i < cut - 2:
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
        j = i + 1 + k
        if j >= len(toks):
            continue
        clean = lambda t: re.sub(r"[^a-z]", "", t.lower())   # noqa: E731
        options = [(clean(toks[j]), j)]
        if j + 1 < len(toks):
            options.append((clean(toks[j]) + clean(toks[j + 1]), j + 1))
        for s, end in options:
            d = lev(s, anchor, dist)
            if d > dist:
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
            note = "" if not kind or not line_kind or line_kind == kind else line_kind
            cand = (GRADES.index(grade), d, grade, f"{tok} {' '.join(toks[j:end + 1])}", note)
            if best is None or cand[:2] < best[:2]:
                best = cand
    return best and best[2:]


def vocab_terms(con, number: str, anchor: str, dist: int):
    """The index's words that may be the street word or the number."""
    con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp.vocab USING fts5vocab(main, records_fts, row)")
    streets, numbers = [], []
    lo, hi = min(len(anchor) - dist, len(number) - 1), max(len(anchor) + dist, len(number) + 2)
    for term, n in con.execute("SELECT term, doc FROM temp.vocab WHERE length(term) BETWEEN ? AND ?",
                               (lo, hi)):
        if term.isalpha() and abs(len(term) - len(anchor)) <= dist and lev(term, anchor, dist) <= dist:
            streets.append((term, n))
        elif as_number(term) == number:
            numbers.append((term, n))
    return streets, numbers


def fts_rows(con, terms: list) -> dict:
    out = {}
    for i in range(0, len(terms), 200):
        q = " OR ".join(f'"{t}"' for t in terms[i:i + 200])
        for r in con.execute(
                "SELECT r.rowid, r.record_id, r.year, r.usable, r.name_resolved, "
                + ", ".join(f"r.{f}" for f in FIELDS)
                + " FROM records_fts f JOIN records r ON r.rowid = f.rowid WHERE records_fts MATCH ?",
                (q,)):
            out[r["rowid"]] = r
    return out


def next_line(con, record_id: str):
    vol, leaf, n = record_id.rsplit(":", 2)
    return con.execute("SELECT raw_line FROM records WHERE record_id = ?",
                       (f"{vol}:{leaf}:{int(n) + 1}",)).fetchone()


def find(con, address: str, dist: int) -> list:
    number, words, kind = parse(address)
    anchor = max(words, key=len)
    streets, numbers = vocab_terms(con, number, anchor, dist)
    print(f"street words within {dist} of {anchor!r}: "
          + ", ".join(f"{t} ({n})" for t, n in sorted(streets, key=lambda x: -x[1])[:40])
          + (" ..." if len(streets) > 40 else ""))
    print(f"number forms of {number}: " + ", ".join(f"{t} ({n})" for t, n in numbers))
    rows = fts_rows(con, [t for t, _ in streets + numbers])
    hits = []
    for r in rows.values():
        best = None
        for f in FIELDS:
            m = match_tokens((r[f] or "").split(), number, words, kind, dist)
            if m and (best is None or GRADES.index(m[0]) < GRADES.index(best[0])):
                best = m
        if best is None:                               # the number last, the street on the next line
            toks = (r["raw_line"] or "").split()
            if any(as_number(t) for t in toks[-2:]) and (nxt := next_line(con, r["record_id"])):
                best = match_tokens(toks + (nxt[0] or "").split(), number, words, kind, dist,
                                    cut=len(toks))
        if best:
            hits.append((best, r))
    return hits


def links(base: str, ids: list) -> list:
    return [base + "?" + urllib.parse.urlencode({"record_id__in": ",".join(ids[i:i + LINK_IDS]),
                                                 "_sort": "year", "_size": "max"})
            for i in range(0, len(ids), LINK_IDS)]


def name_of(r) -> tuple:
    return tuple(re.sub(r"[^a-z ]", "", (r["name_resolved"] or "").lower()).split())


def report(con, hits: list, base: str, people: bool, address: str, dist: int):
    by = collections.defaultdict(list)
    for (grade, how, note), r in hits:
        by[grade].append((r["year"] or 0, r["record_id"], how, note, r))
    # a near line is worth a look when its person, or their surname, is at the address in some
    # other volume: the same household one digit off is more likely a misread than a move
    at = {name_of(r) for g in GRADES[:4] for *_, note, r in by[g] if not note and name_of(r)}
    surnames = {n[0] for n in at}
    for g in GRADES:
        if not by[g]:
            continue
        rows = sorted(by[g])
        print(f"\n== {g}: {len(rows)} ==")
        for year, rid, how, note, r in rows:
            flag = ("TYPE " + note if note else "SAME NAME" if g == "near" and name_of(r) in at
                    else "SURNAME" if g == "near" and name_of(r)[:1] and name_of(r)[0] in surnames
                    else "")
            print(f"{year} {rid:40} u={r['usable']} {how!r:24} {flag:9} {(r['raw_line'] or '')[:90]}")
        for url in links(base, [rid for _, rid, *_ in rows]):
            print(url)
        if g == "near":
            look = [rid for _, rid, _, note, r in rows if not note and name_of(r)[:1]
                    and name_of(r)[0] in surnames]
            if look:
                print(f"near lines whose name or surname is at the address elsewhere ({len(look)}):")
                for url in links(base, look):
                    print(url)
    if not people:
        return
    number, words, kind = parse(address)
    seen = set()
    print("\n== the people at it, in every volume ==")
    for g in ("exact", "street", "number", "wrapped"):
        for _, _, _, note, r in sorted(by[g]):
            name = name_of(r)
            if note or len(name) < 2 or name in seen:
                continue
            seen.add(name)
            print(f"\n{' '.join(name)}")
            for p in con.execute(
                    "SELECT r.year, r.record_id, r.name_resolved, r.raw_line FROM records_fts f "
                    "JOIN records r ON r.rowid = f.rowid WHERE records_fts MATCH ? ORDER BY r.year",
                    (f'name_resolved: "{name[0]}"',)):
                if name_of(p) == name:
                    at = match_tokens((p["raw_line"] or "").split(), number, words, kind, dist)
                    print(f"  {p['year']} {p['record_id']:40} {(at[0] if at else ''):7} "
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
    assert parse("166 Lefferts pl") == ("166", ["lefferts"], "pl")
    assert parse("12 De Kalb av") == ("12", ["de", "kalb"], "av")
    assert m("h 166 Lefferts pl")[1] == "166 Lefferts"
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
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--base", default=BASE, help="the records table's URL in the browser")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        self_test()
        return 0
    if not a.address:
        ap.error("give an address")
    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    hits = find(con, a.address, a.dist)
    report(con, hits, a.base, a.people, a.address, a.dist)
    return 0


if __name__ == "__main__":
    sys.exit(main())
