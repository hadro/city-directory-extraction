# Style profiles

Per-publisher×era "style cards" distilled from **visual samples** of the actual volumes (front
matter + listing pages), produced by the visual-sampling workflow
(see `~/.claude/plans/would-it-be-possible-floofy-patterson.md`).

Each card captures a volume/family's real print style so we can (a) backfill structural metadata in
`master_directories.csv` (`column_count`, `start_page`/`end_page`, `key_page`, `page_offset`) and
(b) parameterize the synthetic generator (`synth_persons.py`) to match real layout + abbreviations —
the lever for closing the synth→real gap.

## Card schema
- **publisher / era / representative volume(s)** (master `id`s)
- **column_count** — and whether stated in a preface vs. counted
- **abbreviations legend** — transcribed from the volume's *abbreviations key page* (ground truth)
- **entry format** — line template + a verbatim sample line
- **field order / markers** — widow/spouse/occupation/employer/home conventions
- **structure** — title-page canvas, TOC (with section page numbers), key-page canvas, listing range
- **page_offset** — canvas_index − printed_page (note: drifts across the volume; record local value)

## How a card is built (free; no Gemini)
1. `directory-pipeline/sources/sample_directories.py <master.csv> --front 20 -k 2 ...` (downloads
   front matter + listing pages only).
2. `pipeline/detect_columns.py` + `pipeline/detect_spreads.py` (deterministic first pass).
3. Visually read the front matter → title page, TOC, abbreviations key (transcribe legend); read a
   listing page → confirm columns + entry format; compute `page_offset`.

## Lessons (pilot, 2026-06-19)
- The **abbreviations key page is the ground truth** for a volume's conventions; in some volumes
  (e.g. Trow) it doubles as the listing-start page.
- **`detect_columns` can under-count** dense listings (Trow: detector said 2, the preface says 3) —
  trust the preface / your eye over the detector for `column_count`.
- **`--front 12` is too shallow** for ad-heavy volumes; use ~**20** (Trow's key page sits ~canvas 14
  behind a wall of ad pages + a foldout map + an index-to-advertisers).
- **`page_offset` drifts** (Trow: ≈ −1 near the front, ≈ +9 by p.353) because of unpaginated plates;
  record it as a local anchor near the listing start, not a global constant.
