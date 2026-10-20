#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Load the record files into one SQLite database for browsing in Datasette (browse/README.md).

    python3 browse/build_db.py              # bring data/browse.db up to date with the files
    python3 browse/build_db.py --rebuild    # start the database over (also compacts it)
    python3 browse/build_db.py --self-test

What it loads is browse/sources.toml. A file is reloaded when its size or mtime has changed since
the last build, and its rows are deleted when it has gone -- unless its source now matches no
files at all, which is a missing copy of the data, not an empty run. A file that cannot be read
whole (one assemble_records.py is still writing, say) keeps its previous rows and is retried on
the next build. Each file is swapped in one transaction, so a Datasette reading the database
while this runs sees the old rows or the new ones, never half. When most of a table changed --
an assemble rewrites every volume of its root -- its indexes come down for the load and go back
up after (BULK_SHARE), and the browser is slow for that minute.

Everything happens inside data/browse.db, so a running Datasette sees it -- except --rebuild,
which deletes the file: Datasette keeps reading the deleted one until it is restarted.

The database is a view of the files, never a source: nothing in it is edited, and --rebuild
regenerates all of it. Values are the files' own, except JSON true/false become 1/0 (SQLite has
no boolean) and lists become JSON text (`ditto_flags`, which Datasette can facet as an array).
Every row also gets `run` (the file's directory, unless the source sets one), `source_file`, and
`root` where the row lacks it and the source says where to look (`infer_root`).

rowids are not stable across reloads, so a Datasette row URL is not a bookmark; record_id is.
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import glob
import gzip
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import time
import tomllib
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CONFIG = REPO / "browse" / "sources.toml"
DB = REPO / "data" / "browse.db"
BATCH = 5000
# Past this share of a table's bytes changed, its indexes are dropped for the load and built
# again after (strip_for_bulk). Row-by-row upkeep ran at ~180 s per whole table, a one-pass
# rebuild at ~40 s: the two cross near a quarter.
BULK_SHARE = 0.2
UNREADABLE = (OSError, EOFError, ValueError, zlib.error)   # truncated gzip, half-written line


def resolve(p: str) -> Path:
    path = Path(os.path.expanduser(p))
    return path if path.is_absolute() else REPO / path


def rel(path: Path) -> str:
    """Repo-relative where it can be, so a database copied to another checkout still matches."""
    try:
        return str(path.resolve().relative_to(REPO))
    except ValueError:
        return str(path.resolve())


def q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def cell(v):
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    return v


def read_rows(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def columns(con, table: str) -> list:
    return [r[1] for r in con.execute(f"PRAGMA table_info({q(table)})")]


def sql_type(v) -> str:
    """The declared type matters: Datasette passes every filter value as text (`?leaf=9`), and
    only a column with INTEGER affinity compares '9' equal to 9."""
    if isinstance(v, (bool, int)):
        return "INTEGER"
    return "REAL" if isinstance(v, float) else "TEXT"


def create_table(con, table: str, cols: dict, fts: list, refs: dict | None = None):
    """The table ({column: type}), the index the reloads delete by, and the full-text index kept
    by triggers. No INTEGER PRIMARY KEY: Datasette then links rows by rowid, which the FTS table
    follows -- so this database must never be VACUUMed (that renumbers rowids); --rebuild
    compacts it. `refs` {column: (table, column)} declares foreign keys, which SQLite does not
    enforce here and Datasette reads to show a label in place of the value."""
    refs = refs or {}
    defs = [f"{q(c)} {t}" + (f" REFERENCES {q(refs[c][0])}({q(refs[c][1])})" if c in refs else "")
            for c, t in cols.items()]
    con.execute(f"CREATE TABLE {q(table)} ({', '.join(defs)})")
    con.execute(f"CREATE INDEX {q(f'idx_{table}_source_file')} ON {q(table)} (source_file)")
    fts = [c for c in fts if c in cols]
    if not fts:
        return
    # content=[table] is the form Datasette's FTS detection looks for
    con.execute(f"CREATE VIRTUAL TABLE {q(table + '_fts')} USING fts5("
                f"{', '.join(q(c) for c in fts)}, content=[{table}])")
    create_fts_triggers(con, table)


def fts_columns(con, table: str) -> list:
    return columns(con, f"{table}_fts") if f"{table}_fts" in tables(con) else []


def create_fts_triggers(con, table: str):
    f, fts = f"{table}_fts", fts_columns(con, table)
    new = ", ".join(f"new.{q(c)}" for c in fts)
    old = ", ".join(f"old.{q(c)}" for c in fts)
    names = ", ".join(q(c) for c in fts)
    con.execute(f"CREATE TRIGGER {q(f'{table}_ai')} AFTER INSERT ON {q(table)} BEGIN "
                f"INSERT INTO {q(f)} (rowid, {names}) VALUES (new.rowid, {new}); END")
    con.execute(f"CREATE TRIGGER {q(f'{table}_ad')} AFTER DELETE ON {q(table)} BEGIN "
                f"INSERT INTO {q(f)} ({q(f)}, rowid, {names}) VALUES ('delete', old.rowid, {old});"
                f" END")


def triggers(con, table: str) -> set:
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'trigger' AND "
                                      "tbl_name = ?", (table,))}


def strip_for_bulk(con, table: str):
    """Before loading most of a table: drop the indexes (all but the one the swaps delete by) and
    the FTS triggers. Updating them row by row is what makes a reload slow -- every volume
    re-assembled at once took 145 s that way, against 42 s for --rebuild -- and building them
    again in one pass afterwards (ensure_indexes, ensure_fts) is cheap."""
    for name in triggers(con, table) & {f"{table}_ai", f"{table}_ad"}:
        con.execute(f"DROP TRIGGER {q(name)}")
    for (name,) in con.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND "
                               "tbl_name = ? AND sql IS NOT NULL", (table,)).fetchall():
        if name != f"idx_{table}_source_file":
            con.execute(f"DROP INDEX {q(name)}")


def ensure_fts(con, table: str) -> bool:
    """A full-text index without its triggers was loaded around (strip_for_bulk), or a bulk build
    was interrupted: put the triggers back and rebuild it from the table. -> whether it did."""
    if not fts_columns(con, table) or {f"{table}_ai", f"{table}_ad"} <= triggers(con, table):
        return False
    con.execute("BEGIN")
    for name in triggers(con, table) & {f"{table}_ai", f"{table}_ad"}:
        con.execute(f"DROP TRIGGER {q(name)}")
    create_fts_triggers(con, table)
    con.execute(f"INSERT INTO {q(table + '_fts')} ({q(table + '_fts')}) VALUES ('rebuild')")
    con.execute("COMMIT")
    return True


def wanted_indexes(tcfg: dict) -> dict:
    """{name: [columns]} from a [tables.<name>] block: `index` entries (a column, or a list for a
    composite), and per `facets` column one led by it carrying every `filters` column (see
    sources.toml for why)."""
    out = {}
    for entry in tcfg.get("index", []):
        cols = [entry] if isinstance(entry, str) else list(entry)
        out["_".join(cols)] = cols
    for f in tcfg.get("facets", []):
        out[f"facet_{f}"] = [f] + [c for c in tcfg.get("filters", []) if c != f]
    return out


def ensure_indexes(con, table: str, tcfg: dict) -> bool:
    """Make the configured indexes and drop the ones the config no longer names. -> any change"""
    have = set(columns(con, table))
    want = {f"idx_{table}_{k}": [c for c in cols if c in have]
            for k, cols in wanted_indexes(tcfg).items() if cols[0] in have}
    want[f"idx_{table}_source_file"] = ["source_file"]
    have_idx = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'index' "
                                          "AND tbl_name = ? AND sql IS NOT NULL", (table,))}
    for name in have_idx - set(want):
        con.execute(f"DROP INDEX {q(name)}")
    for name in set(want) - have_idx:
        con.execute(f"CREATE INDEX {q(name)} ON {q(table)} "
                    f"({', '.join(q(c) for c in want[name])})")
    return have_idx != set(want)


def root_finder(dirs: list):
    """volume -> the first of `dirs` holding a chunk directory for it, as written in the config
    (the form assemble_records.py writes in `root`)."""
    cache = {}

    def find(volume):
        if volume not in cache:
            cache[volume] = next((d for d in dirs if volume and (resolve(d) / volume).is_dir()),
                                 None)
        return cache[volume]
    return find


class VolumeMeta:
    """[volumes] in sources.toml: browse/volumes.py's describe() of each value of `key`, the
    `copy` columns of it put on every row of `table`, and the `volumes` table."""

    def __init__(self, vcfg: dict):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import volumes
        self.describe = volumes.describe
        self.table = vcfg.get("table", "records")
        self.key = vcfg.get("key", "volume")
        self.copy_cols = list(vcfg.get("copy", []))

    def copy(self, ident) -> dict:
        d = self.describe(ident) if ident else {}
        return {c: d.get(c) for c in self.copy_cols}

    def fingerprint(self, idents) -> str:
        """Of what was copied onto a file's rows: a catalog edit (or a change to `copy`) makes
        it differ, and the file is reloaded."""
        blob = json.dumps([[i, self.copy(i)] for i in idents], sort_keys=True, default=str)
        return hashlib.sha1(blob.encode()).hexdigest()

    def refs(self) -> dict:
        return {self.key: ("volumes", "volume")}


def write_volumes(con, meta: VolumeMeta):
    """The volumes table, rewritten whole on every build (a few dozen rows): describe() of each
    value of the key column, and the counts of its rows. usable_per_stated_name only where the
    volume is in one run, since two runs over it would count it twice."""
    t = meta.table
    if t not in tables(con):
        return
    have = set(columns(con, t))
    agg = ", ".join(["count(*)",
                     "group_concat(DISTINCT run)" if "run" in have else "NULL",
                     "group_concat(DISTINCT root)" if "root" in have else "NULL",
                     "sum(usable)" if "usable" in have else "NULL"])
    rows = []
    for ident, n, runs, roots, usable in con.execute(
            f"SELECT {q(meta.key)}, {agg} FROM {q(t)} WHERE {q(meta.key)} IS NOT NULL "
            f"GROUP BY {q(meta.key)}").fetchall():
        d = dict(meta.describe(ident))
        stated = d.get("stated_name_count")
        per = (round(usable / stated, 3) if isinstance(stated, (int, float)) and stated
               and usable is not None and runs and "," not in runs else None)
        d.update(records=n, usable=usable, usable_per_stated_name=per, runs=runs, roots=roots)
        rows.append(d)
    cols = list(dict.fromkeys(k for r in rows for k in r))
    types = {c: next((sql_type(r[c]) for r in rows if r.get(c) is not None), "TEXT") for c in cols}
    defs = ", ".join(f"{q(c)} {types[c]}" + (" PRIMARY KEY" if c == "volume" else "")
                     for c in cols)
    con.execute("BEGIN")
    con.execute("DROP TABLE IF EXISTS volumes")
    con.execute(f"CREATE TABLE volumes ({defs})")
    con.executemany(f"INSERT INTO volumes ({', '.join(q(c) for c in cols)}) "
                    f"VALUES ({', '.join('?' * len(cols))})",
                    [[cell(r.get(c)) for c in cols] for r in rows])
    con.execute("COMMIT")


def load_file(con, table: str, tcfg: dict, path: Path, extra: dict, source: str, find_root,
              prev_table, meta=None):
    """Swap one file's rows in, `extra` the columns added to each, and `meta` (a VolumeMeta) the
    volume's columns where the table is the one [volumes] describes. -> rows loaded, or None if
    the file could not be read whole (its previous rows are kept)."""
    src = extra["source_file"]
    con.execute("BEGIN")
    try:
        if prev_table and prev_table in tables(con):
            con.execute(f"DELETE FROM {q(prev_table)} WHERE source_file = ?", (src,))
        cols = columns(con, table)
        n, batch, keys = 0, [], set()

        def flush():
            # a column is made when a value first appears in it, typed by that value; until
            # then its rows are null, which is all they would have held
            types = {}
            for k in dict.fromkeys(k for r in batch for k in r):
                v = next((r[k] for r in batch if r.get(k) is not None), None)
                if v is not None:
                    types[k] = sql_type(v)
            if not cols:
                create_table(con, table, types, tcfg.get("fts", []),
                             meta.refs() if meta else None)
                cols.extend(types)
            for k, t in types.items():
                if k not in cols:
                    con.execute(f"ALTER TABLE {q(table)} ADD COLUMN {q(k)} {t}")
                    cols.append(k)
            con.executemany(
                f"INSERT INTO {q(table)} ({', '.join(q(c) for c in cols)}) "
                f"VALUES ({', '.join('?' * len(cols))})",
                [[cell(r.get(c)) for c in cols] for r in batch])
            batch.clear()

        for rec in read_rows(path):
            if not rec.get("root") and find_root:
                rec["root"] = find_root(rec.get("volume"))
            if meta:
                keys.add(rec.get(meta.key))
                for k, v in meta.copy(rec.get(meta.key)).items():
                    rec.setdefault(k, v)              # the file's own value wins
            batch.append({**rec, **extra})
            n += 1
            if len(batch) >= BATCH:
                flush()
        if batch:
            flush()
        st = path.stat()
        keys = sorted(k for k in keys if k is not None)
        con.execute("INSERT OR REPLACE INTO loaded_files (path, tbl, run, source, size, mtime_ns, "
                    "rows, loaded_at, volumes, meta) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (src, table, extra["run"], source, st.st_size, st.st_mtime_ns, n,
                     _dt.datetime.now().isoformat(timespec="seconds"),
                     json.dumps(keys) if meta else None,
                     meta.fingerprint(keys) if meta else None))
        con.execute("COMMIT")
        return n
    except UNREADABLE as e:
        con.execute("ROLLBACK")
        print(f"  SKIPPED {src}: cannot read it whole ({type(e).__name__}: {e}); kept its old "
              f"rows, will retry next build")
        return None
    except BaseException:
        con.execute("ROLLBACK")
        raise


def tables(con) -> set:
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def build(config: Path, db: Path, rebuild: bool = False, bulk_share: float = BULK_SHARE) -> int:
    cfg = tomllib.loads(config.read_text(encoding="utf-8"))
    if rebuild:
        for suffix in ("", "-wal", "-shm"):
            Path(str(db) + suffix).unlink(missing_ok=True)
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db, isolation_level=None)
    con.execute("PRAGMA journal_mode = WAL")       # readers are never blocked by a build
    con.execute("PRAGMA synchronous = NORMAL")
    # a ceiling, not an allocation. At the default ~2 MB, reloading 1906BPL (194k rows into
    # fifteen indexes) re-read index pages from disk for every row: 110 s, against 97 s for a
    # whole --rebuild
    con.execute("PRAGMA cache_size = -400000")
    con.execute("CREATE TABLE IF NOT EXISTS loaded_files (path TEXT PRIMARY KEY, tbl TEXT, "
                "run TEXT, source TEXT, size INTEGER, mtime_ns INTEGER, rows INTEGER, "
                "loaded_at TEXT, volumes TEXT, meta TEXT)")
    for col in ("volumes", "meta"):                 # a database from before [volumes]
        if col not in columns(con, "loaded_files"):
            con.execute(f"ALTER TABLE loaded_files ADD COLUMN {col} TEXT")
    loaded = {r[0]: r for r in con.execute(
        "SELECT path, tbl, size, mtime_ns, source, volumes, meta FROM loaded_files")}
    meta = VolumeMeta(cfg["volumes"]) if cfg.get("volumes") else None
    t0 = time.time()
    n_stale = 0
    seen, empty_sources, touched = set(), set(), set()
    todo, total_bytes, changed_bytes = [], collections.Counter(), collections.Counter()
    for src in cfg.get("sources", []):
        table = src.get("table", "records")
        files = sorted(Path(p) for p in glob.glob(str(resolve(src["glob"]))))
        if not files:
            empty_sources.add(src["glob"])
            print(f"  no files match {src['glob']}: left its rows alone")
            continue
        find_root = root_finder(src["infer_root"]) if src.get("infer_root") else None
        for path in files:
            key = rel(path)
            if key in seen:
                continue
            seen.add(key)
            st = path.stat()
            total_bytes[table] += st.st_size
            prev = loaded.get(key)
            if prev and prev[1] == table and (prev[2], prev[3]) == (st.st_size, st.st_mtime_ns):
                if not (meta and table == meta.table
                        and prev[6] != meta.fingerprint(json.loads(prev[5] or "[]"))):
                    continue
                n_stale += 1                        # same file, its volumes' metadata changed
            changed_bytes[table] += st.st_size
            todo.append((table, path, key, src, find_root, prev[1] if prev else None))
    if n_stale:
        print(f"  {n_stale} files to reload for changed volume metadata ([volumes] in the config, "
              f"or the catalog, census or survey sidecars)")
    present = tables(con)
    for table in changed_bytes:
        if table in present and changed_bytes[table] > bulk_share * total_bytes[table]:
            print(f"  {changed_bytes[table] / total_bytes[table]:.0%} of {table} changed: loading "
                  f"it without its indexes, then building them again")
            strip_for_bulk(con, table)
    n_loaded = n_rows = n_skipped = 0
    for table, path, key, src, find_root, prev_table in todo:
        extra = {"run": src.get("run") or path.parent.name, "source_file": key}
        n = load_file(con, table, cfg.get("tables", {}).get(table, {}), path, extra, src["glob"],
                      find_root, prev_table, meta if meta and table == meta.table else None)
        if n is None:
            n_skipped += 1
            continue
        touched.add(table)
        n_loaded += 1
        n_rows += n
        print(f"  loaded {key}  {n:,} rows -> {table} (run {extra['run']})")
    n_removed = 0
    for key, (_p, table, _s, _m, source, _v, _h) in loaded.items():
        if key in seen or source in empty_sources:
            continue
        con.execute("BEGIN")
        if table in tables(con):
            con.execute(f"DELETE FROM {q(table)} WHERE source_file = ?", (key,))
        con.execute("DELETE FROM loaded_files WHERE path = ?", (key,))
        con.execute("COMMIT")
        touched.add(table)
        n_removed += 1
        print(f"  removed {key}: the file is gone")
    present = tables(con)
    for table in sorted({r[0] for r in con.execute("SELECT DISTINCT tbl FROM loaded_files")}
                        & present):
        if ensure_fts(con, table):
            touched.add(table)
        if ensure_indexes(con, table, cfg.get("tables", {}).get(table, {})):
            touched.add(table)
    if meta:
        write_volumes(con, meta)                     # after the indexes: its counts read one
    if touched:
        # a full ANALYZE (~3 s at 0.8M rows), never a sampled one: on a sample the planner took
        # the entry_shaped index (94% of rows) for role=runover&entry_shaped=1, 6.9 s against 0.4
        con.execute("ANALYZE")
    counts = {t: con.execute(f"SELECT count(*) FROM {q(t)}").fetchone()[0]
              for (t,) in con.execute("SELECT DISTINCT tbl FROM loaded_files ORDER BY tbl")
              if t in present}
    con.close()
    state = (f"{n_loaded} files loaded ({n_rows:,} rows), {n_removed} removed"
             if n_loaded or n_removed else "indexes updated" if touched else "up to date")
    print(f"{state}; {', '.join(f'{t} {c:,} rows' for t, c in counts.items()) or 'empty'}  "
          f"[{rel(db)}, {time.time() - t0:.1f}s]")
    if n_skipped:
        print(f"{n_skipped} files skipped: see above")
    return 1 if n_skipped else 0


def _self_test() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "volumes_a" / "volA").mkdir(parents=True)
        run = tmp / "records" / "runX"
        run.mkdir(parents=True)

        def write(name, rows, gz=True):
            data = "".join(json.dumps(r) + "\n" for r in rows).encode()
            (run / name).write_bytes(gzip.compress(data) if gz else data)

        write("volA.jsonl.gz", [{"record_id": "volA:1:0", "volume": "volA", "raw_line":
                                 "Smith John, grocer, 12 Pine", "usable": True,
                                 "printed_page": None, "ditto_flags": []},
                                {"record_id": "volA:1:1", "volume": "volA", "raw_line":
                                 '" Wm, carman', "usable": False, "printed_page": None,
                                 "ditto_flags": ["orphan"]}])
        write("volB.jsonl.gz", [{"record_id": "volB:3:0", "volume": "volB", "raw_line":
                                 "Jones Mary, widow", "usable": True, "printed_page": 7,
                                 "root": "given", "scan": "its own"}])
        cfg = tmp / "sources.toml"
        cfg.write_text(f'[tables.records]\nindex = ["record_id", ["volume", "usable"]]\n'
                       f'facets = ["volume"]\nfilters = ["volume", "usable", "run"]\n'
                       f'fts = ["raw_line"]\n[[sources]]\ntable = "records"\n'
                       f'glob = "{run}/*.jsonl.gz"\ninfer_root = ["{tmp / "volumes_a"}"]\n'
                       f'[volumes]\ntable = "records"\ncopy = ["scan", "year"]\n')
        db = tmp / "b.db"
        rows = lambda: sqlite3.connect(db).execute(  # noqa: E731
            "SELECT record_id, usable, ditto_flags, run, root FROM records ORDER BY rowid"
        ).fetchall()
        fts = lambda term: [r[0] for r in sqlite3.connect(db).execute(  # noqa: E731
            "SELECT r.record_id FROM records_fts JOIN records r ON r.rowid = records_fts.rowid "
            "WHERE records_fts MATCH ?", (term,))]

        assert build(cfg, db) == 0
        got = rows()
        assert got[0] == ("volA:1:0", 1, "[]", "runX", str(tmp / "volumes_a")), got[0]
        assert got[1][2] == '["orphan"]' and got[2][4] == "given", "a row's own root wins"
        assert fts("grocer") == ["volA:1:0"] and fts("widow") == ["volB:3:0"]
        con = sqlite3.connect(db)
        idx = lambda: {r[0]: [c[2] for c in con.execute(f"PRAGMA index_info({q(r[0])})")]  # noqa
                       for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'index' "
                                            "AND tbl_name = 'records'")}
        assert idx() == {"idx_records_record_id": ["record_id"],
                         "idx_records_volume_usable": ["volume", "usable"],
                         "idx_records_facet_volume": ["volume", "usable", "run"],
                         "idx_records_source_file": ["source_file"]}, idx()
        assert "COVERING INDEX idx_records_facet_volume" in con.execute(
            "EXPLAIN QUERY PLAN SELECT volume, count(*) FROM records WHERE usable = 1 AND "
            "run = 'runX' GROUP BY volume").fetchall()[-1][3], "a facet count reads its index alone"
        # Datasette's filters arrive as text: a column null in the first file is still typed
        assert con.execute("SELECT count(*) FROM records WHERE usable = '1'").fetchone()[0] == 2
        assert con.execute("SELECT record_id FROM records WHERE printed_page = '7'"
                           ).fetchall() == [("volB:3:0",)]

        # [volumes]: copied columns (the file's own value wins; an all-null one is not made),
        # the volumes table with counts, and the foreign key Datasette labels volumes by
        assert con.execute("SELECT volume, scan FROM records ORDER BY rowid").fetchall() == [
            ("volA", "book scan"), ("volA", "book scan"), ("volB", "its own")]
        assert "year" not in columns(con, "records")
        assert con.execute("SELECT volume, records, usable, scan FROM volumes ORDER BY volume"
                           ).fetchall() == [("volA", 2, 1, "book scan"), ("volB", 1, 1, "book scan")]
        assert [(r[2], r[3], r[4]) for r in con.execute("PRAGMA foreign_key_list(records)")] == [
            ("volumes", "volume", "volume")]
        cfg.write_text(cfg.read_text().replace('copy = ["scan", "year"]',
                                               'copy = ["scan", "ia_url"]'))
        assert build(cfg, db) == 0
        assert con.execute("SELECT DISTINCT ia_url FROM records WHERE volume = 'volA'"
                           ).fetchall() == [("https://archive.org/details/volA",)], \
            "a change to what is copied reloads the files"

        # unchanged files are not reloaded
        con = sqlite3.connect(db)
        before = con.execute("SELECT loaded_at, rowid FROM loaded_files").fetchall()
        assert build(cfg, db) == 0
        assert con.execute("SELECT loaded_at, rowid FROM loaded_files").fetchall() == before

        # an index taken out of the config is dropped
        cfg.write_text(cfg.read_text().replace('["record_id", ["volume", "usable"]]',
                                               '["record_id"]'))
        assert build(cfg, db) == 0
        assert "idx_records_volume_usable" not in idx()

        # a changed file replaces its rows, and a new key becomes a column (row by row: the
        # indexes and FTS triggers stay up throughout)
        write("volB.jsonl.gz", [{"record_id": "volB:3:0", "volume": "volB", "raw_line":
                                 "Jones Mary, milliner", "usable": True, "new_field": "x"}])
        assert build(cfg, db, bulk_share=2) == 0
        assert [r[0] for r in rows()] == ["volA:1:0", "volA:1:1", "volB:3:0"]
        assert fts("widow") == [] and fts("milliner") == ["volB:3:0"], "FTS follows the swap"

        # most of the table changed: loaded without indexes or triggers, both rebuilt after
        write("volA.jsonl.gz", [{"record_id": "volA:1:0", "volume": "volA", "raw_line":
                                 "Smith John, baker, 12 Pine", "usable": True}])
        write("volB.jsonl.gz", [{"record_id": "volB:3:0", "volume": "volB", "raw_line":
                                 "Jones Mary, widow", "usable": True, "new_field": "x"}])
        assert build(cfg, db, bulk_share=0) == 0
        assert fts("grocer") == [] and fts("baker") == ["volA:1:0"] and fts("widow") == ["volB:3:0"]
        assert set(idx()) == {"idx_records_record_id", "idx_records_facet_volume",
                              "idx_records_source_file"}, idx()
        assert triggers(con, "records") == {"records_ai", "records_ad"}
        write("volB.jsonl.gz", [{"record_id": "volB:3:0", "volume": "volB", "raw_line":
                                 "Jones Mary, milliner", "usable": True, "new_field": "x"}])
        assert build(cfg, db, bulk_share=2) == 0
        assert fts("widow") == [] and fts("milliner") == ["volB:3:0"], "the triggers are live"

        # a bulk build cut off after dropping the triggers is mended by the next build
        con.execute("DROP TRIGGER records_ai")
        con.execute("INSERT INTO records_fts (records_fts) VALUES ('delete-all')")
        con.commit()
        assert build(cfg, db) == 0
        assert triggers(con, "records") == {"records_ai", "records_ad"}
        assert fts("baker") == ["volA:1:0"], "FTS rebuilt from the table"
        assert "new_field" in columns(sqlite3.connect(db), "records")

        # a half-written file keeps its old rows and fails the build
        good = (run / "volB.jsonl.gz").read_bytes()
        (run / "volB.jsonl.gz").write_bytes(good[: len(good) // 2])
        assert build(cfg, db) == 1
        assert fts("milliner") == ["volB:3:0"], "old rows kept"
        (run / "volB.jsonl.gz").write_bytes(good)

        # a deleted file's rows go; a source matching nothing leaves its rows alone
        (run / "volA.jsonl.gz").unlink()
        assert build(cfg, db) == 0
        assert [r[0] for r in rows()] == ["volB:3:0"]
        (run / "volB.jsonl.gz").unlink()
        assert build(cfg, db) == 0
        assert [r[0] for r in rows()] == ["volB:3:0"], "an absent copy of the data is not a wipe"

        # plain .jsonl too, and --rebuild starts over
        cfg.write_text(cfg.read_text().replace("*.jsonl.gz", "*.jsonl"))
        write("volC.jsonl", [{"record_id": "volC:1:0", "volume": "volC", "raw_line": "x"}],
              gz=False)
        assert build(cfg, db, rebuild=True) == 0
        con = sqlite3.connect(db)
        assert con.execute("SELECT record_id FROM records").fetchall() == [("volC:1:0",)]
        assert columns(con, "records") == ["record_id", "volume", "raw_line", "scan", "ia_url",
                                           "run", "source_file"], \
            "the files' order, then what [volumes] copies; no root found, no column"
    print("self-test ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(CONFIG))
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--rebuild", action="store_true", help="delete the database and reload all")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()
    return build(Path(args.config), Path(args.db), rebuild=args.rebuild)


if __name__ == "__main__":
    sys.exit(main())
