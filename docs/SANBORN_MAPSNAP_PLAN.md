# mapsnap and the city directories: linking listings to Sanborns and other spatial data

**Date:** 2026-11-16. **For:** hadro, and any session picking up Phase 6 of `docs/RENUMBERING_PLAN.md`.
**Also kept as a Claude Doc:** https://claude.ai/artifact/7YA4cKqXtUKgh6JEzZk3TB (same content, with the
diagram and the two crops shown).
**Status:** research and plan only. Nothing here is built; the lookup below was a scratch script, not kept.

## Summary

We don't need to run mapsnap to use it in NYC. Its published v2.0 run (2026-10-24) already places 9,332
of the 12,362 Library of Congress Sanborn sheets for New York City, 1885-1951. Each placement is an
Allmaps-ready IIIF georeference.

- **A point lookup works today.** Our address point for 462 Court St falls on Brooklyn 1886 vol. 1 sheet
  18L and on vol. 1 sheet 39 in 1904, 1915, 1939 and 1950. A full-resolution crop centred on the computed
  pixel lands on the building, and its printed house number is legible.
- **The overlap with our data is large.** About 10.5 million of the finder's 14.2 million usable lines are
  from 1885 or later: Trow's Manhattan 1903-22 and Brooklyn 1886-1912. Manhattan before 1876 needs NYPL's
  atlases instead, and most of those are already in Allmaps from Map Warper.
- **It settles two open items in `docs/ATLAS_INVENTORY.md`.** mapsnap did place the 1886-88 Brooklyn
  edition, though only 248 of its 564 sheets. The sheet showing Court St at 3rd Pl is now a lookup, not a
  search.
- **There are ideas to borrow and something to give back.** We can borrow its two methods: reading text
  against a known vocabulary, and carrying a placement from one edition of a sheet to the next. Our street
  registry of renamings is the kind of data mapsnap says it lacks.
- **Main caveats:** mapsnap's NYC accuracy is untested against human placements except for Brooklyn 1939.
  Its annotations are licensed ODbL (share-alike). Its mirrored images are a quarter of full size, too small
  to read house numbers, so readings need the Library of Congress originals.

## What mapsnap does

[mapsnap](https://github.com/danvk/mapsnap) (Dan Vanderkam, Apache-2.0, Python) georeferences Sanborn
fire-insurance sheets automatically. It reads the printed street names and fits them to OpenStreetMap. It
has been run over the whole Library of Congress Sanborn collection: v2.0 places 343,403 sheets from about
35,100 volumes. Placements are published at
[data.mapsnap.org](https://data.mapsnap.org/runs/v2.0/items.tsv) and browsable in the
[mapsnap.org atlas](https://mapsnap.org/atlas). The repo is active: its last commit was 2026-10-29.

How a volume is placed ([HOW-IT-WORKS](https://github.com/danvk/mapsnap/blob/main/docs/HOW-IT-WORKS.md)):

1. **Inputs.** It takes the LoC IIIF manifest for a volume and an OpenStreetMap extract of its county.
   Scans are worked on at 25% of full size.
2. **Find text.** EasyOCR's CRAFT detector runs on each sheet at 0°, 90° and 270°.
3. **Read streets against a vocabulary.** A recognizer fine-tuned on Sanborn lettering decodes each box
   through a prefix tree of nearby OSM street names, so every read is a real street. It uses no language
   model.
4. **Locate the sheet.** It reads the volume's key map, whose printed sheet numbers give each sheet a
   search centre. Margin numerals on each sheet name its neighbours, which builds an adjacency graph.
5. **Fit.** Each street label is extended along its axis. Crossings that also exist in OSM become control
   points. RANSAC picks the pair of points that best explains the other labels, giving a four-parameter
   Helmert fit (shift, scale and rotation).
6. **Rescue and refine.** A road-probability UNet is matched against OSM's street geometry, which places
   sheets whose labels failed. One arbiter then picks one pose per sheet.
7. **Publish.** It writes a IIIF Georeference AnnotationPage per volume. Each sheet gets control points, a
   clipping mask that gives each block to one sheet, and a confidence score.

**Accuracy.** It is scored against the hand placements of OldInsuranceMaps.net volunteers. Pooled over 689
volumes, 80.0% of sheet weight lands within 25 ft and 1.2% lands 200 ft or more off. Its score is the first
minus the second, 78.7%. In NYC only Brooklyn 1939 vols. 1-2 have truth; vol. 1 scores 87.2%.

**Where it fails, by its own account:** where streets were renamed or reworked since the survey (Queens
before its 1911 renaming is its example), on short street names, and in Washington, DC. It matches against
today's streets, so a street that is gone or renamed gives it nothing.

**What a published sheet looks like.** Each sheet is one annotation, which contains:

- a label ("Brooklyn, New-York | 1906 | sanborn05791_018 p11")
- a `confidence` between 0 and 1
- an SVG mask polygon in pixel space
- two control points with a `helmert` transform (5,938 of the 6,774 Brooklyn and Manhattan annotations; a
  split sheet's panels are annotated separately), or four corners with an order-1 polynomial

Images point at a mirror (`cdn.chronoscope.io`) that serves the 25% copy only (level 0, about 1,400 px
wide). The full scan, four times larger, is at `tile.loc.gov` under the same service id. The annotations are
licensed [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/).

## Where our data stands spatially

Today our records reach the ground only through today's addresses. The renumbering crosswalk is the bridge
to the past. What is built (branch `claude/tender-planck-rcrih6`, as of 2026-11-16):

| Piece | What it gives | State |
| --- | --- | --- |
| Finder map (`space/where.py`, PIPELINE #40) | A pin for today's address from NYC GeoSearch, an OpenStreetMap embed, and a Street View link | Live on the test Space |
| Location search (`space/here.py`) | Buildings near the phone, ranked by distance to the city's footprints, with PLUTO's year built | Local and test Space |
| Renumbering crosswalk (`addresses/`) | Any address in any era as its form in every other era. Brooklyn 1871-75: 432 chains on 149 streets, 91% of held-back anchors placed and 85% of those right. `tables/eras.csv` has 1,659 eras on 1,053 streets | Committed, not pushed; the finder uses it locally |
| Street registry (`addresses/registry.py`) | 6,059 street ids. It includes the 65 renamings of 1871, read from leaves 934-935 of `1871BPL` | Committed |
| 1855 Perris atlas numbers (Space/Time `addresses`) | 6,068 house numbers with points on 159 Brooklyn streets; 3,031 pair with a point of today's within 15 m | Used as a check, not in the fit |
| Allmaps coverage (`results/allmaps_coverage.py`) | Of 740 sampled NYPL Map Warper sheets, 734 already have Allmaps annotations | Measured |
| Geocoded directory (plan Phase 6.1) | `bbl`, `bin`, `lat`, `lon` and a crosswalk grade on every line | Not built |
| Sheets georeferenced and read (Phases 6.2-6.3) | House numbers read off atlas sheets, as anchors | Not started |

The plan already names mapsnap as the second source for Phase 6.2 ("tried on one Brooklyn volume first").
`docs/ATLAS_INVENTORY.md` left two questions open that the published run now answers. First, mapsnap did
place the 1886-88 Brooklyn edition: 248 of 564 sheets. Second, the sheet with Court St at 3rd Pl is vol. 1
sheet 18L in 1886 and vol. 1 sheet 39 from 1904 on.

## How mapsnap might be useful

Most of the value is in mapsnap's output, not its code. Its run has done Phase 6.2 for every Library of
Congress Sanborn of New York City. For us, using it starts with downloading 189 JSON files.

**NYC in the v2.0 run, against our directories** (from mapsnap's `items.tsv` and our
`data/space/records.parquet`, both read 2026-11-16):

| Borough | LoC volumes | Years | Sheets placed | Our directories in those years |
| --- | --- | --- | --- | --- |
| Manhattan and the Bronx ("New York") | 73 | 1890-1951 | 3,847 of 4,628 (83%) | Trow 1903-22: 41 volumes, 7.9 M usable lines |
| Brooklyn | 46 | 1886-1951 | 2,842 of 3,538 (80%) | 1886-1912: 20 volumes, 2.6 M lines |
| Queens | 30 | 1898-1951 | 1,719 of 2,889 (60%) | none (ours are 1885-91) |
| Staten Island | 13 | 1885-1950 | 849 of 965 (88%) | none |

The 1904-08 Brooklyn edition (16 volumes) is placed best: 1,384 of 1,543 sheets (90%). The 1886-88 edition,
the one nearest the Williamsburg renumbering, is placed worst: 248 of 564 (44%). Queens' 1886-97 village
volumes are barely placed, 39 of 151 sheets. Our Manhattan directories of 1786-1876 have no LoC Sanborn;
they need NYPL's Perris, Dripps and Robinson atlases through Allmaps.

**Three ways to use it, cheapest first:**

1. **Use the placements as data.** Any point and year gives the sheets that cover it, the pixel on each
   sheet, and a full-resolution crop (next section). The same annotations draw as overlays through Allmaps'
   map plugins ([`@allmaps/maplibre`, Leaflet, OpenLayers](https://allmaps.org/)), so the finder's map could
   show the Sanborn of a line's year under the pin.
2. **Run the tool where the run is weak.** The 1886-88 Brooklyn volumes and the Queens villages are its weak
   spots. Its README blames renamed streets for failures like these, and our registry holds Brooklyn's
   renamings (see "Other ideas"). It also has a bring-your-own-images mode. That might work on NYPL's
   street-labelled Bromley, Hyde and Robinson plates, but the README makes no claim beyond Sanborns, and Map
   Warper's placements of many of those plates are already in Allmaps.
3. **Borrow two methods.**
    - *Reading against a vocabulary.* mapsnap decodes every street label through a tree of street names
      known to be near the sheet. When we read house numbers off a sheet, the crosswalk already says which
      numbers to expect along that frontage. We can also read street names against the registry's list for
      that year, rather than today's.
    - *Edition transfer* (`mapsnap/edition_transfer.py`). Sanborn kept sheet numbering across editions, so a
      sheet placed in one edition is placed in another by matching the two images, not the city. Brooklyn
      vol. 1 sheet 39 draws the same ground in 1904, 1915, 1939 and 1950. Our 1904 placement for 462 Court
      St falls at pixel (288, 980) of that sheet, and at (282, 967), (261, 967) and (286, 958) in the later
      three editions. Anything we read or correct on one edition carries to the rest.

## Connecting directory records to Sanborn sheets

A directory line reaches a building on a Sanborn sheet in six steps. Steps 1-3 are our crosswalk and
geocoding work, and mapsnap has already done the hard part of 4-5.

1. **Read the address as printed.** `addresses/streets.py` gives number, street key and place. It reads
   95.1% of Brooklyn's address lines that hold a digit.
2. **Carry it to today and to the sheet's year.** `addresses/chain.py` gives the address in every era of its
   street, with a grade. Today's form gets the point, and the sheet year's form is the number to look for on
   the sheet. Sanborn printed the numbers in force when a sheet was surveyed. So a line from 1868 is looked
   for under its post-1875 number on an 1886 sheet.
3. **Find a point for today's address,** with its BBL and BIN, from the city's address points
   (`data/city/uf93-f8nk.csv`, 967,871 rows) or GeoSearch.
4. **Find the sheets under the point.** Map each placed sheet's mask to the ground through its control
   points, then test the point against it. Keep the edition nearest the line's year, above a confidence
   floor. A 60-line scratch script did this across all 6,774 Brooklyn and Manhattan annotations in seconds.
5. **Find the pixel on each sheet.** Invert the sheet's transform: two control points fix a Helmert exactly,
   and `@allmaps/transform` does the general case. Multiply by 4 for the LoC scan, and ask LoC's IIIF server
   for a region around that pixel.
6. **Read the building.** A sheet gives the house number, the storeys, brick or frame, and the use (S. for
   store, D. for dwelling). It also names uses outright, such as "Hand Printing" at 458 Court St in 1904.

The check that makes it trustworthy runs from step 6 back to step 2: a printed number that matches the
crosswalk confirms both the crosswalk and the placement.

**Worked example: 462 Court St.** Our address point (-73.99806, 40.67823) falls on these sheets:

| Edition (LoC item) | Sheet | mapsnap confidence | Pixel (25% frame) |
| --- | --- | --- | --- |
| Brooklyn 1886 vol. 1 (sanborn05791_001) | 18L | 0.98 | (1211, 1046) |
| Brooklyn 1904 vol. 1 (sanborn05791_013) | 39 | 0.99 | (288, 980) |
| Brooklyn 1905, unnumbered (sanborn05791_029) | 2R | 0.12 | (438, 1590) |
| Brooklyn 1909, unnumbered (sanborn05791_030) | 2R | 0.14 | (315, 1678) |
| Brooklyn 1915 vol. 1 (sanborn05791_032) | 39 | 0.97 | (282, 967) |
| Brooklyn 1939 vol. 1 (sanborn05791_053) | 39 | 0.98 | (261, 967) |
| Brooklyn 1950 vol. 1 (sanborn05791_059) | 39 | 0.99 | (286, 958) |

The two low-confidence rows are why a confidence floor is needed. The full-resolution crops of 1886 and
1904, centred on the computed pixel with no hand adjustment, both land on the row 456-470 Court St:
three-storey brick stores numbered as they are today. In 1886 (sheet 18L, drawn with Court St at the top)
the pixel falls on the line between 460 and 462; in 1904 (sheet 39) it falls on lot 462 itself, with 433-447
across the street and 458 marked "Hand Printing". So on this block face the 1886 numbering is today's,
which agrees with the crosswalk's finding for Court St.

To re-fetch the two crops (800 x 800 px, the pixel at the centre; LoC answered with a browser-like
`User-Agent`, e.g. `curl -A "Mozilla/5.0"`):

- 1886: `https://tile.loc.gov/image-services/iiif/service:gmd:gmd380m:g3804m:g3804bm:g3804bm_g05791188601:05791_01_1886-0018L/4444,3784,800,800/full/0/default.jpg`
- 1904: `https://tile.loc.gov/image-services/iiif/service:gmd:gmd380m:g3804m:g3804bm:g3804bm_g05791190401:05791_01_1904-0039/752,3520,800,800/full/0/default.jpg`

mapsnap puts 80% of sheet weight within 25 ft of the volunteers' placement, and a Brooklyn lot is roughly
20-25 ft wide. So a lookup can land a lot off, and a crop should show the block face, not one lot; the
printed numbers then settle which lot. The check runs both ways. A printed number that matches the crosswalk
confirms both the placement and the crosswalk, and a mismatch flags one of them. This is the plan's own
Phase 6.2 test ("grade A points land on the buildings carrying those numbers"), and it can now run without
georeferencing anything ourselves.

## Other ideas for linking the directories to spatial data

The strongest idea is to use Sanborn sheets as renumbering evidence at scale. They could answer the
crosswalk's largest open question for the roughly 90% of addresses the 1855 atlas cannot reach. The rest
build on the same lookup.

| Idea | What it gives | First step |
| --- | --- | --- |
| **Sanborns as renumbering evidence** (the plan's kind D, at scale) | `chain.py` cannot yet say whether the last directory's numbering is today's on 683 streets (90% of addresses). Numbers printed on the 1904-08 Brooklyn sheets, against today's address points at the same spot, would answer it. The 1886-88 edition sits inside the Williamsburg 1887-89 event | Read 2 numbers per block face on 50 block faces. Gate: the numbers rise along the frontage, one parity per side |
| **House histories** | Every directory line at one building, beside that building on each Sanborn edition. It shows when a building was replaced, which the plan's Phase 6.4 wants and neither numbers nor PLUTO can say | A "this building" view in the finder: the crosswalk's groups plus one crop per edition |
| **The Sanborn in the finder** | A crop of the sheet nearest the line's year, beside the line image the finder already shows. Later, the sheet drawn under the map pin with `@allmaps/maplibre` | A IIIF region link per line, fetched only on demand, like the finder's IA images. Allmaps' own [Here](https://here.allmaps.org) app does the same for the phone's location, so "where you're standing" could add "and in 1906" |
| **Uses and businesses on the sheet** | Sanborn's printed uses (S., D., "Hand Printing") at an address, beside the directory's occupations and the business-directory sibling's firms. mapsnap's text detector finds every word on a sheet but keeps only street names | Ask whether mapsnap's text boxes (`p*.boxes.json`) for NYC can be shared, or detect text on one volume's full-resolution scans ourselves |
| **Street names of the period, for mapsnap** (giving back) | An alias table of old name to current street, from the registry (the 65 renamings of 1871, the guides' "(late X)" names) and `street_strings.parquet` (71,920 place-decade-street rows). mapsnap says renamed streets defeat it | Export the table and ask Dan Vanderkam whether it fits mapsnap's vocabulary step. Test it on the 1886-88 Brooklyn volumes. Whether renamings explain their 44% is unchecked |
| **A historical geocoder** | Address ranges per block face per year, from directories, guides and crosswalk, checked against Sanborn numbers. It would geocode other sources of the period, such as census and newspapers. Mapping Historical New York traced ranges like these for 1850, 1880 and 1910 but publishes no data | After Phase 6.1, the geocoded directory |

## Risks, open questions and first experiments

The first experiment costs a day and decides the rest: check mapsnap's NYC placements against our own grade
A addresses.

**Risks**

- **Accuracy is unmeasured in NYC.** Only Brooklyn 1939 vols. 1-2 have volunteer truth. Our grade A
  crosswalk points are an independent check, and nobody else has one.
- **A lot is about the size of the error.** A within-25-ft placement on a 20-25 ft lot needs the printed
  number to pick the lot. Without a reading, the lookup gives a block face.
- **Licence.** The annotations are ODbL 1.0, so a published database built on their geometry must carry ODbL
  too. That bears on the open release decision about licence. mapsnap's code is Apache-2.0. LoC's rights
  statement for the scans was not checked.
- **Images.** The mirror holds the 25% copy only. Full-resolution regions came from `tile.loc.gov` on
  2026-11-16, but mapsnap reports LoC downloads as unreliable behind Cloudflare. Any reading job needs a
  cache and a polite request rate.
- **A moving target.** v2.0 was republished on 2026-10-24. Pin the run version, as the business-directory
  sibling pins its ports.
- **Gaps.** No LoC Sanborn covers Manhattan before 1890, so our 1786-1876 Manhattan lines depend on NYPL
  atlases. The 1886-88 Brooklyn edition is 44% placed.
- **Publishing.** The renumbering plan's rule 5 holds: no annotation, crop or overlay goes public without
  hadro.

**Open questions**

- After a renumbering, did Sanborn print the old numbers too, or only the new? Look at Bronx sheets after
  1907-08 and Williamsburg sheets after 1887-89.
- Which "New York" volumes cover the Bronx? The item titles don't say.
- Would Dan Vanderkam share NYC text boxes, and would he take an alias table?

**First experiments, cheapest first**

1. **Fetch and index (half a day).** A script under `results/` pulls the 189 NYC annotation files (about
   12 MB for Brooklyn and Manhattan) from `https://data.mapsnap.org/runs/v2.0/iiif/chronoscope/<main>`,
   where `<main>` is the `main` column of `items.tsv`. It writes a sheet table with item, year, volume,
   sheet, confidence, ground polygon and transform. It must be re-runnable, like everything in
   `addresses/`.
2. **Spot check (a day).** Draw 50 grade A Brooklyn addresses across 1886-1912 and crop each from the
   nearest-year sheet at full resolution. Read the number by eye or with Sonnet. Measure the share that lands
   on the right building, by edition and confidence.
3. **Finder crop, local only.** Add "On the Sanborn, 1906" beside each line, with no new library.
4. **The Phase 6.3 pilot on Sanborns.** Read every number on one block face in 1886 and 1904, and compare it
   with the crosswalk.
5. **Talk to Dan Vanderkam** about the alias table, NYC truth and the text boxes.

## Sources

- [danvk/mapsnap](https://github.com/danvk/mapsnap): README, `docs/HOW-IT-WORKS.md`, `docs/corpus-run.md`,
  `mapsnap/edition_transfer.py`, `scripts/atlas/` (cloned 2026-11-16, commit 672c155)
- [mapsnap v2.0 item list](https://data.mapsnap.org/runs/v2.0/items.tsv) and the per-volume annotations
  under `data.mapsnap.org/runs/v2.0/iiif/chronoscope/` (downloaded 2026-11-16)
- [Library of Congress IIIF image service](https://tile.loc.gov/image-services/iiif/) for the
  full-resolution crops
- [Allmaps](https://allmaps.org/): map plugins, `@allmaps/transform`, Allmaps Here
- This repo: `docs/RENUMBERING_PLAN.md`, `docs/ATLAS_INVENTORY.md`, `space/README.md`,
  `data/space/records.parquet`, `data/city/uf93-f8nk.csv`
