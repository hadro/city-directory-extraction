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
(Trow re-pulled at `--front 27`). Only Trow's card is written; the other 6 dirs are downloaded but
not yet carded.

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

## Lessons / gotchas (hard-won in the pilot)
- **Abbreviations key = ground truth**; in some volumes (Trow) it doubles as the listing-start page.
- **`detect_columns` under-counts** dense listings (Trow: detector said 2; the preface says **3**).
  Trust the preface / your eye for `column_count`; treat the detector as a hint.
- **`--front 12` too shallow** for ad-heavy volumes — use **`--front 20`** (Trow's key sits ~canvas
  14 behind ads + a foldout map + the advertiser index).
- **`page_offset` drifts** across a volume (Trow: ≈ −1 at front, ≈ +9 by p.353) due to unpaginated
  plates → record a *local* value near the listing start, not a global constant.
- **Microfilm (BPL) volumes** are often double-page **spreads** + degraded (`detect_spreads` flags
  them; a spread = 2 printed pages per canvas, which complicates `page_offset`).
- **Bonus:** Trow's preface prints **spelling-variant name clusters** (Bauer/Baur/Bower,
  Schafer/Schaffer/Schaefer…) — a candidate seed for name generation vs. surname regularization.
- **Subagent permission sandbox:** a delegated agent could NOT use Read/Bash (blocked), so it
  couldn't open images. To fan out **cheap Haiku/Sonnet agents** for the bulk visual passes you must
  first allowlist Read/Bash for subagents (run `/fewer-permission-prompts`, or edit
  `.claude/settings.json`). Otherwise the main (Opus) thread does the visual reads — pricier.

## NEXT — Phase 1: backfill at scale (~290 non-NYPL rows)
1. **(Prereq for cheap delegation)** allowlist Read/Bash for subagents (`/fewer-permission-prompts`),
   then dispatch Haiku/Sonnet agents (`Agent` tool, `model:` param) batched N volumes each:
   Haiku/Sonnet for locate-TOC/key + read columns; Sonnet for legend transcription (small print).
   Reserve Opus for ambiguous rows + the heuristic + the `synth_persons.py` code.
2. Sample `--front 20 -k 2` across non-NYPL rows (batch by `--source`/`--publisher`; `--dry-run`
   first). **Skip eval-heldout** volumes (Lain 1897 `1885BPL` is fine, but the held-out `1897BPL`
   and NYU Trow 1850 stay OUT).
3. Run `detect_columns` + `detect_spreads` over all dirs.
4. Per volume: fill `column_count`, `start_page`/`end_page` (from TOC + `page_offset`), `key_page`;
   transcribe each distinct publisher/era legend once.
5. **Test the "consistent fraction" hypothesis:** log `key_page_idx/total` and `toc_idx/total`; if it
   clusters per publisher/era, derive a heuristic so later volumes skip the full front scan.
6. Targeted QA (Opus): the 7 blank-year Longworth rows (read title pages), `trowsgeneraldire1853trow`
   REVIEW, Spooner serial, reprints.
7. Commit per-source. Finish the 5 un-carded pilot volumes (Lain/Doggett/Longworth/Flushing/phonebook)
   as the first style cards.

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
