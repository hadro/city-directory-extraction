# Plan — addresses across renumberings, and the hand-off to Sanborn maps and Allmaps

**For:** an orchestrating agent session on hadro's computer (where the data is), and hadro.
**Status:** Phase 0 done and G0 decided (2026-11-15, on hadro's computer); Phase 1 under way. See
"Where it stands" just below; the rest of the plan is as written at the end of the cloud session
that built the location search (`space/here.py`) and `results/renumbering.py`, except where that
section says it changed.
**Branch:** `claude/tender-planck-rcrih6`. Everything this plan cites is committed there.
**Read first:** `results/renumbering.py` (its docstring holds the findings), `space/README.md`
("Where you're standing"), and "Starting on hadro's computer" at the end of this file.

---

## Where it stands (2026-11-15)

### Phase 0: done

| # | output | what it found |
|---|---|---|
| 0.1 | `results/spacetime_inventory.py`, `.json`; the files in `data/spacetime/x_<name>/` | Six datasets, each one's counts equal to its data package's. **Brooklyn's 1855 Perris atlas is there** (Map Warper layer 860): 12,643 buildings, and in `addresses` 6,068 house numbers with street and point on 159 streets. Court St has 128, up to about no. 247. Manhattan: 1857 Perris (35,854 addresses) and 1854 Perris footprints (62,701 addresses). The joined address set is published as `addresses`, not `building-inspector-nyc-streets` (that name is refused). |
| 0.2 | `docs/STREET_GUIDES.md` | **A guide prints the left and right house number at each cross street**, in walking order. 1869 and 1871 are the same on Court St; 1875 differs at every corner (Joralemon 18/17 → 45/46, Union 265/269 → 343/346, which is the stayers' +78). The 1871 guide says of one street "the new numbers are not ready": the renumbering came after it. `1871BPL` leaf 935, "STREET DIRECTORY CHANGES.", is 31 street **renamings**, no numbers. The 1869/71 guides print dashes south of Carroll St, so old numbers there rest on stayers. OCR: both numbers right on 93% (1869), 95% (1871), 85% (1875) of 81-85 rows. Which side "Left" is: not settled. |
| 0.3 | `results/renumbering_phase0.py`, `results/printed_pairs.json` | "old No." 3,578 lines (3,565 in `1887BPL`); "formerly" + number 346; every other form under 30. |
| 0.4 | the same script, `data/addresses/street_strings.parquet` | 71,920 rows (place, decade, street string). |
| 0.5 | `docs/RENUMBERING_SOURCES.md` | No ordinance text or conversion table found for any event. One primary source: Lain's 1887 preface (the Eastern District streets "were renamed, but not renumbered" yet). Secondary sources date Brooklyn's renumbering 1870 to 1871-72. Not opened by the orchestrator. |
| 0.6 | `docs/ATLAS_INVENTORY.md`; `results/allmaps_coverage.py`, `.json` | Before 1871: Perris 1855. After: Hopkins 1880 vol. 5 plate O (Court, Lorraine, Columbia, Carroll), Robinson 1886. Map Warper is retired, but **its georeferences are in Allmaps**: asked by IIIF image address (`annotations.allmaps.org/?url=https://iiif.nypl.org/iiif/3/<imageId>`), 298 of the first 302 sheets sampled across atlases answered with a georeference annotation. So 6.2's first step (turning control points into annotations) is already done by others. |
| 0.7 | `results/city_data_inventory.json`, `data/city/` | Address points (`uf93-f8nk`, 967,871 rows) and street centerline (`inkn-q76z`, 122,312 rows) downloaded. The Property Address Directory was not found. |

Also on hand, on hadro's NAS (`/Volumes/NYPL stuff/CityDirectories`): New York directories 1849-1923
as PDF and text, **including every year 1866-75** (the gap that hides Manhattan's avenue
renumbering), and Brooklyn 1856-1908 as PDFs.

### G0

- Brooklyn 1855 atlas in the data: **yes**. Evidence D joins version 1 where the atlas reaches.
- Guides give a number at each cross street: **yes**. Evidence B is version 1's backbone.
- The 1871 section a table of renumberings: **no**, renamings. It feeds the street registry.

### Phase 1: so far

- **1.1 `addresses/streets.py`** reads an address into number, street key, district, place.
  42 test lines pass. Over the records: 95.1% of Brooklyn's address lines that hold a digit are
  read and 90.6% of Manhattan's (the rest are mostly advertisement text); 69 of 70 random readings
  right by eye. The plan's 2,000-string Haiku check was not run.
- **1.3 `addresses/events.py`** finds events for every street and pair of years, judged against
  the street's own usual rate: 605 events in `addresses/tables/events.csv`, and every followed
  name in `data/addresses/stayers.parquet`. Brooklyn 1871-75: 147 streets (135 in order, 5
  reversed, 7 mixed). Williamsburg 1887-89: 14 (4 reversed). The Bronx 1907-08: 82. Manhattan
  1865-76: 114, weak. Its tests are the cases measured by hand (Court 1871 found, Court 1907 not,
  Berry 1887 reversed). Renamings are not detected yet.
- **1.2 the registry** is not built: streets are keyed by `streets.read`'s key as it stands.

### Phase 2: started

- **2C `addresses/guides.py`** rebuilds each guide's rows from the OCR words by column and
  height and reads them as entries: 5,244 rows on 407 streets (`1869BPL`), 5,458 on 433
  (`1871BPL`), 5,244 on 392 (`1875BPL`), 5,633 on 417 (`1876BPL`). The guides before the
  renumbering print a number on only about a fifth of their rows (1,139 and 1,230), the ones after
  on nearly all. Each number is marked on or off its side's run (rising, one parity): 11-12% are
  off in 1869/71, 4-5% in 1875/76. Known gaps: an entry whose heading is not read is dropped
  (about a quarter of the "Left. Rt." headers; Court is missed in `1876BPL`); no agent reading yet.
- **`addresses/anchors_guides.py`** pairs corners across the two guides: 467 corners with a
  number in both of 1871 and 1875, on 86 streets. **Against the stayers: of 2,928 stayers lying
  between two paired corners, 85% have their new number between the same two corners (±8)**, 39
  of 75 streets at 90% or more. Under G2's 90%, so the sources of the misses come first (Court
  48%: its "stayers" include people at 166-176 who turn up in the 400s and 500s).
- **Sides cannot be carried across the renumbering.** On Bridge St the stayers at old even
  numbers have new odd ones and the other way round, all along the street, while Court keeps its
  parity. So the mapping is not an offset per side: the old numbers ran house by house and the
  new ones by frontage, and the fit (Phase 3) has to be a rising curve through corners and
  stayers with the new side learnt from the stayers, per street.

### Phase 3: a first fit

- **`addresses/fit.py`** fits **chains**, not offsets: sets of stayer anchors in one order
  (rising or falling), neighbours no more than 100 apart and plausibly spaced, the heaviest
  taken out first, then the next. 816 chains over the 605 events (`addresses/tables/chains.csv`,
  `data/addresses/anchors.parquet`); Brooklyn 1871-75 has 227 on 147 streets.
- **A street often had more than one run of old numbers**, which is what the multiple chains
  are. Court St 1871: a main run (216 → 294), a second (old 290-387 → new 222-296, 13 anchors),
  and the south end (643-651 → 459-467). Myrtle Av: its main run and a second (167-198 →
  623-682). So an old number can be two houses; a new number has one old number per chain.
- **What it answers:** 462 Court St was 644-696 before 1871-75 (few even-side people were
  followed there; 465 was 643-651). 294 Court St was 216. 181 Bridge St was 156-170 (old even).
  677 Myrtle Av was 687-731, or 893-967 on a second run.
- **Anchors are weighted** by the directories that back them (someone at one number in every
  directory of the five years before and one number in every directory of the five after), and
  the **old odd and old even numbers are fitted apart**: each side was numbered house by house
  at its own pace. A new number is looked up only in chains whose anchors are on its own side.
  The 1871/1875 guide corners join as anchors (500 pairings on a chain); they add reach, not
  accuracy.
- **Held back** (fit on four fifths of a street's anchors, test the strong ones of the rest,
  people seen twice or more on both sides, ±2): Brooklyn 1871-75, 3,222 strong anchors, 92%
  reached by a chain and **86% of those where the chain says**; the Bronx 1907-08, 2,592, 83%
  and 93%. Manhattan 1865-76 has no strong anchors (no directory in between). **The ceiling is
  about 90%**: across an ordinary three-year gap (Brooklyn 1880-83, streets with no event) 9.5%
  of strong stayers change number anyway, 7.7% by more than 2.
- **One command**: `addresses/build.py <records.parquet>` runs events, guides, corners and fit
  (a minute). `addresses/tables/guide_pairs.csv` names the guide before and after an event; add
  a row when a volume with a guide comes in.
- Allmaps, finished: of 6,031 Map Warper sheets in 148 atlases (1850-1925, New York City), 740
  were asked and **734 are in Allmaps**, 642 with the same number of control points
  (`results/allmaps_coverage.json`).
- Not yet done: grades on an answer; the 1855 atlas as anchors; the registry; renamings; the
  guide entries the parser drops.

### 2026-11-16: items 1-4 and 6 of the old list, and the finder

Done by four agents (Sonnet), reviewed, built and committed (447fa3a, 1b42ea9, e84a80a, 2dba2f6).
The figures above this section are the earlier ones; these replace them where they differ.

- **Guides (item 1, `guides.py`).** Headings with no street read: 126-141 a volume -> 4-14.
  Rows: 6,653 (`1869BPL`), 6,611 (`1871BPL`), 6,787 (`1875BPL`), 6,981 (`1876BPL`), on 532-545
  streets. Off-run numbers were re-read from the page image for `1871BPL` (206 rows, 77
  changed, 127 as printed) and `1875BPL` (505 rows, 343 changed, 38 unread), cached in
  `data/addresses/work/guide_read/<volume>_<leaf>.json` (**not in git: 71 files, an agent's
  reading; back them up**) and applied before the gate. `guides.py --to-read <volume>` lists
  what is left: nothing for those two, about 1,400 numbers for `1869BPL` and `1876BPL`. Off
  their run now: 7.4% (`1871BPL`, mostly real misprints and starred "nearest" numbers), 1.2%
  (`1875BPL`). Corners paired 1871/1875: **648 on 131 streets** (was 467 on 86); stayers
  between the same corners 86%; Court still 48%, so that is not a parsing problem. The
  readings were not checked against a second source. A misspelled heading is snapped to a
  cross street one letter off it; a few snaps look wrong (newell -> newel, mckibben ->
  mckibbin). Non-guide pages (`1875BPL` 1161, `1871BPL` 976) still give false rows.
- **Fit after the rebuild.** Brooklyn 1871-75: 407 chains on 147 streets, 3,222 strong anchors
  held back, 93% placed, 86% right. No better than before: the corners add reach, not accuracy.
- **Grades (item 2, `fit.graded`).** A: an anchor's own number, or anchors within 10 on both
  sides. B: a wider bracket. C: past the chain's end, **no numbers** (predicting past the end
  is right 96% within 5 numbers of it, 43% at 21-40, 20% beyond). Of 60,827 addresses listed
  after 1875 on the event streets: A 15,092, B 11,879, C 30,221, none 3,635. Why half are C is
  not checked (streets built past their 1871 extent is the guess).
- **1855 atlas (item 3, `atlas.py`).** 3,031 of 6,068 atlas numbers pair with a point of
  today's within 15 m on the same street. Carried across the 1871-75 chains, streets with no
  event between 1855 and 1871: **80% within 2 of today's number, 91% within 10** (Court 88%,
  95%); with an event between, 32%. Union, Duffield, Adelphi and Lawrence disagree with no
  known event between: open. The atlas's Court stops near today's 340, north of Carroll. Not
  joined to the fit (worth it only on streets with no event between, at low weight).
- **Left (item 6).** The walker's left, facing the way the heading says: 453 of 454 corners of
  `1875BPL`/`1876BPL` against today's points, none reversed. In `docs/STREET_GUIDES.md`. The
  test was scratch code, not kept.
- **Registry (item 4, `registry.py`).** 6,059 ids over 6,374 keys. The 1871 table is **65
  renamings on leaves 934-935**, not 31 (`tables/renamings.csv`, read by eye from the images);
  with the guides' "(late X)", 75, of which 22 merge and 53 are old names another street kept.
  The records contradict 21 of the 65 (the directories kept printing the old name). Fulton av
  joins Fulton from 1875; East/West Baltic and Warren, each half numbered from 1 at Court st
  until 1871, are one street from 1875 (the four rows of `tables/street_overrides.csv`). 301
  spelling merges rest on shared people; a few look wrong (walter -> water, clifton av ->
  clinton av, dev -> dey). Using it would add 420 stayers to Brooklyn 1871-75 (Fulton 156,
  Baltic and Warren 195).
- **The finder (Phase 5), local only, not deployed.** hadro answered 2026-11-15: old-number
  hits as groups; 20 numbers is the cutoff for now (`eras.py`, a named constant). Built:
  `space/eras.py`, `find(years=)`, `find_eras`, the groups, the rests-on line, the note with a
  link for a wide bracket, a typed range ("644-696 Court st, before 1871-75", which the link
  needed), CSV columns `searched_as`, `era`, `crosswalk_grade`. `addresses/export_crosswalk.py`
  writes `data/space/crosswalk.csv`; the finder is unchanged without it. Checks:
  `space/check_eras.py` (headless Chrome) passes; its expected brackets are the built
  crosswalk's and move when a rebuild moves an anchor. 181 Bridge st now gives old 158 (grade
  A), not the 156-170 above.

### 2026-11-16, later: the registry in use, `chain.py`, the finder faster

- **The registry's renamings and overrides are used by the events** (f6a6974; not its spelling
  merges). `events.py` is two steps, `events.py people <records>` and `events.py`, with
  `registry.py` between: the build is still one command and gives the same files run twice.
  `street` in the stayers, events, anchors, chains and crosswalk is now the registry's id;
  `street0`/`street1` (stayers) and `old_street` (anchors, chains, crosswalk) are the keys as
  printed. A chain is of one printed old key, so East and West Baltic (each numbered from 1)
  are never pooled.
- **Brooklyn 1871-75 now: 149 streets, 432 chains, 3,450 strong anchors held back, 91% placed,
  85% right** (was 147, 407, 3,222, 93%, 86%). The 228 new strong anchors are on streets that
  had no answer before and are placed 63% of the time: Fulton av's old numbers run to 2,586
  and 244 of its 263 anchors are on no chain (one odd chain, 1173-1363 -> 985-1129, no even
  one); Atlantic av is 55% right of placed. Baltic: E five chains, W two, W falling (one street
  numbered from the west, Court near 255-270). Warren: W's four chains RISE, which does not
  fit "each half numbered from Court" in the override's note: the 1869 guide page was not
  checked.
- **`chain.py` (item 5).** An address in any era as its form in every other, the worst grade
  kept; `tables/eras.csv`, 1,659 eras on 1,053 streets. 400 Pacific (1875 on) was 366 in
  1859-71 and 368-384 before 1859. **Is the last directory's numbering today's?** Only the
  1855 atlas can say, and it covers 159 streets: yes on 40 Brooklyn streets (7% of the last
  directories' addresses; Court 88%, Henry 95%, Hicks 97%), no on 19 (Union, Carlton av,
  Adelphi, Degraw, Bridge, Duffield and others: renumbered after 1912, or an event the
  directories missed), **unchecked on 683 (90% of addresses)**. "The number exists today" was
  tried and does not tell the two apart.
- **The finder's speed** (7843642). A bracket's old numbers are searched together
  (`find_numbers`): 465 Court st two eras 2.33 -> 1.06 s; 43 Atlantic av 5.81 -> 4.01 s, still
  over 2 s (grading in `browse/find_address.py`). A bare street name means the st (Brooklyn
  prints an avenue's type 95-99% of the time), so "155 Franklin" gets no old numbers.

### Picking it up in a new session

Everything is committed on `claude/tender-planck-rcrih6`. **Not pushed**: hadro pushes later.

**To rebuild everything** (two minutes; needs `data/space/records.parquet`, `data/survey_ocr/`,
`data_prep/survey/`, `data/spacetime/x_addresses/`, `data/city/uf93-f8nk.csv`):

    uv run --with duckdb==2.0.0 python addresses/build.py data/space/records.parquet

**To check the finder** (a port of your own, never 8001; stop it by PID):

    PORT=7873 uv run --with-requirements space/requirements.txt python space/app.py
    uv run --with playwright python space/check_eras.py http://127.0.0.1:7873

**On disk, not in git** (gitignored `data/`):
- `data/addresses/`: `people.parquet`, `stayers.parquet`, `anchors.parquet`,
  `atlas_1855.parquet`, `guides/<vol>.jsonl`, `corners_1871BPL_1875BPL.jsonl`,
  `street_strings.parquet` (all rebuilt by build.py or `results/renumbering_phase0.py`);
  `work/guide_read/` (the readings: NOT rebuilt), `work/guide_crops/`, `work/guide_format/`.
- `data/space/crosswalk.csv` (rebuilt by build.py).
- `data/spacetime/`: the six Space/Time zips, unpacked in `x_<name>/`, and `allmaps_cache.json`.
  Re-fetch: `http://s3.amazonaws.com/spacetime-nypl-org/datasets/<name>/<name>.zip` for
  `building-inspector`, `addresses`, `perris-atlas-footprints`, `nyc-streets`, `mapwarper`,
  `nyc-wards`; unzip each into its own `x_<name>/`.
- `data/city/`: `uf93-f8nk.csv` (address points), `inkn-q76z.csv` (centerline).
- hadro's NAS, `/Volumes/NYPL stuff/CityDirectories` (when mounted).

**Next, in order**
1. Done 2026-11-16: the finder follows the renamed streets. An old group is searched and
   titled under the street its numbers were printed on ("As 1173 Fulton av" for 985 Fulton st,
   "As 96 W Baltic st" for 146 Baltic st); a typed "Elliott pl" reaches "s elliott pl" through
   the crosswalk's `keys` column; E./W. Baltic lines after 1875 (about 35 a directory, the
   same numbers as plain Baltic) count as the street. Each case in `space/check_eras.py` was
   checked on a person found in both groups. Not looked at: E/W Warren after 1875; a new
   Baltic number that reaches both an East and a West group (none found; asserts only).
2. hadro tries the finder locally on a renumbered street (G5), then it goes to the test Space
   (which needs the new `crosswalk.csv`, `eras.py`, `search.py`, `app.py` and `fit.py`).
3. `1869BPL` and `1876BPL` off-run numbers re-read (`guides.py --to-read`); the non-guide pages
   filtered out; the doubtful snaps and spelling merges looked at.
4. Why half the post-1875 addresses are grade C; Union, Duffield, Adelphi, Lawrence against
   the atlas.
5. Fulton av's old numbers (thin, to 2,586: the greedy fit drops a chain that takes good
   anchors with it); West Warren's rising chains against the 1869 guide; today's numbering
   outside the atlas's 159 streets (needs another source: a later atlas, or the city's
   address points with a year).
6. The finder for the other events (Williamsburg 1887-89, the Bronx 1907-08), once Brooklyn
   1871-75 is tried.
7. Manhattan 1865-76 needs the 1866-75 volumes (hadro's NAS has PDFs and 2016 text; running
   them through the pipeline is outside this plan).

**Traps met**
- The plan's Phase 3 below (segments with an offset per side) is superseded by chains: sides do
  not carry across (Bridge st), and a street can have several runs of old numbers (Court st).
- `results/renumbering.py` folds "st" and "av" together; `addresses/streets.py` does not
  (Franklin and Franklin av are two streets). Use the latter.
- The Bronx's streets sit under place "Manhattan" (Trow's lists them there).
- urllib's default agent gets a 403 from annotations.allmaps.org; the service is slow (0.5-4 s a
  request, timeouts), so `allmaps_coverage.py` caches.
- IA's IIIF image server times out on some leaves (`1875BPL` 1146 and 1153 never came).
- oldmapsonline.org refuses automated readers (403).
- The two web-research notes (`RENUMBERING_SOURCES.md`, `ATLAS_INVENTORY.md`) were written by
  agents and their sources were not opened by the orchestrator.

**A first message for the next session**

> Read "Where it stands" in `docs/RENUMBERING_PLAN.md` (down to "What changed from the plan as
> written"). Check `git status` and that `data/addresses/anchors.parquet` exists (if not, run
> `addresses/build.py`). Then carry on with "Next, in order" from item 1. Ask me about the finder
> design before building any of it. Keep everything re-runnable from the records file.

### What changed from the plan as written

1. **Everything is re-runnable** (hadro, 2026-11-15): volumes will be added to the records over
   the coming months. Every step is a script that takes the records file; nothing is edited by
   hand (a human decision goes in a small overrides file the script reads); anything an agent
   reads is cached per volume and leaf, so a re-run reads only new leaves; one `build.py` redoes
   the lot. A new directory year inside 1872-74 would date Brooklyn's renumbering by itself.
2. **Fewer agents.** The three research notes and the guide reading went to agents; the queries,
   `streets.py` and `events.py` were written by the orchestrator, which was quicker than a
   packet and a review. Web research is over; later phases fetch only from named hosts (the
   Internet Archive, NYC Open Data, Allmaps, NYPL's image server).
3. **6.2 starts from Allmaps**, not from Map Warper's control points.
4. It is for **every street**, not Court St: Court is the worked example the numbers were first
   measured on.

### Next

1. 2C: parse the four guides (`1869BPL`, `1871BPL`, `1875BPL`, `1876BPL`) into rows from the OCR
   words by position, with the gate; failed streets to an agent with the image, cached.
2. 2A stayers as anchors (from `stayers.parquet`); 2D the 1855 atlas numbers against today's
   address points; the Phase 2 report and G2.
3. 1.2 the registry, starting from the 1871 renamings table and the guides' own street list.
4. Phase 3, the fit, on Brooklyn 1871-75.

---

## What this builds

One table, and three things that use it.

**The table** says, for a house number on a street in a given year, what that address was called in
every other era of that street, and what it is today: today's address, the city's lot and building
ids (BBL, BIN) and a point. Every row names the evidence it rests on and how sure it is.

**What uses it:**
1. **The finder.** A search for a modern address (typed, or from the phone's location) also
   searches the number that building had before each renumbering. Standing at 462 Court St would
   bring up its 1860s residents, who are listed under a number in the 640s or 650s.
2. **A geocoded directory.** Every directory line gets a modern lot and a point, with a confidence.
   This is the dataset the Sanborn and Allmaps work needs.
3. **The map work.** Georeferenced atlas sheets print house numbers on buildings. The table tells
   a map reader what number to expect where, and the sheets fill the stretches the directories
   cannot.

**Scope.** Brooklyn and Manhattan, 1786-1922, the years of the records. The Bronx comes along
where Trow's lists it (from 1898). Version 1 is one renumbering, Brooklyn's of 1871-75, carried all
the way into the finder. Everything after that is the same machinery run on more events.

---

## What is known already (measured, 2026-11-14 and 15)

All from `data/space/records.parquet` (15,497,151 lines, 152 volumes; the Space's copy, held-out
rows already dropped), unless it says otherwise.

**Renumberings can be seen in the directories.** A renumbering moves everyone who stayed put to a
new number at once. `results/renumbering.py` takes the names on a street in both of two consecutive
directories (once on it in each) and counts who kept their number.
- Court St, Brooklyn: between the 1871 and 1875 directories 3 of 118 kept their number. Every
  other pair of years, 70-98% did. (`results/renumbering_court_brooklyn.txt`)
- The same test over every street (`--scan`): Brooklyn 1871-75, 103 streets; Williamsburg
  1887-89 (Berry, Driggs, Havemeyer and Roebling reversed; Bedford, Wythe, Keap, Hewes, Clymer in
  order); the Bronx 1907-08 (Westchester Av, Jennings, Wendover, Simpson, Longwood, Home and
  others); Manhattan's avenues somewhere in 1865-76. (`results/renumbering_brooklyn.txt`,
  `results/renumbering_manhattan.txt`)

**The mapping is clean where the evidence is good, and it is not one shift.** Court St people at
one number in two or more directories before 1873 and one number in two or more after (38 of them):

| side | old → new | offset |
|---|---|---|
| even, north end | 16 → 44, 62 → 84, 152 → 168 | +28, +22, +16 |
| even, middle | 164 → 238, 170 → 244, 194 → 272, 216 → 294, 224 → 302, 236 → 314, 242 → 320, 290 → 382 | +74 to +92 |
| even, south end | 742 → 550, 744 → 552 | −192 |
| odd, north end | 65 → 93 | +28 |
| odd, middle | 69 → 139, 73 → 143, 75 → 145, 77 → 147, 215 → 287, 263 → 335 | +70 to +72 |
| odd, south end | 643 → 459, 645 → 465, 651 → 467 | −180 to −184 |

So the model is a set of in-order pieces per side of a street, each with its own offset, with
seams between them. Old numbers 300-640 on Court St have almost nobody to follow. Today's 462 was
an even number near old 646-654 (−184 to −192); the directories followed only odd-side people
there. Movers, namesakes and misread numbers show up as pairs that break the order.

**The directories print some of the answers.**
- `1887BPL` marks 3,566 addresses "old No.": Bedford 1,120, Marcy 615, Kent 594, Hewes 278, Keap
  238, Rodney 221, Hooper 213, Maspeth 38, Wythe 19. The same people in `1889BPL` give the pairs:
  Keap 63 → 65, 81 → 85, 89 → 93, 93 → 97, 99 → 103, 132 → 140, 134 → 142, 144 → 152, 146 → 154.
- Scattered lines give both numbers at once: "215 FULTON c Concord (old No. 205)" (1875BPL),
  "404 E. 75th, Old No. 378" (Trow 1876), "h 258 Fourth, new number, 86 W. 4th between Wooster &
  Thompson" (New York 1865, 19 such lines), "29 4th E.D. now 56 Bedford av" (1887BPL, a renaming).

**Street guides exist for nearly every year and are not in the records.** The survey
(`data_prep/survey/*.json`, `sections.runs`, kind `street_guide`, from `data_prep/section_titles.py`)
found 115 street-guide runs in 90 volumes, 3,729 leaves; 88 runs have 10 or more leaves. They
cover Brooklyn 1856-1912 almost yearly and Trow's 1857-1922/23. The ones beside each renumbering:

| event | before | after |
|---|---|---|
| Brooklyn 1871-75 | `1869BPL` 855-896 (40 leaves); `1871BPL` 935-977 (42) | `1875BPL` 1146-1187 (42); `1876BPL` 1180-1219 (40) |
| Williamsburg 1887-89 | `1886BPL` 1281-1316 (36); `1887BPL` 1363-1400 (38) | `1889BPL` 1433-1473 (41) |
| Bronx 1907-08 | `trowsgeneraldir1907p3trow` 1113-1253 (70) | `trowsgeneraldir1908p4trow` 913-1051 (70) |
| Manhattan 1865-76 | `bub_gb_hY4tAAAAYAAJ` (1865) 1150-1173 (23) | `trowsnewyorkcity1876trow` 1684-1696 (13) |

Two things about them are **not yet read** and are Phase 0's first job:
- What a guide prints. Expected, from how such guides usually read: each street with where it
  runs, then the house number at each cross street. If so, a guide before and a guide after give the
  old and new number at every intersection, for the whole street and both sides.
- `1871BPL`'s run is titled **"STREET DIRECTORY CHANGES."** (the survey's quote of its title
  page). It may be an ordinary guide with a running head, or the publisher's own account of the
  renumbering. Nobody has looked.

**Manhattan's 1865-76 gap can be closed.** The records have New York for 1859, 1863, 1865 and then
1876. `data_prep/master_directories.csv` lists NYPL's volume for every year 1866-67 to 1875-76 (ten
rows, `source=nypl`), none of them extracted. Running them is pipeline work outside this plan, and
it is the only way to date Manhattan's avenue renumbering to a year.

**PLUTO's year built is often filled in**, so it cannot say which lines were about today's
building (`here.ESTIMATED`, `space/README.md`). The maps are what can.

---

## The NYC Space/Time Directory: what this repo's notes say, and what it published

hadro asked for this repo to be checked for notes on the project's data. There are four mentions,
and they cover one dataset only.

| where | what it says |
|---|---|
| `results/spacetime_nyu_agreement.py` (docstring) | The `city-directories` dataset: `city-directories.zip` from `http://s3.amazonaws.com/spacetime-nypl-org/datasets/city-directories/`, 984,791,909 bytes, sha256 `5f3b781b…db2c`, holding `city-directories.objects.ndjson`. A grep of it for Doggett 1850/51 sits (gitignored) at `data/spacetime/doggett1850_51.objects.ndjson`. It is CC0, the 2017 CRF extraction. |
| `data_prep/master_directories.README.md` ("Seeded from") | The catalog was seeded from Space/Time's `DIRECTORIES.md`: 81 volumes, 1786-1921/22. |
| `docs/pitch.md` (links) | The archived site, `wayback.archive-it.org/23478/20241118143457/https://spacetime.nypl.org/`, and Mapping Historical New York, which acknowledges Space/Time data and publishes none. |
| `docs/PIPELINE.md` #40 (open items) | "Pre-1898 lines would be better served by period maps than by today's (the NYPL Map Warper atlases) or by OldNYC's geocoded photos; not looked at." |

Nothing in the repo records the project's map-derived datasets. The project's public pages list
them (read through a web search on 2026-11-15, not from the files themselves):

| dataset | what it is said to hold | why it matters here |
|---|---|---|
| `building-inspector` | Building footprints, house numbers and building names traced from insurance atlases by Building Inspector's volunteers. CC0. | House numbers with a place on the ground, from before the renumberings. |
| `building-inspector-nyc-streets` | A derived set: Building Inspector's house numbers joined to historical street lines, giving whole addresses with a year (its tutorial shows "119 East 59th Street", 1857-58). | A ready-made historical address list with geometry: the "old" side of a renumbering without the directories. |
| `nyc-streets` (later the `nyc-historical-streets` repo) | Centerlines of streets traced from atlases, each with its name, year and map layer. About 700 streets in 2017. | Period street names with geometry: renamings, and streets that are gone. |
| `mapwarper` | The outlines (and the control points behind them) of about 8,000 maps georectified in NYPL's Map Warper. | A head start on Allmaps: sheets that are already georeferenced. |
| `perris-atlas-footprints` | Footprints from Perris's 1854 Manhattan atlas, traced by NYPL staff. | An earlier building layer for Manhattan. |
| `city-directories` | The 2017 extraction (above). | Already used. |
| `oldnyc`, `nyc-churches`, `nyc-wards` | Geocoded photos, churches, ward boundaries. | Wards help place early addresses; the others are for later. |

Each dataset is a data package with two NDJSON files, objects and relations. The 2017 counts
quoted were 180,000 addresses and buildings.

**Not known, and Phase 0 settles it:**
- Which atlases each layer covers. Building Inspector finished Manhattan's 1857 Perris atlas and
  had Brooklyn's 1855 Perris atlas as its next job. If Brooklyn 1855 is in the data, it is the
  pre-1871 numbering with coordinates, which is exactly the missing side.
- Whether the files are still downloadable. The `city-directories` zip answered on 2026-11-15.
  A check of the other datasets by guessed file names was refused by the cloud session's
  permission rules, so nothing else was fetched. hadro worked on the project and may have copies,
  or know the right addresses.
- The fields of each record.

Outside Space/Time, three more things matter for the map phase: Library of Congress Sanborn
volumes are served as IIIF images; `danvk/mapsnap` georeferences a Sanborn volume automatically
against OpenStreetMap streets and writes Allmaps annotations (its own example is a Brooklyn
volume); and NYC Open Data lists a "Building Footprints (Historical)" dataset, not yet looked at,
which may record demolished buildings.

---

## The idea: five kinds of evidence, one table

No single source covers a street. Each kind of evidence gives pairs of (old number, new number) on
a street, called **anchors** here. The work is to collect anchors of every kind, check them against
each other, and fit one mapping through them.

| | evidence | gives | where it is strong | where it is weak |
|---|---|---|---|---|
| A | **Printed statements**: "old No." lines, "new number" lines, the 1871 "changes" section if it is one | A pair on one line, or a marked old number to pair with the same person later | Exact, and the publisher's own word | Only some streets and years |
| B | **Street guides**, before and after | The number at every cross street, both sides, for the whole street | Covers stretches with no residents; ties numbers to intersections, so to the ground | Needs extracting; small type; corners only |
| C | **Stayers**: people, firms and institutions at one number before and one after | Many pairs wherever people lived | Dense, already working | Movers, namesakes, misread numbers; nothing where nobody stayed |
| D | **Atlas house numbers** with geometry (Building Inspector; later, Sanborn sheets) | A number at a place, to pair with whatever number is at that place in another era | Independent of people; settles which side and which lot | Coverage unknown until Phase 0; later sheets need reading |
| E | **Today's address points** (the city's PAD, through GeoSearch or in bulk) | The modern number at a place | Complete | Only today |

The quality measure that matters most is **agreement between kinds**: where a stayer pair and a
guide anchor or a printed pair cover the same stretch, do they give the same offset? That is
measured in Phase 2 and gates Phase 3.

---

## Rules

1. **Evidence is never invented.** Every row of the final table points to the anchors under it.
   A number with no anchor on it is marked interpolated and carries a range, or is marked unknown.
2. **Order is tested, not assumed.** Four Williamsburg streets were renumbered from the other
   end. Early numbering did not always keep odd and even to opposite sides.
3. **A cheap agent's output is never merged unchecked.** Each reading job has a structured
   output, an arithmetic gate that needs no model, and a sample audited one tier up. This is the
   repo's own finding (`docs/VISUAL_SAMPLING_HANDOFF.md`, session 4): the cheap tier read column
   counts reliably and page numbers badly, and an arithmetic gate caught the bad ones.
4. **A script before an agent, a cheap agent before a dear one.** An agent never does what a
   query can. The orchestrator reads summaries and failures, not dumps.
5. **Nothing is published without hadro**: no dataset, no Space, no Allmaps annotation.
6. **Training and evaluation are not touched.** This work reads `records.parquet`, which has no
   held-out rows, and writes no training data. If a table from here is ever used to build training
   or gold data, the leakage rule (`README.md`, `docs/NAME_HARVEST_PLAN.md`) applies again.
7. **Measured numbers go in the doc with their date**, as everywhere else in this repo.

---

## Who does what: the tiers

The orchestrator is the main session. It delegates through the Agent tool, naming a model for each
agent. Each agent starts cold, so every packet is self-contained: the task, the input files by
path, the output file and its schema, the gate it will be checked against, and what to do when
unsure (say so in the output, never guess).

| tier | used for | never used for |
|---|---|---|
| **Script** (no model) | Queries, joins, parsing regular text, fitting, building tables, every gate. Most of this plan. | |
| **Haiku** | Reading one page or a few lines into a fixed schema; labelling short lists (are these two spellings one street?); looking at a line image to confirm a number. One small unit per call, many in parallel. | Anything needing judgment across units, or writing code that others build on |
| **Sonnet** | Writing a module from a written spec with tests; re-reading what a Haiku agent's gate rejected; reading atlas sheets; web research with citations; auditing a sample of Haiku output. | The data model, the fit's design, the finder's search semantics |
| **Orchestrator** (the session's own model) | The data model; the fit's design; reviewing every diff an agent writes; deciding at the gates; anything where a wrong call spreads. Reads agent summaries, runs the gates, audits samples of Sonnet output. | Reading pages, bulk transcription, boilerplate |

**How a reading fan-out runs** (the pattern of `data_prep/trow_fanout_prep.py` and
`data_prep/trow_fanout.workflow.js`):
1. A script cuts the work into units and writes one packet per unit under
   `data/addresses/work/<job>/<unit>.packet.json`.
2. Haiku agents run in the background, a few units each, eight or so at a time. Each writes
   `<unit>.out.json` in the schema. They get Read and the packet's files, nothing else.
3. A script runs the gate over every output and sorts units into pass, fail and unsure.
4. Fails and unsures go to a Sonnet agent with the page image.
5. The orchestrator audits a random 5% of passes (20 at least) and reads every unit Sonnet also
   failed. An audit error rate over 2% sends the whole job back with a better packet.

**How a code job runs:** the orchestrator writes the spec and the test cases (real lines from the
records, with the expected answer). A Sonnet agent implements in its own worktree, runs the tests,
and reports. The orchestrator reads the diff and runs the tests itself before merging.

---

## Where things go

Suggested, and hadro's to rename:

```
addresses/                  the code
  README.md                 what each file is, how to rebuild, measured numbers
  streets.py                reading an address; the street registry
  events.py                 renumbering and renaming events (grown from results/renumbering.py)
  anchors_stayers.py        evidence C
  anchors_printed.py        evidence A
  anchors_guides.py         evidence B: parse street guides, pair before and after
  anchors_atlas.py          evidence D
  fit.py                    the mapping through the anchors
  chain.py                  eras of a street, composed to today
  build.py                  runs it all, in order
  packets/                  agent packets, schemas and gates, one folder per reading job
  tables/                   small reviewed tables, committed as CSV:
    street_names.csv          the registry
    events.csv                the events, with their status
    segments.csv              the fitted pieces
data/addresses/             everything large or regenerable (gitignored, like the rest of data/)
  anchors.parquet           every anchor, with its source
  crosswalk.parquet         the table itself
  guides/<volume>.jsonl     street guides as rows
  work/                     agent packets and outputs
space/eras.py               the finder's reader of the crosswalk
```

`.gitignore` ignores `*.parquet`, `*.jsonl` and `data/*`, so anything committed must be CSV or
JSON outside `data/`.

### The tables

**`street_names.csv`**: one row per street as a thing on the ground in a span of years.
`street_id`, `place` (Brooklyn, Manhattan, Bronx), `district` (Brooklyn's Eastern or Western, where
a name is used twice), `name` (as the directories print it most), `type`, `direction`, `variants`
(every spelling and abbreviation: b'way, g'wich, wash'n, lex., 4th and fourth), `from_year`,
`to_year`, `became` (the `street_id` it was renamed to), `modern_name` (as the city's address list
has it), `source`.

**`events.csv`**: `event_id`, `street_id`, `last_old_year` (the last directory with old numbers),
`first_new_year`, `kind` (renumbered, reversed, renamed, renamed and renumbered, extended),
`stayers`, `kept`, `in_order`, `status` (detected, printed, confirmed by a guide, confirmed by a
map), `note`.

**`anchors.parquet`**: `event_id`, `street_id`, `old_number`, `new_number`, `kind` (A to E),
`weight`, `source` (the two `record_id`s; or volume, leaf and line of a guide; or an atlas object
id), `on_chain` (false for a pair the fit set aside, with why).

**`segments.csv`**: `event_id`, `street_id`, `old_side` (odd, even, both), `old_from`, `old_to`,
`new_from`, `new_to`, `direction` (+1 or −1), `offset`, `anchors`, `kinds`, `worst_residual`,
`grade`.

**`crosswalk.parquet`**: `street_id`, `number`, `from_year`, `to_year`, then for the same building
in each other era `era_street_id`, `era_number_low`, `era_number_high`, and for today
`modern_address`, `bbl`, `bin`, `lat`, `lon`; `grade`; `anchor_ids`. One row per number per era.

**Grades**, used everywhere:
- **A** observed: an anchor on this very number, or anchors within 10 numbers on both sides in
  one segment.
- **B** inferred: inside a segment with a constant offset, anchors further off.
- **C** range: in a seam between two segments, or past the last anchor. Carries a low and a high.
- **U** unknown: no segment reaches it.

The keys chosen so the maps plug in later: BBL, BIN and coordinates on the modern side; year ranges
on every row; and each directory line's own IIIF `crop` address (already in the records) as the
link to its image.

---

## Phase 0. Find out what there is (1 day, mostly parallel)

Nothing here changes code. Each task ends in a short note under `docs/` or a JSON under
`results/`, and the phase ends at gate G0.

| # | task | who | output | gate |
|---|---|---|---|---|
| 0.1 | **Space/Time datasets.** Get `building-inspector`, `building-inspector-nyc-streets`, `nyc-streets`, `mapwarper`, `perris-atlas-footprints` (hadro's copies, or the published files with his go-ahead). For each: record count, fields, years, a count by borough from the geometry, 5 sample records. | Script, run by one Haiku agent with DuckDB | `results/spacetime_inventory.json`, sha256 of each file | Counts add up to the data package's own |
| 0.2 | **What the street guides print.** Read 3 leaves each of `1869BPL` 855-896, `1871BPL` 935-977 and `1875BPL` 1146-1187, from the page images and from the OCR text on disk. Say what a guide entry is, transcribe two streets from each (Court St one of them), and say what "STREET DIRECTORY CHANGES." is. | One Sonnet agent with the images (it is a judgment about format, 9 pages) | `docs/STREET_GUIDES.md`: the format, the samples, how good the OCR is | hadro or the orchestrator looks at the same leaves |
| 0.3 | **The printed pairs.** Count and sample every line with "old No.", "new No.", "new number", "now" and "formerly" before a number, by volume and street. | Script | `results/printed_pairs.json` | |
| 0.4 | **Street spellings.** Every distinct street string in an address, by place and decade, with its line count. | Script | `data/addresses/street_strings.parquet` | |
| 0.5 | **The record.** What is published on these renumberings: Brooklyn's 1870-71 ordinance and its dates, Williamsburg 1887-89, the Bronx 1907-08, Manhattan's avenues in the 1860s; Hoffmann's 1937 article on changed house numbers; Rose-Redwood's 2012 paper. With citations. | One Sonnet agent with web search | `docs/RENUMBERING_SOURCES.md` | Each claim has a source the orchestrator can open |
| 0.6 | **Maps to hand.** Which atlases cover Brooklyn and Manhattan between 1850 and 1920 (Perris, Dripps, Bromley, Robinson, Hopkins, Sanborn), where each is served as IIIF (Library of Congress, NYPL), and which are already georeferenced (Map Warper, Allmaps). | One Sonnet agent with web search | `docs/ATLAS_INVENTORY.md`, a table | |
| 0.7 | **City data in bulk.** Find the NYC Open Data ids for address points, the Property Address Directory, the street centerline, MapPLUTO and "Building Footprints (Historical)", and download the first three. | One Haiku agent | `results/city_data_inventory.json` | |

**G0, decided by the orchestrator with hadro (about half an hour):**
- Is Brooklyn's 1855 atlas in the Space/Time data? If yes, evidence D joins version 1. If no, D
  waits for Phase 6.
- Do the guides give a number at each cross street? If yes, evidence B is version 1's backbone.
  If they give only where a street runs, B is dropped and C carries it.
- Is the 1871 section a table of changes? If yes, it comes first of everything.

---

## Phase 1. Streets and events (1.5 days)

**1.1 Reading an address (`addresses/streets.py`).** One function from an address string to
(number, street words, type, direction, place marker, district), built on what exists:
`find_address.parse`, `street_type` and `ordinal`; `search.MARKERS`; `here.directory_form` for the
city's spellings. It must handle "h 462 Court", "29 4th E.D.", "404 E. 75th", "112 1/2 Park av",
"Hamilton n Gates av" (no number: skipped), "b'way" and "B'way". Known wrong today and to be
fixed here: "Avenue B" is read as a street called "avenue" (`space/README.md`, "Not handled").
- Who: the orchestrator writes 60 test lines from the records with expected answers. A Sonnet
  agent implements. The orchestrator reviews.
- Done when: all tests pass, and on a random 2,000 address strings a Haiku fan-out (20 per call)
  agrees with the function on 98%, the disagreements read by the orchestrator.

**1.2 The registry (`street_names.csv`).**
1. Script: group the strings of 0.4 by cleaned name, type and place.
2. Script: propose merges, two groups being one street when they are an edit apart or one
   abbreviates the other, and they share residents at the same numbers in the same year.
3. Haiku fan-out: each proposed merge, with 5 sample lines from each side, answered same street,
   different streets or unsure. Gate: a merge needs shared residents or a known abbreviation.
   Unsures go to Sonnet.
4. Script: add the modern name from the city's address list (which keeps old names beside new:
   Lenox Av with Malcolm X Blvd, as `here.py` found).
- Done when: 99% of address lines in Brooklyn and Manhattan fall on a registry street, and the
  orchestrator has read the 100 commonest streets' rows.

**1.3 Events (`addresses/events.py`).** `results/renumbering.py` grown up:
- Stayers by registry street, not by raw string.
- A street's change rate in each pair of years is judged against its own usual rate, not a fixed
  half. Court St's usual is 2-30%; 97% is an event.
- Kinds: renumbered (order kept); reversed (order turned: Berry, Driggs); renamed (a street's
  stayers reappear together on another street the same year: 4th St E.D. to Bedford Av); extended
  (numbers shift from one point on).
- A pair of directories more than three years apart is marked weak, since people moving add up.
- Who: the orchestrator specifies. Sonnet implements. Tests are the cases already measured: Court
  1871-75 found; Court 1907-08 not found; Berry 1887-89 reversed; Atlantic and Fulton 1865-67
  (flagged two years running) looked at and explained.
- Done when: every event in 0.5's published record with 20 or more stayers is found, and no
  event is found in three control pairs (Brooklyn 1902-03, 1907-08; New York 1908-09 outside the
  Bronx).

**1.4 hadro reads `events.csv`** for the 30 biggest events: a quarter of an hour.

---

## Phase 2. Anchors (2 to 3 days, the four kinds in parallel)

**2A. Stayers (`anchors_stayers.py`).** Script only.
- A stayer is a name on the street at one number in the directories before the event and one
  number after, and nowhere else on the street. Weight grows with the number of directories on
  each side (Court: 38 with two or more each side) and falls for a name found more than once in the
  city that year.
- Firms and institutions count, and are worth more: "Long Island Historical Society", "Chumar &
  Son".
- A matching occupation adds weight.

**2B. Printed pairs (`anchors_printed.py`).**
- Script: the regular forms ("old No. 145 Keap" in 1887 joined to the same name in 1889; "(old
  No. 205)"; "new number, 86 W. 4th").
- Haiku fan-out: the irregular remainder of 0.3, a line in, a pair out or "no pair".
- If G0 found the 1871 section to be a table of changes: it is parsed as a street guide (2C) and
  its rows are kind A.

**2C. Street guides (`anchors_guides.py`).** The biggest reading job; only if G0 said yes.
1. Script: take the OCR text of the guide's leaves (the text the pipeline already holds for every
   leaf), and parse it with the format found in 0.2 into rows: street, where it runs, then cross
   street with the number on each side.
2. Script, the gate, per street: numbers rise along the street; odd and even keep to their
   columns; cross streets are registry streets; streets follow the alphabet across leaves.
3. Leaves or streets that fail go to a Haiku agent with the page image and the same schema. What
   fails again goes to Sonnet. What Sonnet cannot read is listed for hadro, not guessed.
4. Script: pair a street's guide before with its guide after on the cross street's name (through
   the registry, since cross streets get renamed too). Each pair of numbers at one corner is an
   anchor, kind B.
- Size for version 1: four volumes, about 164 leaves. If the script reads four leaves in five, the
  agents see about 35.
- Done when: for the 50 Brooklyn streets with the most stayers, the guide rows pass the gate and
  the orchestrator has checked 3 streets against the images.

**2D. Atlas numbers (`anchors_atlas.py`).** Only if G0 found the coverage.
- Script: each historical address point (Space/Time) is matched to the modern address points
  within 15 m on the same registry street. The pair (atlas number, today's number) is an anchor
  that skips every event in between, kind D.
- Sonnet writes the join. The test is a block the orchestrator checks by hand.

**The Phase 2 report** (script, `results/anchors_summary.json`), per event and street: anchors by
kind; the share of the street's numbers within 10 of an anchor; and, wherever two kinds overlap,
the share of anchors whose offsets agree within 2.

**G2, the orchestrator:** agreement between kinds under 90% on a street means something is wrong
with a source there, and it is found before any fitting.

---

## Phase 3. The mapping (2 to 3 days; the orchestrator's own work)

**The fit (`addresses/fit.py`)**, per event, street and side:
1. **Direction.** The rank correlation of old and new numbers over the anchors. Clearly positive:
   in order. Clearly negative: reversed. Neither: no fit, and the street is flagged.
2. **The chain.** The heaviest set of anchors that is in order from end to end (a weighted longest
   increasing run). Anchors off it are kept in the table, marked off-chain: movers, namesakes,
   misreadings.
3. **Segments.** Along the chain, the offset (new minus old; for a reversed street, new plus old)
   is constant in stretches. A new segment starts where the offset changes by more than 4 and the
   change is held by two anchors, or by one of kind A or B.
4. **Seams.** Between two segments, a number maps to a range, from the one offset to the other.
5. **Sides.** Fitted per side when old numbers keep odd and even apart. Where they do not (early
   numbering), one fit for both, and the new side comes from the anchors' new numbers.
6. **Slope.** Where numbers were respaced and not just shifted, a line through the segment's
   anchors, kept only when it fits them within 2.
7. **Ends.** Past the last anchor a segment runs on 20 numbers at grade C, then unknown.

It is simple on purpose: every answer can be shown to a person as "these anchors on either side
say so".

- Who: the orchestrator writes the spec and a generator of made-up streets (a known mapping, with
  movers and misread digits thrown in). Sonnet implements against it. The orchestrator reviews,
  then runs it on Court St and reads every segment against the table above.

**Checking it:**

| check | how | who | wanted |
|---|---|---|---|
| Held-back anchors | Fit on four fifths of a street's anchors, predict the rest, five times | Script | Grade A: 95% exact. Grade B: 90% exact. Grade C: 80% inside the range |
| One kind against another | Fit on stayers alone, test on guide corners and printed pairs | Script | The same |
| The readings | 100 crosswalk rows across the grades; for each, the two line images behind its nearest anchors: is the number what the record says? | Haiku with the images, Sonnet on disagreements | Under 3% misread |
| By eye | 10 addresses hadro knows or can look up | hadro | |

The wanted figures are a first guess. They are fixed, and written here, once Phase 2's report
shows what the data can bear.

**G3, the orchestrator with hadro:** is Brooklyn 1871-75 good enough to put in front of people?

---

## Phase 4. From any year to today (1.5 days)

**4.1 Eras (`addresses/chain.py`).** A street's years split at its events into eras. Mappings
compose across eras, ranges widening as they go. A renaming carries the numbers to the new street
(4th St E.D. into Bedford Av). Fulton St has at least two events (1824-25 and 1871-75).

**4.2 Is the last directory's numbering today's?** Not to be assumed: Sixth Avenue, for one, is
said to have been renumbered in the 1920s. The check is cheap if the guides are in:
- Script: the last guide's number at each corner (Brooklyn 1912; Trow's 1922/23) against today's
  address points nearest that corner on that street (corners from the city's street centerline).
- Where they differ along a street, that is an event after the directories, and the corner pairs
  are its anchors: dense, and free.
- Without the guides: the same check from the last directory's businesses that still stand (thin),
  or left to the maps.

**4.3 Today's side.** Each modern address gets its BBL, BIN and point from the city's bulk files
(0.7), not one request at a time. `here.py` keeps using GeoSearch for the live lookup.

**4.4 What numbers cannot say.** A flag on the row where today's building covers several old
numbers (955-967 Dean St is one building), where the street is gone, or where the lot was merged.

**4.5 The table is built** (`build.py`), with a README of its own and its measured numbers.

---

## Phase 5. The finder (2 days)

**5.1 `space/eras.py`.** Loads the crosswalk at start-up (it is small). `eras(address, place)`
gives, for each era, the years, the street and the number or range, and the grade.

**5.2 `space/search.py`.** `find()` takes a year range, applied in SQL before grading, so each
form is searched only in its own years. A search over eras is one `find()` per era, merged, each
hit marked with the era it was found under. A range (grade C) is searched number by number, at most
5.
- Timing wanted on the real records: a typed search with two eras under 2 s (one era today:
  0.4-1.9 s).

**5.3 `space/app.py`.**
- Lines grouped under what they were found as: "As 462 Court st, 1875-1912" and "As 646-654 Court
  st, before 1871: renumbered between the 1871 and 1875 directories".
- A grade C group says it is a range and may hold the neighbours.
- A line under each group says what the mapping rests on ("4 people followed across the change
  within 10 numbers").
- The CSV gains `searched_as`, `era` and `crosswalk_grade`.
- The located search uses it too, and the note on when the building went up is unchanged.

**5.4 Checks.** The headless-browser cases of `space/README.md` plus: 462 Court St shows both
groups; a street with no event shows one; a reversed street (Berry) maps the right way; timing.

- Who: the orchestrator specifies 5.2, since it changes what a search means. Sonnet implements 5.1
  and 5.3. The orchestrator tests and deploys to the test Space.
- **G5:** hadro tries it on a phone on a renumbered street.

---

## Phase 6. The maps (a pilot of 3 to 5 days, then open-ended)

**6.1 What goes out to the maps.**
- The crosswalk as points with year ranges (GeoJSON).
- The geocoded directory: `records.parquet` with `bbl`, `bin`, `lat`, `lon` and
  `crosswalk_grade` added to every line.

**6.2 Sheets, georeferenced.** In this order, cheapest first:
1. Sheets NYPL's Map Warper already rectified: turn their control points into Allmaps
   georeference annotations on NYPL's IIIF images. A script.
2. Library of Congress Sanborn volumes through `danvk/mapsnap`, which writes Allmaps annotations.
   Tried on one Brooklyn volume first. (2026-11-16: its published v2.0 run already places 9,332 of
   12,362 NYC sheets; see `docs/SANBORN_MAPSNAP_PLAN.md`.)
3. The Allmaps editor by hand, for what neither gives.
- The test of a georeferenced sheet: the crosswalk's grade A points, drawn on it, land on the
  buildings carrying those numbers.

**6.3 Reading numbers off a sheet: the pilot.** One block, both sides, two atlases either side of
1871 (Court St between 3rd and 4th Place: the 1855 atlas if there is one, and one from the 1880s).
1. Script: cut the sheet image along the street's frontage into overlapping tiles.
2. Sonnet agents with the tiles: every house number, with its place in the tile. Reading atlas
   numbers is harder than reading a page, so Sonnet first; Haiku is tried on the same tiles to see
   whether it can take over.
3. Script: tile position to image position to the ground, through the sheet's annotation
   (Allmaps' transform library), then to the lot under it (MapPLUTO).
4. The gate: numbers rise along the frontage, and a side keeps its odd or even.
5. Each (number on the sheet, lot) is an anchor of kind D for that atlas's year.
- The pilot's measures: the share of lots read; agreement with the crosswalk where it is grade A;
  the cost per block.

**6.4 What comes back.** The stretches with nobody to follow (old 300-640 Court St), which even
number 462 was, and, from footprints on sheets of different years, whether the house standing in
1880 is the one standing now, which neither numbers nor PLUTO can say.

**6.5 Publishing** the annotations and the gazetteer is hadro's call.

---

## The agent jobs in one table

| job | phase | tier | units | fan-out | gate (script) | escalates to |
|---|---|---|---|---|---|---|
| Inventory Space/Time files | 0.1 | Haiku ×1 | 5 files | none | counts match the package | orchestrator |
| Guide format | 0.2 | Sonnet ×1 | 9 leaves | none | hadro or orchestrator looks | |
| Published record | 0.5 | Sonnet ×1 | | none | sources open | |
| Atlas inventory | 0.6 | Sonnet ×1 | | none | links open | |
| City data ids | 0.7 | Haiku ×1 | 5 datasets | none | files download | |
| `streets.py` | 1.1 | Sonnet ×1 | | worktree | 60 tests | orchestrator review |
| Address-reading check | 1.1 | Haiku | 2,000 strings, 20 per call | 100 calls, 8 at once | agreement with the function | orchestrator reads disagreements |
| Street merges | 1.2 | Haiku | proposed merges, 10 per call | as many as there are | shared residents | Sonnet |
| `events.py` | 1.3 | Sonnet ×1 | | worktree | the measured cases | orchestrator review |
| Irregular printed pairs | 2B | Haiku | lines, 25 per call | | the pair's person exists both years | Sonnet |
| Guide leaves | 2C | Haiku with images | failed leaves, 1 per call | about 35 for version 1 | rising numbers, sides, alphabet | Sonnet, then hadro |
| Atlas join | 2D | Sonnet ×1 | | worktree | one block by hand | orchestrator review |
| `fit.py` | 3 | Sonnet ×1 | | worktree | made-up streets recovered | orchestrator review and Court St |
| Reading check | 3 | Haiku with images | 100 rows, 5 per call | 20 calls | | Sonnet |
| `eras.py`, page | 5 | Sonnet ×1 | | worktree | browser cases | orchestrator review |
| Sheet numbers | 6.3 | Sonnet with images | tiles of one block | | rising numbers, sides | orchestrator |

The orchestrator's own work is the data model, the three specs (events, fit, search), every
review, the gates and the audits.

---

## Order and time

```
Phase 0  (1 day)     0.1  0.2  0.3  0.4  0.5  0.6  0.7   all at once        -> G0
Phase 1  (1.5 days)  1.1 -> 1.2 -> 1.3                                      -> hadro reads events
Phase 2  (2-3 days)  2A | 2B | 2C | 2D   at once, after 1.3                 -> G2
Phase 3  (2-3 days)  spec -> fit.py -> checks                               -> G3
Phase 4  (1.5 days)  4.1 -> 4.2 -> 4.3 -> 4.5       (4.3 can start in Phase 2)
Phase 5  (2 days)    5.1 | 5.2 -> 5.3 -> 5.4                                -> G5
Phase 6  (3-5 days)  6.1 after 4.5;  6.2 can start after 0.6;  6.3 after 6.2
```

- **Version 1** (Brooklyn 1871-75, into the finder): Phases 0 to 3 for that one event, then Phase
  5. About a week.
- **Both boroughs, to today:** about two weeks.
- **The map pilot:** three to five days more, and can run beside Phases 3 to 5 once 0.6 is in.
- hadro's time: about half an hour at G0, a quarter at 1.4, half an hour at G3, a phone test at G5.

---

## What could go wrong

| risk | what is done about it |
|---|---|
| The guides do not give numbers at cross streets | Known at G0, on day one. Stayers and printed pairs carry version 1, and the maps come sooner |
| Guide OCR is too poor to parse (small type, columns of figures) | The gate sends bad leaves to agents with the image. If most fail, the leaves go through the repo's re-OCR route (`data_prep/reocr_columns.py`), a decision for hadro |
| Space/Time's files are gone, or do not cover Brooklyn | Evidence D waits for Phase 6. Nothing in Phases 1 to 5 depends on it |
| Namesakes and movers pass for stayers | Stability on both sides, the in-order chain, and the check against other kinds |
| A street was renumbered twice between two directories | The fit shows no clean chain. Flagged, and left for the guides or the maps |
| Manhattan's events cannot be dated (no directories 1866-75) | Marked weak. Fixed only by extracting NYPL's ten volumes, outside this plan |
| The same street name in two districts (Brooklyn's Eastern and Western; "4th E.D.") | `district` in the registry, read from the line's own marker |
| Streets that are gone (downtown Brooklyn, the bridge approaches) | The crosswalk ends at the last era with a number, with Space/Time's street line as geometry if there is one |
| A renumbering after 1922 | 4.2 |
| Half numbers, rear houses, "near" addresses | Left out of the table; the finder searches them as it does now |
| Agents cost more than expected | Scripts first. The Phase 2 report says how many units reached an agent, and a job reaching more than a third of its units goes back to the script |

---

## For hadro to decide or do

1. **Space/Time's map datasets:** do you have copies, and which atlases do they cover? Otherwise,
   a go-ahead to fetch the published files.
2. **Version 1's scope:** Brooklyn 1871-75 first, as proposed?
3. **Names:** `addresses/` and the table names above, or others.
4. **The ten NYPL volumes for New York 1866-75:** worth queueing for extraction, to date
   Manhattan's renumbering?
5. **Publishing:** whether the crosswalk and the geocoded directory ride with the records release.

---

## Starting on hadro's computer

The cloud session cannot move, and no folder on hadro's computer is shared with it. The work
moves through the branch.

```bash
git fetch origin claude/tender-planck-rcrih6
git switch claude/tender-planck-rcrih6
```

**What the computer has that the cloud did not:**
- `data/browse.db` and `data/space/records.parquet` with both indexes (the cloud downloaded only
  the records, from the private dataset `hadro/cde-space-data`).
- The OCR text and images of every leaf, so the street guides need no network.
- `data/spacetime/`, at least the Doggett grep, and perhaps the whole `city-directories` zip.
- The Internet Archive, NYPL and every other host. The cloud environment allowed only GeoSearch,
  NYC Open Data, Hugging Face and its download host; `archive.org` was blocked there.

**What changed in the cloud session, all on the branch:**
- `space/here.py`, `space/app.py`, `space/search.py`, `space/README.md`: the location search,
  ranking by building walls, the year-built note and its estimate warning. Deployed to the test
  Space `hadro/cde-finder-timing` (Space commit `cfe785d`), not yet tried on a phone.
- `results/renumbering.py` and its three result files.
- This plan.

**A first message for the new session:**

> Read `docs/RENUMBERING_PLAN.md` and `results/renumbering.py`. Run Phase 0. You are the
> orchestrator: delegate each task to the tier the plan names, in the background, with a
> self-contained packet, and check every output against its gate before using it. Start with 0.2
> (what the street guides print, and what `1871BPL` leaves 935-977 are) and 0.1 (ask me where the
> Space/Time datasets are before fetching anything). Stop at G0 and show me what you found.
