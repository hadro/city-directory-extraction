---
title: City Directory Address Finder
colorFrom: gray
colorTo: blue
sdk: gradio
sdk_version: 6.31.0
app_file: app.py
pinned: false
---

# space/ — the address finder as a Hugging Face Space

`browse/find_address.py`'s search as a web page: every line that may give an address, OCR
misreadings included, each with its line image from the Internet Archive. It runs on DuckDB over
the records Parquet, with no SQLite and no full-text index. At 5.5M rows it starts in ~2 s
(building the word list) and searches in ~1–1.5 s, against ~13 s for the SQLite script. A street
as common as "45 Fulton" takes ~5 s.

## Running it locally

```bash
uv run space/build_parquet.py        # data/browse.db -> data/space/records.parquet, ~35 s, ~190 MB
uv run --with-requirements space/requirements.txt python space/app.py
open http://127.0.0.1:7860
```

`build_parquet.py` makes a stand-in for the release: only the columns the app reads, the
`eval_holdout` rows dropped, ordered by year, volume, leaf and line. Rebuild it after
`browse/build_db.py` picks up new records. `RECORDS_PARQUET` points the app at another file;
`PORT` changes the port.

The files:

- **`search.py`:** the DuckDB search. It grades lines with `find_address`'s own readers, so the
  script and the page agree. Run it directly to test without the page:
  `uv run --with duckdb==2.0.0 python space/search.py data/space/records.parquet "166 Lefferts pl"`.
- **`app.py`:** the Gradio page.
- **`build_parquet.py`:** the local stand-in above.

**Where an address is.** The "Where the address is" boxes (Manhattan, Brooklyn, Elsewhere) filter
on each line's own place, not its directory's. A marker printed right after the matched street
decides it: Trow's prints Brooklyn homes as "h 168 Lefferts pl Bklyn", and Brooklyn's
directories print New York addresses as "107 Fulton, N. Y." or "Mhtn" (`MARKERS` in `search.py`,
with OCR forms such as Eklyn and Mhta). A marker further along the line belongs to another
address in it ("683 B'way Mhtn h 106 Lefferts pl"), so it doesn't count. Without a marker, an
address takes its directory's city: Brooklyn or Williamsburgh for theirs, Manhattan for New
York's, which before 1898 was the City of New York. Each line's badge says which way it was
decided. Where a directory left the marker out, or the OCR lost it, the line goes to the
directory's city: 2 Trow's lines for Lefferts Pl, a Brooklyn street, show as Manhattan.
"45 Fulton" splits 2,318 Brooklyn / 1,711 Manhattan / 15 elsewhere.

**Downloads.** After a search, "Download the matches" gives every line found as a CSV, near
misses included (the page shows at most 300 of those), with the place filter applied: grade,
flag, place and its marker, directory, record id, resolved name and occupation, the line, its
resolved addresses, and the line and page image URLs. With "Trace the residents" ticked,
"Download the resident trace" gives each traced person's line in every volume, and whether it
gives the address (`gives_address`: its grade, or `no`). The trace matches on the resolved name
alone, so a common one gathers namesakes: "Williams William" at 155 Franklin brings every
William Williams from 1798 on.

**Being kind to IA's image server.** A line image is fetched only when its row is on screen (within
200 px), so nothing in a closed section is requested until it's opened. At most 4 requests are in
flight (`IMG_AT_ONCE` in `app.py`). An image asks for `,64` (64 px high, the smallest useful
download) and falls back to `max` once, the size rule of `browse/plugins/records_cells.py`. A
request IA leaves hanging frees its slot after 15 s. The context and page links fetch only when
clicked. Measured in headless Chrome on 2026-11-01: no image in a closed section was requested,
and none from a previous search. IA took 10–25 s an image that day, so rows fill in slowly.

The page and the script differ only in the held-out rows. For example, the script's
"h 76 Leffert© pi" (1906BPL:1193:111) is an `adjacent` holdout, so the page doesn't show it.

## Putting it on Hugging Face (not done yet)

1. **The data.** The release Parquet, once it's up. The app reads these columns: `record_id`,
   `volume`, `leaf`, `line`, `year`, `label`, `usable`, `name_resolved`, `occupation_role`,
   `raw_line`, `address_resolved`, `home_address_resolved`, `crop`. If the release lacks `line`
   or `label`, derive them: `line` from `record_id`, `label` from the volumes table. Download the
   files to the Space's disk at startup (`huggingface_hub.snapshot_download`) rather than reading
   `hf://` paths. Every search scans the address columns, and over HTTP that would be every
   query.
2. **The code.** A Space repo holding `app.py`, `search.py`, `requirements.txt`, this README
   (its header is the Space config), and a copy of `browse/find_address.py`. `search.py`
   imports that copy when it's beside it.
3. **Hardware.** The free CPU tier should do (2 vCPU, 16 GB). At the full corpus (~15.6M rows,
   ~3× today) expect a few seconds a search there.
