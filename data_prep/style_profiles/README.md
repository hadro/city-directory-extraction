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
- **`--front 20` is also too shallow, and "front matter" is the wrong place to look.** Hearne 1852's
  key page is **leaf 27** — and it is not front matter at all: the legend is printed at the *head of
  the "A" listings*, with the first entries following it on the same page. The card sat on
  "no legend reached / meaning uncertain" for ~3 months because the sample stopped at 20. **If a
  front sample finds no legend, sample the listing-start page before recording the conventions as
  inferred** — a legend that resolves a marker is worth more than the leaves it costs to reach.
- **`page_offset` drifts** (Trow: ≈ −1 near the front, ≈ +9 by p.353) because of unpaginated plates;
  record it as a local anchor near the listing start, not a global constant.

## Status: nothing consumes these yet (checked 2026-09-13)

Both apparent Python consumers are prose in comments (`nyu_to_eval.py:25`, `eval/evaluate.py:245`);
`synth_persons.py` does **not** read `style_profiles.json`, despite that file's own `_meta` naming
it as the consumer. 9 of the 17 markdown cards are consolidated into the JSON, against 449 catalog
rows.

**They should not be wired into the ingest filters.** Those rules self-calibrate against each
page's own distribution, which is what lets one setting span an 1786 single-column folio and a 1933
six-column Polk; a card is per publisher × era, a volume can depart from its family, and 17 cards
do not cover 449 volumes. `ia_volume_to_jsonl.leaf_bands` reading *"the volume's OWN admitted ditto
set, never a hard-coded glyph"* is a deliberate stance.

**What they are good for is an outside check, and a precondition for opt-in rules.**

### `data_prep/reconcile_style_profiles.py`

Compares each ingested volume's runtime-derived ditto mark against its card. Two independent
derivations — a human reading the printed page, and a frequency inference that knows nothing about
the publisher — that had never been compared.

```bash
python3 data_prep/reconcile_style_profiles.py data/*_lines.jsonl \
    --json results/reconcile_style_profiles.json
```

First run (5 volumes): **1906BPL agrees**, which is the load-bearing result since every published
figure rests on it — and the card supplies what the run structurally cannot, namely that `44` is
ABBYY's misreading of `"`. It also found:

- **`trow_manhattan_1890s` over-generalizes.** Its `—` and glued `-Michl` were read off the 1890s
  volume at printed p.353 and are not what Trow **1915** prints; `year_range` [1859, 1922] projects
  one volume across 63 years. Annotated in place, not overwritten — it is a human reading of a real
  page. **Narrow the range or add a 1910s card.**
- **Longworth and Boyd print a *word* ditto (`do.` / `do`)**, which `DITTO_SHAPE` cannot match at
  any frequency — structurally invisible, never even reaching the review queue. On the cached 1798
  Longworth, `do`-variants lead 7 of 13,280 lines (0.05%), so the gap is real but unexercised.
  **Do not widen `DITTO_SHAPE` until a volume that actually uses it is in hand.**

⚠️ **If a card is ever wired into something that *decides*, match on the CATALOG publisher, never
the trained tag.** `micro_IABROOKLYN_0013` carries `publisher=trow` from `tag_publisher`'s
out-of-vocabulary fallback and is an 1836/37 Brooklyn volume; only a year mismatch stopped it being
compared against a Trow card.

