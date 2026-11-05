"""A table's default facets, unfiltered, from the counts browse/build_db.py keeps (`facet_counts`).

At 16M rows Datasette's own facet count over the whole records table read a 16-column index per
facet: 1.6 s warm, ~6 s cold, past the 3 s facet limit, so the first page showed only `volume`
after ~11 s. The counts change only when the build loads, so the build writes them, and this
answers the unfiltered facet from them. A filter, a search or a _facet= on a column the build
did not count goes to Datasette as before. So does a table with no counts: the build deletes a
table's counts before it changes its rows, so the browser counts live (slow, right) until the
build is done, and never shows old counts.

It wraps ColumnFacet.facet_results (Datasette 0.65.5, which serve.sh pins) and gives that one
facet instance a `ds` whose execute reads facet_counts in place of the facet query. The rest
(the toggle links, the selected value, labels) is Datasette's own code.
"""
import re

from datasette.facets import ColumnFacet
from datasette.utils import escape_sqlite

# ColumnFacet.facet_results' query, as 0.65.5 formats it
FACET_SQL = re.compile(r"\s*select (?P<col>.+?) as value, count\(\*\) as count from \(\s*(?P<inner>.*)\)"
                       r"\s*where (?P=col) is not null\s*group by (?P=col) order by count desc, value"
                       r" limit (?P<limit>\d+)\s*", re.S)


class _Counted:
    """The datasette object, but a facet query over the whole table reads facet_counts."""

    def __init__(self, ds, table: str, counted: dict):
        self._ds, self._table, self._counted = ds, table, counted     # escaped column -> column

    def __getattr__(self, name):
        return getattr(self._ds, name)

    async def execute(self, db_name, sql, params=None, **kw):
        m = FACET_SQL.fullmatch(sql)
        if m and m.group("col") in self._counted and _whole_table(m.group("inner"), self._table):
            sql = ("select value, count from facet_counts where tbl = :tbl and col = :col "
                   f"order by count desc, value limit {int(m.group('limit'))}")
            params = {"tbl": self._table, "col": self._counted[m.group("col")]}
        return await self._ds.execute(db_name, sql, params, **kw)


def _whole_table(sql: str, table: str) -> bool:
    """The table view's facet SQL with no WHERE: `select <columns> from <table> `."""
    return sql.rstrip().endswith(" from " + escape_sqlite(table)) and " where " not in sql.lower()


_facet_results = ColumnFacet.facet_results


async def facet_results(self):
    if self.table and not self.params and _whole_table(self.sql, self.table):
        db = self.ds.get_database(self.database)
        if await db.table_exists("facet_counts"):
            cols = [r[0] for r in (await db.execute(
                "select distinct col from facet_counts where tbl = ?", [self.table])).rows]
            if cols:
                real = self.ds
                self.ds = _Counted(real, self.table, {escape_sqlite(c): c for c in cols})
                try:
                    return await _facet_results(self)
                finally:
                    self.ds = real
    return await _facet_results(self)


ColumnFacet.facet_results = facet_results
