# browse/ — a local browser for the extracted records

[Datasette](https://datasette.io) over one SQLite file that `build_db.py` keeps in step with the
record files `postprocess/assemble_records.py` writes. Sort, filter, facet and full-text search
over every row, with each line's image from IIIF beside what the model made of it. Nothing to
install into the repo: `uvx` fetches Datasette.

```bash
bash browse/serve.sh                 # update data/browse.db, then serve it
open http://127.0.0.1:8001/browse/records
```

Needs `python3` (3.11+, for `tomllib`) and [`uv`](https://docs.astral.sh/uv/). It serves on
localhost only.

## Refreshing

```bash
python3 browse/build_db.py           # in another terminal, then reload the browser tab
```

There is no need to restart Datasette. The build reloads only the files whose size or mtime has
changed, and removes the rows of files that have gone. At 0.8M rows:

| | |
|---|---|
| nothing changed | 0.1 s |
| one microfilm volume re-assembled (50k rows) | 10 s |
| 1906BPL re-assembled (194k rows) | 35 s |
| the reocr tier re-assembled (41 files, 530k rows) | 45 s |
| `--rebuild` (start over; also compacts the file) | ~40–60 s |
| `data/browse.db` | ~1.1 GB (gitignored) |

Each file is swapped in one transaction, so the browser shows the old rows or the new ones, never
half. A file that can't be read whole (because `assemble_records.py` is still writing it, say)
keeps its old rows and is retried next time.

When more than a fifth of a table's data changed, the build drops its indexes, loads, and builds
them again in one pass. A run of `assemble_records.py` rewrites every volume of its root, so
this is the usual case. It's about three times faster than updating the indexes row by row, but
the browser is slow, and search may be stale, for that minute.

Use `--rebuild` only after changing `fts` in `sources.toml`; everything else in the config takes
effect on the next build. **Restart `serve.sh` after a `--rebuild`.** The rebuild replaces the
file, and a running Datasette keeps reading the old, deleted one.

There's no file watcher. Run the build after an assemble step.

## What's in it

**`sources.toml`** says which files are loaded: today `data/records/*/*.jsonl.gz`, one table,
`records`. To load another folder (including one outside this repo), add a `[[sources]]` block.
A file whose rows have a different shape goes in a table of its own. A new key in a file
becomes a new column.

The rows are the files' own values, plus three columns:

- **`run`**: the records directory the file is in (`4b-100k+guard`).
- **`root`**: the chunk directory the volume was assembled from. **One run directory can mix
  roots.** `4b-100k+guard` holds run 1's five volumes (`data/volumes_run1`) and the reocr tier's
  39 (`data/volumes_reocr`), so split a run's totals by `root`. `assemble_records.py` writes
  `root` on every row from 2026-10-20 on. For files assembled before that, it's inferred from
  `infer_root` in `sources.toml`.
- **`source_file`**: where the row came from. The `loaded_files` table lists every file, with
  when it was loaded and its row count.

**Volume metadata.** The `volumes` table has one row per volume. `volumes.py` assembles it from
the catalog (`data_prep/master_directories.csv`), IA's own metadata (`data/survey_census/`) and
the survey sidecars (`data_prep/survey/`), and adds record counts. Its columns:

- **When:** a numeric `year` (the first year of the catalog's `1852/53`), `catalog_year` as the
  catalog writes it, `year_covered`, `year_published`, and IA's date.
- **Who and where:** publisher, IA's publisher, printer, city, borough, title, volume number.
- **The scan:** `scan` (microfiche, BPL PDF upload, or book scan), contributor, IA's collections
  and OCR engine, and the re-OCR if there's been one.
- **The book itself:** leaves, the listing's leaves, the name count the book states (only 3
  volumes state one), and a link to archive.org.

Five of these are also copied onto every record, so you can filter, sort and facet by them:
`year`, `publisher`, `city`, `borough` and `scan`. For example, `?year__gte=1850&year__lt=1860`
or `?scan=book+scan`.

In the records table, `volume` shows a label in place of the bare identifier: "1858 Lain
(Brooklyn)" for `micro_IABROOKLYN_0039`, both in cells and in the volume facet. The label links
to the volume's row. The link comes from a foreign key declared on `records.volume`.

Edits to the catalog, census or sidecars reach the browser on the next build: the `volumes` table
is rewritten every time. If a change alters a copied column, that volume's record files are
reloaded. Changing which columns are copied (`copy` under `[volumes]` in `sources.toml`) reloads
everything.

The catalog is shown as it is, inconsistencies included. A publisher facet splits "Lain" from "J.
LAIN AND COMPANY", and "Spooner" from "spooner". `micro_IABROOKLYN_0042` has no publisher, because
the catalog marks it unverified; IA's publisher column has "J. Lain and Company".

Column descriptions are in the "Column descriptions" toggle above the table and in each column's
header menu. They come from `assemble_records.py`'s docstring, via `metadata.yml`.

**`plugins/records_cells.py`** changes how the pages display, and nothing in the database:

- **`crop`**: no line image loads until you ask for it. **show** loads that row's image, and
  **open** opens it full size in a new tab. The **Show all N line images** button above the
  table loads every row on the page; it toggles back to hiding them. Showing a page's images
  goes back to off when you move to another page.
- **page** (in the `crop` cell, and `canvas`'s **page image**): opens the line's whole page, with
  the line outlined and scrolled into view. IA fails some image requests, so the viewer tries
  several sizes, giving each 10 s. It also has direct links to the image at fixed sizes.
- **`leaf`**: links to every line on that leaf, in reading order.
- **`ditto_source`**: links to the line the surname was carried from, and shows that line's text
  underneath. When a name has the wrong surname, this is where to look: "millions— Try them."
  means an ad supplied it.
- It puts the columns in the order set in `metadata.yml` (see below) and folds the column
  descriptions.

## Arranging the columns

| to | do this | lasts |
|---|---|---|
| change the default column order | edit `column_order` in `metadata.yml`, save, reload the page | always |
| choose columns, and their order, for one view | `?_col=raw_line&_col=name_resolved&...` in the URL; exports follow it | that URL |
| hide a column in this view | its header menu (⚙) → "Hide this column" (adds `?_nocol=`) | that URL |
| sort, or facet by, a column | its header menu (⚙) | that URL |
| change the default facets | `facets` in `metadata.yml`, and the same list in `sources.toml` so each gets its index | always |
| edit a column's description | `columns:` in `metadata.yml` | always |

`serve.sh` runs Datasette with `--reload`, so it restarts itself a few seconds after you save
`metadata.yml`. A change to the plugin's code needs `serve.sh` restarted. Columns not named in `column_order` follow in the table's own
order. A column listed twice goes where it's listed first. `column_order` affects only the page
display: CSV/JSON exports and SQL `select *` keep the table's order, which is the record files'
order. A URL with `_col=` keeps the order it gives, and the plugin leaves it alone.

## Using it

- **Facets:** `root`, `volume`, `role` and `usable` come back in ~0.1–0.3 s under any mix of
  the common filters. That's because each has a covering index; see `sources.toml`. You can add
  a facet on any other column from its header menu. It works, but may take a second or two.
- **Search box:** full-text search over `raw_line`, the resolved name and addresses, occupation,
  employer and spouse. To search a single column, use `?_search_occupation_role=carman`.
- **"contains" filters:** these read every row. Over the whole table that's ~10 s a page; within
  one volume it's well under a second. **Prefer the search box, or filter to a volume first.**
- **Bookmarks:** bookmark a row by its `record_id` filter (`?record_id=1906BPL:9:11`), not by
  its row URL. Row numbers change when a file is reloaded.
- **Exports:** every view has CSV/JSON export links. "View and edit SQL" opens the query behind
  the view, for anything the filters can't express.
- **Images:** IA's image server hangs on some requests. A given URL can fail every time (a 504
  after ~60 s) while the same box at another size loads in ~1 s. A thumbnail that hangs falls
  back to the other size after that wait. The plugin's docstring has the URLs I probed. "Show
  all" loads images only as they scroll into view, so a 200-row leaf doesn't fire 200 requests
  at once.

## Giving someone a copy

The database is one self-contained file. Copy `data/browse.db` and the `browse/` folder, put
them at the same paths in a checkout of this repo, and run

```bash
bash browse/serve.sh --no-build
```

They need only `uv`. Running without `--no-build` is safe too: a source that matches no files
leaves its rows alone instead of emptying the database. The copy includes the `eval_holdout`
rows: flagged, but there. Those must not be trained on or published.

## Later

Written down 2026-10-20, none of it built yet:

1. **Panel errors.** Make a table with one row per gold line and model run: the gold fields, the
   predicted fields, and a match flag for each field. Facet by volume, field and match to see
   where a model goes wrong, next to the line image. The sources are the gold files
   (`data/*_eval.jsonl`), the prediction files, and the alignment `eval/evaluate.py` already
   does. This would be the most useful addition for model work.
2. **Run against run.** Every row carries `run`, so two runs over the same lines can be joined
   on `record_id`. For example, assemble `4b-100k` next to `4b-100k+guard` to see the 32,941
   reocr-tier records the guard changed. That join could be saved as a view showing only the
   fields that differ.
   `record_id` is stable only across runs over the same lines. After a re-OCR the ids no longer
   line up.
3. **The page with its boxes.** A leaf view that draws each line's `xywh` on the page image and
   links each box to its row. It would show `role` mistakes, such as the microfilm margin
   inversion in 71ca30f, at a glance. This needs a custom Datasette template or a small separate
   page.
4. **More sources.** The business-directory sibling's records, once it writes them. The stanza is
   commented out in `sources.toml`.
5. **Automatic refresh.** An opt-in flag on `assemble_records.py` to run the build when it
   finishes, or a watcher. A watcher is safer now than it sounds, since a half-written file is
   skipped.
6. **Sharing wider than two people.** `datasette publish` (Cloud Run, Fly), or a static Parquet
   file with a DuckDB-WASM page. First drop the `eval_holdout` rows and settle what the records
   may be published under.
7. **Scale.** The remaining tiers are several times this size. Re-time the facets when they
   land. The options, in order: more covering indexes (`facets` in `sources.toml`), a table per
   tier, or DuckDB, which Datasette doesn't serve natively.
8. **Corrections from browsing.** A way to mark a row wrong while looking at it, kept in a
   separate table, that feeds gold fixes.
9. **The `crop` size `assemble_records.py` writes.** It writes `full`, which IA serves
   unreliably for some lines (see "Images" above). No other size is reliable for every line
   either, so this is open. A consumer may be better served by `canvas` + `xywh`.
