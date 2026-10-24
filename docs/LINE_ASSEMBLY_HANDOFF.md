# Line assembly: PIPELINE #30 and #32 (b)–(e)

**Written 2026-10-24, at commit 8129853**, for an agent picking up these five defects cold. The full
findings are in [PIPELINE.md](PIPELINE.md) #30 and #32; this file says what state things are in,
how to work on them without breaking what is out at NYU, and how to show a change is safe. Read
[BOOKSCAN_HANDOFF.md](BOOKSCAN_HANDOFF.md)'s top update for the wider picture.

## 1. Where things stand

The book-scan re-OCR (LightOnOCR-3 text over a word layer's boxes) feeds the survey, which feeds
the 4B extractor. Line assembly is `data_prep/reocr_pair.py` (`boxed_lines`, `pair_tile`,
`align`, `split`, `respell`, `page_dump`) run by `reocr_books.py import`, then the survey's
wrap-joiner (`data_prep/ia_volume_to_jsonl.py` `join_wraps`) and filters (`survey_harvest`).

| commit | what | measured |
|---|---|---|
| de9521a | same-row fix: a printed line the layer cut at a wide space is joined where ONE model line covers its pieces | Longworth 1826 split pairs 1,159 -> 41; pilot no row lost |
| b88ecda | PIPELINE #31 steps 1-3: import on several cores, output byte-identical | 33 volumes in 77 min (was ~5 h) |
| 071e202 | #32 (a): a ditto line hung on a misread mid-line word is pulled back to the margin | glued entries 1.18% -> 0.39%, 1.00% -> 0.31% in the two "generaldire" Trow volumes; pilot no row lost |
| da3ca91 | the damaged tier (35 volumes) and the canary (4) re-imported with all of the above | |
| 8129853 | those 39 staged for the 4B: `data/volumes_books_damaged_v2`, `cde-volumes-books-damaged-v2.tar.gz` | 258 tasks, ~103 GPU-h |

**Out at NYU (or about to be):** C, the 4B over those 39 volumes; D, the LightOn re-read of the last
two tiers (`first`, 58 volumes, and `abbyy8-clean`, 17), whose answers come back for import here.

**Why timing matters.** A fix to line assembly reaches the corpus only through an import. D's
import is the next one, so **a fix committed before D returns costs nothing**. A fix that should
also reach the damaged tier means re-importing it (~1.5 h now) and, for its records, a new 4B run
(~103 GPU-h), so batch such fixes. Never restage `data/volumes_books_damaged_v2` in place (§5).

## 2. The five tasks

Ranked by what each costs the 4B. Each needs its own before/after per §3. Page images:
`https://iiif.archive.org/iiif/<id>$<leaf>/full/max/0/default.jpg`.

### #30 — the panel scores a gold row against another person's line (do first; no production data)

`eval/volume_run_report.align`, used by `eval/ia_panel.build`, gives a gold row the best line at
ratio >= 0.6 within a length window of max(12, 60%). A same-address neighbour can win: boyd1890 gold
row 73 (leaf 105), `McElroy John A, news agent, h 84 Bradford ave`, got `McElroy Bernard E, bill
poster, h 84 Bradford ave` at 0.622, because the right line had an ad banner glued on (78
characters against 43) and fell outside the window. Upper bound: 55 of 2,206 rows on `data/iapanel`,
15 of 1,963 on the LightOn panel (some are only garbled names, e.g. franks1786 row 37).

- **Fix:** a single-line candidate also needs the gold's leading surname token, and its first
  given-name token where printed, to match (token ratio >= ~0.75), except ditto-led gold rows; a
  failing row stays unmatched. Widen the window for a line that starts like the gold (prefix
  ratio), so a glued tail shows as an inexact line, not a wrong person.
- **Verify:** `ia_panel.build` writes `data/iapanel` and the tracked `results/ia_panel_manifest.json`
  by default, so build into a new directory instead (set `ia_panel.PANEL_DIR` and
  `ia_panel.MANIFEST`, as `eval/lighton_pilot.py` does), then diff
  by `gold_row`. Every changed row should be one of the ~70, now unmatched or the gold's own person;
  no exact row may change. Report pooled row EM before and after with matched counts beside it.
- **Second half** (the joiner gluing a display banner, e.g. `... Bradford ave LLIOTT, Plumbing,
  Steam and Gas Fitt`): see PIPELINE #30. Riskier; #28 showed indent alone cannot separate starts
  from run-overs.

### #32 (b) — table mode: entries merged in one cell, ditto dashes dropped, header rows kept

LightOn answered 20-25% of tiles as tables on Brooklyn 1905 p1 and c1905 and Trow 1903 p1-p3 (6.6% of
the tier). `hpc/lightonocr_tiles.untable` recovers one entry per line, but: a cell can hold two
entries (Trow 1909 vol 1 leaf 97, tile c1_h1: `| Philippa sec ... N Y Abbihl Jacob H h 408 W 150th |`);
cells drop the printed ditto dash (`| Chas I ice ...` for `—Chas I ice ...`); the ", " restored at a
field cut lands after the NAME in these styles (`Dorfman Dora, dry gds`, unprinted); and an HTML
`<thead>` row survives as a line (76 in the tier: `python3 eval/line_assembly.py tables`).

- **Fixes, cheapest first:** drop a `<thead>` row whose cells are all generic column words (the
  76; re-import only, since the import re-flattens from `.raw.txt`); then count, per volume, cells
  holding two entries (a mid-cell `Surname Given` after an address). If more than a handful, re-read
  those tiles on Torch with a prompt or sampling that discourages tables (a few hundred tiles,
  minutes of GPU) rather than splitting cells here. `untable` lives in `hpc/lightonocr_tiles.py`,
  which the Torch runner also uses: a change there changes what Torch writes too.
- **Verify:** `tables` before/after; pilot both layers (table tiles exist in the pilot: 10 of 138 on
  the bench).

### #32 (c) — `respell` places unmatched words off the column; the banner filter drops the line

Trow 1909 vol 1 leaf 95: IA's words have nothing under `Aal Siegfried`, so `respell` runs the name
leftward from the first matched word at an inflated character width, to x = -43, and
`survey_harvest` drops the over-wide line as `banner`. About 0.05% of lines (107 in Trow 1909 vol 1).

- **Fix (cheap, safe):** clamp a line's words to its tile's left edge (each row carries `x0`) and cap
  `respell`'s per-character width at the page's median `char_w`.
- **Verify:** count lines off the page's left edge before/after; `moved` on two volumes (should be
  small, all far-left lines); pilot both layers.

### #32 (d) — a hyphenated word's tail, a layer piece of its own, is dropped as `short`

Brooklyn 1905 p1 leaf 563: LightOn read `... 4 New Chambers Mhtn h 155 Cornelia`; IA's layer has `... 4
New Cham-`, then `bers` as its own piece, then `Mhtn ...`, so `split` gives `bers` a row and the
survey drops it, leaving `... 4 New Cham-` / `Mhtn h 155 Cornelia`. `bers` misses the same-row rule
by half a pixel (middles 12 px apart, limit 11.5).

- **Fix:** in `pair_tile`/`split`, a piece too short to stand (under ~5 characters, no digit) joins
  its neighbour in the same run rather than becoming a row.
- **Verify:** `page HEAD brooklynnewyork1905p1geor 563 Dornheim`; pilot both layers. Not measured
  corpus-wide: count rows of 1-4 letters with `start=0` before/after on a few volumes.

### #32 (e) — the same-row rule assumes a level line

On a tilted page a line's right-hand piece sits 15-20 px off its left partners, and `boxed_lines`
(middles within half the shorter height) can group it with the line above or below; the reorder
shifts `align`, a global best path over the tile. Longworth 1826 leaf 409: `Eager & Tompkins,
grocers 162 Spring`, one line before de9521a, became `Eager` / `& Tompkins ...`, and `Eakins
Archibald` went model-only. Rare (needs a garbled layer and a tilt); the volume's net is strongly
positive.

- **Fix:** compare middles after correcting for the column's measured slope (fit from pieces' ends,
  or use the tile's angle where nonzero); and do not reorder pieces whose row membership is within
  ~20% of the limit.
- **Verify:** `page de9521a~1 longworthsameric1826newy 409 Eager Eakins` (before the same-row rule)
  against the working tree; the Longworth split count must stay near 41 (`samerow` measure in PIPELINE
  #27); pilot both layers.

### Optional: #31 step 4, a banded `align`

~5x more on the import's hot spot, but it CAN change pairings. Same verification as any behaviour
change. Not needed for speed now.

## 3. How to show a change is safe

Every behaviour change so far needed all three; #32 (a) took four rounds because the first three
each failed one.

1. **Gold, both word layers.** `eval/lighton_pilot.py` rebuilds the 17-set real-OCR pilot through
   the production path. ~15 min each; writes a work dir of ~270 MB under `data/`.
   ```bash
   python3 eval/lighton_pilot.py --page-dir data/reocr_pilot_pages_ia --work data/lighton_pilot_X_ia \
       --panel-dir data/iapanel_lighton_X_ia --diff-against data/iapanel_lighton_pull_ia
   python3 eval/lighton_pilot.py --work data/lighton_pilot_X_tess \
       --panel-dir data/iapanel_lighton_X_tess --diff-against data/iapanel_lighton_pull_tess
   ```
   `data/iapanel_lighton_pull_{ia,tess}` are the panels at 071e202 (the current code): pooled exact
   **83.7%** (IA's words, 2,066 rows) and **83.1%** (fresh tesseract, 2,064 rows). The rule so far:
   **no exact row lost** on either. IA's words is what production book scans use; fresh tesseract
   is what failed-OCR volumes use (`better_layer`).
2. **Target, on real volumes.** Re-dump to scratch (`reocr_pair.py dump ... --out-dir DIR`, writes no
   sidecar) or re-import (`reocr_books.py import --ids ...`, rewrites dumps and sidecars: commit
   sidecars first so `facts --against HEAD` is the before). Measure the defect's own count.
3. **Collateral.** `python3 eval/line_assembly.py moved DIR <vol>` on two or three volumes that do not
   have the defect: lines whose start moved. Hundreds in a volume, for a change aimed at one shape,
   is suspicious; tens of thousands is a bug (a wider #32 (a) moved a quarter of a Trow part's lines).
4. **A refactor meant to change nothing** must be byte-identical: `line_assembly.py same` on an
   IA-layer volume (e.g. `longworthsameric1798newy`) and a tesseract-layer one
   (`trowsgeneraldire19073trow`), and `reocr_pair.py --self-test`.

Add a self-test case for each fix (`reocr_pair._self_test` has the house style: real lines from
real pages).

## 4. The tool

`eval/line_assembly.py` (read-only): `page REV VOL LEAF [PATTERN ...]` runs one page through the
import's own path at a git revision and in the working tree side by side; `proxy` is #32 (a)'s
glued-entry measure; `moved`, `same`, `tables` as above. Its docstring has the details.

## 5. Traps

- **Never restage a sent package's directory in place** (`data/volumes_books_damaged_v2`); new
  staging, new directory. And `hpc/35_volumes.sbatch` always reads `data/volumes/tasks.txt`, which
  every 4B package's tar replaces: a second 4B package must never be unpacked at NYU while one runs.
- **A copy of reocr_pair run from outside `data_prep/` gets no confirmed ditto marks**
  (`ditto_decisions.json` is read beside the module). `line_assembly.py page` handles this.
- **`align` is a global best path over a tile**: a change that reorders two layer lines can move a
  pairing several lines away (#32 (e)). Read diffs a few lines either side.
- **"Read by the layer" is exact-box membership in the margin pull** (`page_dump`); changing that
  test also removes old pulls (one rejected #32 (a) version did, moving 25-30% of line starts).
- **Model-only lines have invented boxes** (`synth_line`, at the tile's edge): never use them as
  evidence of where the print is (Brooklyn 1905's banner ad put a margin at x 30).
- **Do not lower the joiner's indent threshold** to catch a missed join (PIPELINE #28).
- Respect the disk (`df -h .`; Finder's figure counts purgeable space). Pilot work dirs are ~270 MB
  each; `data/lighton_pilot_{pre_rowmerge,rowmerge}_*` from 2026-10-23 can go once you have your own
  baselines.
- Other sessions run in this repo (`city-directory-extraction-*`). Stop only processes you
  started, by PID; never `pkill` a pattern another session's job could match.
- `facts --against HEAD` is the before only if the sidecars were committed before the import.

## 6. When you finish a fix

Commit it with its numbers (gold both layers, target, collateral), mark it in PIPELINE #30/#32 as
the #32 (a) entry is marked, and say in BOOKSCAN_HANDOFF's top update whether it is in the code D's
import will use.
