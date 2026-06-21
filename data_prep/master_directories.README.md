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
| `borough` | rec. | Manhattan \| Brooklyn \| Queens \| Bronx \| Staten Island \| "" — auto-filled by `ingest_collection.py` **only when a single borough is named in the title**; multi-borough volumes stay blank with a `covers X, Y` note |
| `year` | rec. | `1875` or `1875/76` |
| `start_page` | opt. | first **printed** listing page (skips front matter). Blank → sampler uses the middle ~80% of canvases |
| `end_page` | opt. | last printed listing page |
| `column_count` | opt. | print layout columns (1–5); useful later for style tagging |
| `sample_page` | opt. | a known-good listing page number (sanity reference) |
| `key_page` | opt. | page of the "Explanation of abbreviations" key (the volume's ground-truth legend); from visual sampling. See `style_profiles/` |
| `page_offset` | opt. | `canvas_index − printed_page` near the listing start (maps a printed/TOC page number to a scan canvas). Drifts across a volume — local anchor, not a global constant |
| `holding_institution` | rec. | NYPL, BPL, Columbia, LoC, Internet Archive, … (provenance) |
| `title` | rec. | the volume's title (MODS primary title / manifest label); auto-filled by `ingest_collection.py` |
| `notes` | opt. | anything (e.g. microform, condition, "Greater NY", `PHONEBOOK`, `covers …`) |

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

## Sources surveyed (provenance log)
What we've already mined, so we don't re-walk it. All ingested via `ingest_collection.py`.

| source / search | what it is | result |
|---|---|---|
| NYPL "New York City directories" (collection UUID `f7533140-…`) | NYPL's NYC directory set | **156 `nypl` rows** (seed + full ingest) |
| IA Trow gap-fill (item ids) | later Trow vols NYPL lacks | **+4 `ia`**: Trow general 1915/1917/1922-23 |
| IA `brooklyncitydirectoriesonmicrofiche` (BPL) | Brooklyn dirs + NYC phone books | **+186 `ia`**: 79 residential + **107 `PHONEBOOK`** |
| IA `durstoldyorklibrary?query=directory` | Durst Old York Library | **+27 `ia`** (KEEP-NYC-only; 69 hits, heavy noise) |
| IA `allen_county?query=directory` | Allen County PL genealogy (nationwide) | **+74 `ia`** NYC residential (of 1803 hits) |
| LoC `location:new york\|brooklyn & q=city directory` | LoC faceted search | **+2 `loc`** (22 hits, mostly guidebooks) |
| LoC `location:new york\|new york city & q=city directory` | LoC faceted search | **0** (127 hits, all noise) |
| LoC `fa=subject:directories \| location:new york` | LoC subject facet (the *right* facet) | 50 hits but ~all **upstate-county**; 0 net-new NYC |
| Wikipedia *Brooklyn directories* article (2026-06) | cross-check vs the published Brooklyn bibliography | **0 net-new**: the residential run (Spooner→Hearne→Smith→Lain→Upington→Brooklyn Directory Co., 1822–1912) is already held; the rest is BIZ/élite/blue-book/almanac/guidebook (excluded). Notably we **already hold** its "Not found online" Hope&Henderson *consolidated* series 1856–68 (LCCN 01-15253 = `loc/01015253` + `micro_IABROOKLYN_0035/0037/0039/0040/0042`). **1901 Upington confirmed absent from IA** (FamilySearch-only). |

**Query lessons:** on LoC use `fa=subject:directories`, never `q=city directory` (full-text → guides/
histories/fiction). IA `?query=` within a collection works but is full-text too → always curate.
**Aggregator / bibliography pages** (ldsgenealogy.com, the Wikipedia *Brooklyn directories* article)
are coverage cross-checks, not ingest sources — most of their links are paywalled (Ancestry/MyHeritage)
or out-of-scope specialty dirs; only the Internet Archive links resolve to IIIF. All cross-checks so
far return **0 net-new residential** volumes.

## Leads not yet ingested (areas of interest left untouched)
Deliberately out of the current **NYC-residential** scope, but catalogued here as known, ready leads:

- **National / other-city directories** (for the future *other-cities / cross-city transfer* goal):
  `allen_county` has **~1700 unreviewed non-NYC** directories (US-wide); LoC `subject:directories`
  surfaces **~24 upstate-NY county** gazetteer/business directories. `allen_county` is the richest lead.
- **Business / trade / copartnership / mercantile directories** (the "BIZ" shape — firms, not
  residents; a candidate *separate* model track). Seen but skipped: Wilson's business, Goulding's,
  Jones's mercantile, Trow business/copartnership, NY State business directory, Phillips' business.
- **Biographical / social / élite registers** (persons data, not residential dirs): "Prominent
  families of NY", "Makers of New York", "Men of affairs", "Notable New Yorkers", Phillips' élite,
  Lain & Healy's élite, "The list" (visiting/shopping).
- **Street / number directories & guidebooks** (no persons): Rand McNally street-number guides,
  "Miller's New York as it is", Wilson's street & avenue directory, etc. — not useful, don't ingest.
- **Telephone directories** — already in (`PHONEBOOK`-tagged, BPL 1909–1967) as a separate track;
  **post-1928 are likely in copyright**, and they're out of the 1786–1925 training era.
- **IIIF holders — both settled (2026), little left to walk):**
  - **Columbia** — the IA `durstoldyorklibrary` collection (already ingested) is a **sub-collection of
    the larger `ColumbiaUniversityLibraries`** collection. Diffed them: Columbia parent has 173
    "directory" items vs Durst's 69, i.e. **104 in Columbia but not Durst — but ~all non-city-directory**
    (~57 *Medical directory of NY* vols, ~25 missionary/student/church directories, trade/institutional).
    The only city-directory items outside Durst are **business** (`ldpd_6943151` Polk's/Trow's
    copartnership, `ldpd_10754283` Mercantile Union — BIZ, excluded) and a **third copy of the 1786 NY
    directory** (`ldpd_5684790`, already held ×2). So for *residential* NYC directories, Durst already
    covered Columbia; no need to walk Columbia's IIIF separately.
  - **BPL** — **no public IIIF**. Its Digital Collections is a custom Drupal app of CBH photos/maps,
    and its city directories were digitized straight to IA (already ingested). No separate trove.
- **Known gap**: Trow **1898/99** is absent from both NYPL and IA — try HathiTrust / Google Books / LoC.
- **Data cleanup leads**: the Durst `longworthsameric*` rows have **blank years** (the allen_county
  Longworths *have* years — cross-fill candidate); duplicate scans + p1/p2/p3 parts exist across IA
  collections (dedupe at sample time); `trowsgeneraldire1853trow` year is `REVIEW`-flagged.
