# NYPL Space/Time Directory: Lessons for NYC City Directory Extraction

**Written 2026-10-21** (Josh Hadro, with Claude). Exported from the working doc; the doc may be ahead of
this file. Companion to [PIPELINE.md](PIPELINE.md): everything here concerns a new post-model address stage
(normalization, geocoding) that does not exist yet.

## Executive summary

NYPL's Space/Time Directory (2016–2017, dormant since December 2017) built the stage our pipeline does not
have yet: turning a directory address into a historical street, an address point and a coordinate. Its code
is small and dated, but its data is CC0, still downloadable, and directly usable. Five things matter most:

1. **A CC0 parse of ~4.3M Manhattan entries, 1849–1880, is still online.** `city-directories.objects.ndjson`
   (2.2 GB, December 2017) has one record per OCR line with page UUID, pixel bbox, raw text, CRF-parsed name,
   occupation and addresses, and geocodes for 19–49% of lines. NYU's later release of the same work, which we
   use for eval, is CC-BY-SA-NC; this one is CC0, so it can feed training and silver labels where NYU's cannot.
2. **The historical geocoder is a usable baseline, with a hazard.** On our 4B model's own output for 6
   Manhattan volumes it placed 14–51% of addresses. But its fuzzy street match moves uptown streets onto
   downtown ones (`E. 79th` → East 19th Street): at least 11 of 218 hits (5%) were the wrong street, every one
   above 59th Street.
3. **The street and address gazetteers are the real asset.** 861 street centerlines (1855–1921) and 42,744
   address points, 84% of them from one 1857 Manhattan atlas, plus 158 ward polygons (1703–1895) and 746 1900
   enumeration districts. All CC0.
4. **The street normalizer is a ready rule set**, about 60 abbreviation fixes (`B'way`, `G'wich`, `Av. 6`) we
   can port to Python, with a few bugs to fix on the way (`Cortl'dt` → `Corlandt`, `B'man` → `Beckman`).
5. **Their data model fits our outputs.** Space/Time NDJSON (`id`, `type`, `validSince`/`validUntil`, `data`,
   `geometry` + a relations file) is a near-free export target for `assemble_records.py`.

The parsing side is less useful: their CRF parser ships with 70 labeled training lines and five labels,
against our 8-field contract and 1,583-line panel. Nobody has scored it on our panel yet; its value is as a
baseline to score and a source of silver data, not a technique to adopt.

Allmaps, the same author's current IIIF georeferencing project, is the way past the 1857 coverage limit: with
a georeferenced atlas, any house number found on the page image converts to a coordinate, and the same
transform in reverse gives reviewers an atlas crop at each placed address. It already holds NYPL's Map Warper
georeferencing, including thousands of 1850s–1910s insurance-atlas plates across all five boroughs; Manhattan
in the 1860s–1870s is the thin spot.

## Where our project stands today

Our pipeline already gets from scan to a structured, verbatim 8-field person record; it stops before anything
spatial. Addresses leave the pipeline exactly as printed (`h 256 Fulton`, `r97-15 97th av, Ozone Pk`), with no
street expansion, no historical street identity and no coordinates. That is the stage Space/Time built most of
its tooling for.

| Stage | Ours today | Status |
| --- | --- | --- |
| Catalog | `master_directories.csv`, 449 volumes, seeded from Space/Time's `DIRECTORIES.md` (81 NYPL volumes) | Done |
| Ingest + layout | IA hOCR → lines (`ia_volume_to_jsonl.py`), wrap joins, column roles, re-OCR tiers | Done, calibrated per volume |
| Line → record | Fine-tuned Qwen 4B, 82.0 normalized EM on a 21-volume, 1,583-line gold panel | Release candidate |
| Post-model | `copy_guard.py`, `resolve_dittos.py`, `assemble_records.py` (IIIF canvas + `xywh` per line) | Done |
| Address normalization | None: the contract stores addresses verbatim | **Gap** |
| Geocoding / street identity | None (MODEL_CARD: the model does not expand or geocode) | **Gap** |
| Linking people across years | None | **Gap** |

Two existing ties to Space/Time are worth knowing. Our catalog was seeded from its `DIRECTORIES.md`. And our
NYU external eval set (Wolf, Chioh, Balogh, Spaan 2020) is the output of the Space/Time CRF parser, run at
scale: its `labeled_entry` structure is that parser's output shape.

## Survey of the nypl-spacetime repositories

Of the ~40 public repositories reviewed, 12 bear directly on our work; nearly all were last committed in late
2017. The table is sorted by relevance to us. All code is MIT; all datasets named below are CC0 unless noted.

| Repo | What it is | How we could use it | Relevance |
| --- | --- | --- | --- |
| [nyc-historical-geocoder](https://github.com/nypl-spacetime/nyc-historical-geocoder) | Node geocoder: normalize street → fuzzy-match a street name (Lunr, edit distance ≤ 2) → exact match `number + street` against address points | Baseline geocoder for `address`/`home_address`; port to Python with fixes | High |
| [nyc-street-normalizer](https://github.com/nypl-spacetime/nyc-street-normalizer) | ~60 regex fixes + ordinal/avenue rules; 57 test cases | Port as `address_normalized` rules; reuse its tests | High |
| [etl-city-directories](https://github.com/nypl-spacetime/etl-city-directories) | hOCR tarballs → column detection → CRF parse → geocode → Space/Time dataset | Reference pipeline; its output dataset is the big asset | High |
| [city-directories](https://github.com/nypl-spacetime/city-directories) | `DIRECTORIES.md`: 81 NYPL volumes with `startPage`, `endPage`, `columnCount`; hOCR file naming | Already seeded our catalog; cross-check our listing bounds | Medium (used) |
| [city-directory-entry-parser](https://github.com/nypl-spacetime/city-directory-entry-parser) | sklearn-crfsuite parser, labels NC/OC/AC/PA/D; 70 labeled lines; 87,674 raw 1851/52 lines | Cheap CRF baseline to score; unlabeled real lines for noise and name pools | Medium |
| [hocr-detect-columns](https://github.com/nypl-spacetime/hocr-detect-columns) | Ckmeans clustering of line x-positions into n columns; k-NN joins indented run-overs | Second opinion against our `layout_roles` / `join_wraps` | Medium |
| [etl-building-inspector-nyc-streets](https://github.com/nypl-spacetime/etl-building-inspector-nyc-streets) | Builds `addresses`: snaps each crowdsourced house number to the nearest street ≤ 25 m and ≤ 15 years away | The rule to reuse if we extend the address gazetteer | Medium |
| [nyc-historical-streets](https://github.com/nypl-spacetime/nyc-historical-streets) | QGIS shapefiles of street centerlines for 10 Map Warper layers (1855–1921) | Street gazetteer source; layers 867 (Brooklyn 1886) and 883 (Bronx 1921) left unfinished | Medium |
| [etl-nyc-wards](https://github.com/nypl-spacetime/etl-nyc-wards), [etl-enumeration-districts](https://github.com/nypl-spacetime/etl-enumeration-districts) | Manhattan ward polygons 1703–1895; 1900 Manhattan/Bronx EDs | Spatial joins for aggregation and census linking | Medium |
| [spacetime-schemas](https://github.com/nypl-spacetime/spacetime-schemas), [spacetime-cli](https://github.com/nypl-spacetime/spacetime-cli) | Object/relation JSON Schemas; NDJSON → GeoJSON/CSV tools | Export format for our records | Medium |
| [label-fields](https://github.com/nypl-spacetime/label-fields), [fix-ocr](https://github.com/nypl-spacetime/fix-ocr), [brick-by-brick](https://github.com/nypl-spacetime/brick-by-brick) | Crowdsourcing apps: tag CRF training tokens; correct a line's OCR from its bbox crop | Design reference only; our `make_gold_tool.py` already covers this | Low |
| [tutorial-historical-addresses](https://github.com/nypl-spacetime/tutorial-historical-addresses), [maps-by-decade](https://github.com/nypl-spacetime/maps-by-decade), [etl-mapwarper](https://github.com/nypl-spacetime/etl-mapwarper) | Address tutorial; 5,000+ georectified maps grouped by decade, with tile URLs | QA: overlay geocoded records on a same-decade map | Low |

The rest (`etl-oldnyc`, `etl-nyc-churches`, `surveyor`, `building-inspector`, `etl-geonames`, `fuzzy-dates`,
`spacetime-etl`, `spacetime-config`) is photo geotagging, crowdsourcing infrastructure or the Node ETL runner,
with no direct use for us.

## Deep dive: nyc-historical-geocoder

The geocoder is 326 lines of Node and does one thing: given `"34 Talman Street"` and a borough, return a
GeoJSON point plus the IDs of the historical street and address it matched. It is a good design to copy and a
risky one to run unchanged.

**How it works.** Every step is one function in `index.js`:

1. `cleanAddress` strips everything but letters, digits, `.,½-'&` and spaces.
2. `parseAddress` requires a leading house number (`^([\d½]+) (.*)`), else it fails.
3. The street part runs through `nyc-street-normalizer` (`W. 17th` → `West 17th Street`).
4. Lunr full-text search over the borough's street names, each word longer than 3 letters allowed 2 edits;
   results are kept only if whole-string Levenshtein distance ≤ 2, best first.
5. `number + matched street name` must exist exactly in the address-point gazetteer, else it fails. No
   interpolation along the street.

**What it ignores.** Each street and address carries `validSince`/`validUntil`, but the geocoder never reads
them, so an 1880 entry is matched against an 1857 map. `borough` defaults to Manhattan, and the
city-directories ETL never passed one. Our contract keeps residence markers in `address` (`h 256 Fulton`), and
step 2 rejects those outright; the Space/Time data shows the same failure (`"value":"h 167 E . T8th"`, not
geocoded).

**Measured on our output.** The unmodified geocoder over the 4B release candidate's predicted `address` and
`home_address` for six Manhattan panel volumes, after stripping a leading `h`/`r`/`b`/`bds` marker and
anything after a comma:

| Volume | Year | Addresses | Placed | Rate |
| --- | --- | --- | --- | --- |
| rode1851 | 1851 | 71 | 36 | 51% |
| trowwilson1865 | 1865/66 | 197 | 88 | 45% |
| doggett1846 | 1846 | 50 | 17 | 34% |
| trow1884 | 1884/85 | 185 | 44 | 24% |
| trow1907 | 1907 | 89 | 17 | 19% |
| trow1913 | 1913 | 117 | 16 | 14% |

Stripping markers alone lifted trowwilson1865 from 36 to 88 placed. The fall after the 1860s is coverage, not
parsing: the address points are one 1857 survey, which stops well south of where the city grew.

**The false-positive hazard.** The edit-distance step turns an uncovered uptown street into a covered downtown
one: `E. 79th` → East 19th Street, `W 116th` → West 16th Street, `E. 128th` → East 18th Street, `W65th` → 6th
Street. At least 11 of 218 placed addresses (5%) landed on the wrong street, all above 59th Street, so the
error grows with the year. Two causes: numbered streets are fuzzy-matched like names, and the normalizer's
spelled-ordinal table stops at Fifty-ninth. The fix is cheap: match numbered streets exactly and allow edits
only on named streets.

**How to apply it.** Port the five steps to Python (Lunr → `rapidfuzz`), then add what it lacks: strip our
markers first, pick the borough from the catalog row (Lain → Brooklyn), filter the gazetteer to the layer
nearest the volume's year, match numbered streets exactly, and write a status per address (`placed`,
`street_only`, `no_street`, `no_number`) instead of throwing. `street_only` still has value: a street ID and
centerline with no house point.

## Data assets we can reuse

Every dataset below is still served from `s3.amazonaws.com/spacetime-nypl-org/datasets/<id>/` (checked
2026-10-21), even though `spacetime.nypl.org` no longer resolves. Each has `<id>.objects.ndjson`, usually
`.relations.ndjson`, `.geojson`, `.zip` and a `datapackage.json`. All were last built in December 2017;
download and pin copies now rather than depend on the bucket.

| Dataset | Contents | Objects file | License | Use for us |
| --- | --- | --- | --- | --- |
| `city-directories` | ~4.3M `st:Person` records, Manhattan 1849/50–1879/80 (Doggett, Trow/Wilson) | 2.2 GB | CC0 | Silver training/eval data, name and occupation pools, comparison baseline |
| `addresses` | 42,744 address points: 35,854 Manhattan 1857, 6,068 Brooklyn 1855, the rest 1890–1915 | 15 MB | CC0 | House-number gazetteer for geocoding |
| `nyc-streets` | 861 street centerlines: Manhattan 1857 (422), Brooklyn 1855 (212), Queens 1915 (125), Manhattan 1893–1903 (98) | 0.5 MB | CC0 | Street gazetteer: a street ID even when no house point exists |
| `nyc-wards` | 158 ward polygons in 11 periods, 1703–1895 | 0.1 MB | CC0 | Assign a ward to every placed record |
| `enumeration-districts` | 746 1900 census EDs, Manhattan and Bronx | 0.3 MB | CC0 | Link 1900-era records to census EDs |
| `building-inspector` | Crowdsourced building footprints and house numbers from insurance atlases | 70 MB | CC0 | Raw input to extend `addresses` |
| `perris-atlas-footprints` | Building footprints from Perris's 1854 atlas | 42 MB | CC0 | Context layer for 1850s volumes |
| `mapwarper` / `group-maps` | Outlines and tile URLs of 5,000+ georectified NYC maps, grouped by decade | 16 MB | CC0 | Pick a same-decade base map for QA |
| `emigrant-city` | Transcribed, geocoded Emigrant Savings Bank records | 8 MB | CC0 | Possible record-linkage partner |

**The city-directories dataset, in detail.** Each record has `id` = `<years>.<page>.<bbox>`, `name` (the first
parsed subject), and in `data`: `volumeUuid`, `pageUuid`, `pageNum`, pixel `bbox`, raw `text`, `occupation`,
`locations` (each with its `h`/`r`/`b` labels), and `geocoded` (address and street IDs); a point `geometry`
when geocoded. Sampling 34,000 records across the file put the geocode rate at 45% in 1849/50, falling to 19%
by 1879/80, 28% overall. Quality is uneven: OCR junk becomes persons (`"name":"nee ae"`), and wrapped lines are
joined with the run-over's text appended.

Three ways to use it:

- **Silver data at scale.** Unlike NYU's CC-BY-SA-NC release, this one is CC0, so it can feed training without
  tainting the model's license. Use it the way `harvest_own.py` uses pipeline output: filter, map to the 8
  fields, and keep it off the panel.
- **Name and occupation pools.** Surnames and occupations by year, 1849–1880, for `synth_persons.py` and
  `harvest_occupations.py`, with era skew built in.
- **Leakage check first.** It contains two volumes we evaluate on: Doggett 1850/51 (`4adf9ec0`, the NYU set)
  and Trow/Wilson 1865/66 (`4b119360`, `trowwilson1865` in the panel). Drop both before any use, and run
  `verify_harvest_leakage.py` over the rest.

## ETL rules and parsing techniques to adopt

The rules worth taking are the address rules; the parsing and layout techniques mostly confirm choices we
already made. None of this touches the model or the labeling contract: it all belongs in a new post-model
step beside `resolve_dittos.py`, writing new columns and never overwriting the verbatim 8 fields.

### Street normalization: port, then fix

`nyc-street-normalizer` runs nine steps in order: lower-case, trim, ~60 regex fixes, numeric ordinals (`19` →
`19th`), avenue rules (`Av. 8`, `8th Av` → `Eighth Avenue`; a bare `Fourth` → `Fourth Avenue`), append
`Street` when no street type is present, spelled ordinals to digits for non-avenues, capitalize. Its 57 test
pairs are a ready regression set. Testing it on forms from our own volumes turned up these defects:

| Input | Output today | Should be | Cause |
| --- | --- | --- | --- |
| `Cortl'dt` | Corlandt Street | Cortlandt Street | A misspelled rule fires before the correct one |
| `B'man` | Beckman Street | Beekman Street | Misspelled target |
| `W. Fortieth` | West Fortieth Street | West 40th Street | Table spells it "Fourtieth" |
| `Sixty-first` | Sixty-1st Street | 61st Street | Spelled-ordinal table stops at 59th |
| `n. Av. 4` | North Av. 4th Street | near Fourth Avenue | `n.` means "near" in early volumes, not North |
| `W'm` | W'm Street | William Street | Abbreviation missing (in their own 1851/52 sample) |
| `Water-street` | Water-street | Water Street | 1780s–1810s hyphenated form not handled |
| `Hudson R. R.` | Hudson R. R. Street | Hudson River Railroad (a place) | Non-street locations get `Street` appended |

The better source for the abbreviation table is ours: the 17 style cards in `data_prep/style_profiles/` record
each publisher's printed abbreviation legend (`key_page`). Seed the Python port with Space/Time's ~60 rules,
then add each legend's street abbreviations per publisher and era, so `n.` reads as "near" only where the
legend says so.

### Address pre-processing our contract needs

Our `address` keeps the printed residence marker (2,523 of 8,800 gold addresses do). Before normalizing:

1. Split the marker into its own column (`h`, `r`, `b`, `bds`, and print-fused forms such as `h463 W 166th`).
2. Split compound addresses on `&` and on `n.`/`cor.` ("corner of"), keeping each part's role.
3. Split a trailing neighborhood or town (`, Ozone Pk`, `, B'klyn`, `Orange, N. J.`) into a locality column
   that also overrides the borough.
4. Then normalize the street and geocode.

### Parsing and layout: what they did, compared with us

- **The CRF parser** tokenizes on spaces and on `.`, `,`, `&`, wraps each line in START/END tokens, and labels
  tokens as name (NC), occupation (OC), address (AC), address predicate (PA, the `h`/`r` marker) or delimiter
  (D). Features are a ±2-token window of case, digit, delimiter, `jr` and `wid`/`widow` flags. One feature is
  mis-coded (`word[2:]` where the name says the last two characters). It is worth a single run on our panel as
  a cheap extractive baseline next to GLiNER, nothing more.
- **hocr-detect-columns** clusters line left edges with Ckmeans into `columnCount + 4` clusters (±25 px
  tolerance, ≥ 50 lines per column) and attaches each unassigned (indented) line to its nearest line up and to
  the left. That is the same idea as our wrap joins, with the threshold problem we found on 1856BPL: a fixed
  pixel tolerance does not travel across volumes. Their ETL also never merged the bboxes of joined lines (a
  TODO in the code); ours keeps per-line `xywh`.
- **Stable IDs from geometry.** Their record ID is `<years>.<page>.<x0-y0-x1-y1>`, like our
  `<volume>:<leaf>:<n>`. Keep ours, and add their page UUID wherever our volume is the same NYPL item, so
  records can be joined to theirs.

## Data model, provenance and export conventions

We should publish an export in the Space/Time shape alongside our JSONL/CSV. It costs one writer function in
`assemble_records.py`, and it makes our records joinable with every dataset above without anyone writing glue
code.

The model, from `spacetime-schemas`, has three parts:

- **Objects** (`<dataset>.objects.ndjson`): one JSON object per line with `id`, `type` (`st:Person`,
  `st:Address`, `st:Street`, `st:Ward`), `name`, `validSince`/`validUntil` (years), a free-form `data` object,
  and an optional GeoJSON `geometry`.
- **Relations** (`<dataset>.relations.ndjson`): `{from, to, type}` edges, mainly `st:in` (a person in an
  address, an address on a street) and `st:sameAs` (one thing in two datasets). IDs from another dataset are
  prefixed with its name (`addresses/116808-1`).
- **A Frictionless `datapackage.json`**: title, license, sources, contributors with roles, and the file list.

A mapping for our records:

| Space/Time field | Our source |
| --- | --- |
| `id` | `record_id` (`<volume>:<leaf>:<n>`) |
| `type` | `st:Person` (their closed type list in `spacetime-config` has no business type, so keep `is_business` in `data`) |
| `name` | `name_resolved` |
| `validSince` / `validUntil` | the catalog `year` (`1865/66` → 1865, 1866), as their ETL did |
| `data` | the 8 verbatim fields, `raw_line`, `canvas` + `xywh`, `printed_page`, `district`, flags, and the new normalized-address and geocode-status columns |
| `geometry` | Point, or MultiPoint when both `address` and `home_address` are placed |
| relations | `st:in` → `addresses/<id>`, `nyc-streets/<id>`, `nyc-wards/<id>`; later `st:sameAs` between records of one person across years |

Two provenance conventions are worth copying even outside that export. Every dataset names its upstream
sources and contributors with roles (`wrangler`, `author`), which our dataset card can mirror. And every
geocode names the exact gazetteer object it matched, so a reader can audit a point, not just see it. Our
records already carry the IIIF canvas and line box; adding the gazetteer IDs completes the chain from page
pixel to map point.

## Gaps, caveats, licensing and maintenance

The biggest limit is coverage, not code: the gazetteers describe Manhattan around 1857 and Brooklyn around
1855, while our catalog runs 1786–1925 across five boroughs.

| Issue | Detail | Consequence for us |
| --- | --- | --- |
| Temporal coverage | 84% of address points are from one 1857 Manhattan atlas; Bronx and Staten Island have one street each | Expect useful geocoding for ~1840–1870 Manhattan and ~1850–1865 Brooklyn only; later volumes need other gazetteers |
| House renumbering | The geocoder matches an 1880 number against 1857 numbering, with no check | A placed point can be the wrong building even on the right street; flag any match more than ~15 years from the gazetteer layer |
| Fuzzy street match | Edit distance ≤ 2 on numbered streets | At least 5% wrong-street hits on our output; must be fixed before use |
| Dead website | `spacetime.nypl.org` does not resolve; the S3 bucket still serves files but refuses listing | Download and pin the datasets with checksums now |
| Unmaintained code | Node, 2017 dependencies, `standard` as the only test; one CLI bug passes the wrong option names | Port the logic to Python; do not add a Node dependency |
| Silver quality | The 4.3M city-directories records include OCR junk parsed as persons and joined run-overs | Filter with our `entry_rate` / `copy_guard` logic before any training use |
| Eval leakage | The CC0 dataset includes NYU's Doggett 1850/51 and our `trowwilson1865` volume | Exclude both, always |
| Licensing | Code MIT; Space/Time datasets CC0, except `oldnyc` and `nyc-churches` (CC BY-NC); the NYU repackaging is CC-BY-SA-NC | Prefer the CC0 S3 copy over NYU for anything that touches training |

**Other gazetteers to pair with this one.** For post-1870 coverage the usual sources are outside this org: the
NYC Open Data street and address layers (LION and PAD) for modern street identity, the NYC Department of City
Planning's historical street-name changes, and georectified atlases in NYPL's Map Warper for tracing more
layers the Space/Time way. These should be checked for license and fitness separately; they were not reviewed
here.

## Allmaps: IIIF georeferencing

[Allmaps](https://github.com/allmaps/allmaps) is the active successor to Space/Time's map work (last commit
2026-10-13), and it fixes our biggest gap: gazetteer coverage after the 1850s. It georeferences IIIF images in
place through a W3C standard, the [Georeference Annotation](https://iiif.io/api/extension/georef/): a Web
Annotation holding an image's IIIF URI, a mask polygon and ground control points. Its packages
(`@allmaps/annotation`, `transform`, `project`, `analyze`, `attach`, `io`, `id`) and the CLI are MIT;
georeference data is CC0; only the apps are GPL-3.0. New York Public Library is one of the organizations it
indexes (`iiif.nypl.org`).

Four uses for us, in order of value:

1. **Build address gazetteers for later decades.** Space/Time traced streets by hand in QGIS from one 1857
   atlas. With a georeferenced IIIF atlas, a house number or street label found anywhere on the page converts
   to a coordinate with `allmaps transform coordinates` (pixel → lon/lat, polynomial or thin-plate spline). Our
   pipeline already finds text in IIIF page images, so finding the printed house numbers on 1870s–1910s
   insurance atlases is a nearby task. Points on each street, from each decade, mean geocoding no longer stops
   at the 1857 survey.
2. **Side-by-side QA for the 150-per-era check.** The same transform runs in reverse (`toResource`): from a
   geocoded point to the pixel on a same-period atlas, then a IIIF Image API crop around it. A reviewer sees
   the directory line's crop (`canvas` + `xywh`, which we already have) beside the atlas at the placed spot,
   and judges "right street, right number" in seconds.
3. **Map overlays without hosting.** The Allmaps tile server turns any Georeference Annotation into XYZ tiles
   (`allmaps.xyz/{z}/{x}/{y}.png?url=…`), so our Datasette browser or a MapLibre page can show records over a
   warped period atlas. Its API can also list maps by area and source
   (`/maps?intersects=…&imageServiceDomain=iiif.nypl.org`), replacing Space/Time's static `maps-by-decade`
   list.
4. **One annotation model across text and maps.** Our records already point at a IIIF canvas and a line box.
   Publishing each record as a Web Annotation (canvas + `xywh` selector as the target, the 8 fields and the
   geocode as the body) would put directory lines and georeferenced maps in the same standard. Allmaps IDs (a
   SHA-1 of the IIIF URI) give a stable key to join the two.

Smaller points: `@allmaps/analyze` reports a georeferencing's residual error (RMSE) and distortion, which
bounds how far a point taken from that atlas can be trusted; and its geocoder UI queries the
[World Historical Gazetteer](https://whgazetteer.org), a candidate for non-NYC places in `home_address`
(`Orange, N. J.`).

**Caveats.** It is a TypeScript monorepo on Node 24; call the CLI as an external tool from `data_prep/`, or port
the transform math to Python, rather than add a Node dependency to the pipeline. Allmaps knows NYPL maps by
image, not by manifest (all `canvases` are empty), so look them up with `iiif.nypl.org/iiif/2/<image id>`, and
pass bounding boxes to its API latitude first.

### What NYPL coverage Allmaps already has (checked 2026-10-21)

Mostly reuse: the atlases we need are already georeferenced. A Manhattan query capped at 1,000 km² returned
100 maps (the limit, so there are more), with a median size of 0.05 km²: single insurance-atlas plates. 99
were bulk-created on 2022-07-10, and 59 of the 100 match by image ID the Map Warper maps in Space/Time's CC0
`mapwarper` dataset, so Allmaps evidently imported NYPL's Map Warper georeferencing.

That makes the `mapwarper` file (9,657 maps, with image IDs, ground control points, descriptions and years) a
free offline inventory of what Allmaps holds, as of 2017. Its city-scale sheets (≤ 2 km²) by decade and
borough, placed by the centre of each sheet:

| Decade | Manhattan | Brooklyn | Bronx | Queens | Staten Island |
| --- | --- | --- | --- | --- | --- |
| 1850s | 343 | 9 | 0 | 0 | 0 |
| 1860s | 75 | 8 | 1 | 0 | 0 |
| 1870s | 39 | 7 | 5 | 2 | 1 |
| 1880s | 872 | 719 | 73 | 237 | 195 |
| 1890s | 367 | 87 | 127 | 1 | 0 |
| 1900s | 425 | 198 | 261 | 63 | 22 |
| 1910s | 521 | 56 | 167 | 31 | 120 |
| 1920s | 54 | 17 | 81 | 71 | 1 |

Read the decades loosely: Map Warper's year field is unreliable (sheets from "Atlas 108, Vol. 1, 1903" are
dated 1884), so group by the atlas citation in each description instead. The large runs are Bromley and
Robinson insurance atlases: Manhattan 1894–1915, Brooklyn 1893–1907, Queens 1901–1912, Staten Island
1898–1917, Bronx from the 1900s. The thin spot is Manhattan in the 1860s and 1870s, which is exactly where
Space/Time's 1857 address points stop working. The other 41 of the 100 are not in the 2017 file (image IDs
from `57565…`), so they were added later; the live API is the only full list of those.

**Beyond NYPL.** A second query over the same box without the NYPL filter returned 200 maps, the cap for
anonymous users, so it was cut off: 191 NYPL and 9 Library of Congress Sanborn sheets. The LoC sheets are
Manhattan 1905 vol. 1 (3 sheets around the Bowery and Greenwich Village, created 2026-10-13, so someone is
working on it now), Brooklyn 1888 vol. 9 (5 sheets, Williamsburg and Bushwick, 2022) and Brooklyn 1951 vol. 4
(1 sheet, 2024). No other institution appeared. LoC's other NYC Sanborn volumes would need georeferencing in
Allmaps Editor, which opens their IIIF manifests directly; none of this fills the 1860s–1870s Manhattan gap.

**Querying tips.** Give `intersects` as south, west, north, east, latitude first. Pass `maxArea=1000000000` to
drop world maps. Anonymous queries return at most 200 maps, so use small boxes. To see only what was added
after the July 2022 Map Warper import, pass `modifiedAfter=2022-07-11`.

### Full sweep, all five boroughs (2026-10-21)

Nine area queries (maps added after the July 2022 import) plus one LoC-only query returned 485 unique maps.
North Brooklyn and Queens hit the 200 cap, so those two are incomplete. What matters for geocoding is
address-scale sheets (under 0.5 km²), and nearly all of those come from one place:

| Source | Maps | Address-scale sheets | What they are |
| --- | --- | --- | --- |
| NYPL, added since 2022 | 193 | 188 | One complete Manhattan atlas, 187 plates (image IDs 5222332–5222522, Battery to Inwood), georeferenced 17–24 Jan 2025; title and year not yet identified |
| NYPL, from the Map Warper import | 25 | 9 | Insurance-atlas plates also in the 2017 `mapwarper` file |
| David Rumsey | 149 | 3 | City and borough maps, mostly added Feb 2025 |
| Library of Congress | 45 | 11 | Sanborn Brooklyn 1888 vols. 7 and 9, Sanborn Manhattan 1905 vol. 1, and 9 plates of an "Atlas of the city of New York, Manhattan Island" (~1 km² each) |
| Digital Commonwealth | 41 | 1 | Historical city plans, 1660s–1900s |
| Others (Princeton, Harvard, Michigan, UW–Milwaukee, NYU, Smithsonian, Northwestern, Internet Archive, a Map Warper bridge) | 32 | 5 | Single maps |

The 1860s–1870s gap is smaller than it looked. The 2017 `mapwarper` file already holds 20 sheets of the 1867
*Plan of New York City, from the Battery to Spuyten Duyvil Creek*, which shows every lot and prints street
numbers at the corners of blocks, enough to interpolate house numbers along each block. It also holds 68
Bromley sheets dated 1879–80. Next step: identify the January 2025 atlas from any one of its plates.

## Recommended roadmap

Start with the address stage: it is new capability, it needs no retraining, and it leaves the panel and the
labeling contract untouched. In priority order:

1. **Pin the data.** A `data_prep/fetch_spacetime.py` that downloads the objects, relations and datapackage
   files for `city-directories`, `addresses`, `nyc-streets`, `nyc-wards` and `enumeration-districts` into
   `data/spacetime/` with SHA-256 checksums, plus a row in the catalog README's provenance log.
2. **Address normalization**, `postprocess/normalize_address.py`: split marker, compound parts and locality;
   port the street normalizer with the fixes listed above; add per-publisher abbreviations from the style-card
   legends. New columns only (`address_marker`, `address_number`, `address_street_norm`, `address_locality`).
   Tests: their 57 pairs plus our own forms.
3. **Geocoding**, `postprocess/geocode.py`: the five steps in Python, with borough from the catalog, the
   gazetteer layer nearest the volume's year, exact matching for numbered streets, a `geocode_status` per
   address, and the matched street and address IDs. Ward and enumeration district by point-in-polygon.
4. **Measure it before shipping it.** Fix the numbered-street match first. Then hand-check 150 placed addresses
   per era (1840–1859 and 1860–1879), starting with `rode1851` and `trowwilson1865` against a same-period atlas
   (the Allmaps section shows how to put the atlas crop beside the directory line); report precision by status.
   Ship only if the sample shows no systematic error and wrong-street placements are under an agreed threshold.

   Proposed threshold: **2% wrong-street**, shown with at most 1 error in 150 checks per era (0 in 150 bounds
   the true rate near 2% at 95%, by the rule of three). Systematic errors, such as the uptown-to-downtown
   shift, get zero tolerance and are fixed in code. A right street but wrong building, from renumbering since
   the gazetteer's year, is reported as its own rate and flagged when the volume is more than ~15 years from
   the gazetteer layer; it does not count against the 2%.
5. **Space/Time export** in `assemble_records.py` (`--format spacetime`), mapped as in the data-model section,
   so the records open in QGIS or geojson.io directly.
6. **Use the CC0 silver set.** First as name and occupation pools by year, 1849–1880 (low risk). Then,
   separately and A/B-tested, as training augmentation, remembering the project's own finding that field rates
   do not transfer but demonstrated transformations do. Exclude `4adf9ec0` and `4b119360` throughout.
7. **Score their CRF parser once** on the panel, as a second extractive baseline next to GLiNER.
8. **Later:** extend coverage past 1870 (harvest house numbers from georeferenced later atlases with Allmaps,
   as above; or finish Space/Time's unfinished layers 867 Brooklyn 1886 and 883 Bronx 1921), and link one
   person across annual volumes with `st:sameAs`, using name + occupation + placed address.

### Where the code lives

Build it inside this repo first, under `postprocess/` (`normalize_address.py`, `geocode.py`) with the
gazetteer fetch in `data_prep/`. It reads what `assemble_records.py` writes and is measured against our own
predictions and panel, so while its columns are still changing, one repo avoids versioning across two.

Plan to spin it out as a third companion repo once the geocode columns are frozen and the 150-per-era check
passes. It is useful without our model (on the CC0 Space/Time set, on NYU's data, on anyone's NYC address
strings), and it brings dependencies the model side never needs: GIS libraries and multi-megabyte gazetteers.
In the planned `city-directory-data` / `city-directory-model` split it belongs to neither half, since it sits
downstream of the model's output. This report travels with the code as `docs/SPACETIME.md`.

### Sources

Repositories reviewed (all under [github.com/nypl-spacetime](https://github.com/nypl-spacetime), cloned
2026-10-21): [nyc-historical-geocoder](https://github.com/nypl-spacetime/nyc-historical-geocoder),
[nyc-street-normalizer](https://github.com/nypl-spacetime/nyc-street-normalizer),
[etl-city-directories](https://github.com/nypl-spacetime/etl-city-directories),
[city-directories](https://github.com/nypl-spacetime/city-directories),
[city-directory-entry-parser](https://github.com/nypl-spacetime/city-directory-entry-parser),
[hocr-detect-columns](https://github.com/nypl-spacetime/hocr-detect-columns),
[etl-building-inspector-nyc-streets](https://github.com/nypl-spacetime/etl-building-inspector-nyc-streets),
[nyc-historical-streets](https://github.com/nypl-spacetime/nyc-historical-streets),
[etl-nyc-wards](https://github.com/nypl-spacetime/etl-nyc-wards),
[spacetime-schemas](https://github.com/nypl-spacetime/spacetime-schemas),
[spacetime-config](https://github.com/nypl-spacetime/spacetime-config),
[tutorial-historical-addresses](https://github.com/nypl-spacetime/tutorial-historical-addresses),
[nypl-spacetime.github.io](https://github.com/nypl-spacetime/nypl-spacetime.github.io) (dataset list). Also
[allmaps/allmaps](https://github.com/allmaps/allmaps) (cloned 2026-10-21; package READMEs and API routes read,
live API not reachable from the sandbox). Datasets read from `s3.amazonaws.com/spacetime-nypl-org/datasets/`.
Geocoding measurements: the unmodified geocoder on `results/runs/scale-runs/preds/preds_4b-100k_*.txt` in this
repo.
