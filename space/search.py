"""
browse/find_address.py's search in DuckDB over the records Parquet: no SQLite, no full-text index.

The word list of the three address-bearing columns is built once (~2 s at 5.5M rows); a search
then picks the street word's spellings and the number's look-alikes from it, pulls every row
holding one as a whole word (~0.6 s), and grades them with find_address's own readers, so the
two give the same answer. Wrapped lines are read with the next line by record_id, never by row
order.
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import duckdb

try:
    import find_address as fa                     # deployed: copied in beside this file
except ImportError:                               # in the repo: browse/find_address.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "browse"))
    import find_address as fa

COLS = ["record_id", "volume", "leaf", "line", "year", "label", "usable", "name_resolved",
        "occupation_role", "raw_line", "address_resolved", "home_address_resolved", "crop", "city",
        "borough"]
PLACES = ["Manhattan", "Brooklyn", "Elsewhere"]
# Place markers as the directories print them after an address, letters only, lowercased: Trow's
# (Manhattan) "h 168 Lefferts pl Bklyn", a Brooklyn directory's "107 Fulton, N. Y.". OCR forms
# seen in the lines: Eklyn, Bkn, B'klyn.
MARKERS = {
    "Brooklyn": re.compile(r"[be]k?l[yi]?n|[be]kn|bk[yi]n|bklyn\w*|brklyn|brooklyn|wmsburgh?"
                           r"|williamsburgh?|wburgh|wmsbg|bkiyvo"),
    "Manhattan": re.compile(r"mhtn|mhta|mhn|manh|manhattan|ny|newyork|nyc"),
    "Elsewhere": re.compile(r"nj|li|si|lic|jerseycity|jc|hoboken|newark|bronx|queens|flush(ing)?"
                            r"|jamaica|astoria|yonkers|statenisland|stapleton|tompkinsville"
                            r"|newbrighton|paterson|chicago|boston|phila(delphia)?|baltimore"
                            r"|buffalo|albany|montreal|london|paris"),
}
TEXT = "lower(coalesce(raw_line, '') || ' ' || coalesce(address_resolved, '') || ' ' " \
       "|| coalesce(home_address_resolved, ''))"
WORDS = f"regexp_split_to_array({TEXT}, '[^a-z0-9]+')"


class Records:
    def __init__(self, parquet: str):
        self.con = duckdb.connect()
        src = parquet.replace("'", "''")
        self.con.execute(f"CREATE VIEW r AS SELECT * FROM read_parquet('{src}')")
        t = time.time()
        self.con.execute(f"""CREATE TABLE vocab AS SELECT w AS term, count(*) AS n
                             FROM (SELECT unnest({WORDS}) AS w FROM r) WHERE w <> '' GROUP BY w""")
        self.rows, self.volumes = self.con.execute(
            "SELECT count(*), count(DISTINCT volume) FROM r").fetchone()
        self.words = self.con.execute("SELECT count(*) FROM vocab").fetchone()[0]
        self.load_s = time.time() - t

    def _dicts(self, sql: str, params=()) -> list:
        cur = self.con.execute(sql, params)
        names = [d[0] for d in cur.description]
        return [dict(zip(names, row)) for row in cur.fetchall()]

    def terms(self, number: str, anchor: str, dist: int):
        dist = fa.street_dist(anchor, dist)
        if fa.ordinal(anchor):                    # a numbered street: its digits, look-alikes folded
            streets = [(t, n) for t, n in self.con.execute(
                "SELECT term, n FROM vocab WHERE length(term) BETWEEN ? AND ? "
                "AND regexp_full_match(term, '[0-9ilogbsz]+(st|nd|rd|th|d|h|t)?') ORDER BY n DESC",
                [len(anchor) - 2, len(anchor) + 1]).fetchall()
                if fa.ordinal(t) == fa.ordinal(anchor) and t != number]
        else:
            streets = self.con.execute(
                "SELECT term, n FROM vocab WHERE length(term) BETWEEN ? AND ? "
                "AND levenshtein(term, ?) <= ? AND regexp_full_match(term, '[a-z]+') ORDER BY n DESC",
                [len(anchor) - dist, len(anchor) + dist, anchor, dist]).fetchall()
        numbers = [(t, n) for t, n in self.con.execute(
            "SELECT term, n FROM vocab WHERE length(term) BETWEEN ? AND ? "
            "AND regexp_full_match(term, '[hr]?[0-9ilogbsz]+') AND regexp_matches(term, '[0-9]') "
            "ORDER BY n DESC", [len(number) - 1, len(number) + 2]).fetchall()
            if fa.as_number(t) == number]
        return streets, numbers

    def find(self, address: str, dist: int = 2, people: bool = False) -> dict:
        number, words, kind = fa.parse(address)
        anchor = fa.anchor_of(words)
        t = time.time()
        streets, numbers = self.terms(number, anchor, dist)
        streets, dropped = fa.other_streets(streets, anchor)
        pat =r"\b(" + "|".join(t for t, _ in streets + numbers) + r")\b"
        # \b on the lowercased text finds the same rows as the word split, ~6x faster
        rows = self._dicts(f"SELECT {', '.join(COLS)} FROM r WHERE regexp_matches({TEXT}, ?)",
                           [pat]) if streets or numbers else []
        skip = frozenset(t for t, _ in dropped)
        hits, wrap = [], []
        for r in rows:
            best = fa.best_reading(r, number, words, kind, dist, skip)
            if best:
                hits.append((best, r))
            elif fa.ends_on_number(r):
                wrap.append(r)
        if wrap:                                  # the number last, the street on the next line
            nxt = {x["record_id"]: x["raw_line"] for x in self._dicts(
                "SELECT record_id, raw_line FROM r WHERE record_id IN (SELECT unnest(?))",
                [[next_id(r["record_id"]) for r in wrap]])}
            for r in wrap:
                if next_id(r["record_id"]) in nxt:
                    best = fa.read_wrapped(r, nxt[next_id(r["record_id"])], number, words, kind,
                                           dist, skip)
                    if best:
                        hits.append((best, r))
        at = fa.residents_at(hits)
        out = []
        for (grade, how, note, tail), r in hits:
            place, marker = place_of(tail, r)
            out.append(dict(r, grade=grade, how=how, flag=fa.flag_of(grade, note, r, at),
                            place=place, marker=marker))
        out.sort(key=lambda h: (fa.GRADES.index(h["grade"]), h["year"] or 0, h["volume"],
                                h["leaf"], h["line"]))
        res = {"address": address, "number": number, "anchor": anchor, "kind": kind,
               "streets": streets, "dropped": dropped, "numbers": numbers,
               "candidates": len(rows), "hits": out,
               "seconds": time.time() - t, "people": {}}
        if people:
            res["people"] = self.residents(out, number, words, kind, dist)
            res["seconds"] = time.time() - t
        return res

    def residents(self, hits: list, number, words, kind, dist) -> dict:
        """Each person found at the address, in every volume: a year whose line read the address
        too badly to match shows up at another address, or not at all."""
        names = []
        for h in hits:
            n = fa.name_of(h)
            if h["grade"] != "near" and not h["flag"] and len(n) >= 2 and n not in names:
                names.append(n)
        out = {}
        for n in names[:12]:
            rows = self._dicts(
                f"SELECT {', '.join(COLS)} FROM r WHERE lower(name_resolved) LIKE ? "
                "ORDER BY year, volume, leaf, line", [n[0] + "%"])
            out[" ".join(n)] = [dict(p, grade=(fa.best_reading(p, number, words, kind, dist)
                                               or ("",))[0])
                                for p in rows if fa.name_of(p) == n]
        return out


def home_place(r) -> str:
    """The directory's own place: Brooklyn for a Brooklyn or Williamsburgh directory (or a
    consolidated New York one for the Brooklyn borough), Manhattan for New York's (Trow's,
    Longworth's, Doggett's; New York City meant Manhattan before 1898)."""
    if r.get("borough") == "Brooklyn" or r.get("city") in ("Brooklyn", "Williamsburgh"):
        return "Brooklyn"
    return "Manhattan" if r.get("city") == "New York" else "Elsewhere"


def place_of(tail: str, r) -> tuple:
    """(place, the marker that says so, or '' where it is the directory's own place). Only the
    first one or two tokens after the street count: a marker further on belongs to another
    address in the line ("683 B'way Mhtn h 106 Lefferts pl")."""
    toks = [re.sub(r"[^a-z]", "", t.lower()) for t in tail.split()[:2]]
    for cand, shown in ((toks[0] if toks else "", tail.split()[:1]),
                        ("".join(toks), tail.split()[:2])):          # "N Y", "L I", "Jersey City"
        if not cand:
            continue
        for place, pat in MARKERS.items():
            if pat.fullmatch(cand):
                return place, " ".join(shown)
    return home_place(r), ""


def next_id(record_id: str) -> str:
    vol, leaf, n = record_id.rsplit(":", 2)
    return f"{vol}:{leaf}:{int(n) + 1}"


if __name__ == "__main__":
    recs = Records(sys.argv[1])
    print(f"{recs.rows:,} rows, {recs.words:,} words, loaded in {recs.load_s:.1f} s")
    res = recs.find(sys.argv[2], people=True)
    print(f"{len(res['hits'])} hits from {res['candidates']} candidates in {res['seconds']:.2f} s")
    for h in res["hits"]:
        if h["grade"] != "near" or h["flag"]:
            print(h["grade"], h["flag"], h["year"], h["record_id"], h["raw_line"])
    for name, rows in res["people"].items():
        print(name, [(p["year"], p["grade"]) for p in rows])
