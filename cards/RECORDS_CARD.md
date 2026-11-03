---
license: other
language:
  - en
pretty_name: New York and Brooklyn City Directory Records, 1786–1923
tags:
  - glam
  - city-directory
  - historical-documents
  - genealogy
  - new-york-city
  - brooklyn
  - iiif
size_categories:
  - 10M<n<100M
---

<!-- DRAFT 2026-10-31, for the v1 release. Pending hadro's decisions before upload: the licence
(`license: other` above is a placeholder; the source scans are public domain in the US, so CC0
or CC-BY-4.0 are both open), the repo namespace (<namespace>), whether v1 ships on 13 Nov with
the volumes done by then or waits for all 153, and whether the OCR text layer is published
beside the records. Fill <FILL> marks from the final assembly and the release audit. -->

# New York and Brooklyn City Directory Records, 1786–1923

One record per printed line of the residential listings in <FILL: N> city directories of New
York and Brooklyn, 1786–1923: <FILL: N> records, of which <FILL: N> are marked `usable`. Each
record gives the line as read, eight fields extracted from it, and the line's place on the page
scan, so every value can be checked against the printed page.

The directories were read again for this dataset: page scans from the Internet Archive went
through [LightOnOCR-3](https://huggingface.co/lightonai/LightOnOCR-3-1B), wrapped entries were
joined, and each line went through the
[City Directory Extractor 4B](https://huggingface.co/<namespace>/city-directory-extractor-4b).

## Coverage

| | Volumes |
|---|---|
| Brooklyn | 84 |
| Manhattan (New York) | 65 |
| Queens | 3 |
| Bronx | 1 |
| **Total** | **153** |

The largest series are Trow (46 volumes), Spooner (26), Lain (23), Upington (12) and Longworth
(11). Where the Internet Archive holds more than one scan of an edition, only one is read (25
copies left out). The scans were contributed by the Brooklyn Public Library (69 volumes), the
Allen County Public Library (59), Columbia University Libraries (23), the New York Public Library
(1) and Harvard University (1). The earliest volume is Franks' 1786 directory, read from its 1851
reprint. `volumes.csv` lists every volume with its year, publisher, scan and record counts.

<FILL: if v1 ships with part of the corpus, say which volumes are in it and that the rest follow
as files are added.>

## A record

```json
{
  "record_id": "doggettsnewyorkc1845dogg:38:38",
  "volume": "doggettsnewyorkc1845dogg",
  "leaf": 38,
  "printed_page": 32,
  "printed_page_how": "read",
  "section": "listing",
  "canvas": "https://iiif.archive.org/iiif/doggettsnewyorkc1845dogg$38/canvas",
  "xywh": "177,2078,758,41",
  "crop": "https://iiif.archive.org/iiif/doggettsnewyorkc1845dogg$38/177,2078,758,41/full/0/default.jpg",
  "raw_line": "Bayard John, grocer, 141 W. Twentieth",
  "name": "Bayard John", "is_business": "False", "spouse_name": "", "race_designation": "",
  "occupation_role": "grocer", "employer": "", "address": "141 W. Twentieth", "home_address": "",
  "name_resolved": "Bayard John",
  "address_resolved": "141 W. Twentieth",
  "role": "start", "entry_shaped": true, "non_entry_page": false,
  "line_source": "model", "usable": true
}
```

Open `crop` to see the printed line.

## Fields

**Where the line is**

| Field | Meaning |
|---|---|
| `record_id` | `<volume>:<leaf>:<n>`, n the line's order on its leaf |
| `volume`, `leaf` | Internet Archive identifier and leaf (scan page) number |
| `printed_page`, `printed_page_how` | The page number printed on the leaf: `read` off its margin, `repaired` (a leading digit the OCR dropped, restored from the sequence) or `inferred` from the pages around it |
| `section` | The residential run the line came from (`listing`, `late_names`, …) |
| `canvas`, `xywh`, `crop` | The IIIF canvas, the line's box on it, and a IIIF image of just that line |

**What it says**

| Field | Meaning |
|---|---|
| `raw_line` | The line as read, wrapped run-overs joined, verbatim |
| `name`, `is_business`, `spouse_name`, `race_designation`, `occupation_role`, `employer`, `address`, `home_address` | The model's eight fields, verbatim from the line (see the model card) |
| `name_resolved` | The name with a ditto mark replaced by the surname it repeats; otherwise `name`. Empty where `name_fragment` is set |
| `address_resolved`, `home_address_resolved` | The address with a ditto (`do.`) expanded where the early directories use one |
| `ditto_source`, `ditto_header`, `ditto_flags` | Where a resolved surname came from (another record, or a surname header over the column), and review flags (`cross_leaf`, `letter_conflict`, `orphan`, and `mark_lost`: no ditto mark was read, but the line opens on a given name, so it took the surname above) |
| `name_mark`, `district` | A marker the line opens with (Brooklyn's Eastern District `E`, a `*`), and `Eastern` where it marks an Eastern District resident |

**How far to trust it**

| Field | Meaning |
|---|---|
| `usable` | **The recommended filter.** True when the line is entry-shaped, starts an entry, sits on a listing page, and is not a `duplicate_of` another record |
| `role` | `start`, `runover` (the tail of the entry above), `other` or `thin`, from the line's position |
| `entry_shaped` | The record has a name and an address-like field |
| `non_entry_page` | The leaf was flagged as an advertisement page or a failed reading |
| `line_source` | Whose reading the line is: `model` (LightOn's text on the word layer's box), `tesseract`, `bleed`, or `model-only`, a line no word layer found, whose box is a stand-in at its tile's edge, so `crop` does not show it |
| `duplicate_of` | A `tesseract` line that repeats the model's reading of the same printed line: the `record_id` of that record. Never `usable` |
| `name_fragment` | The name opens on a lowercase word that no name opens on: the start of the line was cut off in the scan or the OCR (`n H` for `—Wm H`), or the line is not a name. `name_resolved` is empty; `name` keeps the reading |

Nothing is dropped except evaluation lines (below). A record that is not `usable` is kept with its
flags, so a different filter can be built.

## How accurate it is

<FILL: the release audit: N `usable` records sampled across the corpus, each checked against its
page image. Report the share whose eight fields match the print, and the share that are not real
entries at all, with 95% intervals, overall and by tier (microfilm; damaged ABBYY; other book
scans).>

Volume by volume, where a directory prints how many names it lists, `usable` records per printed
name:

| Volume | Usable records per printed name |
|---|---|
| Doggett's New York 1845 | 0.982 |
| Lain's Brooklyn 1876 | 0.982 |
| Longworth's New York 1826 | 0.897 |
| Brooklyn (microfilm reel 0039) | 0.861 |
| Brooklyn (microfilm reel 0046) | 0.722 |
| <FILL: the remaining volumes with a printed count> | |

<FILL/CHECK: Trow's 1903 part 1 reads 0.351, probably because its printed count covers more than
that part. Confirm before release, and list it with the explanation or leave it out.>

On hand-labeled pages scored line by line through the same pipeline, 67.0% of records match the
gold exactly in all eight fields (17 sets, 2,062 lines; model card, "End to end").

## Known problems

- **Records that are not people.** The model makes a record of any line it is given: an
  advertisement, a running head, the second line of a wrapped entry. `usable` removes most of
  them. Expect some to remain, more on pages with advertising in the margins.
- **Wrapped entries.** Joining an entry's run-over lines is done by indent and by the OCR's own
  reading. Some entries stay split (a `runover` record), and some neighbouring entries are joined
  into one.
- **OCR misreads** remain in `raw_line` and the fields copied from it, more on microfilm volumes.
  Brooklyn microfilm reel 0046's 0.722 is mostly lines the OCR did not find.
- **Ditto resolution** can carry the wrong surname across a column or page break.
  `ditto_flags` marks the doubtful cases.
- **Invented given names** for some widows the directory lists without one.
- **`model-only` lines** have no real box; their `crop` shows the edge of the page column, not
  the line.

## Not included

Lines on the pages that serve as this project's evaluation gold, and on the pages beside them,
are left out, so the gold stays unseen: <FILL: N> lines (1,798 in the first 78 volumes).
<!-- The export must drop rows with eval_holdout set; assemble_records keeps them, flagged. -->
<!-- The export must also keep ONE copy of each volume. Doggett 1845 (doggettsnewyorkc1845dogg)
     is assembled twice: run 1's IA-text reading (root data/volumes_run1, data/records/) and the
     damaged tier's re-OCR (root data/volumes_books_damaged_v4, data/records_books_damaged/).
     browse/ loads both on purpose (browse/sources.toml); a release must not. Keep the re-OCR,
     which the 0.982 above is computed from (60,199 usable / 61,333 printed names); both copies
     together read 1.966. space/build_parquet.py's SUPERSEDED applies the same rule. -->
<!-- The 1,798 lines (78 volumes) count the reocr and damaged-tier roots only. Run 1's root
     holds 12,793 more held-out lines (gold 4,445, adjacent 8,348) in its own volumes; if any of
     run 1's volumes ship, count those too. -->

<FILL: if decided, the OCR text layer (every line LightOn read, with word positions) as a
separate configuration.>

## Sources and rights

Every volume was published between 1786 and 1923 and is in the public domain in the United States.
The scans are the Internet Archive's, from the contributing libraries above. Their own OCR was
replaced here, though its word positions place LightOn's lines on most pages. The extracted
records are released under <FILL: licence>.

## Ethical considerations

The directories record the social categories of their time, and this dataset copies them as
printed. `race_designation` holds the markers directories used to set Black residents apart
(`col'd`, `(c)`, `colored`). `spouse_name` holds widowhood. Occupations and addresses reflect
who a directory canvasser recorded, and who they missed. The people listed lived between the
1780s and the 1920s. These are public commercial publications of their day, kept here for
historical and genealogical research. Use these fields as historical evidence, not as
descriptions of people, and give them that context wherever they are shown.

## How it was made

Code: [city-directory-extraction](https://github.com/hadro/city-directory-extraction) at
<FILL: release commit>.

1. **Survey.** For each volume: where the residential listing starts and ends, its sections,
   printed page numbers, and pages of advertising.
2. **OCR.** LightOnOCR-3-1B reads each page in half-column tiles. On book scans, the Internet
   Archive's word positions place each line on the page (tesseract where that OCR had failed);
   on microfilm, a fresh tesseract pass does.
3. **Lines.** Run-over lines are joined to their entries, and ditto marks are normalized.
4. **Extraction.** The 4B model, one line at a time, then a copy guard that restores printed
   words the model rewrote.
5. **Records.** Dittos are resolved, each line is placed on its IIIF canvas, and flags are set.

## Citation

<FILL: citation.>
