"""
A faceted browser over the records Parquet, the Space's Browse tab (app.py): search every text
column, narrow by year, usable lines and facets with counts, and page through the lines in the
directories' own order. What browse.db's Datasette does, on DuckDB.

It shares search.Records' connection and its table `r` (the records in memory, rowid = row
number). A search reads a second word index beside the records, records.terms.parquet: every
word of TERM_COLS (browse/sources.toml's `fts` columns, so the search box covers what
Datasette's does) with the rows holding it, sorted by word, stamped like the finder's. The
finder's own index covers only the three address columns, and its word counts decide which
spellings are another street, so it is left as it is.

    uv run --with duckdb==2.0.0 python space/browse.py data/space/records.parquet "smith grocer"
"""
from __future__ import annotations

import collections
import re
import sys
import threading
import time
from pathlib import Path

import duckdb

from search import Records, index_stamp, load_records, quoted, sql_str

TERM_COLS = ["raw_line", "name_resolved", "occupation_role", "employer", "address_resolved",
             "home_address_resolved", "spouse_name"]
# "Search in": the columns a word must be in, after the index has found the rows
IN_COLUMNS = {"any column": None, "name": ["name_resolved"], "occupation": ["occupation_role"],
              "employer": ["employer"], "address": ["address_resolved", "home_address_resolved"],
              "the line as printed": ["raw_line"], "spouse": ["spouse_name"]}
# facet -> (label, SQL of its value as text, order of its choices, at most this many choices)
FACETS = {
    "volume": ("Directory", "volume", "year", 400),
    "decade": ("Decade", "CAST(year // 10 * 10 AS VARCHAR)", "value", 50),
    "role": ("Role", "role", "count", 50),
    "occupation": ("Occupation", "occupation_role", "count", 100),
    "publisher": ("Publisher", "publisher", "count", 100),
    "city": ("Directory's city", "city", "count", 20),
    "scan": ("Scan", "scan", "count", 20),
}
SORTS = {"directory order": "rowid", "newest first": "year DESC, rowid",
         "name A-Z": "name_resolved NULLS LAST, rowid"}
SHOW = ["record_id", "year", "label", "volume", "leaf", "line", "printed_page", "role", "usable",
        "name_resolved", "occupation_role", "employer", "address_resolved",
        "home_address_resolved", "spouse_name", "raw_line", "crop"]
PAGE = 50
CSV_MAX = 50_000
MAX_SPELLINGS = 300       # a word* or a misspelling stands for at most this many words
TOKEN = re.compile(r"[a-z0-9]+\*?")


def terms_path(parquet: str) -> Path:
    """records.parquet -> records.terms.parquet, beside it."""
    return Path(parquet).with_suffix(".terms.parquet")


def terms_sql(cols: list) -> str:
    text = "lower(concat_ws(' ', " + ", ".join(cols) + "))"
    return f"""SELECT DISTINCT w AS term, CAST(rid AS UINTEGER) AS rid
               FROM (SELECT rowid AS rid, unnest(regexp_split_to_array({text}, '[^a-z0-9]+')) AS w
                     FROM r) WHERE w <> ''"""


def columns_of(con, parquet: str) -> list:
    return [c for c, *_ in con.execute(
        f"DESCRIBE SELECT * FROM read_parquet({sql_str(parquet)})").fetchall()]


def write_terms(parquet: str, out: str | None = None) -> Path:
    """The browser's word index of `parquet`, sorted by word, stamped with the records' row count
    and fingerprint (search.write_index's stamp)."""
    out = Path(out) if out else terms_path(parquet)
    con = duckdb.connect()
    have = columns_of(con, parquet)
    rows, _, fingerprint = load_records(con, parquet, extra=[c for c in TERM_COLS if c in have])
    tmp = out.with_suffix(".tmp")
    con.execute(f"""COPY ({terms_sql([c for c in TERM_COLS if c in have])} ORDER BY term, rid)
                    TO {sql_str(tmp)} (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 122880,
                    PARQUET_VERSION v2, KV_METADATA {{rows: '{rows}', fingerprint: '{fingerprint}'}})""")
    tmp.replace(out)
    return out


class Browser:
    def __init__(self, records: Records, parquet: str):
        t = time.time()
        con = self.con = records.con
        loaded = {c for c, *_ in con.execute("DESCRIBE r").fetchall()}
        self.term_cols = [c for c in TERM_COLS if c in loaded]
        self.show = [c for c in SHOW if c in loaded]
        self.facets = {k: f for k, f in FACETS.items()
                       if re.sub(r"CAST\((\w+).*", r"\1", f[1]) in loaded}
        self.in_columns = {k: v for k, v in IN_COLUMNS.items()
                           if v is None or all(c in loaded for c in v)}
        path = terms_path(parquet)
        if index_stamp(path) == (records.rows, records.fingerprint):
            con.execute(f"CREATE VIEW terms AS SELECT * FROM read_parquet({sql_str(str(path))})")
            self.index = str(path)
        else:
            print(f"{path} is missing or was built for other records: building the browser's word "
                  "index in memory (space/build_parquet.py --index-only writes it)", file=sys.stderr)
            con.execute(f"CREATE TABLE terms AS {terms_sql(self.term_cols)} ORDER BY term, rid")
            self.index = "built at start-up"
        # every word once with the rows holding it, for a misspelling's neighbours
        con.execute("CREATE TABLE tvocab AS SELECT term, count(*) AS n FROM terms GROUP BY term")
        self.labels = {}
        for v, label, year in con.execute(
                "SELECT volume, any_value(label), min(year) FROM r GROUP BY volume").fetchall():
            self.labels[v] = (label or v, year or 0)
        twice = collections.Counter(label for label, _ in self.labels.values())
        self.labels = {v: (f"{label} · {v}" if twice[label] > 1 else label, year)
                       for v, (label, year) in self.labels.items()}
        self.cache, self.lock = collections.OrderedDict(), threading.Lock()
        self.load_s = time.time() - t
        self.browse()                              # the counts with nothing chosen, cached

    def spellings(self, cur, token: str, dist: int) -> list:
        """(word, rows) the token stands for: itself, every word it starts if it ends in *, or
        every word within `dist` edits (none for a number, or a word under 4 letters)."""
        if token.endswith("*"):
            stem = token[:-1]
            return cur.execute(
                "SELECT term, n FROM tvocab WHERE starts_with(term, ?) ORDER BY n DESC LIMIT ?",
                [stem, MAX_SPELLINGS]).fetchall() if stem else []
        if dist and len(token) >= 4 and not token.isdigit():
            return cur.execute(
                "SELECT term, n FROM tvocab WHERE length(term) BETWEEN ? AND ? "
                "AND levenshtein(term, ?) <= ? ORDER BY term = ? DESC, n DESC LIMIT ?",
                [len(token) - dist, len(token) + dist, token, dist, token, MAX_SPELLINGS]).fetchall()
        return cur.execute("SELECT term, n FROM tvocab WHERE term = ?", [token]).fetchall()

    def where(self, words: list, in_col: str, chosen: dict, years: tuple, usable: bool,
              skip: str | None = None) -> tuple:
        """The WHERE clause and its parameters: the hits (a temp table, when there are words),
        each word in the chosen column, the facets chosen (except `skip`, whose own counts are
        being taken), the years and usable."""
        sql, params = ["true"], []
        if words:
            sql.append("rowid IN (SELECT rid FROM hits)")
        cols = self.in_columns.get(in_col)
        if words and cols:
            text = "lower(concat_ws(' ', " + ", ".join(cols) + "))"
            for terms in words:
                sql.append(f"regexp_matches({text}, ?)")
                params.append("(^|[^a-z0-9])(" + "|".join(t for t, _ in terms) + ")([^a-z0-9]|$)")
        for f, values in chosen.items():
            if values and f != skip and f in self.facets:
                sql.append(f"coalesce({self.facets[f][1]}, '') IN ({', '.join('?' * len(values))})")
                params.extend(values)
        if years[0]:
            sql.append("year >= ?")
            params.append(int(years[0]))
        if years[1]:
            sql.append("year <= ?")
            params.append(int(years[1]))
        if usable:
            sql.append("usable = 1")
        return " AND ".join(sql), params

    def _open(self, query: str, dist: int):
        """A cursor with the query's hits in a temp table `hits`, and its words' spellings (None
        where a word matches nothing, so nothing can be found)."""
        cur = self.con.cursor()
        words = [self.spellings(cur, t, dist) for t in dict.fromkeys(TOKEN.findall((query or "").lower()))]
        if words and all(words):
            cur.execute("CREATE TEMP TABLE hits AS " + " INTERSECT ".join(
                f"SELECT rid FROM terms WHERE term IN ({quoted(t for t, _ in terms)})"
                for terms in words))
        return cur, words

    def browse(self, query: str = "", in_col: str = "any column", dist: int = 0,
               chosen: dict | None = None, years: tuple = (None, None), usable: bool = False,
               sort: str = "directory order", page: int = 0) -> dict:
        chosen = {f: sorted(v) for f, v in (chosen or {}).items() if v}
        t = time.time()
        key = repr((query, in_col, dist, chosen, years, usable))
        cur, words = self._open(query, dist)
        try:
            with self.lock:
                counts = self.cache.get(key)
                if counts:
                    self.cache.move_to_end(key)
            if words and not all(words):
                counts = {"total": 0, "facets": {f: [] for f in self.facets}}
            elif not counts:
                sql, params = self.where(words, in_col, chosen, years, usable)
                counts = {"total": cur.execute(f"SELECT count(*) FROM r WHERE {sql}", params).fetchone()[0],
                          "facets": {}}
                for f, (_, expr, order, most) in self.facets.items():
                    fsql, fparams = self.where(words, in_col, chosen, years, usable, skip=f)
                    rows = cur.execute(f"SELECT coalesce({expr}, '') AS v, count(*) AS n FROM r "
                                       f"WHERE {fsql} GROUP BY v ORDER BY n DESC LIMIT ?",
                                       [*fparams, most]).fetchall()
                    have = {v for v, _ in rows}
                    rows += [(v, 0) for v in chosen.get(f, []) if v not in have]
                    if order == "value":
                        rows.sort()
                    elif order == "year":
                        rows.sort(key=lambda r: (self.labels.get(r[0], ("", 0))[1], r[0]))
                    counts["facets"][f] = rows
                with self.lock:
                    self.cache[key] = counts
                    while len(self.cache) > 64:
                        self.cache.popitem(last=False)
            rows = []
            if counts["total"]:
                sql, params = self.where(words, in_col, chosen, years, usable)
                cur2 = cur.execute(f"SELECT {', '.join(self.show)} FROM r WHERE {sql} "
                                   f"ORDER BY {SORTS.get(sort, 'rowid')} LIMIT {PAGE} OFFSET ?",
                                   [*params, int(page) * PAGE])
                names = [d[0] for d in cur2.description]
                rows = [dict(zip(names, r)) for r in cur2.fetchall()]
        finally:
            cur.close()
        return dict(counts, rows=rows, page=int(page), pages=-(-counts["total"] // PAGE),
                    spellings=words, seconds=time.time() - t)

    def export(self, query: str, in_col: str, dist: int, chosen: dict, years: tuple,
               usable: bool, sort: str) -> list:
        """The first CSV_MAX lines of a search, every SHOW column."""
        chosen = {f: sorted(v) for f, v in (chosen or {}).items() if v}
        cur, words = self._open(query, dist)
        try:
            if words and not all(words):
                return []
            sql, params = self.where(words, in_col, chosen, years, usable)
            c = cur.execute(f"SELECT {', '.join(self.show)} FROM r WHERE {sql} "
                            f"ORDER BY {SORTS.get(sort, 'rowid')} LIMIT {CSV_MAX}", params)
            names = [d[0] for d in c.description]
            return [dict(zip(names, r)) for r in c.fetchall()]
        finally:
            cur.close()


if __name__ == "__main__":
    recs = Records(sys.argv[1])
    b = Browser(recs, sys.argv[1])
    print(f"{recs.rows:,} rows; browser ready in {b.load_s:.1f} s (index: {b.index})")
    for q in sys.argv[2:] or [""]:
        res = b.browse(q)
        print(f"{q!r}: {res['total']:,} lines in {res['seconds']:.2f} s; "
              + "; ".join(f"{f} {v[:3]}" for f, v in res["facets"].items()))
