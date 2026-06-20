# Handoff — Visual sampling of directory volumes

> Self-contained handoff for the **visual-sampling** workstream (started 2026-06-19).
> Designed to be picked up cold (incl. Claude Code / Dispatch on mobile). Companion:
> [HANDOFF.md](HANDOFF.md) (the broader Qwen fine-tune project), [../README.md](../README.md).

## Goal
Take a *visual* sample (front matter + a couple listing pages) of the volumes in
`data_prep/master_directories.csv` (449 rows: nypl/ia/loc) to:
1. **Backfill structural metadata** — `column_count`, `start_page`/`end_page`, and the new
   `key_page` + `page_offset` — for the ~290 non-NYPL rows that are blank.
2. **Locate + transcribe each volume's abbreviations key page** (the "Explanation of abbreviations":
   `h`=house, `r`=resides, `bds`=boards, `wid`=widow, …) — the *ground-truth* style legend. The
   front-matter **table of contents** gives section start pages (persons/street/business).
3. **Build per-publisher×era style profiles** (`data_prep/style_profiles/`) and use them to
   parameterize the synthetic generator `data_prep/synth_persons.py` — the lever to close the
   synth→real gap (the model regularizes unseen surnames / misses out-of-style layouts, e.g. Lain
   Brooklyn). *(Out of scope for now: auto OCR/NER prompts, eval-set expansion.)*

## Status — Phase 0 (pilot) DONE ✅
Validated the whole chain on **Trow 1890/91** (nypl `4b984650-317a-0134-f64d-00505686a51c`) and
confirmed it generalizes (Doggett 1845 TOC found). Committed:
- this repo: `b970511` — `key_page`+`page_offset` columns (CSV + `ingest_collection.py` FIELDS +
  README schema), Trow pilot row backfilled, `data_prep/style_profiles/` (README + first card
  `trow_manhattan_1890s.md`).
- sibling `directory-pipeline`: `bd4ca4f` (branch `claude/local-ocr-city-directories-ey5741`) —
  `sources/sample_directories.py --front N` option (samples front matter too).

Pilot downloads live in `directory-pipeline/output/<slug>/` (gitignored): 7 volumes
(nypl Trow, ia Lain/Doggett/Longworth/Flushing/phonebook, loc Spooner) sampled at `--front 12 -k 2`
(Trow re-pulled at `--front 27`).

## Status — Phase 1 (scale-out) STARTED 2026-06-19

**Completed so far (2 sessions):**

**Pilot volumes — all 6 un-carded downloads are now carded** (`e1f5b46`, 2026-06-19):

| Style card | Source/ID | col | key_page | page_offset |
|---|---|---|---|---|
| `lain_brooklyn_1880s.md` | `ia/1885BPL` | 2 | 1 | 0→+50 (drift) |
| `doggett_manhattan_1840s.md` | `ia/doggettsnewyorkc1845dogg` | 2 | — | +10→+16 |
| `longworth_manhattan_1830s.md` | `ia/longworthsameric1839newy` | 1 | — | +6 (constant) |
| `boyd_flushing_1880s.md` | `ia/flushingnewyork188586boyd` | 1 | — | +15 persons / +64 biz |
| `lain_brooklyn_1881_loc.md` | `loc/01015253` | — | — | stub — resample needed |

The `loc/01015253` row is the Lain 1881 serial (LCCN): both `--front 12 -k 2` samples landed in
front-matter index blocks — no persons listing page captured. Resample: `--front 5` targeting
the persons section (which starts well past the index block in a large volume).

**Already-downloaded un-carded volumes** (`d775172`, 2026-06-19):

- `nypl/b14662b0` (Franks/Kollock 1786): carded as `franks_newyork_1786.md` — first NYC
  directory ever published; 1 col; page_offset **+8 constant** (measured from IIIF canvas labels
  25/36/47 vs printed pp. 17/28/39); format `Surname Firstname, occupation, Number, Street`.
  Covers 5 CSV rows (1 NYPL original + 2 IA originals + 2 reprints — column_count=1 backfilled
  for all; page_offset only set for the NYPL copy; others need sampling to measure their offset).
- `ia/newyorkcityincl1917newy_1` ("New York City Inclusive"): confirmed **PHONEBOOK** — all
  sampled canvases are classified business ad sections; listing pages are 4–5 narrow columns with
  embedded ads (Donnelley-style telephone directory); NOT a residential persons training target.
  Notes updated in CSV.

**Permissions** (`d775172`, 2026-06-19): `.claude/settings.json` created with HF CLI read
patterns (`hf jobs ps *`, `hf jobs logs *`, `hf auth whoami`, `hf download *`). Note: `Read` and
basic Bash commands (`ls`, `grep`, etc.) are auto-allowed for subagents already; HF CLI was the
only gap. Subagent delegation has not yet been tested in practice.

**Longworth cohort backfilled** (2026-06-19, session 3): sampled 3 representative NYPL volumes
across the 1797–1843 run (1797 `9c27dfc0`, 1820/21 `d0c00950`, 1842/43 `5a28bac0`) at
`--front 20 -k 2`. **All 61 Longworth rows (NYPL + IA) got `column_count=1`** — verified single
column at both extremes; the run predates the ~1845 two-column transition. `page_offset` recorded
for the 3 sampled volumes only (it is **per-volume, no cohort constant**: +19 const / −5→+7 drift /
−9 const). The other 45 NYPL + 10 IA Longworth rows still need per-volume sampling for `page_offset`
(and `start_page`/`end_page` — no TOC reached in the front sample; front matter is almanac calendar
pages). Card `longworth_manhattan_1830s.md` extended with the NYPL run table + findings. NOTE:
negative offsets appear in later volumes (`canvas_index = printed_page + offset`).

**Doggett cohort backfilled** (2026-06-19, session 3): sampled 4 representatives across 1842–1855
(nypl 1842/43 `8ca2a950`, nypl 1846/47 `88fe6240`, nypl 1854/55 `a4b1de40`, ia 1847). **All 11
uncarded Doggett rows got `column_count=2`** — Doggett was two-column from its first (1842/43)
volume, unlike the Longworth single-column directories it replaced. `page_offset` recorded for the 4
sampled (per-volume, mostly drifting: +5 const / +17→+29 / +6→+8 / +3→−3). Card
`doggett_manhattan_1840s.md` extended with the cohort table. Remaining 7 Doggett rows need
per-volume offset sampling.

**Hearne (Brooklyn) cohort carded** (2026-06-19, session 3): sampled 4 reps (regular IA 1850 & 1852,
microfilm `micro_IABROOKLYN_0028`/`_0032`). **New card `hearne_brooklyn_1850s.md`** written
(publisher Henry R. & William J. Hearne; distinctive Brooklyn `NY h` commuter notation +
`n`/`c`/`b`/`op` street-relation grammar). **All 7 Hearne rows got `column_count=1`** (single column
on both regular IA and microfilm). KEY: the `micro_IABROOKLYN` scans are **single-page single-column,
NOT double-page spreads** (contra the microfilm-spread warning) — just darker/degraded. `page_offset`
recorded for the 4 sampled (per-volume drift: +16→+22 / +12→+16 / +8 / +6).

**Current CSV state:** **164 rows** now have `column_count` (was 88; +58 Longworth, +11 Doggett,
+7 Hearne); **16 rows** have `page_offset` (was 5; +3 Longworth, +4 Doggett, +4 Hearne). ~285 rows
(of 449 total) still need `column_count` backfilled.

## The workflow (all FREE — no Gemini/API)
```bash
PY=/Users/joshhadro/github/directory-pipeline/.venv/bin/python   # has requests/numpy/PIL
MASTER=/Users/joshhadro/github/city-directory-extraction/data_prep/master_directories.csv
cd /Users/joshhadro/github/directory-pipeline

# 1. sample front matter (~20 pages: title/TOC/key) + listing pages — downloads ONLY those pages
$PY sources/sample_directories.py "$MASTER" --front 20 -k 2 --width 1800 \
      --source ia --publisher Trow --limit 1            # filters: --source/--publisher/--limit; --dry-run to just resolve
# 2. deterministic structure detectors (no model)
$PY pipeline/detect_columns.py output/<slug>            # -> output/<slug>/columns_report.csv (num_columns, confidence)
$PY pipeline/detect_spreads.py output/<slug> --csv output/<slug>/spreads_report.csv
# 3. VISUAL read of output/<slug>/*.jpg (Read tool renders images): find title page (year), TOC
#    (section page numbers), abbreviations key (transcribe legend); read a listing page -> confirm
#    columns + entry format; compute page_offset = canvas_index - printed_page near listing start.
# 4. backfill the row(s) in $MASTER and write data_prep/style_profiles/<publisher>_<era>.md
```

## Lessons / gotchas (hard-won in the pilot and Phase 1)
- **Abbreviations key = ground truth**; in some volumes (Trow) it doubles as the listing-start page.
- **`detect_columns` under-counts** dense listings (Trow: detector said 2; the preface says **3**).
  Trust the preface / your eye for `column_count`; treat the detector as a hint.
- **`--front 12` too shallow** for ad-heavy volumes — use **`--front 20`** (Trow's key sits ~canvas
  14 behind ads + a foldout map + the advertiser index).
- **`page_offset` drifts** across a volume (Trow: ≈ −1 at front, ≈ +9 by p.353) due to unpaginated
  plates → record a *local* value near the listing start, not a global constant.
- **`page_offset` can be constant** in older volumes where ads are a fixed front block with no
  interspersed pages (Longworth 1839: exactly +6 at both measured points; Franks 1786: exactly +8).
- **Section-boundary jumps** are huge: Boyd Flushing 1885/86 jumps +49 between persons and
  classified-business sections (a large unnumbered ad insert). Always note which section an offset
  measurement applies to.
- **LoC serial records** cover a multi-decade run; the specific digitized volume may differ from the
  catalog publisher. Always read the title page (sampled as a front-matter canvas) before assuming
  the master-list publisher matches the physical volume.
- **Donnelley/telephone directories** look like persons directories at first glance but have 4-5
  narrow columns with ads embedded in listing pages — unmistakable once you see a listing page.
  The IA "New York City Inclusive" series is one of these. Already-PHONEBOOK rows in the CSV are
  often these.
- **Publisher clustering** is the efficiency lever: once you sample one volume from a publisher/era
  and write the card, other volumes in that cohort only need page_offset measured (not a new card).
  Sample one Hearnes, cover all 7; extend the Lain card for each subsequent Lain year.
- **Reprints** (Patterson 1874 of Franks 1786; Disturnell 1876) have the same entry format but
  potentially different page_offsets (different digitizing institution adds different front matter).
  Backfill `column_count` from the original's card; leave `page_offset` blank until sampled.
- **Microfilm (BPL) volumes** are often double-page **spreads** + degraded (`detect_spreads` flags
  them; a spread = 2 printed pages per canvas, which complicates `page_offset`).
- **Bonus:** Trow's preface prints **spelling-variant name clusters** (Bauer/Baur/Bower,
  Schafer/Schaffer/Schaefer…) — a candidate seed for name generation vs. surname regularization.
- **Subagent permissions:** `Read` and basic Bash (`ls`, `grep`, etc.) are auto-allowed for
  subagents. HF CLI commands (`hf jobs ps`, `hf jobs logs`, etc.) are NOT — added to
  `.claude/settings.json` via `/fewer-permission-prompts` (2026-06-19). Subagent visual-read
  delegation not yet tested in practice.

## NEXT — Phase 1 (continued): backfill at scale (~359 remaining rows)

✅ **Done:** step 1 (permissions), step 7 (pilot volumes + already-downloaded).

**Remaining steps:**

2. Sample `--front 20 -k 2` across non-NYPL rows **in publisher batches** (same publisher/era →
   share a card; only measure page_offset per volume). `--dry-run` first. **Skip eval-heldout**
   volumes (`1897BPL` Lain and NYU Trow 1850 stay OUT).

   High-leverage batches to do next (ordered by ROI):
   | Publisher | Remaining vols | Action |
   |---|---|---|
   | Lain Brooklyn (1884–1897) | 6 | Extend `lain_brooklyn_1880s.md`; measure offset per vol |
   | ~~Hearne Brooklyn (7 vols)~~ | ~~done~~ | ✅ new card `hearne_brooklyn_1850s.md`; col=1 backfilled for all 7; offset done for 4 (2 IA + 2 micro). Remaining: per-volume offset for 3 |
   | ~~Doggett (12 vols)~~ | ~~done~~ | ✅ col=2 backfilled for all 11; offset done for 4 (1842/43, 1846/47, 1854/55 nypl + ia 1847). Remaining: per-volume offset for 7 |
   | ~~Longworth (61 vols)~~ | ~~done~~ | ✅ col=1 backfilled for all 61; offset done for 3 (NYPL 1797/1820/1842). Remaining: per-volume `page_offset` for 45 NYPL + 10 IA (low priority — offset is per-volume, no shortcut) |
   | Trow (51 vols) | 51 | Have card; sample each → measure offset only |
   | Blank-publisher IA rows | ~172 | Identify first (read title pages) — some may be SKIP |

   Also: resample `loc/01015253` (Lain 1881) with `--front 5` targeting persons section to
   complete the stub card `lain_brooklyn_1881_loc.md`.

3. Run `detect_columns` + `detect_spreads` over downloaded dirs.
4. Per volume: fill `column_count`, `start_page`/`end_page` (from TOC + `page_offset`), `key_page`;
   transcribe each distinct publisher/era legend once.
5. **Test the "consistent fraction" hypothesis:** log `key_page_idx/total` and `toc_idx/total`; if it
   clusters per publisher/era, derive a heuristic so later volumes skip the full front scan.
6. Targeted QA (Opus): the 7 blank-year Longworth rows (read title pages), `trowsgeneraldire1853trow`
   REVIEW, Spooner serial, reprints.

## THEN — Phase 2: style profiles → synth generator
- Consolidate `data_prep/style_profiles/*.md` + a machine-readable `style_profiles.json` (legends +
  TOC maps). Card schema is in `style_profiles/README.md`.
- Extend `synth_persons.py` (`render_tulsa`/`render_nyc`, `_finish()` `context`) with a style layer
  keyed by publisher/era so synthetic lines use volume-accurate abbreviations/layout; then regenerate
  + retrain + re-run the eval panel (existing Wave-1 procedure in HANDOFF.md) to confirm the
  `name`/EM lift, esp. on Lain.

## Key paths
- Master list: `data_prep/master_directories.csv` (schema in `master_directories.README.md`).
- Style cards: `data_prep/style_profiles/` (`README.md` = card schema + build recipe + lessons).
- Ingest tool (FIELDS): `data_prep/ingest_collection.py`.
- Sampler + detectors: `../directory-pipeline/sources/sample_directories.py`,
  `../directory-pipeline/pipeline/detect_columns.py`, `detect_spreads.py`.
- Synth generator (Phase 2 target): `data_prep/synth_persons.py`.
