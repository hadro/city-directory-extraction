# Line assembly: PIPELINE #30 and #32 (b)–(e)

**Written 2026-10-24 at commit 8129853; revised the same day after every example was checked against
its page image.** For an agent picking up this work cold. [PIPELINE.md](PIPELINE.md) #30 and #32
hold the original findings. **Where they disagree with §2 here, §2 is right:** two of the five
diagnoses were wrong, and the checks found a sixth defect that does more damage than any of them.
§3 is the plan, in order. Read [BOOKSCAN_HANDOFF.md](BOOKSCAN_HANDOFF.md)'s top update for the wider
picture.

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

**Why timing matters.** A fix to line assembly reaches the corpus only through an import (or, for
the survey's joiner, a re-derive). D's import is the next one, so **a fix committed before D returns
costs nothing**. A fix that should also reach the damaged tier means re-importing or re-deriving it
and, for its records, a new 4B run (~103 GPU-h), so batch such fixes. Never restage
`data/volumes_books_damaged_v2` in place (§6).

## 2. What the pages show

Each example was traced on its page image (crops at the dump's own coordinates:
`https://iiif.archive.org/iiif/<id>$<leaf>/<x>,<y>,<w>,<h>/full/0/default.jpg`) and through
`page_rows` / `page_dump` at HEAD (b9b2e8c).

### (c) Unread words land in the wrong place, and that glues entries, not only drops them

Trow 1909 vol 1 leaf 95, column 0 (tile x 173-789; page `char_w` 14.8, median word height 18). The
page prints `Aabv Edwd N manager h 516 W 162d` / `Aachen & Munich Fire Ins Co 84 William` / (run-over)
`R 902, 95 William & 871 Brook av` / `Aal Siegfried clerk h 2 W 118th`. The survey has:

    KEPT          [75, 2960, 711, 3001]  Aabv Edwd N manager h 516 W 162d Aachen & Munich
    DROP banner   (-64, 3003, 751, 3022) Fire Ins Co S4 William R 902, 95 William & 871 Brook av
    DROP banner   (-43, 3024, 752, 3164) Aal Siegfried clerk h 2 W 118th CAREFUL

Two people in one record and two entries lost, from two causes:

1. **`respell`'s character width.** ABBYY 8's word boxes on this page abut (`h` 464-495, `2` 495-526,
   `W` 526-566): each carries the space after it, so a one-letter word measures ~31 px a character
   against the page's 14.8, and `respell` takes the median over all of a line's words. Words the
   layer never read are laid out leftwards from the first read word at that width: `Aal Siegfried`
   from `clerk` (x 391) to x = -43, `Aabv Edwd` from `N` (x 375) to x = 75, left of the tile. A start
   placed left of the margin makes the NEXT entry look indented: `Aachen & Munich` (x 211) sat 7.5
   line heights right of `Aabv`, and the indent rule glued it on. "0.05% of lines dropped as
   `banner`" undercounts what this costs.
2. **`split` gives unread words to the wrong printed line.** The layer read only `Aachen & J unloh`
   of the second printed line (x 211-430). `split` cuts the model's entry by text similarity alone,
   and unread words cost less ratio on the longer piece, so `Fire Ins Co S4 William` went to the
   run-over, whose first read word (`R`, x 281) already sits at the run-over indent with no room
   before it. Laid out leftwards from there it starts at -64, cannot join its entry (a negative
   indent), and is dropped. No width cap moves this line: its width (15.0) was not inflated.

### (d) A side-banner glyph inside an entry, not a hyphen tail

Brooklyn 1905 p1 leaf 563. The earlier account (`bers` a layer piece of its own, half a pixel off the
same-row rule) is wrong. The layer's pieces in reading order are `Dornheim Chas lithographer 4 New
Cham-` (x 511-1205), **`U)` (x 338-366)**, `bers Mhtn h 155 Cornelia` (x 720-1045; `bers Mhtn` is ONE
layer word). `U)` is the rotated `S.` of a vertical side banner. Its top falls between the entry's
two printed lines, so `align`'s best run for the model line takes all three pieces, and `split`,
which must give every piece a word, gives `U)` the word `bers`. The joiner compares a line only with
the entry above it, and `bers` (x 338-401) does not overlap `Mhtn ...` horizontally, so the run-over
is left alone and `bers` is dropped as `short`.

A "short piece joins its neighbour" rule would happen to work here, because `respell` drops the
unread `U)`, but it would also merge real short pieces (initials, `St`, ditto stubs, E marks). A
"short alphabetic suffix after a hyphen" rule never fires: the piece's layer text is `U)`.

### (e) Mostly a broken layer; the tilt part is small

Longworth 1826 leaf 409. The tile angle is 0 (book scans are not deskewed), so "use the tile's
angle" changes nothing. IA's layer has NO pieces for two printed lines (`Eagle Henry, 436 Broadway`,
`Eagle John, 452 Pearl`) and garbles the rest (`Kager 6z Ton:`, `leaker,`, `i-ddv :`). The pairing was
already one line off before de9521a (`grocer 226 Greenwich` on the piece that is `Eager & Tompkins`'
printed line). So "restore Eager/Eakins" would restore output that was also wrong: do not use it as
the target.

The tilt is real but small. `»* Leonard` sits 19.5 px from its row's anchor (limit 20, grouped) and
`219 Hester luPJiynder` 27 px (limit 18, a row of its own). The joiner rejoins the latter anyway
(`cont` 1, 522 px right). It does show the rule's weak point: a piece's middle is compared with the
row's FIRST piece, so tilt accumulates across a wide line.

### (b) Tables: real, and the glue they cause is mostly the next defect

`line_assembly.py tables` at HEAD finds 6,318 of 96,378 tiles in table mode (6.6%). Brooklyn 1905 p1
is at 25.7%, c1905 at 23.8% and Trow 1903 p1-p3 at 19-21%; every other volume is at 0-7.5%. There
are 76 invented header lines (`Name, Address` 34, `Name, Occupation, Address` 20, ...). Trow 1909
vol 1 leaf 97, tile c1_h1, kept:

    " Philippa sec 51 Front h Mt Vernon N Y Abbihl Jacob H h 408 W 150th
    Chas I ice 314 W 16th & sec 137 8th av h Rutherford N J          (printed "—Chas I ...")

The first is two people in one record. The cell put both entries on one model line, so `pair_tile`
marked `Abbihl` a run-over (`cont` 1), and the joiner's margin guard, which should have refused it,
did not (next item). The second lost its ditto dash: a table cell carries no Markdown bullet, and
the layer did not see the dash either.

### NEW: the joiner's margin guard measures from a hanging ditto dash

`join_wraps` lets a line the model read as a run-over (`cont` 1) join at `MODEL_INDENT` 0.5 line
heights, on the rule that "a line at the column margin never joins on `cont` alone" (#28). But it
measures the indent from the BOX of the entry above. Trow hangs its ditto dash in the margin: on
leaf 97 the ditto line's box starts at x 746 and names at 775. So an entry at the margin sits ~1.5-1.7
line heights right of a ditto line above it, and clears 0.5.

Any false `cont` 1 under a ditto line is then glued: a two-entry table cell, a model line that ran
two entries together, or a `mark_continuations` false positive. It is not only tables. Trow 1908 p2:
`— Frank, Co signs 949 Bway R 514` + `Fechter Adolph J books 235 Bway R 53`, also `Fickeis Jacob`,
`Fickinger Emil H`, `Firemen's Ins Co of Newark`. Trow 1909 vol 1: `Ackerman's Fred. Steam Carpet
Cleaning`, `Acmy Real Estate Club`.

A census over the production dumps counted model-read lines with `cont` 1 that open `Surname Given`
and sit 0.5-3 line heights right of a ditto line above:

| volume | candidates |
|---|---|
| Trow 1909 vol 1 | 162 |
| Trow 1903 p1 | 476 |
| Trow 1908 p2 | 122 |
| Brooklyn 1905 p1 | 2 |

The census mixes glue with real run-overs, and the two separate by indent. Glue sits ~1.6-1.7 line
heights from the dash, i.e. at the name margin. Real run-overs sit ~2.4-2.7 (`Plains N Y`, `Canal &
230 Grand`, `Yonkers N Y`), about 1 line height past the name. Image-read a sample before quoting a
glue rate.

### #30, panel half: a name GATE drops the wrong rows; a VETO is the right shape

Each rule was simulated in memory: `ia_panel.build` into a scratch dir with `ia_panel.align`
replaced, diffed by `gold_row`. No exact row changed in any version.

**A gate** (the line must match the gold's surname and, where printed, given name, at token ratio
>= 0.75; overlong lines admitted when their head matches), on the LightOn pilot with IA's words:
- matched 2,066 -> 2,043, exact 1,730 -> 1,730 (83.7 -> 84.7%: the rise is the smaller denominator
  only).
- It rejected the right person's line wherever the name was garbled (`Werts Albert` for Alberts
  Albert, `Ageliar` for Agelger, `Alwens` for Alwang) or lost (`Henry, lawyer, 9 Court, h. 90
  Johnson` for Hagner Henry). Those are the rows the panel exists to charge the pipeline for.
- An unchecked two-line pair then took each rejected line plus the next entry.

**A veto** rejects only on evidence of a different person: a given name that cannot be the gold's,
or an unrelated surname where the line has not merely lost it. Pairs are checked on their first
line, and the long-line window applies to single lines only. Results:

| panel | matched | exact |
|---|---|---|
| pilot, IA's words | 2,066 -> 2,056 | unchanged |
| pilot, fresh tesseract | 2,064 -> 2,051 | unchanged |
| IA panel, rebuilt from today's `data/survey_ocr` lines (+1 added) | 2,363 -> 2,335 | unchanged |

The IA panel's 2,363 is not `data/iapanel`'s 2,206: the lines have changed since that was built.

What the veto got right:
- It removed every wrong person of the McElroy kind: boyd `Crawford Miss Susie L` for John W and
  `McElroy Bernard E`; lain1876 `Seabury Samuel` for William; lain `Ammons Fred'k` for Peter,
  `Kaplon Solomon` for Jimenez Tony, `Agen H'y` for Ageliar Romia; ogden `Fordham Charles` for
  Austin; hearne `Rogers Lewis` for F; smith1855 `Farrel Brid` for Francis.
- It re-matched McElroy and Polk 1917 row 27 to the gold's own (glued) line.

Its remaining errors, about 40 rows across the three panels and most of them on the IA panel, are
four fixable shapes:
1. A speck or false mark before the right surname is read as a ditto line (`-Altz`, `_ Holstrom`,
   `"Simmons`, `- McCormick`, ~13 rows). A line whose mark is followed by the gold's own surname is
   the gold's line.
2. Surname disagreement alone (`Wm Albert` for Albin Albert, `F Mary` for Faagg Mary). Never veto
   when the given name agrees.
3. Tokens glued by punctuation or split by OCR (`Hiigh,mercht.`, `Ki chard`). Compare letters-only
   tokens, a given name over one or two of them.
4. The abbreviation test accepted `Harris C.` for Harrison Richard because `c` occurs inside
   `richard`. An abbreviation keeps its first letter. Two- or three-letter names with different
   first letters (`Vi'm`/Wm, `KUO`/GEO) are OCR noise, not evidence.

No rule rescues a name the OCR destroyed outright (`Paley Gears` for Fargue John, `UNG yn` for
Simonson, fragments that open on a middle initial). Expect a short, listed residue of these on the
IA panel. Side finding for GROUND_TRUTH_HANDOFF: lain gold rows 75, 90 and 194 each hold two entries
in one `raw_line`.

### #30, joiner half: confirmed as described

boyd1890 leaf 105 (pilot, IA's words). `McElroy John A ...` (line 50) is at x 561. Next comes `LLIOTT,
Plumbing, Steam and Gas Fitt` (line 51, a model-read start, `cont` 0) at x 891: 2.1 line heights
below and 6.1 in (median word height 54 px), beside the layer-only drop cap `ELLIOTT`, 140 px tall.
The indent rule joins it.

## 3. The plan

In this order. Steps 1-6 can all land before D returns. Each step's "before" is the previous step's
"after". Each needs §4's checks plus what is listed under it.

**Progress** (newest last; numbers in each commit and in PIPELINE #30/#32):
- Step 0 DONE (a52dd99): self-tests pass, drift check clean, `glue` and `panel` added.
- Step 1 DONE (e6084c4): the veto, with two rules beyond refinements 1-4 (PIPELINE #30). **Diff later steps
  against `data/iapanel_lighton_post30_{ia,tess}`** (pilot: IA's words 2,059 rows, 1,730 exact;
  fresh tesseract 2,056, 1,715) and `data/iapanel_post30` (production lines, 2,352 rows, 1,394
  exact), not the `_pull_` panels. `eval/ia_panel.py build --ocr DIR --panel-dir DIR` builds a
  panel elsewhere than `data/iapanel`.
- Step 2 DONE (08911f5), CHANGED from the plan (PIPELINE #32 (f)): measured from the text only for a line
  that opens like a name. The plan's version cut 18 real run-overs in 40 sampled: §2's "real
  run-overs sit ~1 line height past the name" holds on 1903 p1 but not on the respelled parts,
  where they print at the name's x. New tools: `line_assembly.py joins REV VOL` (the joins a
  joiner change removes, on identical input, with crop URLs), `proxy --dir --kind lines`, and
  `lighton_pilot.py --survey-only DUMPS` (re-runs the survey alone, for steps 2 and 6).
- Step 3 DONE (8100ced), CHANGED (PIPELINE #32 (c)): `split`'s room rule takes the layer's unread print
  before line t+1 first, then the end of line t (leaf 245 showed the plan's order wrong); the
  `respell` width cap was measured and rejected (51,834 starts moved, a wash downstream), replaced
  by a clamp to the tile edge for non-ditto leading runs that fit. Measuring a dump change needs a
  survey re-derive and an image-read sample of the derived differences, not only `moved`: the
  scratch scripts used are described in the step's commit.
- Step 4 DONE (fece5b8) as planned (PIPELINE #32 (d)); it rejoins far more than hyphen tails on Brooklyn
  1905. `moved` overcounts a change that reorders rows (it compares by line index): read the
  derived differences instead. New: `fragments`, `moved --base DIR`, `tables --damage` (step 5b).
- Step 5a DONE (4274724), minimal (PIPELINE #32 (b)): the heading row is left out of untable's text but kept
  in its margin and packing counts, so no other line on any tile changes. 5b measured (numbers in
  #32 (b)). 5c is Torch-only and waits for D's table rate; the recommendation is there.
- Step 6 DONE (22590c8) (PIPELINE #30, joiner half): the cap is the p99 of the volume's model run-over JOIN
  indents (not all `cont` 1 lines: their tail is layout noise, p99 9-34 line heights), and only
  over 1,000 or more of them. The pilot cannot test it (no pilot volume has that many).
- Step 7 NOT DONE, by its own rule: the count does not say so (PIPELINE #32 (e); `samerow`).
- Steps 2-6 together, pilot against the post-#30 baselines: no exact row lost or gained on either
  layer; IA's words 1 row re-read (better), fresh tesseract 3 (inexact both ways). **The baselines
  for further work are now `data/iapanel_lighton_s6_{ia,tess}`** (work dirs
  `data/lighton_pilot_s6_{ia,tess}`, at 22590c8). Step 8: every step is in D's import, and C had
  not been sent, so its 39 volumes were re-imported (629b27f) and restaged as
  `data/volumes_books_damaged_v3`, since replaced by v4 with #32 (g) (657e9c4; BOOKSCAN_HANDOFF
  §2): no second 4B run is needed for them. The
  re-import flipped 1876BPL's wrap calibration on a knife edge (`survey_harvest.WRAP_PINS`); the
  rule wants hysteresis before the next import (PIPELINE #32, open).
- After step 8, PIPELINE #32 (g) (2026-10-25): on a dash page, a dash tesseract glued to the word is a
  ditto even where the word fits the surname chain (Trow 1909 vol 1 +788 dittos, 1903 p1 +167). C
  was held for it and re-imported again. **Baselines now `data/iapanel_lighton_s8_{ia,tess}`**
  (work dirs `data/lighton_pilot_s8_{ia,tess}`), which also carry the 13 trimmed lain gold rows:
  IA's words 2,064 rows, 1,738 exact; fresh tesseract 2,061, 1,723.
- (g) widened 2026-10-26 (a standalone dash, and the given name of the ditto line above), after C's
  re-import showed the first version gluing lost-dash lines under newly dittoed ones; pilot
  `data/iapanel_lighton_s9_{ia,tess}` identical to s8. Open there: the joiner's lost-dash glue under
  dash-led entries, which neither the indent nor the text's shape separates from run-overs.

Where each step lands:

| step | lands in | applied by |
|---|---|---|
| 1 | eval only | — |
| 2, 6 | the survey | a re-derive |
| 3, 4, 5a | the import | a re-import |
| 5c | Torch | a re-read job |

**0. Baselines and tools.**
- Run `reocr_pair.py --self-test`, `ia_volume_to_jsonl.py`'s self-test and `ia_panel.py --self-test`.
- Drift check: `lighton_pilot.py --skip-derive --work data/lighton_pilot_pull_{ia,tess} --panel-dir
  data/iapanel_lighton_head_{ia,tess} --diff-against data/iapanel_lighton_pull_{ia,tess}` must
  change no row.
- Add two subcommands to `eval/line_assembly.py`:
  - `glue VOL ...`: the census above, with each candidate's indent from the dash and from the name.
  - `panel A B`: two panel dirs diffed by `gold_row` into dropped / added / re-matched / exact
    lost, in counts.
- Record each target page's output (`page HEAD ...`).

**1. #30, the panel matcher** (`eval/volume_run_report.align`; eval only).
- The veto with refinements 1-4. The long-line window (head ratio >= 0.85 over the gold's length)
  for single lines only. Pairs vetoed on their first line.
- Self-test cases from §2's rows:
  - McElroy/Bernard and `Harris C.` vetoed;
  - `Werts Albert`, `-Altz` and `Henry, lawyer` kept;
  - a ditto-led gold row on ratio alone;
  - a start + run-over pair still matched.
- **Accept** when all three of these hold on all three panels:
  - no exact row changes;
  - every wrong-person row in §2 is unmatched or re-matched to the gold's own line;
  - the right-person rows still dropped are listed, and every one is a destroyed name.
  Report matched and exact counts, not rates.
- Then rebuild the post-#30 baselines, IA panel included, into NEW dirs, never `data/iapanel` or
  `results/ia_panel_manifest.json` in place. Every later step diffs against these.
- The 4B's existing panel predictions still line up with unchanged rows. A row whose line changed
  needs a Torch run to score.

**2. The margin guard, measured from the text** (`ia_volume_to_jsonl.join_wraps` + `sweep`; survey).
- For a line that would join on `cont` alone, measure its indent from where the text of the entry
  above begins: the x of its first word that is not a ditto mark (`DITTO_SHAPE`), passed per line
  from `sweep`, which has the words.
- Only where `cont` exists (re-OCR'd leaves). The indent rule, and every IA-only volume, is
  unchanged. Real run-overs under a ditto line sit ~1 line height past the name and still clear 0.5.
- **Verify:**
  - Re-derive into scratch, as `lighton_pilot.derive` does (`survey_harvest.OUT = DIR`, then
    `derive(ident, holdout)`): Trow 1909 vol 1, 1907 vol 3, 1908 p2, 1903 p1, Brooklyn 1905 p1, and
    a non-Trow control (e.g. 1876BPL; check on its images whether it hangs its dash).
  - Count joins removed per volume.
  - Image-read a uniform sample of >= 30 removed joins; nearly all should be two-entry glue.
  - The `glue` census.
  - `proxy` on the two "generaldire" volumes (#32 (a)'s measure: 0.39% and 0.31% now).
  - The pilot on both layers.

**3. (c), `respell` and `split`** (`reocr_pair.py`; import).
- `respell`: lay out words the layer never read at the page's `char_w` (the line's median only where
  it is smaller), clamped to the tile's left edge (`x0` is on every row; pass it in). Words the layer
  read keep their boxes exactly.
- `split`: words the layer never read, between the last read word of printed line t and the first
  read word of line t+1, go where there is room:
  - first the end of line t, up to the column edge at `char_w`;
  - then before line t+1's first read word, where the room is that word's x less the line's start.
    A run-over whose first read word sits at the indent has none.
  This is a constraint on `split`'s cut choice from each part's word extents. Where every word is
  read it changes nothing.
- **Verify:**
  - Leaf 95: `Aabv` at the margin and `Aachen` not glued to it; `Fire Ins Co S4 William` on the first
    printed line and `R 902 ...` joined to it; `Aal Siegfried` at the margin and kept.
  - Lines left of their tile, before/after, on Trow 1909 vol 1 (107 off the page) and Longworth 1826
    (11).
  - `moved` on two or three volumes.
  - The pilot on both layers.

**4. (d), a stray piece inside an entry** (`reocr_pair.split` + `pair_tile`; import).
- Let `split` give an inner piece no words when its layer text carries none of the entry and a
  neighbour's layer text carries what it would get (`bers` is in `bers Mhtn`). The hyphen step then
  looks across it.
- Emit that piece as an unpaired layer row AFTER the entry's rows, so the entry's printed lines stay
  adjacent for the joiner.
- **Verify:**
  - Leaf 563: `... Chambers Mhtn h 155 Cornelia` comes out as one entry.
  - Short model fragments (<= 5 characters, `cont` 1) whose next line is a run-over they do not
    overlap, counted before/after on Brooklyn 1905 p1 and Trow 1909 vol 1.
  - `moved`.
  - The pilot on both layers.

**5. (b), tables.**
- **5a (import).** Drop a `<th>` row whose cells are all generic column words (`HEADER_WORD` in
  `line_assembly.py`); keep `<th>` rows that are entries (see `html_rows`' note).
  - `untable` lives in `hpc/lightonocr_tiles.py`, which the Torch runner also uses, but the import
    re-flattens every LightOn answer from `.raw.txt`, so only the import reads the change.
  - Verify: `tables` 76 -> 0 header lines with no entry lost; the pilot (10 of 138 bench tiles are
    tables).
- **5b (after step 2).** Extend `tables` to count, per volume:
  - cells holding two entries (a model line covering >= 2 printed lines whose second sits at the
    name margin);
  - dashes the layer saw that the cell dropped;
  - ", " added by the field-split join in a volume that prints no comma after a name.
- **5c (Torch, batched).** No cell-splitting or punctuation-guessing on the Mac.
  - If 5b shows material damage, re-read the table-mode tiles with table output banned in decoding
    (e.g. vLLM `bad_words` on `|` and `<table`).
  - Run it first on the bench's 10 table tiles, scored against gold. Then run this tier's 6,318 and
    D's table tiles in ONE job, keeping the first answers and a tile-to-override manifest.
  - Cost: ~1 GPU-h of decoding at vLLM's 0.58 s a tile, plus engine start-up.
  - Decide when D's table rate is known.

**6. #30, joiner half: a cap for model-read starts** (`sweep` / `join_wraps`; survey).
- Carry `sources` beside `cont` (a new `WordDump.page_sources`; today only `cont` reaches the
  joiner), dropped wherever `cont` is dropped (a column split, a length mismatch).
- A line the model read as a start (source `model`, `cont` 0) joins on the indent alone only below an
  upper bound from the volume's own model-confirmed run-overs, e.g. the p99 of `cont` 1 joins'
  indents. Measure it in a pre-pass, or store it in the sidecar as `wrap_calibration` is. McElroy's
  banner is 6.1 line heights in.
- No test on the line's text, and the lower threshold is untouched (#28).
- **Verify:** joins removed per volume (should be few), an image-read sample of them, the pilot on
  both layers.

**7. (e), only if a count says so** (`reocr_pair.boxed_lines`; import).
- First count, per volume, pieces left out of a row they overlap vertically by >= half the shorter
  height, that begin right of a row piece's end within a few characters.
- If the count is material: compare the FACING words of horizontally neighbouring pieces (the left
  piece's last word, the right piece's first) instead of a piece's middle with the row's first
  piece. That cancels tilt without fitting a slope. Borderline cases (within ~20% of the limit) keep
  top-to-bottom order.
- **Accept** only if Longworth 1826's split pairs stay near 41 (#27's `samerow`), neither pilot
  loses an exact row, and `moved` is small. Otherwise record the count and leave it.

**8. Shipping.**
- Each step gets its own commit with its numbers (gold on both layers, target, collateral). Mark it
  in PIPELINE #30/#32, and say in BOOKSCAN_HANDOFF's top update whether it is in D's import.
- The damaged tier (package C) stays as sent. When C's results are back, decide once whether the
  batched fixes justify a re-derive (steps 2 and 6) or a re-import (3, 4, 5a) of those 39 volumes,
  into a NEW staging directory, plus another ~103 GPU-h 4B run.
- #31 step 4 (a banded `align`) stays deferred. It is ~5x on the import's hot spot but CAN change
  pairings, so it needs the same verification as any behaviour change.

**Open, not in this plan:** false ditto marks before printed surnames on panel lines (`"Ackermann
Albert Y.` on the LightOn pilot's lain; `-Altz`, `_Ackerno` on IA's). At assembly, a ditto takes the
surname above. Count them and find their source (`reocr_pair.dittos`, or the survey's ditto
normalisation) before deciding anything.

## 4. How to show a change is safe

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
   `data/iapanel_lighton_pull_{ia,tess}` are the panels at 071e202, which are still the current
   import code: pooled exact **83.7%** (IA's words, 2,066 rows) and **83.1%** (fresh tesseract, 2,064
   rows). After step 1, diff against the post-#30 baselines instead: the matcher itself changes the
   rows. The rule so far: **no exact row lost** on either layer. IA's words is what production book
   scans use; fresh tesseract is what failed-OCR volumes use (`better_layer`).
2. **Target, on real volumes.** Re-dump to scratch (`reocr_pair.py dump ... --out-dir DIR`, which
   writes no sidecar) or re-import (`reocr_books.py import --ids ...`, which rewrites dumps and
   sidecars: commit sidecars first so `facts --against HEAD` is the before). Measure the defect's own
   count. For a survey-side change, re-derive into scratch instead (step 2).
3. **Collateral.** `python3 eval/line_assembly.py moved DIR <vol>` on two or three volumes that do not
   have the defect: lines whose start moved. Hundreds in a volume, for a change aimed at one shape,
   is suspicious; tens of thousands is a bug (a wider #32 (a) moved a quarter of a Trow part's lines).
4. **A refactor meant to change nothing** must be byte-identical: `line_assembly.py same` on an
   IA-layer volume (e.g. `longworthsameric1798newy`) and a tesseract-layer one
   (`trowsgeneraldire19073trow`), and `reocr_pair.py --self-test`.
5. **A change to the joiner** (steps 2 and 6): image-read a uniform sample of the joins it REMOVES,
   not of the ones it keeps. The deep-indent gate's story in `join_wraps`' docstring is the reason.
6. **A change to the panel** (step 1): count rows, not only rates. Dropping inexact rows raises the
   exact rate with nothing fixed.

Add a self-test case for each fix (`reocr_pair._self_test` has the house style: real lines from
real pages).

## 5. The tool

`eval/line_assembly.py` (read-only): `page REV VOL LEAF [PATTERN ...]` runs one page through the
import's own path at a git revision and in the working tree side by side; `proxy` is #32 (a)'s
glued-entry measure; `moved`, `same`, `tables` as above. Step 0 adds `glue` and `panel`. Its docstring
has the details.

## 6. Traps

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
- **Check a diagnosis on the page image before fixing it.** (d)'s and (e)'s first accounts were read
  off dump output and were wrong (§2).
- **`ia_panel.build` writes each set's file path relative to the repo**: a panel dir outside the repo
  fails unless `ia_panel.REPO` is set too. It also writes `results/ia_panel_manifest.json` unless
  `ia_panel.MANIFEST` is redirected, as `eval/lighton_pilot.py` does.
- Respect the disk (`df -h .`; Finder's figure counts purgeable space; 43 GB free on 2026-10-24).
  Pilot work dirs are ~270 MB each; `data/lighton_pilot_{pre_rowmerge,rowmerge}_*` from 2026-10-23 can
  go once you have your own baselines.
- Other sessions run in this repo (`city-directory-extraction-*`). Stop only processes you
  started, by PID; never `pkill` a pattern another session's job could match.
- `facts --against HEAD` is the before only if the sidecars were committed before the import.

## 7. When you finish a fix

Commit it with its numbers (gold both layers, target, collateral), mark it in PIPELINE #30/#32 as
the #32 (a) entry is marked, and say in BOOKSCAN_HANDOFF's top update whether it is in the code D's
import will use.
