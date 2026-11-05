# Race markers: what each volume prints, and the post-processing fix

> Dug 2026-11-04 (PIPELINE #37); **the fix was built the same day** (this rewrite). If you are
> picking this up: read "Status", then "Decision", then "Traps". The numbers are round 13 + #38.

## Status

**Built, not yet released.** `race_designation` (the model's field) is kept verbatim, as every
model field is; the new column **`race_designation_resolved`** holds the printed marker where the
volume's own convention supports it, and `district` now also takes the Eastern District star.

| | usable rows | volumes |
|---|---:|---:|
| `race_designation` non-empty (the model) | 30,177 | 153 have some |
| **`race_designation_resolved` non-empty** | **26,107** | **63** (≥ 5 each) |
| of which `*` | 4,199 | 32 |
| of which textual (`(col'd)`, `(col.)`, `colored`, ...) | 21,908 | 31 |
| `district = Eastern` added by the star | 13,649 | 5 |

Model → resolved: 23,471 kept, 6,698 cleared, 2,628 added, 8 changed. Per volume, with examples:
`results/race_rule.json` (`python3 -I results/race_rule.py --out results/race_rule.json`, ~5 min,
run BEFORE a re-assembly: it reads the records on disk).

**Done with it:** the three cards (`cards/RECORDS_CARD.md`: the column, "count this, not
`race_designation`", and the ethics paragraph; `cards/MODEL_CARD.md`: a limitation, the model cannot
tell what `*` means; `cards/DATASET_CARD.md`: the generator stars two publishers only), a pointer in
`docs/HANDOFF.md` and in `synth_persons.py`'s docstring for the next training set.

**Still to do:**
- **Rebuild browse.db.** The build of 2026-11-04 15:26 predates the re-assembly, so it lacks the
  column; it picks it up by itself, and `browse/metadata.yml` already shows and describes it. The
  address finder's Parquet (`space/build_parquet.py`) carries no race column, so it needs nothing.
- **Which column the release export ships** (hadro's call, see `release-open-decisions`). Proposal:
  `race_designation_resolved`, perhaps under the public name `race_designation`, with the model's
  value in an audit column. The cards are written for both columns shipping as they are now.
- **The blog draft** (`docs/drafts/city-directories-blog-post`, untracked) still says "about 9,800
  usable records, in 68 of the 82 volumes processed": the edit was made, then an older copy of the
  file replaced it on disk the same day. The sentence to use: "about 26,000 usable records, in 63 of
  the 153 volumes, carry one [TKTK final count at release]".

## How it works

1. **Per-volume claims in the sidecar** (`data_prep/survey_race_markers.py`, the evidence table;
   `--write` merges them into `data_prep/survey/ia_<id>.json`). Two `book_says` claims, each citing a
   leaf and a verbatim quote, `method: agent-read` so a front-matter re-read keeps them:
   - `race_marker`: the printed form that marks a colored person — `*` (32 volumes) or the textual
     form (31). No claim = the volume prints none.
   - `star_meaning`: what a leading `*` means where it is not race — `eastern_district` (5) or
     `advertiser` (55).
   The writer keeps an earlier claim of the same value (Ogden's and Trow 1859's were read on images)
   and refuses to overwrite one that disagrees.
2. **The rule** (`postprocess/assemble_records.race_resolved`), per line:
   - `*` volume: `*` where the line opens on a star — the assembly's `name_mark` (`*`, or `•`, the
     OCR's star in 0015 and nine others), the raw line (`*M'Garrell`, which the mark classifier
     passed by; at most one stray character before it, `E *Taylor J. W. A. waiter`), or the model's
     own field. Never a star after the address (`109 Atlantic 11*`, OCR debris).
   - textual volume: the model's value where it is a form of "colored" (`RACE_TEXT`, which adds the
     OCR's damage `(col d)`, `(cold.)`, `(col:)` and drops `colr`/`coll.`, collector); else the
     form as the line prints it after the name (`line_form`: before the first digit, a bare form
     lowercase and within four words, never after `dep.`/`tax`/`pres.`, never the abbreviations key).
     That fallback adds 437, 371 of them Lain 1862, whose bare `col.` the model almost never copied.
   - any other volume: empty.
   - `district = Eastern` also where `star_meaning` is `eastern_district` and the line is starred.
3. **Re-assembly** of the three tiers (2026-11-04) wrote the column; nothing else changed. Checked
   row by row against an APFS clone of the previous records (`cp -c`), with
   `results/race_reassembly_check.py <before dir>`: 15,776,206 rows in 153 volumes, row counts
   equal, every other field equal, `race_designation_resolved` equal to the rule recomputed, and
   `district` changed only None → Eastern on a starred line of an `eastern_district` volume, on
   14,560 rows (13,649 of them `usable`, the count above). The summaries differ only in the new
   `race` block and the ditto block's `district_eastern`.

## Decision (hadro asked 2026-11-04: post-processing or retraining?)

**Post-processing, and no targeted retrain or re-run either** (asked again the same day: retrain and
run the ~26K race lines through the revised model?). The evidence:
- **The model reads OCR text, not the image.** Where the OCR kept the star, `name_mark` and the raw
  line catch it deterministically; where it lost it, no text model can recover it. What a star
  *means* is the volume's key page, which the model never sees.
- **Textual forms are already in the text.** The model copies them at 99%+; the 437 it missed are now
  taken from the line by rule. The residual a better model could still touch is at most 101 textual
  lines and 167 star lines (`text_unmarked`, `star_unmarked` in `results/race_rule.json`), and read on
  samples most are not race at all (a merged second entry, `colored paper`, debris after an address).
- **Re-running only the 26K marked lines cannot fix the misses**, which are lines with *no* value; it
  would also leave those lines from a different model than their neighbours, for no measured gain.
  Retraining means an NYU round trip, and the release plan froze line assembly after round 13.
- **For the next model, not this release:** `synth_persons.py` keys `*` by publisher (HANDOFF.md,
  "FIX: era/publisher-gate the directional form"), which is probably why the 4B sets race on firms'
  stars. A future training set should gate `*` by volume family and include starred firm and
  Eastern District lines with race empty.

## What each volume prints (read on key pages, crops and lines, 2026-11-04)

The sidecar claims are the record; this is the summary.

| What is printed | Where | Meaning | Evidence |
|---|---|---|---|
| leading `*` | Spooner 1829-49 microfilm, Ogden 1839, Spooner 1843/1848, Hearnes 1850-55 | **colored** | "Names having an * are of colored persons" (1829-35), "NOTE.—Names having a * are the names of colored people" (1838-52): key read on the image in 19 volumes, in the OCR text in 3, starred lines in the rest |
| leading `*` | Williamsburgh: micro 0043 (1849-50), Reynolds 0044-0048 (1850-54) | **colored** | key on the image in 0043 and 0044; 0045/0047/0048 start mid-listing; same households starred across years |
| leading `*` | Hope & Henderson 1856/57 (micro 0035) | **Eastern District** | "Names marked thus * are persons residing or doing business in the Eastern District" (leaf 38) |
| raised `ᴱ`, OCR'd as `*` | Consolidated 1858-60 (micro 0039/0040/0042), Lain 1866 | **Eastern District** | the key prints "(ᴱ)"; crops of starred lines show the ᴱ |
| leading `*` | Trow 1859-1876 and 1903-14, Lain 1884-99, Upington 1902-10 | **firm / advertiser** | lines read: `*KRANICH & BACH, pianos`, `*BANK OF MONTREAL`; key pages not read (they would not change the rule: anything not race is empty) |
| `(col'd)` | Doggett 1845-48, Rode 1851, Trow 1857-65, Hope & Henderson 1856/57, Lain 1871, Longworth 1816/1840 | colored | key or lines |
| `(col.)` | Smith 1856, Lain 1858-69, the Consolidated microfilm, the 1845 micro 0022 | colored | key "col. colored" (Lain, the Consolidated), lines |
| `col.` | Lain 1862 | colored | key; 371 lines the model missed |
| `(colored)` / `colored` | Longworth 1826/1835/1836, Smith 1857 | colored | lines |

The other 90 volumes print no race marker (52 of them star advertisers): Longworth/Mercein before
1816, Spooner 1822-28, and everything after Lain 1871.

## Traps

- **Do not count `race_designation`.** It is the model's field, 30,177 rows, wrong both ways. Count
  `race_designation_resolved`.
- **`*` is the same glyph with opposite meanings across adjacent decades and even across the river**
  (Ogden 1839 and Reynolds' Williamsburgh 1850 colored, Hope & Henderson 1856 Eastern District, Trow
  1905 firm). Never gate on the glyph or the publisher; read the volume's key.
- **An OCR'd `*` may not be a star.** In micro 0039/0040/0042 and Lain 1866 it is the raised Eastern
  District E. Look at a crop before trusting a glyph.
- **The same abbreviation flips meaning by volume.** `col.` is colored in Lain 1862, collector in Lain
  1876/1878, Colonel in Longworth 1813 (`Rutgers col. Henry`); `(Col)` is Colorado in Trow 1915-22.
  The textual forms count only in the 31 claimed volumes.
- **`usable` lets an abbreviations key through** (micro 0039 leaf 11, `col. colored; com.
  commission`); the line fallback refuses a line with a key gloss.
- **`data/records/4b-100k+guard` holds five stale run-1 files** (1906BPL, Doggett 1845, Mercein,
  micro 0030, 0036). Read a tier by its summary's volume list, never by globbing the directory or
  taking the first match; `race_marker_recall.py` and the dig's sampling did the latter.
- **The numbers move with assembly.** Re-run `results/race_rule.py` (before re-assembling), do not
  edit the tables.

## Files

- `data_prep/survey_race_markers.py`: the evidence table and the sidecar writer.
- `postprocess/assemble_records.py`: `race_resolved`, `starred`, `line_form`, `RACE_TEXT`; the
  column and the summary's `race` block; self-tests from lines read.
- `results/race_rule.py` / `results/race_rule.json`: the before/after and the residuals.
- `results/race_reassembly_check.py`: the row-by-row check of a re-assembly against a copy of the
  records taken before it (clone `data/records*` with `cp -c` first; the 2026-11-04 copy is deleted).
- `results/race_markers.py` (+ `_tally.json`, `.json`): the dig, superseded for the count.
- `results/race_marker_recall.py`: the first textual-recall check (six volumes).
- Style profiles: `reynolds_williamsburgh_1850s.md` (key found), `hope_henderson_brooklyn_1850s.md`.
- Cards: `cards/RECORDS_CARD.md`, `cards/MODEL_CARD.md`, `cards/DATASET_CARD.md`.
- Blog post: `docs/drafts/city-directories-blog-post`, the `race_designation` paragraph (NOT yet
  updated, see "Still to do").
