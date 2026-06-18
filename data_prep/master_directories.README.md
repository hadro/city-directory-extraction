# Master directory list (`master_directories.csv`)

A growing, multi-institution catalog of digitized city directories we want to **sample pages from**
— for (a) harvesting real era/place-authentic names into the synthetic generator, and later (b)
building the real eval panel and (c) per-publisher/era style coverage.

The page-sampler (`directory-pipeline/sources/sample_directories.py`) reads this file, resolves each
row to a IIIF manifest, samples K listing pages, and downloads **only those pages** (never whole
volumes) for the pipeline to OCR/extract.

## Schema (one row per directory volume)

| column | required | meaning |
|---|---|---|
| `source` | **yes** | which resolver to use: `nypl` \| `ia` \| `loc` \| `iiif` |
| `id` | **yes** | the source-specific identifier (see below) |
| `publisher` | rec. | Trow, Lain, Polk, Doggett, Sampson, Boyd, … |
| `city` | rec. | New York, Brooklyn, Chicago, … |
| `borough` | rec. | Manhattan \| Brooklyn \| Queens \| Bronx \| Staten Island \| "" |
| `year` | rec. | `1875` or `1875/76` |
| `start_page` | opt. | first **printed** listing page (skips front matter). Blank → sampler uses the middle ~80% of canvases |
| `end_page` | opt. | last printed listing page |
| `column_count` | opt. | print layout columns (1–5); useful later for style tagging |
| `sample_page` | opt. | a known-good listing page number (sanity reference) |
| `holding_institution` | rec. | NYPL, BPL, Columbia, LoC, Internet Archive, … (provenance) |
| `notes` | opt. | anything (e.g. microform, condition, "Greater NY") |

### What goes in `id`, per `source`
- **`nypl`** — the item **UUID** (e.g. `4b4b2b90-317a-0134-6800-00505686a51c`). Resolves to
  `https://api-collections.nypl.org/manifests/{id}` (the API host — the `digitalcollections.nypl.org`
  host is bot-blocked, don't use it).
- **`ia`** — the Internet Archive **identifier** (the slug in `archive.org/details/<id>`).
- **`loc`** — the Library of Congress item id or full `loc.gov/item/...` URL.
- **`iiif`** — a **full IIIF Presentation manifest URL** (v2 or v3) for anything else (BPL, Columbia,
  CONTENTdm, etc. — if an institution exposes IIIF, this works directly).

## Curation notes
- **Borough**: the NYPL seed rows default to `Manhattan` (NYPL's set is Manhattan-centric). **Verify
  and correct** — e.g. post-1898 Polk "Greater New York" volumes span all boroughs; Lain is Brooklyn.
- **Avoid eval leakage**: keep volumes used for the *evaluation* panel OUT of the sampling/harvest set
  (or mark them in `notes`), so they stay honest held-out tests. Currently held out:
  NYU's Trow Manhattan 1850/51 and the Lain Brooklyn 1897 volume.
- **Breadth is the goal**: aim for variety across **publisher × era × city/borough × institution** —
  that variety is what teaches the model to copy arbitrary names and generalize across styles.

## Seeded from
NYPL Space/Time `DIRECTORIES.md` (81 volumes, 1786–1921/22): every row is `source=nypl`. Extend by
appending rows from BPL / Columbia / Internet Archive / LoC and other cities.
