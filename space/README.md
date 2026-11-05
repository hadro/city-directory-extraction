---
title: City Directory Address Finder
colorFrom: gray
colorTo: blue
sdk: gradio
sdk_version: 6.31.0
python_version: "3.12"
app_file: app.py
pinned: false
---

# space/ — the address finder as a Hugging Face Space

`browse/find_address.py`'s search as a web page: every line that may give an address, OCR
misreadings included, each with its line image from the Internet Archive. It runs on DuckDB over
the records Parquet and a word index beside it, with no SQLite. At 15.5M rows (2026-11-04, all
three tiers), on the laptop held to 2 threads (the free CPU tier's count): it starts in ~8 s and
~2 GB (the records go into memory), and a search with the resident trace takes 0.9-1.9 s ("100
5th av", 23,633 hits, 3.1 s). The full scan it replaced took 9-14 s on 8 threads (PIPELINE #39).
`browse/find_address.py` runs this same search, reading the file instead of loading it (~3 s for
one search).

## Running it locally

```bash
uv run space/build_parquet.py        # data/browse.db -> data/space/records.parquet (~4 min, ~550 MB)
                                     #   + records.words.parquet (~1 min, ~143 MB)
uv run --with-requirements space/requirements.txt python space/app.py
open http://127.0.0.1:7860
```

`build_parquet.py` makes a stand-in for the release: only the columns the app reads, the
`eval_holdout` rows dropped, ordered by year, volume, leaf and line. Then it writes the word index
beside it (`--index-only` writes just the index, for a Parquet that is already there). Rebuild both
after `browse/build_db.py` picks up new records. `RECORDS_PARQUET` points the app at another file;
`PORT` changes the port.

**The word index.** `records.words.parquet` lists every word of `raw_line`, `address_resolved` and
`home_address_resolved` (lowercased, split on anything but a-z and 0-9) with the row numbers holding
it, sorted by word, so a search reads only the row groups of its own words. It is stamped with the
records' row count and a fingerprint of their record ids in order. An index that is missing or
stamped for other records is rebuilt in memory at start-up, with a warning; that takes about a
minute on 8 threads and several on 2, so ship it beside the records. A search takes the rows
holding a street spelling or a number form that also hold a word reading as the number or one
digit off (every grade needs one). Of those it grades only the ones where such a token is followed,
within a few tokens, by a piece of the street word (`address_shape` in `search.py`). A line that
may wrap the address (a near number among its last two tokens) is read on into its next line only
when the two lines together have that shape. Both shape tests run in DuckDB, as RE2 patterns
translated from the Python ones (`re2`), so the rest never reach Python. All of these are
conditions every match meets, so the hits are the same as a full scan's: checked on 17 addresses
against the scanning version on 2026-11-04, and on 40 after the shape tests moved into DuckDB. The word counts behind `other_streets` are now rows
holding the word, the same count the CLI uses (`fts5vocab`'s `doc`), not occurrences. On one of the
17 that dropped one more spelling as another street: "24 Lef ferts pl" lost two `near` lines on
Ferns.

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
ZERO_RESULTS, none linked), never against Google itself. On 2026-11-05 it worked against Google
on the test Space (key as a Space secret): "155 Franklin" gave a Street View link for each pin,
Manhattan's Franklin St (heading 188°) and Brooklyn's Franklin Av (97°), with no key in the page.

The page and the script give the same lines: since 2026-11-04 the script runs this search over
the same Parquet. So neither shows a held-out row, such as "h 76 Leffert© pi" (1906BPL:1193:111,
an `adjacent` holdout), which the script found when it read browse.db.

## Putting it on Hugging Face (not done yet)

1. **The data.** The release Parquet, once it's up. The app reads these columns: `record_id`,
   `volume`, `leaf`, `line`, `year`, `label`, `usable`, `name_resolved`, `occupation_role`,
   `raw_line`, `address_resolved`, `home_address_resolved`, `crop`. If the release lacks `line`
   or `label`, derive them: `line` from `record_id`, `label` from the volumes table. Download the
   files to the Space's disk at startup (`huggingface_hub.snapshot_download`) rather than reading
   `hf://` paths: the records go into memory, and every search reads the word index. Ship
   `records.words.parquet` beside the records, built with `build_parquet.py --index-only --out
   <the release Parquet>`. It is tied to that file's rows and their order, so rebuild it whenever
   the release changes. The index names one file; a release in several files needs one index
   built over them in the order `read_parquet` reads them.
2. **The code.** A Space repo holding `app.py`, `search.py`, `where.py`, `requirements.txt`,
   this README (its header is the Space config), and a copy of `browse/find_address.py`.
   `search.py` imports that copy when it's beside it. Set `GOOGLE_MAPS_API_KEY` as a Space
   secret for the Street View links ("Where it is today" above).
3. **Hardware.** ZeroGPU, the one Gradio hardware a free account may use (up to 2 Spaces; the free
   CPU tier now needs PRO: creating a cpu-basic Gradio Space answers 402). Timed there on
   2026-11-05 in a private Space, `hadro/cde-finder-timing`, with the code and both Parquets in
   the Space repo (724 MB, accepted). The container had a 16-CPU quota and 104 GB: start-up 2.7 s;
   a search with the trace 0.4-1.9 s ("1 Wall st", "100 5th av" ~4 s), and 0.7-3.3 s (5-6 s)
   through the page from outside. Held to 2 threads it is slower than the laptop's 2. The header's
   `python_version: "3.12"` matters: the image's default 3.10 has no duckdb 2.0.0. So does the
   never-called `@spaces.GPU` function in `app.py`: without one ZeroGPU stops the Space once it
   has started ("No @spaces.GPU function detected during startup", tried). Hosting a
   CPU-only app on ZeroGPU may be outside that program's intent; HF says nothing either way.
