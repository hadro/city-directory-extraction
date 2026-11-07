"""
browse/find_address.py's search in DuckDB over the records Parquet: no SQLite.

The records are held in memory (~5 s at 15.5M rows on 2 threads, ~2 GB), and a word index
(every word of the three address-bearing columns -> the rows holding it) is read from a Parquet
beside them, records.words.parquet, which build_parquet.py writes. A search picks the street
word's spellings and the number's look-alikes from the index's word list, takes the rows holding
one of them AND a word that reads as the number or one digit off (no grade is possible without
one, PIPELINE #39), and grades those in the address's shape with find_address's own readers, so
the two give the same answer. A full scan per search took ~3 s on 2 threads at 15.5M rows; the
index takes ~0.05 s. The shape tests run in DuckDB, so only lines that may match reach Python.
Wrapped lines are read with the next line by record_id, never by row order. The CLI
(browse/find_address.py) runs this search over the file without loading it (memory=False).
"""
from __future__ import annotations

import itertools
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
# The Browse tab's columns (browse.py), loaded too when the file has them
EXTRA_COLS = ["publisher", "role", "scan", "employer", "spouse_name", "printed_page"]
PLACES = ["Manhattan", "Brooklyn", "Elsewhere"]
TRACE_YEARS = 10       # a traced line further than this from every year at the address is left out
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
# The index's word for a row whose number may be read through a character the word split breaks
# on: as_number reads | ! ] as 1, and str.isdigit is true of non-ASCII numerals (2026-11-04: 8,961
# rows). These rows are always candidates, so the near-number test below misses no line.
ODD = "~odd"
INDEX_SQL = f"""
    SELECT DISTINCT w AS term, CAST(rid AS UINTEGER) AS rid
    FROM (SELECT rowid AS rid, unnest({WORDS}) AS w FROM r) WHERE w <> ''
    UNION ALL
    SELECT '{ODD}', CAST(rowid AS UINTEGER) FROM r
    WHERE regexp_matches({TEXT}, '[|!\\]]')
       OR regexp_matches(regexp_replace({TEXT}, '[0-9]', '', 'g'), '\\p{{N}}')"""
# What grading reads; the other COLS are fetched for the hits only (a column costs a pass over
# every row in memory, and crop is the widest).
GRADE_COLS = ["record_id", *fa.FIELDS]
# What a lowercased character may be read as, as FOLD reads it (B is 8, b is 6). In a whole token
# (as_number), | ! ] are 1 too and any non-ASCII numeral is a digit; in a cleaned street word
# (ordinal), they are gone.
LOOK = {"0": "0o", "1": "1il", "2": "2z", "5": "5s", "6": "6gb", "8": "8b"}
DIGITISH = r"(?:[0-9ilogbsz|!\]]|[^\x00-\x7f])"
STRIP = r"[.:;,'\"()]*"                         # what as_number strips from a token's ends
# What str.split splits on (str.isspace), for RE2, whose \s is ASCII only and lacks \v
WS = r"[\t-\r\x1c-\x1f\x85\p{Z}]"


def looks(d: str, token: bool = True) -> str:
    """The characters that may be the digit d: in a whole token, or in a cleaned word."""
    extra = r"|!\]" if token and d == "1" else ""
    return "[" + d + LOOK.get(d, "") + extra + "]"


def near_token(number: str) -> str:
    """A whitespace token of a lowercased line that as_number may read as `number` or one digit
    off: a pattern every grade needs, `near` and `wrapped` included."""
    digits = [looks(d) for d in number]
    forms = {"".join(digits)}
    for p in range(len(number) + 1):
        if p < len(number):
            forms.add("".join(digits[:p]) + DIGITISH + "".join(digits[p + 1:]))
            forms.add("".join(digits[:p] + digits[p + 1:]))
        forms.add("".join(digits[:p]) + DIGITISH + "".join(digits[p:]))
    forms.discard("")
    return rf"(?<!\S){STRIP}[hr]?(?:{'|'.join(sorted(forms))}){STRIP}(?!\S)"


def address_shape(number: str, words: list, dist: int):
    """A pattern every line match_tokens reads the address in matches, lowercased: a near-number
    token, at most 2 + k tokens (a direction, the street's words before its anchor, the first of
    two rejoined parts), then a piece of the street word kept whole. Split into d + 1 pieces, a
    word within d edits keeps at least one of them; a numbered street keeps its folded digits. A
    piece may run across a hyphen or the gap of a word the OCR split. None where no piece can be
    told (an anchor shorter than d + 1): every candidate is graded then."""
    anchor = fa.anchor_of(words)
    k = fa.split_direction(words)[1].index(anchor)
    gap = "[^a-z0-9]*"
    if (numbered := fa.ordinal(anchor)):
        pieces = [gap.join(looks(d, token=False) for d in numbered)]
    else:
        d = fa.street_dist(anchor, dist)
        if len(anchor) < d + 1:
            return None
        size = len(anchor) / (d + 1)
        pieces = [gap.join(re.escape(c) for c in anchor[round(i * size):round((i + 1) * size)])
                  for i in range(d + 1)]
    return re.compile(rf"{near_token(number)}(?:\s+\S+){{0,{2 + k}}}\s+\S*?(?:{'|'.join(pieces)})")


def ends_near(number: str) -> str:
    """A pattern of a lowercased line with a near-number token among its last two: what
    read_wrapped needs (the number ends the first line)."""
    return rf"{near_token(number)}(?:\s+\S+)?\s*$"


def re2(pattern: str) -> str:
    """A pattern built here, as DuckDB's RE2 reads it: no lookarounds, and \\s and \\S split as
    str.split splits, so a row SQL leaves out is one the Python pattern leaves out too. A
    lookahead (?!\\S) followed by whitespace is dropped (the whitespace says it), and at the end
    becomes whitespace-or-end; a lookbehind (?<!\\S) can only lead the pattern, as it does here."""
    pattern = re.sub(r"\(\?!\\S\)(?=\(\?:\\s|\\s)", "", pattern)
    assert pattern.count(r"(?<!\S)") <= 1 and pattern.find(r"(?<!\S)") <= 0, pattern
    return (pattern.replace(r"(?<!\S)", f"(?:^|{WS})").replace(r"(?!\S)", f"(?:{WS}|$)")
            .replace(r"\s", WS).replace(r"\S", "[^" + WS[1:]))


def index_path(parquet: str) -> Path:
    """records.parquet -> records.words.parquet, beside it."""
    return Path(parquet).with_suffix(".words.parquet")


def sql_str(s) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def load_records(con, parquet: str, memory: bool = True, extra=()) -> tuple:
    """r: the records in the file's order (rowid = row number), a table in memory, or with
    memory=False a view of the file (no start-up; each search reads the file, ~1 s more: for one
    search, as browse/find_address.py makes). `extra`: columns beyond COLS. Returns (rows,
    volumes, fingerprint): the fingerprint ties an index to this order of these record ids."""
    cols = ", ".join(COLS + [c for c in extra if c not in COLS])
    if memory:
        con.execute(f"CREATE TABLE r AS SELECT {cols} FROM read_parquet({sql_str(parquet)})")
    else:
        con.execute(f"CREATE VIEW r AS SELECT file_row_number AS rowid, {cols} "
                    f"FROM read_parquet({sql_str(parquet)}, file_row_number = true)")
    return con.execute("SELECT count(*), count(DISTINCT volume), "
                       "CAST(bit_xor(hash(rowid, record_id)) AS VARCHAR) FROM r").fetchone()


def write_index(parquet: str, out: str | None = None) -> Path:
    """The word index of `parquet`, sorted by word so a search reads only the row groups of its
    own words. ~1 min on 8 threads at 15.5M rows, 143 MB."""
    out = Path(out) if out else index_path(parquet)
    con = duckdb.connect()
    rows, _, fingerprint = load_records(con, parquet)
    tmp = out.with_suffix(".tmp")
    con.execute(f"""COPY ({INDEX_SQL} ORDER BY term, rid) TO {sql_str(tmp)}
                    (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 122880, PARQUET_VERSION v2,
                     KV_METADATA {{rows: '{rows}', fingerprint: '{fingerprint}'}})""")
    tmp.replace(out)
    return out


def index_stamp(path: Path) -> tuple | None:
    """(rows, fingerprint) an index was built for, or None if there is none."""
    if not path.exists():
        return None
    kv = {k.decode(): v.decode() for k, v in duckdb.execute(
        "SELECT key, value FROM parquet_kv_metadata(?)", [str(path)]).fetchall()}
    return (int(kv["rows"]), kv["fingerprint"]) if "rows" in kv else None


def quoted(terms) -> str:
    """An SQL list of index words, inlined so the Parquet reader prunes row groups by them."""
    terms = list(terms)
    assert all(re.fullmatch(r"[a-z0-9]+|" + ODD, t) for t in terms), terms
    return ", ".join(f"'{t}'" for t in terms)


class Records:
    def __init__(self, parquet: str, index: str | None = None, threads: int | None = None,
                 memory: bool = True):
        self.con = duckdb.connect(config={"threads": threads} if threads else {})
        t = time.time()
        have = {c for c, *_ in self.con.execute(
            f"DESCRIBE SELECT * FROM read_parquet({sql_str(parquet)})").fetchall()}
        self.rows, self.volumes, fingerprint = load_records(
            self.con, parquet, memory, extra=[c for c in EXTRA_COLS if c in have])
        self.fingerprint = fingerprint
        path = Path(index) if index else index_path(parquet)
        if index_stamp(path) == (self.rows, fingerprint):
            self.con.execute(f"CREATE VIEW words AS SELECT * FROM read_parquet({sql_str(path)})")
            self.index = str(path)
        else:                                     # minutes on 2 vCPU: ship the index instead
            print(f"{path} is missing or was built for other records: building the word index "
                  "in memory (space/build_parquet.py --index-only writes it)", file=sys.stderr)
            self.con.execute(f"CREATE TABLE words AS {INDEX_SQL} ORDER BY term, rid")
            self.index = "built at start-up"
        # rows holding the word, as the CLI's fts5vocab `doc` counts it
        self.con.execute(f"CREATE TABLE vocab AS SELECT term, count(*) AS n FROM words "
                         f"WHERE term <> '{ODD}' GROUP BY term")
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

    def near_terms(self, number: str) -> list:
        """Every word that may hold the number or one digit off, read as match_tokens reads a
        token (as_number, then lev 1). Every grade needs such a token, `wrapped` and `near`
        included. The index is lowercased, so a b may have been a B: as_number reads b as 6, B
        as 8, and either counts."""
        out = []
        for t, in self.con.execute(
                "SELECT term FROM vocab WHERE length(term) BETWEEN ? AND ? "
                "AND regexp_full_match(term, '[hr]?[0-9ilogbsz]+') AND regexp_matches(term, '[0-9]')",
                [len(number) - 1, len(number) + 2]).fetchall():
            bs = [i for i, c in enumerate(t) if c == "b"]
            for upper in itertools.product((False, True), repeat=len(bs)):
                v = "".join("B" if i in bs and upper[bs.index(i)] else c for i, c in enumerate(t))
                n = fa.as_number(v)
                if n is not None and fa.lev(n, number, 1) <= 1:
                    out.append(t)
                    break
        return out

    def candidates(self, number: str, streets: list, numbers: list) -> list:
        """The row numbers holding a street spelling or a number form (the rows find_address's
        full-text query returns) that also hold a near-number word: the rest can take no grade."""
        if not streets and not numbers:
            return []
        return [rid for rid, in self.con.execute(f"""
            SELECT rid FROM words WHERE term IN ({quoted(t for t, _ in streets + numbers)})
            INTERSECT
            SELECT rid FROM words WHERE term IN ({quoted(self.near_terms(number) + [ODD])})
            """).fetchall()]

    def to_grade(self, rids: list, shape) -> list:
        """The candidates in the address's shape, to grade: the shape test runs in DuckDB, so
        the rest never reach Python."""
        where = f"AND regexp_matches({TEXT}, {sql_str(re2(shape.pattern))})" if shape else ""
        return self._dicts(f"SELECT rowid AS rid, {', '.join(GRADE_COLS)} FROM r "
                           f"WHERE rowid IN (SELECT unnest(?)) {where}", [rids])

    def to_read_wrapped(self, rids: list, number: str, shape) -> list:
        """The candidates that may wrap the address, each with its next line (`next_raw`, by
        record_id): a near number among the line's last two tokens, and the address's shape across
        the two lines. Both are what read_wrapped needs."""
        nid = "regexp_replace(a.record_id, '[0-9]+$', '') || " \
              "(TRY_CAST(regexp_extract(a.record_id, '[0-9]+$') AS BIGINT) + 1)"
        across = f"AND regexp_matches(lower(coalesce(a.raw_line, '') || ' ' || " \
                 f"coalesce(n.raw_line, '')), {sql_str(re2(shape.pattern))})" if shape else ""
        return self._dicts(f"""
            SELECT a.rid, {', '.join('a.' + c for c in GRADE_COLS)}, n.raw_line AS next_raw
            FROM (SELECT rowid AS rid, {', '.join(GRADE_COLS)} FROM r WHERE rowid IN (SELECT unnest(?))
                  AND regexp_matches(lower(coalesce(raw_line, '')), {sql_str(re2(ends_near(number)))})
                 ) a JOIN r n ON n.record_id = {nid}
            WHERE true {across}""", [rids])

    def find(self, address: str, dist: int = 2, people: bool = False) -> dict:
        number, words, kind = fa.parse(address)
        anchor = fa.anchor_of(words)
        t = time.time()
        phases, mark = {}, [t]

        def lap(name):                            # seconds per phase, for results/finder_timing.py
            phases[name] = time.time() - mark[0]
            mark[0] = time.time()
        streets, numbers = self.terms(number, anchor, dist)
        streets, dropped = fa.other_streets(streets, anchor)
        lap("terms")
        rids = self.candidates(number, streets, numbers)
        lap("candidates")
        skip = frozenset(t for t, _ in dropped)
        shape = address_shape(number, words, dist)
        hits = []
        graded = self.to_grade(rids, shape) if rids else []
        for r in graded:
            if (best := fa.best_reading(r, number, words, kind, dist, skip)):
                hits.append((best, r))
        lap("grade")
        found = {r["rid"] for _, r in hits}
        # the number last, the street on the next line
        wrap = [r for r in (self.to_read_wrapped(rids, number, shape) if rids else [])
                if r["rid"] not in found]
        for r in wrap:
            if (best := fa.read_wrapped(r, r.pop("next_raw"), number, words, kind, dist, skip)):
                hits.append((best, r))
        lap("wrap")
        full = {x.pop("rid"): x for x in self._dicts(
            f"SELECT rowid AS rid, {', '.join(COLS)} FROM r WHERE rowid IN (SELECT unnest(?))",
            [[r["rid"] for _, r in hits]])} if hits else {}
        hits = [(best, full[r["rid"]]) for best, r in hits]
        at = fa.residents_at(hits)
        out = []
        for (grade, how, note, tail), r in hits:
            place, marker = place_of(tail, r)
            out.append(dict(r, grade=grade, how=how, flag=fa.flag_of(grade, note, r, at),
                            place=place, marker=marker))
        out.sort(key=lambda h: (fa.GRADES.index(h["grade"]), h["year"] or 0, h["volume"],
                                h["leaf"], h["line"]))
        lap("hits")
        res = {"address": address, "number": number, "anchor": anchor, "kind": kind,
               "streets": streets, "dropped": dropped, "numbers": numbers,
               "candidates": len(rids), "graded": len(graded), "wrap": len(wrap), "hits": out,
               "seconds": time.time() - t, "people": {}, "phases": phases}
        if people:
            res["people"] = self.residents(out, number, words, kind, dist)
            lap("trace")
            res["seconds"] = time.time() - t
        return res

    def residents(self, hits: list, number, words, kind, dist) -> dict:
        """Each person found at the address, in every volume: a year whose line read the address
        too badly to match shows up at another address, or not at all.

        The name alone gathers namesakes ("Williams William" at 155 Franklin: every William
        Williams from 1798), so each line not at the address gets `left_out`, why it is probably
        someone else: its home is in another place than any of the person's lines at the
        address, or it is more than TRACE_YEARS from all of them. Nothing is dropped; the page
        and the CSV decide what to show."""
        names, anchors = [], {}
        for h in hits:
            n = fa.name_of(h)
            if h["grade"] != "near" and not h["flag"] and len(n) >= 2:
                if n not in names:
                    names.append(n)
                years, places = anchors.setdefault(n, (set(), set()))
                years.add(h["year"])
                places.add(h["place"])
        names = names[:12]
        # one scan for every name: the lines whose name starts with one of the surnames (O'Brien
        # is not obrien%), then the whole rows of the ones with the very name
        want = set(names)
        rids = [rid for rid, name, lname in self.con.execute(
            "SELECT rowid, name_resolved, lower(name_resolved) FROM r "
            "WHERE regexp_matches(lower(name_resolved), ?)",
            ["^(" + "|".join(sorted({n[0] for n in names})) + ")"]).fetchall()
            if (n := fa.name_of({"name_resolved": name})) in want and lname.startswith(n[0])
        ] if names else []
        by_name = {}
        for p in self._dicts(f"SELECT {', '.join(COLS)} FROM r WHERE rowid IN (SELECT unnest(?)) "
                             "ORDER BY year, volume, leaf, line", [rids]) if rids else []:
            by_name.setdefault(fa.name_of(p), []).append(p)
        out = {}
        for n in names:
            years, places = anchors[n]
            traced = []
            for p in by_name.get(n, []):
                p = dict(p, grade=(fa.best_reading(p, number, words, kind, dist) or ("",))[0])
                p["place"], p["marker"] = home_place_of(p)
                gap = min((abs(p["year"] - y) for y in years if y and p["year"]), default=None)
                p["left_out"] = ("" if p["grade"] else
                                 ("elsewhere" if p["place"] == "Elsewhere" else f"in {p['place']}")
                                 if p["place"] not in places else
                                 f"{gap} years from the address" if gap is not None
                                 and gap > TRACE_YEARS else "")
                traced.append(p)
            out[" ".join(n)] = traced
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


STREET_WORD = re.compile(r"(av|ave|avenue|st|street|pl|place|rd|road|ct|court|turnpike|tpke)\.?",
                         re.I)


def home_place_of(r) -> tuple:
    """(place, marker) of the line's HOME, for a line that does not give the address searched:
    the part after its last `h` (Trow's "h 228 Lenox av Bklyn"), or the whole line if it has
    none; the first place marker there, else the directory's own place. A marker followed by a
    street word is a street, not a place: "h 167 N Y av", "Flushing av" and "Jamaica av" are
    Brooklyn's."""
    toks = (r.get("raw_line") or "").split()
    hs = [i for i, t in enumerate(toks) if t.rstrip(".,") in ("h", "r", "res")]
    seg = toks[hs[-1] + 1:] if hs else toks
    for i in range(len(seg)):
        place, marker = place_of(" ".join(seg[i:i + 2]), r)
        if not marker:
            continue
        after = seg[i + len(marker.split())] if i + len(marker.split()) < len(seg) else ""
        if not STREET_WORD.fullmatch(after.rstrip(",")):
            return place, marker
    return home_place(r), ""


if __name__ == "__main__":
    recs = Records(sys.argv[1])
    print(f"{recs.rows:,} rows, {recs.words:,} words, loaded in {recs.load_s:.1f} s "
          f"(index: {recs.index})")
    res = recs.find(sys.argv[2], people=True)
    print(f"{len(res['hits'])} hits from {res['candidates']} candidates ({res['graded']} graded) "
          f"in {res['seconds']:.2f} s")
    for h in res["hits"]:
        if h["grade"] != "near" or h["flag"]:
            print(h["grade"], h["flag"], h["year"], h["record_id"], h["raw_line"])
    for name, rows in res["people"].items():
        print(name, [(p["year"], p["grade"]) for p in rows])
