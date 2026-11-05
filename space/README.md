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
the records Parquet, with no SQLite and no full-text index. At 5.5M rows it started in ~2 s
(building the word list) and searched in ~1–1.5 s, against ~13 s for the SQLite script; "45
Fulton" took ~5 s. **At 15.5M rows (2026-11-04, all three tiers) it is too slow**: it starts in
~6-9 s, and a search with the resident trace takes 9-14 s. PIPELINE #39 has the breakdown and is
open.

## Running it locally

```bash
uv run space/build_parquet.py        # data/browse.db -> data/space/records.parquet, ~4 min, ~550 MB
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
- **`where.py`:** where the address is today (below). Run it directly to test one borough:
  `uv run --with duckdb==2.0.0 python space/where.py "155 Franklin av" Brooklyn`.

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
gives the address (`gives_address`: its grade, or `no`).

**Namesakes in the trace.** The trace matches on the resolved name alone, so a common one gathers
namesakes: "Williams William" at 155 Franklin brings 141 lines, every William Williams from 1798
on. "Set aside likely namesakes" (on by default) moves a traced line that does not give the
address under its person, closed, when its HOME is in another place than all of the person's
lines at the address (the part after its last `h`, read for a marker as above, a marker before
a street word being a street: "N Y av" and "Jamaica av" are Brooklyn's), or it is more than
`TRACE_YEARS` (10) from all of them. Williams William keeps 17, Donovan John J 25 of 103. The
CSV keeps every line, with `left_out` saying why ("in Manhattan", "elsewhere", "28 years from
the address") and the line's `place`. What it cannot tell: a namesake in the same borough and
years ("Keiser August mechanic h 1096 Halsey" beside the optician at 62 Euclid av), which only
the occupation or the home could separate.

**Being kind to IA's image server.** A line image is fetched only when its row is on screen (within
200 px), so nothing in a closed section is requested until it's opened. At most 4 requests are in
flight (`IMG_AT_ONCE` in `app.py`). An image asks for `,64` (64 px high, the smallest useful
download) and falls back to `max` once, the size rule of `browse/plugins/records_cells.py`. A
request IA leaves hanging frees its slot after 15 s. The context and page links fetch only when
clicked. Measured in headless Chrome on 2026-11-01: no image in a closed section was requested,
and none from a previous search. IA took 10–25 s an image that day, so rows fill in slowly.

**Where it is today.** After the lines come up, `where.py` puts a map of the address as it is
today above them, one per borough with lines found (Manhattan, Brooklyn; not "Elsewhere"). The
point comes from NYC GeoSearch (NYC Planning Labs, open data, no key), and the map is an
OpenStreetMap embed. Each map carries the caveat that streets were renumbered, renamed and cut
through, so an old line's building may not be the one pinned. A map is pinned only when
GeoSearch has ONE street today with the borough, the number, the street's name and its type. The
type is the one asked, or else the one the lines found print most often. Otherwise the page says
why there is no pin:
- "155 Franklin" in Brooklyn's lines is Franklin av, and pins there, though Brooklyn also has a
  Franklin st.
- "131 110th st" is East or West, so there's no pin, and both are listed.
- Brooklyn's 45 Fulton is not there today: GeoSearch answers 415 Fulton and Manhattan's 45
  Fulton, which is why its own `match_type` is not trusted.

With `GOOGLE_MAPS_API_KEY` set (on the Space, a secret), each pin also gets a "Street View ↗"
link. It appears only when Google's metadata request, which is free, finds Google's own outdoor
panorama within 50 m, and the link opens it turned toward the address. It is a link, not an
embed, because Google's Maps Platform terms restrict its content beside a non-Google map; check
those terms before embedding it. The key never reaches the page. Without a key there is no link.
Restrict the key to the Street View Static API, and give it no website (HTTP referrer)
restriction: the request comes from the Python server, which sends no referrer, so it would be
refused. Answers are cached for the server's lifetime, and a GeoSearch failure is not cached.

Locally, the key goes in `.env` at the repo root (git ignores it) as
`GOOGLE_MAPS_API_KEY=...`, and uv passes it in:

```bash
uv run --env-file .env --with-requirements space/requirements.txt python space/app.py
uv run --env-file .env --with duckdb==2.0.0 python space/where.py "155 Franklin av" Brooklyn
```

The second prints the point and, on its second line, the Street View link: `None` means Google
has no panorama of its own within 50 m, and `no GOOGLE_MAPS_API_KEY` means the key wasn't read.
As of 2026-11-04 the check had been tested only against mocked metadata answers (Google's own
panorama 29 m off, linked with heading 30°; a user's photosphere, one ~110 m off, and
ZERO_RESULTS, none linked), never against Google itself.

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
2. **The code.** A Space repo holding `app.py`, `search.py`, `where.py`, `requirements.txt`,
   this README (its header is the Space config), and a copy of `browse/find_address.py`.
   `search.py` imports that copy when it's beside it. Set `GOOGLE_MAPS_API_KEY` as a Space
   secret for the Street View links ("Where it is today" above).
3. **Hardware.** The free CPU tier (2 vCPU, 16 GB) was expected to do at a few seconds a search.
   At the full corpus (15.5M rows) the laptop already takes 9-14 s a search, so fix PIPELINE #39
   before choosing hardware.
