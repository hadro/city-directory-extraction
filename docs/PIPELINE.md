# Running a volume through the pipeline

**Written 2026-09-10.** End-to-end: an Internet Archive identifier in, structured person records
out. Every number here is measured on this corpus, and where a stage is *not* calibrated it says so.

Companion docs: [HANDOFF.md](HANDOFF.md) is the working record and the reason each decision is what
it is; [TAKEOVER.md](TAKEOVER.md) is the cold-start orientation; [GROUND_TRUTH_HANDOFF.md](GROUND_TRUTH_HANDOFF.md)
is the labeling contract that governs the model's output shape; [FIGURE_AUDIT.md](FIGURE_AUDIT.md)
records which published figures were re-derived and which were mis-scoped;
[PAGE_TYPE_CLASSIFIER.md](PAGE_TYPE_CLASSIFIER.md) is the plan for next-step #11, phase 0 run;
[BANNER_CORRECTION.md](BANNER_CORRECTION.md) records the 2026-09-13 `banner` fix, the regenerated
1906BPL artifact, and **which published figures are pinned to the pre-correction file**.

> **The one thing to internalize before running anything: the model never refuses.** Feed it a line
> of advertising and it returns a confidently structured fake person (`address: "entrusted to their
> care"`). Page-type detection is therefore a *correctness* problem, not a cost problem, and every
> filter below exists because of it.

---

## The stages at a glance

| # | stage | script | calibrated? | cost |
|---|---|---|---|---|
| 0 | catalog | `data_prep/ingest_collection.py` | n/a | minutes |
| 1 | **ingest** | `data_prep/ia_volume_to_jsonl.py` | text filter yes, geometry no | ~4 min/volume |
| 2 | bounds | `data_prep/detect_listing_bounds.py` | yes | ~1 s from JSONL |
| 3 | ad/front-matter cut | `data_prep/alpha_run_filter.py` | yes, but **do not `--apply`** | seconds |
| 4 | **model** | `eval/qwen_predict.py` | — | **the expensive one** |
| 5 | **copy guard, ditto resolution** | `postprocess/copy_guard.py`, `postprocess/resolve_dittos.py` | guard: panel 243 fixed / 0 broken; dittos: within-line yes, cross-line partly | seconds |
| 6 | QA | `eval/entry_rate.py`, `eval/evaluate.py`, `eval/volume_run_report.py`, `eval/ia_panel.py` | proxy / gold | seconds |

Stages 1, 4 and 5 are the pipeline. 2, 3 and 6 are instruments you read, not transforms you have to
apply.

---

## Stage 0 — Is the volume in the catalog?

`data_prep/master_directories.csv` holds 449 NYC directories (~1786–1925) across `nypl|ia|loc|iiif`.
New collections go in by link:

```bash
python3 data_prep/ingest_collection.py <collection URL>     # stages rows for review
python3 data_prep/ingest_collection.py <collection URL> --merge
```

You only need the IA identifier to run the rest. The catalog matters because it supplies
`publisher` and `year`, which become the model's context tag.

**The publisher tag is a closed set of 17 trained tokens** (`trow polk-tulsa lain polk longworth
doggett upington duncan hopehenderson smith boyd hearne rode mb mercein franks ogden`). A volume
whose true publisher is outside that set gets a fallback token, not its real name — `backfill_publisher.py`
audits this. **Measured: the tag is inert.** On hearne1852 with tags hearne/trow/spooner, the 4B
produced *one* distinct output across all three, zero rows differing. Don't spend time on it.

---

## Stage 1 — Ingest: IA hOCR → model-ready JSONL

```bash
python3 data_prep/ia_volume_to_jsonl.py --ident 1906BPL \
    --deep-indent-gate \
    --out data/1906BPL_lines.jsonl \
    --dump-dropped data/1906BPL_dropped.txt \
    --ditto-review results/ditto_review_1906BPL.tsv
```

`--deep-indent-gate` is OPT-IN and is shown here because 1906BPL is the volume it was validated
on. **Do not copy it to a new volume without reading `join_wraps` first** — the threshold is
calibrated on this book and destroys real wraps on 1856BPL.

No images downloaded, no OCR run, no GPU — IA already OCR'd 291 of the catalog's volumes and that
OCR was measured good enough to use (CER-all 0.067 excluding one dead volume).

**Never read `_djvu.txt`.** It flattens multi-column pages so several entries merge onto one text
line: CER-all **0.723** against **0.159** for the same page rebuilt from `_hocr.html` `ocr_line`
elements. Same words, 4.5× the error, purely from line segmentation.

### What it does, in order

1. **Joins wrapped entries first.** 11.0% of hOCR lines are continuations (36,417 of 329,989 with
   `--deep-indent-gate`; 12.7% of *candidates*, and 12.8% without the gate). Joining *before*
   filtering matters — a continuation like `259 Himrod` is short enough that the text filter would
   drop it, taking the address off the entry above.

   **The corpus survey (`survey_harvest.py`) adds two per-volume corrections that this CLI leaves
   off (2026-09-28).** The CLI's defaults are pinned to published 1906BPL figures.
   - **The wrap threshold is read off each volume's own indent histogram (`calibrate_indent`).**
     `INDENT_RATIO` = 3.0 fits 1906BPL, whose runovers sit at 3.9–5.2 line heights. Most of the
     corpus indents runovers by ~2.0, so **517,137 scoped lines were unjoined runovers**. A volume
     gets a lower threshold only when two things hold. First, almost no line opens with a ditto
     mark: a dropped mark indents like a runover. Second, the runover mode is sharp, with the
     trough below it under 5% of the mode. Doggett 1845, the 1860s–80s BPL and Rode qualify at
     1.5. 1906BPL, 1897BPL, Smith and Hearnes keep 3.0, and each sidecar records why
     (`harvest.filtered.wrap_calibration`).
   - **Lines tesseract read across a two-column gutter are cut (`split_merged_columns`).** A
     merged line is cut at the right column's margin, where the entry-opening words line up. A
     leaf is cut only when enough lines cut cleanly *and* the right halves read as one alphabet
     column (Fagans, Falconer, Fales…). The alphabet test is what keeps one-column books from
     being cut at their mid-page street names.

   Corpus effect: scoped lines 16,865,145 → 16,247,330, unjoined runovers 517,137 → 268,888, and
   lines on column-merged leaves 27,074 → 16,100 (Smith 1856: 2,548 → 31). A uniform sample of 50
   new joins (Doggett, 1884BPL) held 50 single entries and no two people glued together. The
   runovers that remain are in ditto volumes and noisy microfilm, where joining would glue people
   together. On Hearnes, 17 lines on 2 leaves are cut that should not be.
2. **Text filter** — page numbers, ALL-CAPS running heads, sub-8-char fragments, non-ASCII garbage.
   **Keeps 72.5% whole-volume on 1906BPL** (the 76% in the script's docstring is a 14-leaf sample;
   see [FIGURE_AUDIT.md](FIGURE_AUDIT.md)). **It is not an entry detector** and happily passes ad
   copy.
3. **Geometry filter** — drops lines >2× the page's median line height (`bigtype`) or >1.4× its
   **body line width** (`banner`). Judged against each page's own distribution, so one setting spans
   an 1786 single-column folio and a 1933 six-column Polk. `banner` normalizes by `body_width()`,
   **not** a plain median: widths are bimodal and the plain median sits inside the body cluster,
   which is the bug fixed on 2026-09-13. **Still not validated against gold** — no box-level gold
   exists.
4. **Ditto normalization** (see below), applied *at emission*, after every filter has seen the
   original text.
5. **Band marking** — `context.band` = `head` / `body` / `foot` / `null`. See below.

### Measured throughput

> ⚠️ **`data/1906BPL_lines.jsonl` WAS REGENERATED on 2026-09-13** and now holds 205,590 lines, not
> 199,012. The `banner` rule was normalizing by a plain median over a bimodal width distribution and
> was cutting real entries at about the rate it cut advertising (1,038 entry-shaped killed / 951
> non-entries caught per 300 leaves). The pre-correction artifact is preserved as
> `data/1906BPL_lines.prebanner.jsonl` + `data/1906BPL_dropped.prebanner.txt` — `data/` is
> git-ignored, and those were the only copies every published 1906BPL figure was measured against.
> **Any figure quoted elsewhere against 199,012 is still exact for the `.prebanner.` file and is now
> measuring a population the pipeline no longer produces.** Full record and the pinned-figure list:
> **[BANNER_CORRECTION.md](BANNER_CORRECTION.md)**.

| volume | leaves | hOCR lines | joins | candidates | kept |
|---|---|---|---|---|---|
| 1906BPL — **current artifact** (banner fix + `--deep-indent-gate`) | 1,240 | 329,989 | 36,417 | 293,572 | **205,590 (70.0%)** |
| 1906BPL — banner fix only, no gate | 1,240 | 329,989 | 37,196 | 292,793 | 205,103 (70.1%) |
| 1906BPL — pre-correction (`*.prebanner.*`) | 1,240 | 329,989 | 37,196 | 292,793 | 199,012 (68.0%) |
| micro_IABROOKLYN_0013 (tesseract microfilm) | ~100 | 3,676 | 216 | 3,460 | **2,899 (83.8%)** (was 2,889) |

The gate blocks 779 joins, which is why candidates rise 292,793 → 293,572 while joins fall.

Three more volumes were ingested 2026-09-13 to check the filters across publishers and eras. All
three ran **without** `--deep-indent-gate`:

| volume | publisher | leaves | hOCR lines | joins | candidates | kept |
|---|---|---|---|---|---|---|
| `1856BPL` | Smith 1856 | 635 | 77,278 | 3,007 | 74,271 | **61,439 (82.7%)** |
| `trowsgeneraldire1915trow` | Trow 1915 | 2,466 | 1,690,064 | 36,230 | 1,653,834 | **1,484,446 (89.8%)** |
| `longworthsameric1798newy` | Longworth 1798 | 186 | — | — | — | **12,002** |

**Trow 1915 is the scale reality check**: 1.48M candidate lines, ~7× 1906BPL. At the 0.38–0.6
lines/s measured below that is **weeks** of local compute, not days — it is an HPC job or nothing.

**Smith 1856 has no ditto convention at all** (`no mark cleared the gates`, `no leaf had enough
ditto lines to bound`), so it gets no `context.band` either. That is the honest answer for a volume
outside the rule, and it is also the precondition that makes `--deep-indent-gate` unsafe there.

Cache is `data/ia_cache/`, and **291 MB per volume is the Brooklyn figure, not the ceiling**.
Measured 2026-09-13: 1906BPL 291 MB, 1856BPL 63 MB, longworth1798 14 MB — but
`trowsgeneraldire1915trow` is **1.47 GB**. The Trow NYC volumes are far larger than the Brooklyn
ones, so "291 volumes ≈ 50–60 GB" is low for any sweep that includes them. **Discard the cache per
volume on a corpus sweep.**

Note also that IA's storage node sometimes **ignores a Range request and returns the whole file**
(`_range_get` handles this and caches the result). On a 1.47 GB volume a `--leaves` subset probe
therefore costs the full download once, not the 22 pages you asked for.

### Ditto normalization — on by default, and the part most worth understanding

A surname-repeat ditto is printed `"`, and ABBYY reads it as `44`. On 1906BPL **`44` is the single
most common leading token in the book — 41.5% of the 205,590 kept lines** — and the generator never
emitted it, so it is out of distribution for every adapter.

It is not cosmetic. Measured n=500 paired rows, McNemar exact **p=0.0010**:

```
44 Wm elk h 86 Laf av   →  name='44 Wm elk'   occupation=''
 " Wm elk h 86 Laf av   →  name='" Wm'        occupation='clk'
```

The raw form makes the model run the `name` field too far and swallow the occupation. The trained
form closes it *and* applies the contract's OCR fix (`elk`→`clk`).

**The glyph set is derived per volume, never hard-coded**, because the same mark means different
things in different books — `« Douglas Charles` in NYU is an OCR speck on a complete entry, while
`«* Peter ironwkr` in 1906BPL is a ditto. A mark is admitted only if its **share of leading tokens**
clears a floor (5% digits / 0.5% punctuation) **and** ≥70% of its lines are followed by a
name-shaped token. On 1906BPL that admits exactly `44`, `“`, `"`, `**` and sends 40 candidates to
the review queue.

⚠️ **Calibrate on the whole volume.** The gates are shares, so a `--leaves` subset calibrates on its
own sample — `"` is 1.25% whole-volume (admitted) but 0.42% on a 21-leaf slice (not). Subset runs
are for inspection; only whole-volume runs ship.

`--ditto-marks "'*,*'"` promotes a mark a human confirmed from the review queue. It bypasses the
share floor only — it **cannot** override the follower ratio, so a heading mark stays refused.

### Band marking — where the listing actually sits on the leaf

**Advertising in a dense directory is sold as a strip across the head and foot of ordinary listing
pages, not by the page.** On 1906BPL, ditto-lead density is 0.7% in the top decile of the page, 45%
through the middle eight, and 0.0% in the bottom — and **94% of listing-span leaves have that shape**
(`results/leaf_band_structure_1906BPL.py`). So the body is bounded by the extent of the volume's own
ditto-lead lines, padded by **0.015 of page height** at each end.

Measured against **239 hand-labelled leaves** — 190 labelled with the guess visible, 49 blind:

| | |
|---|---|
| leaves admitting **no** non-listing line | **239/239** |
| leaves exact in both directions | 214/239 |
| listing lines marked strip (cost) | 84 |
| non-listing lines marked body (**the failure that matters**) | **0** |

Whole-volume 1906BPL: 1,158 leaves bounded, 186,470 body / 1,414 head / 1,525 foot, 9,603 lines
unbanded.

- **It marks, it never drops.** Cutting here would strand dittos exactly as `alpha_run_filter
  --apply` does. Downstream decides; `--no-band` turns the field off.
- **The extent is computed over lines that already passed the text filter, and that is the whole
  fix, not an optimization.** `44` is ABBYY's ditto mark *and* a literal street number: the
  recurring Temple Bar ad carries `44 COURT ST.`, which dragged the top edge into the advertisement
  and admitted 22 lines of ad copy on leaf 904 alone. `text_reject` already calls it `allcaps`.
- **A leaf with fewer than 20 ditto lines gets `band: null`**, not a guess. Those are the review
  queue — full-page ads, and anything the rule cannot speak to.
- **The glyph set is the volume's own admitted marks**, never hard-coded, so this inherits the
  per-volume calibration below.

⚠️ **This rule is tier-specific and silently inapplicable on thin volumes.** `micro_IABROOKLYN_0013`
(tesseract, 1836/37) has **0 of 108 leaves** with enough ditto lines — an 1836 directory prints every
surname in full, so there is no extent to bound. The run says so explicitly rather than emitting
nothing. Note the irony: `entry_rate` measures fabrication at **30.1% whole-volume on that thin tier
against a stratified 5.6% on the dense one** (stage 6) — a 5.4× gap — so this solves page-type for
the tier that was already far the better of the two. See
[PAGE_TYPE_CLASSIFIER.md](PAGE_TYPE_CLASSIFIER.md).

### Gotchas

- **The output file stays empty until the sweep ends.** Kept lines are buffered so the frequency
  gate can see the whole volume. Watch the `... n/1240 leaves` lines on stderr instead.
- **`context` gains an optional `raw_line_original`** on normalized lines only (+7.6 MB on 1906BPL).
- **Read `--dump-dropped` before trusting the run.** Selecting on what a filter kept and never
  looking at what it cut is the trap this project has paid for three times.
- Boxes are in the hOCR's own pixel space, not any JPEG you later download. `context.page_size` is
  stored so a `#xywh=` can be scaled. An unscaled box is a plausible-looking lie.

---

## Stage 2 — Where does the listing actually start?

```bash
python3 data_prep/detect_listing_bounds.py --ident 1906BPL --from-jsonl data/1906BPL_lines.jsonl
```

`--ident` is required even with `--from-jsonl`. Reading the JSONL is ~1 s and no network; reading
the hOCR directly is slower but independent. **On a thin volume, check both** — on micro13 they
disagree about the start leaf (14 vs 18), because dropping a handful of lines moves the modal share.

1906BPL: bounds 9–1215, **1,041 leaves inside the letter blocks vs 1,207 in the plain range — 166
leaves are ad runs *between* letter blocks (13%)**.

It reports **leaves, not printed pages**, deliberately: `page_offset` is filled for 9% of IA rows
and drifts within a volume (1884BPL: +54 at p.402 → +82 at p.984), so converting would invent
precision. Ambiguous edges print as `AMBIGUOUS` for a human rather than being silently resolved.

---

## Stage 3 — Cutting ads and front matter

```bash
python3 data_prep/alpha_run_filter.py --lines data/1906BPL_lines.jsonl \
    --dump-cut data/1906BPL_alphacut.txt        # report only; READ THE DUMP
```

Cuts by **alphabetical order, not typography** — a listing runs A→Z, so a block that breaks the run
is front matter or advertising. Cut is 7.5% (1906BPL) / 9.8% (micro13).

**Report-only by default, and leave it that way.** Two independent reasons:

1. Measured against model output on micro13: `--apply` does not pay.
2. **`--apply` structurally breaks ditto expansion** — a ditto whose parent surname was cut has
   nothing to point at. If it runs upstream of stage 5 it must mark, not drop.

**Three things that look like they should work and do not** (do not re-derive these):

- A confidence floor. Ad copy is full of business names, so an ad page carries its own dominant
  letter — leaf 130 is prose at 0.96. A 0.70 floor collapsed the cut to 0.2%.
- Voter share. Genuine listing leaf 200 carries sort keys on 17% of lines; ad leaf 26 on 28%.
- Column detection from hOCR line boxes. Wrapped-line indents make left edges multi-modal; the
  filter inverted and dropped 64% of a page including clean entries.

**A ditto line must abstain from the alphabetical vote.** Getting this wrong inverts the filter —
dittoed entries otherwise vote their *given* name, which cut 1,724 good lines. `first_letter`'s
anchored rule handles it, and also abstains on `H'y`/`Wm`, the abbreviated given names that appear
where OCR dropped the ditto entirely.

---

## Stage 4 — The model run

```bash
PYTORCH_ENABLE_MPS_FALLBACK=1 PYTHONPATH=<tf5-dir> <python> eval/qwen_predict.py \
    --base-model Qwen/Qwen3.5-2B \
    --model ~/Downloads/scale-runs/adapters/2b-100k \
    --gold data/1906BPL_lines.jsonl \
    --target yaml --batch-size 16 \
    --out data/preds_2b-100k_1906BPL.txt
```

**`--target` must match what the adapter was trained with** (`yaml` for all current adapters).

### The corpus run, staged (2026-10-05)

```bash
python3 hpc/prep_volumes.py --corpus --plan                  # sizes from sidecar counts, no writes
python3 hpc/prep_volumes.py --corpus --chunk 20000 --out data/volumes_corpus
tar -czf cde-volumes-corpus.tar.gz -s ',^data/volumes_corpus,data/volumes,' data/volumes_corpus
#   on Torch, in $PROJECT: tar xzf it, source hpc/env.sh, then run each printed submit line
python3 postprocess/copy_guard.py --volumes data/volumes_corpus --run 4b-100k
python3 postprocess/assemble_records.py --root data/volumes_corpus --run 4b-100k+guard
```

`--corpus` stages the decided run set from the sidecars: 153 volumes, **14,871,643 lines** with
duplicates and flagged pages excluded, ~348 H200-hours at 11.88 rows/s. That is 1,569 array
tasks at 10k lines or 835 at 20k, about 28 minutes each on an H200. The array limit is unknown,
so the submit lines come in batches of `--max-array` (default 1000), and `35_volumes.sbatch` adds
each batch's `TASK_OFFSET` to the array index. `staging.json` records what was staged and from
which code.

**Tiers** (`data_prep/run_tiers.py` → `data_prep/run_tiers.json`; stage one with
`--corpus --tier first`). The H200 goes where the output will be best, and nothing is spent on
lines a re-OCR will replace. A tier is set per volume from its OCR family, and a measured
exception overrides it:

| tier | volumes | lines | H200-hours | what |
|---|---:|---:|---:|---|
| `first` | 60 | 5,518,133 | ~129 | ABBYY-9/11 and older Columbia/NYPL book scans, plus Boyd (61/74 IA lines identical to gold after #26) |
| `abbyy8-clean` | 18 | 5,136,257 | ~120 | ABBYY-8 whose numbers are as clean as a book scan's: Trow 1910–1917, 1922/23, three Longworths |
| `abbyy8-damaged` | 36 | 4,009,143 | ~94 | ABBYY-8 with damaged digits: Trow 1903–1909, Brooklyn 1905–1912 parts |
| `defer` | 39 | 208,110 | ~5 | BPL microfilm (54% of a book scan's lines, #27), plus Brooklyn 1912 p3 (typical page 0.04 entry-shaped, 186 pages failed OCR): re-OCR first |

The ABBYY-8 split is a gold-free measure (`results/number_damage.json`). ABBYY-8 reads 6
(Brooklyn's font) or 9 (Trow's) as 0, and a leading 0 is impossible in a house number or street
ordinal, so its rate measures a volume's digit damage. The book scans' median is 0.08%, with their
worst tenth above 0.43%. A volume at or below 0.5% counts as clean. Trow 1910–1917 sit at about
0.01%, and the Trow 1903–1909 parts at 1.6–4.9%, with Trow 1907 p2 the worst; that is the trow1907
panel volume, which scored 7.4 row EM on IA's lines in run 2. The real-OCR panel tests the split:
Polk 1917 is in the clean group, trow1907 in the damaged one. A first corpus run of
`--tier first,abbyy8-clean` is 78 volumes, 10.65M lines, ~249 H200-hours.

`assemble_records.py` reports a volume whose predictions are missing, short or **stale** as
incomplete, skips it and exits 1, instead of stopping the whole run. Stale means made from
another staging of the chunk, caught by the chunk SHA-1 the cluster writes beside each
prediction. Checked on Boyd 1890's restaged panel chunk against run 2's predictions.

### Which adapter

| adapter | EM normalized | note |
|---|---|---|
| `4b-100k` | **82.0** | release candidate — **but see below** |
| `2b-100k` | 81.1 | most of the gain at half the parameters |
| v6 (0.8B) | 78.6 | superseded |

⚠️ **The 4B does not fit a 16 GB Mac. 83.2 min/tag against the 2B's 97 s on the same 52 rows — 51×
slower, not the ~2× the parameter count predicts.** At that rate 1906BPL would take ~7 months.
**The 2B is the only locally runnable adapter; the 4B at any real scale needs the HPC.**

The failure was invisible: a 9 GB MPS model reports 0.03 GB RSS because Metal buffers never enter
the resident set. **Throughput against a known baseline is the only honest instrument on that box —
check rows/s within the first ten minutes of any MPS run.**

### Environment

`transformers` must be **≥5.x** for the `qwen3_5` architecture. Neither the system python (4.36)
nor `directory-pipeline`'s venv (4.57) knows it. Without touching a shared env:

```bash
VP=~/github/directory-pipeline/.venv/bin/python
$VP -m pip install --target <dir> --no-deps peft accelerate transformers tokenizers \
    huggingface_hub safetensors
PYTORCH_ENABLE_MPS_FALLBACK=1 PYTHONPATH=<dir> $VP eval/qwen_predict.py …
```

`Qwen/Qwen3.5-4B` is **not** cached locally — a 24 KB stub, no safetensors. 0.8B (1.6 G) and 2B
(4.3 G) are real.

### Cost

**0.38–0.6 lines/s** for the 2B on an M2 Air 16 GB. So 2,889 lines ≈ 2 h and **199,012 lines ≈ 6
days**. A rented GPU is hours. Do not attempt a whole volume locally.

On NYU Torch the **4B** does **11.88 rows/s on an H200 at batch 64** and **7.3 on an L40S at batch
32**, measured on sustained 10k-line chunks (`hpc/35_volumes.sbatch`, 2026-09-28). That puts 1906BPL
at ~4.5 H200-hours and the whole corpus's 16.7M residential lines at ~390.

---

## Stage 5 — Post-processing: the copy guard, then resolve the dittos

### The copy guard: put back the printed word

```bash
python3 postprocess/copy_guard.py --volumes data/volumes --run 4b-100k   # -> *.preds_4b-100k+guard.txt
python3 postprocess/copy_guard.py --lines <lines.jsonl> --preds <preds.txt> --out <guarded.txt>
```

The model is trained to repair OCR: the generator corrupts 35% of training inputs and keeps the
targets clean. So it also rewrites printed words that were read correctly but are unfamiliar:
`Degraw → Delaware`, `Mhtn → Mthn`, `Bancker → Banker`, `Carll → Carroll`, `rd → dr`, **house
numbers transposed** (`h 623 Grand → h 263 Grand`, on the *clean-text* panel). It also adds
given names that were never printed (Mary, Sarah). The guard aligns every field to its own line
and keeps a change only if it is one of:
- spacing or punctuation only;
- made only of classical OCR misreadings (`elk → clk`, `pi → pl`);
- a piece of a glued word (`boardingh → h`);
- a rare printed word moved to one the volume prints often, within 2 characters (`cartmaa → cartman`).

Anything else gets the printed word back. A name word with no near match in the line is dropped.
The model's predictions are never overwritten; the guarded file sits beside them.

| test | fields fixed | broken |
|---|---|---|
| 21-volume panel, clean text, 4B | 243 | **0** |
| same, 2B | 246 | **0** |
| gold pages read through IA OCR (Mercein/Hearnes/Smith) | 5 | **0** |
| NYU externals (500 rows), before its last rule was added | 39 | 3 (then fixed) |
| **real-OCR panel, run 2, first contact (pre-registered)** | **142** | **76: FAILED** |
| real-OCR panel after the long-s rules (tuned on it) | 143 | 6 |
| clean panel + NYU after those rules (`--check-panel 4b-100k`) | 279 | **0** |

Whole-row EM on the clean panel rises everywhere or stays level: Lain 65.9 → 77.4, Polk 1933 SI
69.6 → 80.4, trow1884 80.1 → 86.5, NYU 56.0 → 61.8. It does not catch `Harman → Harmon` (477
in 1906BPL): a/o is a genuine OCR misreading, and nothing in the book tells the two cases apart.

**Its first test on gold it had never seen failed the bar set before the run.** The bar was to
lower no set's row EM and break at most one field for every ten it fixes. On run 2's real-OCR
panel it fixed 142 and broke 76, and lowered 4 sets: Franks 1786 28.6 → 1.8, its 1876 reprint
37.5 → 8.9, Duncan 1794 50.0 → 44.8, Ogden 1839 36.7 → 31.7. The clean panel could not have
shown this. The breaks are all real-OCR patterns the guard did not know:
- **the long s:** `Water-ftreet`, `William-ltreet`, `Wall-itreet`, `Jofeph`, `Auguflus`, `Han.
  Jquare`, which the model rightly writes as s;
- **punctuation that is a misread letter:** `Genera)`, `10!`;
- **residence markers glued on:** `N. Y.h`, `hl701`;
- **alignment slips.**
With those rules added, the panel reads 143 fixed / 6 broken, and the clean panel plus NYU 279 /
0. **The real-OCR panel is no longer held out, so those figures are tuned.** A clean held-out
test of the guard now needs new gold (next step #10).

### Resolve the dittos

The model emits ditto marks **verbatim by contract** (conventions 11/12), and that contract governs
the generator, all 21 gold volumes and `evaluate.py` at once — resolving inside the model would
mean relabelling the panel. So resolution is a downstream step, and a large one: **67.3% of
1906BPL's lines are ditto-lead**, so this decides `name` for two thirds of the volume.

```bash
python3 postprocess/resolve_dittos.py --preds data/preds_2b-100k_1906BPL.txt   # within-line
python3 postprocess/resolve_dittos.py --lines data/1906BPL_lines.jsonl         # cross-line
python3 postprocess/resolve_dittos.py --lines data/1906BPL_lines.jsonl --inventory
```

**Three scopes, and only one is line-local:**

| scope | example | antecedent | needs reading order? |
|---|---|---|---|
| within-line, `address`→`home_address` | `h do`, `h910 do` | the same record's `address` | **no** |
| cross-line, name prefix | `" Jos`, `44 John C` | previous entry's surname | yes |
| cross-line, address slots (Duncan) | `71 do. do.` | previous line's address | yes — **unimplemented** |

**Within-line is deterministic**: 17 hits, zero false positives. The published denominator of
9,830 was a glob over `data/*_eval.jsonl`, which has since grown to 11,119 rows and now includes
1,000 non-gold ingest stubs — name the panel before re-quoting it ([FIGURE_AUDIT.md](FIGURE_AUDIT.md)).

**Cross-line is not.** It finds an antecedent for every ditto, but two independent checks each
dispute ~20k of 133,902, overlapping only 28% — **31,500 (23.5%) are disputed by at least one**.
Those go to a review queue; nothing silently picks a winner. Use hOCR **emission order**, not
reconstructed columns: the surname sequence is 93.6% alphabetically non-decreasing within a leaf.

It **does not detect non-entries** and shouldn't — on an advertisement leaf it will happily resolve
nonsense, because page type is stage 1/3's problem.

---

## Stage 6 — Did it work?

```bash
python3 eval/entry_rate.py --lines <lines.jsonl> --preds <preds.txt> --by-leaf
python3 eval/evaluate.py --gold <gold.jsonl> --pred <preds.txt> --target yaml --report-normalized
```

**`entry_rate.py` — a fabrication / page-type proxy, and NOTHING more.** Hand-validated at 97.5%
against 40 read lines (the obvious surname-shape proxy scores 67.5%).

### 1906BPL is 5.6% not-real, not 10.4% — and it is concentrated

Stratified, 150 lines per band, seed 20260913, 2b-100k, pre-registered before the sample was drawn
([`ab_band_fabrication_1906BPL_PREREGISTRATION.md`](../results/ab_band_fabrication_1906BPL_PREREGISTRATION.md)
· [result](../results/ab_band_fabrication_1906BPL.py)):

| band | n | not-real | rate | 95% CI | volume share |
|---|---|---|---|---|---|
| **body** | 150 | 1 | **0.7%** | 0.1–3.7% | 93.70% |
| head | 150 | 114 | **76.0%** | 68.6–82.1% | 0.71% |
| foot | 150 | 83 | **55.3%** | 47.3–63.1% | 0.77% |
| unbanded | 150 | 126 | **84.0%** | 77.3–89.0% | 4.83% |

**Strip vs body is 98×.** The stratified volume estimate is **5.6%**. Cutting strip and unbanded
lines would take fabrication to **0.63%** — an 88% reduction — at a cost of **1.28% of kept lines**
that are real. That trade is measured, not assumed. It is still not licence to cut at ingest: a
ditto whose parent surname was cut has nothing to point at, the same reason `alpha_run_filter
--apply` stays off.

**Unbanded is the worst stratum and the largest one — but read it before calling it junk.** Its
misses include `Abraham & Straus, dry goods` and `Federal Audit Co., public accountants`, which are
genuine *business-directory* entries scored not-real only because `is_entry` wants an address-shaped
string. That is real directory content of a different kind, not fabricated people.

⚠️ **The old 10.4% was inflated twice over.** The same `body` band measures 4.7% on top-of-page
lines against 0.7% uniform — a 6.7× positional effect *within one band*.

### The tier comparison, on the same footing at last

**Neither number PIPELINE.md was comparing was a whole-volume rate.** The microfilm **20.7%** is the
rate on **kept leaves only, n=2,227** — it excludes exactly the leaves `alpha_run_filter` judged
worst (CUT 66.9%, ABSTAIN 58.2%). HANDOFF recorded the whole-volume figure at the time and it is
**30.1%**, reproduced by re-scoring all 2,889 predictions.

| | 1836 tesseract microfilm | 1906 ABBYY dense |
|---|---|---|
| not-real, whole volume | **30.1%** (all 2,889 lines) | **5.6%** (stratified) |

**A 5.4× gap**, not the 2× long published. The thin tier is far worse than anyone claimed, and the
dense tier far better. Two separately-scoped numbers had been sitting next to each other in a table.

The original worry behind next-step #4 — that the microfilm figure predated ditto normalization —
**dissolves**: no mark clears the gates on that volume (`ditto-lead normalization: no mark cleared
the gates (nothing changed)`), so normalization cannot have moved it, and `raw_line` is untouched.
The existing 2,889 predictions remain valid.

⚠️ **Why the 10.4% is a top-of-page number.**
`data/1906BPL_sample500_eval.jsonl` is 25 leaves × **the first 20 kept lines of each** (verified:
sampled positions are exactly 0–19 on leaves holding ~166 kept lines), so it reads only the top
~12% of every page — which is where the ad strip lives. The band mix proves it: 36 `head` rows
observed against **3.6 expected** under a uniform draw, and **zero** `foot` or unbanded rows against
3.8 and 24.1 expected. Head lines are 83.3% not-real, so the figure is biased **upward** by
construction, and the "clean tier is 2× better" comparison inherits the bias unless the microfilm
number was drawn the same way.

Re-weighting the measured per-band rates by the volume's actual band mix gives **~5.0%** across the
94.4% of lines those rates cover ([`results/band_vs_fabrication_1906BPL.py`](../results/band_vs_fabrication_1906BPL.py)).
**Cite 10.4% only as "top-of-page", and prefer a uniform band-stratified re-measurement before
citing anything volume-wide.**

**What that same analysis establishes, and it is the reason `context.band` exists:**

| band | n | not-real | rate |
|---|---|---|---|
| head | 36 | 30 | **83.3%** |
| body | 464 | 22 | **4.7%** |

A **17.7× separation**. The band was validated against 239 hand-labelled leaves as *geometry*; this
is the first evidence it lands on the lines the model actually turns into fake people. The per-band
rates are conditional on band, so the sampling bias changes the mix, not these rates.

⚠️ **It cannot see field-boundary quality.** `is_entry` is `name` non-empty AND an address-shaped
string, so `name='44 Wm elk'` with an empty occupation scores as a perfect entry. Proved by paired
re-measurement: 299 of 500 inputs changed, 3 records recovered an occupation, and **zero rows
changed classification**. Cite it for fabrication; never as record quality.

**`evaluate.py` — only where gold exists.** Judge model changes on **`--report-normalized`**, and
publish verbatim. This project spent three cycles learning that a verbatim gain which vanishes
under normalization is typography, not extraction.

### The first whole-volume 4B run: five volumes, 310,932 lines (2026-09-28)

```bash
python3 eval/volume_run_report.py --out results/volume_run_4b-100k.json   # ~25 s, no labels
```

`4b-100k` over the survey's listing-scoped lines for Hearnes 1852, Mercein 1820, Smith 1856,
Doggett 1845 and 1906BPL (`hpc/35_volumes.sbatch`, NYU Torch). All 310,932 records came back and
aligned 1:1. **H200 at batch 64 does 11.88 rows/s, and an L40S at batch 32 does 7.3**, so
the full 16.7M residential lines are **~390 H200 GPU-hours**, not the ~1,700 the plan assumed from a
load-dominated 2.7. The checks were stated before the run. Per-volume detail, examples and the
2B-vs-4B diffs are in [`results/volume_run_4b-100k.json`](../results/volume_run_4b-100k.json) and
[`results/volume_run_1906BPL_2b_vs_4b.tsv`](../results/volume_run_1906BPL_2b_vs_4b.tsv).

**The model is not the binding constraint on old and microfilm volumes; the OCR is.** The panel
pages sit inside three of these volumes, so the same gold rows can be scored twice. Once as the
panel does it, with the model reading the gold's hand-corrected text. Once end to end, with the
model reading IA's OCR line:

| volume | gold rows found in IA OCR | end-to-end row EM | panel row EM, same rows | on identical text |
|---|---|---|---|---|
| mercein1820 | 60/60 | **63.3** | 88.3 | 91.7 = 91.7 (n=36) |
| hearne1852 (microfilm) | 49/52 | **38.8** | 79.6 | 85.7 = 85.7 (n=21) |
| smith1856 (microfilm) | **58/229** | **12.1** | — (held out of the panel) | 58.3 (n=12) |

Where IA's line matches the gold text exactly, the two runs are identical, which also proves NYU
ran the right adapter. Every point of the gap is input. The misses are OCR digit errors (`58
Rutgers` read as `68`), neighbouring-column bleed (`147 Prospect f [ington`), and on Smith, lines
missing entirely: leaf 168 kept 62 of ~108 printed lines. **Panel scores measure the model on
clean text. They are not what a whole-volume run delivers on this tier.**

**Doggett 1845's printed count is met almost exactly, once runovers are removed.** The title page
claims 61,333 names. Named records: 63,632, or 1.038 (inside the 0.9–1.05 band, near its top).
Named records on lines at the column margin: **61,480, or 1.002**. The excess is 2,104
**runover lines turned into people** ('Bleecker', '191 Duane', 'Twenty-fifth'). The 121 unnamed
margin lines are ad prose that the model rightly left empty, so there is no sign of lost entries.
The roles come from box geometry alone (`layout_roles`): starts at 0–15‰ of page width, runovers at
30–45‰, with a clean trough between.

**`join_wraps` joined almost none of these volumes' runovers.** It needs an indent of
≥ `INDENT_RATIO` = 3.0 median line heights, calibrated on 1906BPL. Measured runover indents:

| volume | runover indent, p10–p50–p90 (line heights) | runovers below 3.0 |
|---|---|---|
| Doggett 1845 | 2.00 – 2.08 – 2.17 | 2,814 of 2,814 |
| Smith 1856 | 1.02 – 1.59 – 1.92 | 1,834 of 1,844 |
| 1906BPL | 0.65 – 1.92 – 4.96 | 1,742 of 2,150 |

So 2,815 Doggett entries lost their tail (often the `h.` home address) and each tail became a
fabricated record. That is the train/serve mismatch `join_wraps`' own docstring warns about.
Doggett's band is so tight that a per-volume threshold would separate it cleanly (next step 22).

**Microfilm tesseract merges columns.** On 58 of Smith's 414 leaves (2,548 lines), most lines hold
a left-column entry *and* a right-column entry (`Evans John, brassmoulder, 252 First F. George A.
Lawton, n. Broadway`). The model returns one record per line, so **roughly 2,200 right-column
entries are lost** and some left-column records absorb right-column text. The lines come straight
from the hOCR's own `ocr_line`, so this is IA's segmentation, not ours. The word dump has the boxes
to split them (next step 23).

**The model overwrites real words with familiar ones.** No gold is needed to see it: the check is
field words absent from their own line, traced back to the line word they replaced, and referred
to the volume's own vocabulary (`substitutions`). The top pairs, read by hand:

| volume | printed (and printed how often) | model wrote | records |
|---|---|---|---|
| 1906BPL | `Mhtn` (Manhattan; 14,281) | `Mthn` / `Mtn` | **13,707** |
| 1906BPL | `rd` (road) | `dr` | 2,205 |
| 1906BPL | `Kosc'ko` · `Himrod` · `Degraw` · `Cornelia` · `Harman` · `Maujer` · `Meserole` | `Kosciello` · `Hiramod` · `Delaware` · `Cornelius` · `Harmon` · `Mauer` · `Mersole` | 858 · 669 · 613 · 512 · 477 · 354 · 244 |
| Mercein 1820 | `Bancker` · `Harman` | `Banker` · `Hanman` | 343 · 108 |
| Doggett 1845 | `Goerck` · `Cornelia` · `Laight` | `George` · `Cornelius` · `Liight`/`Light` | 148 · 79 · 56 |
| Smith 1856 | `Meserole` · `Degraw` | `Moseley` · `Delaware` | 61 · 12 |

Each of these is a real street, correctly OCR'd and printed hundreds of times in the book. The
**2B does the same** (Classon, Degraw, Harman, Himrod, `rd` on the shared 500 lines). `Mhtn` is
4B-only: of the 41 shared lines that print it, the 4B dropped it on 40 and the 2B kept it on 37 of
those. None of `Mhtn`, `Mthn`, `Delaware` or `Cornelia` occurs in the 4B's 100k training rows (the
first 100k of `data/synth_train_250k.jsonl`); `Cornelius` occurs 1,713 times. So this is a pull
toward familiar words, not copied training text. **The panel cannot see this.** Two pages per volume rarely hold a given street, and 1906BPL
is not on the panel. The same check also finds genuine repairs (`elk → clk` 14,900, `pi → pl`,
`cartmaa → cartman`), so its `replaces_common_word` class is an upper bound, to be read and not
cited raw. In 1906BPL the hand-read corruptions in the top 30 pairs come to ~20,500 field words.
Most of them are `Mthn`.

**It also invents given names.** Mercein prints 1,391 widows as `Ackerman widow, 47 Elizabeth`,
with no given name. Gold keeps the surname alone (`Duggan widow of Thomas` → `Duggan`). The 4B
adds one on **212 (15%): Mary 104, Sarah 87**. Smaller cases: `Hol lith , 26 N. Y.` → `Holith
Thaddeus`, `Court, n. ueer` → `Court Anne`. Name words with no near match in their line: 0.16%
(1906BPL) to 1.86% (Mercein).

**1906BPL, 2B against 4B on the 500 shared lines:** all 500 found by leaf+bbox, 497 with identical
input. Row agreement is 68.6%. Of 123 address disagreements, 36 are `Mhtn → Mthn` alone, and most
of the rest fall on junk lines. Both models call 448 of the 500 lines entry-shaped.

**1906BPL, against the 140 hand entry labels:** the survey's section scoping removed 31 of the
labelled OCR-garbage lines before the model saw them. It also removed **one real entry** (leaf 8,
`Mancke Flora wid 450- Van Buren`). Leaf 8 is a whole **"Names too Late for Classification"**
page ahead of the listing (~80 entries), which the section inventory filed as front matter:
`page_title`'s title-case rule wants ≤4 words, all capitalised, and this title has five words, two
of them lowercase (next step 25). Of the labelled
non-entries that remained, the model named **55 of 65**, and 17 of those are entry-shaped.
Advertising in head and foot bands is still where fabricated people come from, as the band study
found.

**Entry rate by section:** a second alphabet runs as cleanly as the first. Smith's Eastern
District names 97.0% of lines against the Western's 95.0%. Smith's low 95.5% overall is its
column-merged leaves and runovers, not the district. `late_names` sections are the weakest
everywhere (Mercein 77.5%, Doggett 87.9%): short sections full of headings and notes.

### A panel on the model's real input (`eval/ia_panel.py`, 2026-09-28)

```bash
python3 eval/ia_panel.py build                 # data/iapanel/iapanel_<set>.jsonl + results/ia_panel_manifest.json
python3 eval/ia_panel.py score --run 4b-100k   # after the Torch run predicts on those files
```

The 21-volume panel feeds the model hand-corrected text. This pairs the same gold records with the
line the pipeline actually produces from IA's OCR, with no new labelling. The survey already
verified each gold page's leaf, and the builder checks ±3 leaves where that placement was weak. **14
sets in their own volumes; 1,608 of 1,902 gold rows (84.5%) reach the model as a line at all.**
With the 7 twin sets below, 21 sets and 2,310 of 2,618 rows. The unmatched rows are
loss before the model. Most sets deliver 98–100%. The losses are in the microfilm:

| set | gold rows delivered | why not more |
|---|---|---|
| smith1856 | 140/229 | leaf 168: tesseract kept 62 of ~108 printed lines. Leaf 391 was 13/121 before the column split, 95/121 after |
| smith1855 | 57/185 | the same microfilm tier |
| hopehenderson1856 | 7/60 | IA's OCR of the gold page (leaf 205) is 13 lines, 167 characters of noise |

So on the thin tier, a large part of the gold never reaches the model at any quality. Scoring the
delivered rows needs 4B predictions on them. They are staged with the second Torch run
(`data/volumes/iapanel_*`). Every row carries `eval_holdout: gold`.

**Much of that microfilm ceiling is a choice of scan, not the OCR engine.** A sibling session
matched every gold set against every harvested volume (`data_prep/survey_twins.py`,
`results/survey_twins_gold.json`). Seven gold sets have a **twin**: the same edition in another
scan. Built as their own panel sets (`<set>__<twin>`), on the same gold rows:

| gold | microfilm copy delivers | book-scan twin delivers (identical text) |
|---|---|---|
| smith1856 | 140/229 | **229/229** (185), 1857BPL |
| smith1855 | 57/185 | **185/185** (153), 1856BPL (the 1855–56 edition: pair editions by the printed "year ending") |
| hearne1852 | 49/52 | **52/52** (35), hearnesbrooklync1852unse |

The other twins are ogden1839 (micro_IABROOKLYN_0016), franks1786 (both Durst reprints) and
polk1917, whose gold is NYPL-sourced, in Trow 1917. **The full-corpus run should read the
book scan wherever an edition has one.** The twin pass is the list of which editions do.

**Twins were a holdout leak, now closed.** A twin's gold pages sit under other leaf numbers and
nothing in the gold's image path names it, so they were emitted as ordinary untagged lines.
`survey_harvest.GOLD_TWINS` (keyed by gold set) now locates each twin's gold pages volume-wide,
ranked by token coverage, since the thresholded score ties on common words. It tags the pages
gold and their neighbours adjacent, and re-derives. All seven twins sit at match 0.83–1.0.
`survey_harvest.py --relocate-holdout` re-applies the map. The text ranker cannot place a
partial-book twin or sampled gold: 1906BPL_sample500 against the three geor scans, each holding
half the book. Those take their leaves from a page-structure map
(`results/survey_twins_leafmap_1906BPL.json`, `survey_twins.py leafmap`), with share ≥ 0.8 and
consistent neighbours. Two garbled pages are interpolated linearly between mapped neighbours.
Every sample page is tagged in each scan that holds its half.

⚠️ **Page tags do not cover neighbouring editions.** Doggett 1845 and 1847 reprint 22–27% of the
doggett1846 gold lines verbatim, Trow 1905/06 about 10–12% of trow1907's, Lain 1875 9.7% of
lain1876's. If a training set is ever drawn from harvested lines, the guard has to work at the
line level: drop any line whose normalised text (lower case, non-alphanumerics to spaces)
equals a gold line. Training today is synthetic, so nothing leaks yet. **The guard exists:
`data_prep/gold_line_filter.py`** (2026-09-28). It matches all 10,421 distinct gold lines,
NYPL-sourced sets included, and `--report` counts them in any set of line files. Doggett 1847's
harvested lines, for instance, hold 185 gold lines: 168 of the NYU set's, 10 of doggett1846's
and 8 of doggetts1850's. No page tag reaches any of them.

### Run 2 (2026-09-29): repaired lines, book-scan twins, and the real-OCR panel scored

```bash
python3 eval/volume_run_report.py --out results/volume_run2_4b-100k.json
python3 postprocess/copy_guard.py --volumes data/volumes --run 4b-100k
python3 eval/ia_panel.py score --run 4b-100k --out results/ia_panel_run2.json
```

63 Torch tasks on L40S; 378,296 records. Every prediction carries the SHA-1 of the chunk it was
made from, and all 63 match. Run 1 stays in `data/volumes_run1`. The checks were stated before
the run:

| check | result |
|---|---|
| Doggett 1845 named records per printed name, bar 0.98–1.02 | **1.004** (61,566), from 1.038. **Pass** |
| its named records at the column margin, within 0.5% of run 1 | 61,489 vs 61,480. **Pass**: no entry lost to a join |
| copy guard on unseen gold | **Fail**: 142 fixed / 76 broken, 4 sets lowered (stage 5) |
| Smith 1856 gold pages end to end | 140 of 229 rows delivered (58 in run 1); row EM 15.7, guarded 19.3 (12.1 in run 1) |
| microfilm vs book scan, same gold | **the book scan, decisively** (below) |

**Microfilm against book scan**, whole-row EM (guarded) on the gold rows both copies deliver:

| edition | microfilm copy | book-scan twin | rows delivered, microfilm / book |
|---|---|---|---|
| Smith 1855–56 | 10.5 | **52.6** (1856BPL) | 57 / 185 of 185 |
| Smith 1856–57 | 19.3 | **47.9** (1857BPL) | 140 / 229 of 229 |
| Hearnes 1852–53 | 38.8 | **67.3** (hearnesbrooklync1852unse) | 49 / 52 of 52 |

**The full-corpus run should read the book scan wherever an edition has one**: the sibling
session's `editions` array in `results/survey_twins_pairs.json`. On the same gold pages, the
book scan gives about 4× as many exactly-right records for Smith 1856–57 (115 vs 27), about 15×
for Smith 1855–56 (90 vs 6), and about 1.8× for Hearnes (34 vs 19).

**What the OCR costs.** Over the 17 real-OCR panel sets that also have clean-text predictions
(1,699 gold rows): row EM **47.4** on IA's line (52.1 guarded) against **73.7** on the gold's
hand-corrected text (80.6). That is 26–28 points of whole-record accuracy, and it counts only the
rows the OCR delivers. The worst gaps have causes the pipeline could still address:
- trow1907 is 7.4 against 77.9. Its ABBYY-8 OCR mangles digits (`h 95 7th` → `h OS 7th`,
  `144 W 98th` → `III w 08th`).
- boyd1890 is 24.3 against 90.5. The OCR reads the residence marker `h` as `li`, and side-banner
  noise (`£jjgr`, `■^S2_`) opens lines and lands in the name (next step 26).
- The Trow 1917 twin of polk1917 is 8.3 against 63.9. Its ditto `"` is read `ii` and never
  normalized (next step 18).

---

## What is NOT in the pipeline yet

- **No whole-volume gold**, so volume-scale field accuracy is unmeasured. The 21-volume panel is
  sampled pages; `entry_rate` is a proxy with a known blind spot. The panel also feeds the model
  hand-corrected text: on the gold pages inside Mercein, Hearnes and Smith, end-to-end row EM on
  IA's OCR is 63 / 39 / 12 against the panel's 88 / 80 / — (stage 6, whole-volume run).
- **No records assembly / export.** Predictions land in a `.txt` and stop. There is no CSV/IIIF
  writer downstream of stage 5.
- **No page-type classifier.** Stages 1 and 3 cut by shape and order; neither reads the page.

---

# Next steps

Roughly ordered by value per unit of effort. Each says what it would settle, not just what it is.

> **The numbers are stable identifiers, not reading order.** `PAGE_TYPE_CLASSIFIER.md` cites #3, #6
> and #11 by number, so items added later take the next free number and sit in whichever effort
> section they belong to. Do not renumber.

## Cheap and clearly worth doing

**1. Work the ditto review queue.** `results/ditto_review_1906BPL.tsv` — 40 candidates with count,
share, name-follower ratio and a sample line. The strong ones are obvious on sight: `'*` (316 lines,
99% name-followed), `*'` (279, 98%), `4‘` (133, 99%), `”` (91, 92%). Promoting them via
`--ditto-marks` recovers **~800 lines** the conservative gate gave up. Per volume, and record which
volume it was decided for.

> **Trow 1915 is the bigger prize and the candidates are already identified.**
> `results/ditto_review_trow1915.tsv`: `.1` (10,633 lines, 0.72% share, **98%** name-followed) and
> `,1` (3,502, 0.24%, **99%**) both miss the 5% *digit* gate purely for containing a digit.
> `--ditto-marks .1,,1` admits them plus `"` and recovers **21,289 lines**. Eyeball the samples
> first — this is a human review call, which is the whole point of the queue.
> Queues also exist now for `1856BPL` (nothing worth promoting; that volume has no ditto
> convention) and `longworth1798`.

> **Trow 1915's punctuation and digit forms decided (2026-10-04), by hadro, on the page images.**
> ⚠️ That was the small part. The same day, **letter-shaped readings of the ditto (`ii` `n` `it`
> `i` `ti`) turned up on 1.05M run-set lines** in six ABBYY-8 volumes (Trow 1915 465k, 1917
> 443k, the two Brooklyn 1910 halves 112k, Trow 1922/23 34k). DITTO_SHAPE admits only
> punctuation and digits, so neither the gate nor the review queue ever saw them. A confirmed
> mark may now be letters (`ditto_lead_candidates`; never on counts alone, since `n` is also
> "near"). `results/ditto_review_letters.html` put the six volumes' undecided marks, grouped by
> mark, before hadro: 36 marks on 1.21M lines.
>
> **Decided the same day: 33 yes, 3 no.** Rejected: `h` (the residence marker opening a wrapped
> line, `h Newark N J`), `&`, and `4` (the OCR's `&`). Re-derived, the six volumes' scoped lines
> led by the ditto rose by **1,208,634**:
>
> | volume | ditto-led lines before | after | share of the volume after |
> |---|---:|---:|---:|
> | Trow 1915 | 170,512 | 641,596 | 61% |
> | Trow 1917 | 170,185 | 673,585 | 60% |
> | Brooklyn 1910, two halves | 6,704 | 126,330 | 58–62% |
> | Trow 1922/23, two parts | 449,449 | 563,973 | 47–53% |
>
> Line counts are unchanged, and `h`/`&`/`4` lines are untouched. **Checked on gold, no GPU:** on
> the Polk 1917 page inside Trow 1917 (leaf 688), the gold's 60 ditto-led rows read the ditto
> in IA's line **1 time before, 57 after**. The 3 misses are variants under the page's 500-line
> floor (`li`, `i.`, `i,`); those marks hold ~15.7k lines across the six volumes, still undecided.
> One conversion looked false and is not: the gold row `n Dora Mrs h115 Washn pl` prints `"` on
> the page, so the gold had a transcription slip (corrected 2026-10-04 on hadro's word; see
> GROUND_TRUTH_HANDOFF.md, "Corrections to gold after export"). The real-OCR panel
> score for that twin (8.3 row EM, against 63.9 on clean text) needs a Torch run to re-measure.
>
> **The tails, decided 2026-10-05.** These are the six volumes' marks under the 500-line floor
> (`results/ditto_review_letters_tail.html`, 44 marks) and 1906BPL's queue
> (`results/ditto_review_1906BPL.html`, 8 marks).
> - Rejected as genuine text: `r` (the rooms marker), `of`, `in`, `317` (the directory office
>   in banner ads), `5`, `25`, `30`, `50`, `120`. Also `6` (the OCR's `&`) and `0`.
> - Recorded as **ambiguous**, so not admitted and not asked again:
>   - `li`: sometimes the ditto, sometimes `h` opening a wrapped line;
>   - `'`;
>   - `!`: often cut-off text.
> - Everything else confirmed.
> - The earlier rulings on `&` and `h` now apply to all six volumes.
>
> 1906BPL is re-derived (ditto-led lines 134,124 → 136,103). Its `*` and `1` stay out, though
> confirmed: a capitalised word follows them only 42% and 20% of the time volume-wide, under the
> 0.70 floor no verdict overrides (the review page had measured listing pages only; it now uses
> the gate's own ratio). **The six ABBYY-8 volumes take their tail verdicts at the post-panel
> re-derive**, with `fix_digit_s`, so panel run 3's inputs stay what it measures.
>
> Found while reviewing (hadro): **some late Trow pages have their left edge cut off**, so the
> leftmost column's first letters are lost (1922/23 p2 leaf 653 prints Stahlberg as `tanlberg`).
> Pages with 15+ lines touching the image's left edge: 334 in 1922/23 p1, 136 in p2, 300 in
> 1917 (~66k lines); Brooklyn 1910 has none. Only p2's loss is confirmed by image.
>
> The TSV's one OCR'd line per
> mark could not show the printed glyph, so `data_prep/ditto_review_page.py` puts ten crops per
> mark, each with the line above it, on a page (`results/ditto_review_<id>.html`). On the scoped
> lines there were 16 candidates. 14 are OCR readings of the printed `"`: `.1` `1` `,1` `1.` `,.`
> `,` `.` `.,` `1,` `»` `-` `«` `■1` `•1`. Two are not dittos:
> - `&` (343 lines) is a wrapped business name or address, or the `&` of a `" &` firm entry
>   whose ditto the OCR dropped.
> - `4` (849 lines) is that same `&`, read as `4`: 9 of 10 crops print `" & Mandel (Louis L
>   Gluck, Max Mandel)`. Admitting it as a ditto would make the firm "Gluck Mandel".
>
> The verdict lives in `data_prep/ditto_decisions.json`, the per-volume record this item always
> lacked. `survey_harvest.py --rederive` passes it to the sweep as `confirmed_marks`. Scoped
> lines led by the ditto went **136,510 → 170,512 (+34,002)**, with the line count unchanged. Left
> open: the ~1,190 `&`/`4` lines that are dropped-ditto firm entries still reach the model with
> no surname to carry. Telling them from wrapped lines needs the indent, not the glyph.
>
> ⚠️ Building the page found that **Trow 1915 and 1917's IIIF images are camera frames**, two book
> pages each, while IA OCR'd each page cropped and turned upright (`scandata.xml`). So every crop
> and `#xywh=` built from their hOCR boxes pointed at the wrong place, sideways. That is 2 of 184
> volumes (`results/iiif_frames.json`), but 2.17M of the run set's 14.9M lines.
> `data_prep/iiif_frame.py` maps the boxes, and `assemble_records.py` uses it.

**2. ~~A boundary-sensitive quality proxy.~~ DONE 2026-09-28: `eval/boundary_proxy.py`.**
`entry_rate` is blind to the failure that normalization fixes, so the pipeline had no instrument
for field-boundary quality at all. The pilot's proxy (`results/ab_ditto44_1906BPL_2b100k_preds/
analyze.py`) is now reusable. It flags a line that prints an occupation word after the name, whose
record is not a business, and whose `occupation_role` came back empty. It reads chunk
directories (`--root`, one or more `--run`) or any lines/preds pair, and needs no labels.

```bash
python3 eval/boundary_proxy.py --root data/volumes_run1 --run 4b-100k --run 4b-100k+guard \
    --out results/boundary_proxy_run1.json                 # ~15 s
```

| run 1 (4b-100k) | swallowed / lines printing an occupation |
|---|---|
| 1906BPL | 613 / 121,237 (0.5%), 290 of them `elk` fused into the name (`" Jos elk` → `" Josk`) |
| Doggett 1845 · Mercein 1820 · Hearnes 1852 | 41 · 18 · 19 (0.1–0.2%), mostly ad copy |
| Smith 1856 (microfilm) | 145 / 8,324 (**1.7%**), column-merged lines (`Butler fancy goods` as a name) |

Copy-guard (`+guard`) changes none of it, as it should: it restores street words, not
occupations. Getting to a usable instrument took four fixes, each now in the docstring:
- Widow and race markers are out of the lexicon. `wid` was 84% of the first draft's flags, and
  the gold itself files `wid` in `occupation_role` on 298 rows and only in `spouse_name` on 196.
- Only whole one-word gold occupations are admitted, so `city`, `law` and `eagle` stay out.
- The name and street positions are spared, since Miller and Attorney Street are not trades there.
- The parser returns `is_business` as the string `'False'`, which is truthy.

**Use it to compare runs over the same lines.** It does not measure recall of occupations.

**3. Make `alpha_run_filter` mark rather than drop.** Removes the structural conflict with ditto
expansion and makes `--apply` safe to reconsider on its own merits.

**16. Re-run the pinned 1906BPL figures against the regenerated artifact.** `data/1906BPL_lines.jsonl`
is now 205,590 lines; the figures below it were measured on 199,012 (preserved as
`data/1906BPL_lines.prebanner.jsonl`). Nothing is retracted — each still reproduces against the
`.prebanner.` file — but `entry_rate`'s 97.5%, the implied-surname counts and the 23.5% dispute rate
now describe a population the pipeline no longer produces. **`results/ab_band_fabrication_1906BPL`
is the urgent one: its stratified draw is pre-registered and is void against a new file**, so
re-stratify and re-pre-register rather than re-running it. Full list:
[BANNER_CORRECTION.md](BANNER_CORRECTION.md). *Cheap only because the decisions are already written
down; the labelling inside #16 is not.*

**17. Guard `--deep-indent-gate` on whether the volume has a ditto convention at all.** The gate is
safe on 1906BPL (uniform sample of 30 blocked joins: 17 false merges, 13 ad/OCR fragments, zero real
wraps) and destroys real wraps on 1856BPL. The distinguishing fact is not the threshold — it is that
**Smith 1856 has no ditto convention, so a shallow indent there is always a real wrap.** Guarding on
a non-empty admitted mark set makes it safe by construction on that class of volume. ⚠️ **Not as
cheap as it looks**: marks are calibrated *after* the sweep loop on buffered lines, while joining
happens *inside* it, so this needs a pre-pass or a second pass. And it would still let the gate fire
on Trow, where it is unvalidated.

**4. ~~Re-measure `entry_rate` on the thin tier.~~ DONE 2026-09-13 — and it needed no compute.**
The two published figures were differently scoped: 20.7% was kept-leaves-only (n=2,227) and 10.4%
was a top-of-page sample. Whole-volume against stratified, the gap is **30.1% vs 5.6% = 5.4×**, not
2×. The normalization worry dissolved too: no ditto mark clears the gates on that volume, so
`raw_line` is untouched and the existing predictions stand. See stage 6.

**14. Report a median and a per-volume tail in `evaluate.py`.** It currently pools TP/FP/FN across
the whole panel and prints macro/micro F1 and whole-row EM — one number per field, no distribution.
CLOCR-C (arXiv 2408.17428) reports that pooled means hide catastrophic per-document failure:
individual documents collapsed into complete hallucination or word repetition while the mean stayed
respectable, because the distribution is heavily skewed. That is precisely this pipeline's exposure
— **the model never refuses**, and a volume whose page-type filter let ad copy through produces
confidently structured fake people rather than an obvious error. Nothing currently catches one
volume of 21 collapsing, and `entry_rate` cannot (it is a fabrication/page-type proxy, blind to
record quality). Cheap: the per-field accumulators already exist; add a per-volume breakdown, print
median alongside mean, and flag any volume more than some margin below it.

**21. ~~Guard field copying with the volume's own vocabulary.~~ DONE 2026-09-28:
`postprocess/copy_guard.py`** (stage 5). It needed no per-volume allow-list. A change is kept
when it is spacing, a classical OCR misreading, a glued-word split, or a move toward a word the
volume prints often. Test met: 1906BPL `Mhtn → Mthn` 13,431 → 163, with `elk → clk` untouched
(14,900). Clean panel 243 fields fixed, 0 broken. The residual is `Harman → Harmon`.

**22. ~~A per-volume wrap-join threshold.~~ DONE 2026-09-28: `calibrate_indent`** in
`ia_volume_to_jsonl.py`, applied by the survey harvest (stage 1). Test met at the line level:
Doggett 1845 scoped lines per printed name 1.053 → **1.006**, runover lines 2,911 → 64, start
lines 61,601 → 61,606. Corpus unjoined runovers 517,137 → 268,888; the rest are in volumes
deliberately left at 3.0. The named-record version of the test needs the next Torch run.

**25. ~~Let `page_title` read a title-case heading with lowercase small words.~~ DONE
2026-09-28**, for "names too late" only. Letting small words through for every kind read a
copyright notice ("the Southern District of New York") as a residential `district` title on 8
volumes. Narrowed, the change touches exactly 13 volumes, each gaining its "Names too Late for
Classification" page (1902–1908 BPL, the 1903–1909 Georgetown volumes), plus a title-quote change
on 2 Trows.

**26. ~~Strip side-banner noise from line starts, and read `li` as the `h` marker.~~ DONE
2026-10-05**, in `ia_volume_to_jsonl.py` (`strip_side_bands`, `fix_residence_markers`), applied by
the survey harvest; all 184 volumes re-derived. Boyd 1890's real-OCR panel rows opened with OCR
of a side banner (`£jjgr Corse Titus…`), or ended with it (`…h 161 Broadway gj|3`), and its OCR
read the residence marker `h` as `li`. It scored 24.3 row EM against 90.5 on clean text.
- **`li` → `h`**: a mid-line `li`, `Ii`, `ll`, `1i` or `lI` before a house number or `do` is the
  marker on all 31 real-OCR panel cases. Applied corpus-wide: **132,341** fixes in 72+ volumes
  (2.2% of markers; up to 17.5% in Brooklyn 1912 p3). A leading token is never touched (a
  leading `li` is a ditto in Trow 1917).
- **Side bands**: ABBYY's word boxes run edge to edge, so the scraps show by position. On one
  page they are low-confidence words with a character no entry prints, lined up at the band's
  inner edge. Three guards came from a corpus dry run that first stripped real text:
  - the band must be at least 3% of the page wide;
  - most words inside it must be scraps (1867BPL lost `Adams`, `Auld` and `Buck` without this);
  - a dash-led token is never a scrap, and the band's inner edge is held to the first column's
    text margin (Trow 1912 p2 and 1914 p2 lost ditto dashes without these).

  Final: **5,577 words on ~311 pages**, almost all Boyd's Flushing volumes and Brooklyn 1912 p3.
  Kept lines changed by +5.
- **Measured on the real-OCR panel, no GPU** (IA line identical to gold after lower-casing and
  punctuation): **boyd1890 24 → 61 of 74**, mean similarity 0.964 → 0.981. No set went down,
  and lines delivered are unchanged. Across all 21 sets 1,329 → 1,399, which includes the
  letter-ditto change: Polk 1917's copy in Trow 1917 went 3 → 34. Boyd's 13 left: 6 scraps on
  pages whose band failed the guards, 4 letter misreads (`Golden`/Colden), 3 alignment pairs.
  Row EM needs a Torch run. Run 2's panel inputs are kept in `data/iapanel_run2/`, the files its
  predictions were made on.

## Medium effort, high information

**5. Does the `44` finding generalize?** It is measured on one volume, one OCR engine, one adapter.
The paired design is cheap to repeat — pick a Polk or Trow volume with a *different* dominant ditto
glyph and re-run. **This is the single most load-bearing untested assumption in the pipeline**, since
normalization is now on by default for every volume.

> **The volume this asks for now exists and the glyphs are known (2026-09-13).**
> `trowsgeneraldire1915trow` is ingested at 1,484,446 lines with a dominant ditto family that is
> genuinely different from `44` — `11` (91,431), `,,` (14,866), `..` (13,493), `„` (9,085). The
> A/B needs no new ingest, only GPU time on a paired sample. Note the scale: run it on a sample,
> not the volume.

**18. Group ditto OCR variants before gating them.** (Run 2: Trow 1917 reads its ditto `"` as
`ii` on every ditto line. On polk1917's twin it costs most of a 64-point real-OCR gap.)
The gate is per *variant*, but a printed mark
shatters into several OCR readings and each is gated alone. On 1906BPL the dominant reading `44` is
41.5% and sails through, which is why this never surfaced; on Trow 1915 one mark scatters six ways
(`11` `,,` `..` `„` `.1` `,1`) and only four clear their floors. Summing variants that are the same
glyph would fix it — but that needs a volume where the grouping can be *checked*, not inferred, so
this is a measurement before it is a change. Found by #19.

**19. Extend the style-card reconciliation.** `data_prep/reconcile_style_profiles.py` compares each
volume's runtime-derived ditto against its style card. Its first run agreed on 1906BPL, caught the
Trow card over-generalizing an 1890s observation across [1859, 1922], falsified a claim in
`normalize_ditto_lead`'s own docstring, and surfaced #18. Two things it wants next: **cards for the
8 publishers that have a markdown card but no JSON profile** (9 of 17 are consolidated), and a
**narrowed Trow `year_range` or a 1910s Trow card**. ⚠️ If this is ever wired into anything that
*decides*, match on the **catalog** publisher, never the trained tag — `micro_IABROOKLYN_0013` is
tagged `publisher=trow` by `tag_publisher`'s out-of-vocabulary fallback and is an 1836/37 Brooklyn
volume; only a year mismatch stopped it being compared against a Trow card.

**20. Label the deep-indent gate's blocked joins.** The ~310 fabricated composites it prevents rest
on a regex proxy for "entry-shaped", which was caught missing `roofer`, `tinsmith` and `cloakmkr`
during the measurement. ~80 targeted labels over the blocked cell would convert that estimate into a
figure, and is the precondition for calibrating `DEEP_INDENT` per volume rather than shipping a
constant. The self-calibrating idea — derive it from each volume's own hyphen-break distribution —
is blocked on a real conflict: on 1906BPL a threshold below the hyphen p25 (3.91) gates almost
nothing and gives up most of the 310, so **the constant and the control group disagree about the one
volume where the gate is validated.**

**6. Attack the 23.5% cross-line dispute rate.** It is concentrated at leaf/column boundaries. The
fix is better boundary handling, not a better regex. Concretely: use the bbox x-coordinate to detect
a column break *within* a leaf and reset the carry there, then re-measure the dispute rate.

> **Look at surname block headers first.** A shared surname is printed once as an ALL-CAPS header
> and dittoed beneath, and **100% of them are dropped at ingest** — 123/156 as `short` (under 8
> chars), 33/156 as `allcaps`, ~1,255 per volume
> ([`results/surname_headers_dropped_1906BPL.py`](../results/surname_headers_dropped_1906BPL.py)).
> `resolve_dittos.py` reads the kept-line JSONL, so it never sees one; at a block boundary the
> nearest preceding kept line belongs to the *previous* surname, so the carry has a confidently
> wrong antecedent rather than no antecedent.
>
> **Measured 2026-09-13, and the answer is: this is not why.**
> ([`results/header_orphan_dispute_share_1906BPL.py`](../results/header_orphan_dispute_share_1906BPL.py))
>
> | | n | disputed | rate |
> |---|---|---|---|
> | ditto right after a dropped header | 1,392 | 807 | **58.0%** |
> | every other ditto | 132,750 | 30,757 | 23.2% |
>
> The mechanism is real — **2.5× the dispute rate** — but those rows are 1.0% of dittos and carry
> **2.6% of all disputes**. Repairing every one moves the headline from **23.5% to 22.9%**. A fix
> justified as "this is why the carry disputes 23.5%" would be justified wrongly; the column-break
> reset above is still where that number has to come from.
>
> Worth fixing on *different* grounds: 1,392 rows get a wrong surname more than half the time.
> Detection needs no new idea — ALL-CAPS alphabetic followed by a ditto-lead line is the follower
> test the glyph gate already uses. And 58.0% is a **floor**: a header-orphaned row can be silently
> wrong without being flagged.

> **And the unmarked given-name entry, which is the same wound from the other side.** Sometimes the
> mark is simply absent — printer or ABBYY — and the entry begins at the given name: `Geo C bookkpr
> h 1.18 McDonough` sits in the same block, on the same page, as `" Geo C electrician h 118
> McDonough`. Measured on 1906BPL
> ([`results/implied_surname_lines_1906BPL.py`](../results/implied_surname_lines_1906BPL.py)):
> **5,491 such lines, 87.6% of which `surname_token()` accepts as a new surname**, poisoning the
> carry for **8,017** ditto lines downstream — **12,830 lines, 6.45% of the volume, with a wrong
> surname**, worst single case 137 consecutive lines. Alphabetical position cannot find these:
> entries inside a block are sorted by *given* name, so `Jas`/`John`/`Jos` under a `J` surname vote
> for the leaf's own modal letter. `first_letter` already abstains on `Wm` and `H'y`; it cannot
> abstain on `Jas`, `Geo`, `Thos`, `Chas`, `Edw'd` from shape alone — **the rule needs a
> vocabulary, and the volume supplies one**: a ditto line's second token is a given name by
> construction, and there are 134,142 of them. Score each token by
> `n(given position) / (n(given position) + n(leading position))`; ≥0.90 yields 595 types. The
> 0.50–0.90 band is exactly the names that are genuinely both (`Charlotte`, `Lewis`, `Lawrence`,
> `Morgan`), which is the reason to trust the ends. **5,491 is a floor** — the test declines
> `Isaac` (0.88) and `Lewis` (0.89), both real here.
>
> **Validated against the panel gold, and it is mostly a negative result**
> ([`results/implied_surname_validation.py`](../results/implied_surname_validation.py)). Three
> things to carry: (a) the detector **must be gated** on the volume using implied surnames at all —
> applied blind it throws **242 false positives**, gated it throws **1**, and the panel is bimodal
> (0.0% vs 58.8–97.9%) so the threshold is not delicate; (b) **recall is not measurable** from the
> gold we hold and no recall figure should be quoted — the panel holds **6** clean instances, all
> trow1913, and `1906BPL_sample500_eval.jsonl` cannot help because **0 of its 500 rows carry a
> name**; (c) the production gate **used to miss both Trow volumes** — their dash is glued
> (`-Adolph`), so raw ditto-lead read 0.0% against 58.8%/97.9% gold-implied. **Fixed by #9 on
> 2026-09-12**: `classify_glued_marks` identifies the mark per volume and the gate now agrees with
> gold on every panel volume (trow1907 0.0%→60.3%, trow1913 0.0%→93.5%). (a) and (b) stand.

**7. Feed the model the resolved surname.** Currently dittos are resolved *after* the model, so the
model sees `" Wm` and emits `" Wm`. What if the input said `Ackerman Wm`? That is a different and
possibly larger version of the `44` result — the same "give the model in-distribution input"
mechanism, applied to the 67% of lines that are dittos. Testable with the same paired design and no
gold. **Careful:** a wrong antecedent would inject a wrong surname into the record, so this needs
the dispute rate down first (item 6).

**8. ~~Implement the Duncan address slot grammar.~~ DONE 2026-09-28:
`resolve_dittos.resolve_address_run`.** `71 do. do.` is two independent slots. Each address
resolves against the previous line's *resolved* address, because a street type carries down a
chain: `71 Dey-street.`, `27 Ann do.` → `27 Ann-street`, `11 Rector do.` → `11 Rector-street`.
On duncan1794's 58 gold addresses:
- 13 carry no ditto;
- 39 inherit a type;
- 4 inherit number + street (`30 do.`);
- 1 inherits the whole address (`do.` → `Bowery-lane`);
- 1 fills two slots (`71 do. do.` → `71 Roosevelt-street`);
- none is left unresolved.

A slot with nothing to fill it (no street type to inherit, as after `Broadway`) is
`no_antecedent`, never guessed. It writes `address_resolved` only (`assemble_records.py`), and the
model's `address` stays verbatim.

**9. Trow's glued ditto (`-Michl`). DONE 2026-09-12.** `resolve_dittos.py` now has
`split_glued_mark`, `classify_glued_marks` and a `--glued-marks` flag; `is_ditto_lead` takes an
opt-in `glued` set and **defaults to empty, so every number recorded before this date reproduces**
(1906BPL re-checked: 67.4% ditto-lead, 23.5% dispute rate, unchanged).

The measurement this item asked for came back **zero**: there are no hyphenated surnames among
line-initial `-Xxx` in the panel. The risk was real but in a different costume — **ogden1839
prints `*` glued to the surname as a RACE DESIGNATION** (gold: `race_designation='*'`,
`name='Simmons Aaron'`), and `*` is in `DITTO_LEADERS`, so a blind glued-split would have
destroyed the marker and promoted a surname to a given name on 7 of 7 rows. That is why the mark
set is per-volume and empty by default.

Which glued marks are dittos is **measured, not declared**, by alphabetical coherence: take the
leaf's modal letter from unmarked lines, then ask what follows the mark. A ditto is followed by a
*given* name, which does not sort; a marker is followed by the *surname*, which does. The
separation is total — ogden `*` 100% → MARKER, polk `"` 0%, trow1907 `-` 12%, trow1913 `-` 15% →
DITTO. A token-level test was tried first and rejected at 78.2%: requiring a known given name
fails on Trow's orthography (`Edwd`/`Robt` vs 1906BPL's `Edw'd`/`Rob't`) and on business
continuations (`-Paper Co`, `-& Co`). **It needs a whole volume, not a window** — inside one
surname block the given names are contiguous and vote with the modal letter; the self-test pins
both behaviours.

Effect: on trow1913's 93 gold rows the carry produced **0** surnames before and **86** after. The
failure was silence, not error — `first_letter` anchors at position 0, so a leading dash abstains
from the sort key and the row was neither a surname nor a ditto. It carried nothing and poisoned
nothing. This also unblocks the implied-surname gate (see #6): the production gate now agrees with
gold on **every** panel volume, where it previously missed both Trow books at 0.0%.

**15. Lexicon-constrained abbreviation repair on IA hOCR.** IA's measured weakness is `abbr%`
**84.8% against Gemini's 95.3%** (`historical-ocr-eval`, 10 panel volumes), and since stage 1 now
ingests IA hOCR that gap sits directly upstream of the model. CER does not show it and the NER
layer depends on it: `bds`/`wid`/`h`/`r` are what carry residence and spouse structure.

The repair is **not** an LLM pass (see "Explicitly deprioritized"). IA is classical ABBYY — it
*misreads* abbreviations rather than expanding them — so this is edit-distance correction over a
closed set: the `ABBREVIATIONS` set in `historical-ocr-eval/ocreval/metrics.py` plus the
per-volume `style_profiles` legends. No generation, so no fabrication surface, and a token that
does not match the lexicon within the edit budget is left alone.

Pass/fail is already instrumented and needs no new gold: `score_ocr.py --engine ia-hocr` reports
`abbr%` and `CER-m` directly, so the test is **"does abbr% move 84.8 → ~95 with CER-m unchanged"**.
A CER-m that rises means the repair is firing on tokens that were not abbreviations.

**23. ~~Split column-merged microfilm lines at the gutter.~~ DONE 2026-09-28:
`split_merged_columns`** (stage 1). Test met: on Smith 1856's gold leaf 391, gold rows found in
the pipeline's lines 13/121 → **95/121**; the volume's merged-leaf lines 2,548 → 31. The survey of
microfilm volumes came first, as planned: 83 volumes had leaves that looked merged. The alphabet
test cut that to the 29 that are.

**24. Teach the model to leave an absent given name absent.** Mercein prints widows as `Ackerman
widow, 47 Elizabeth`, and the 4B adds `Sarah` or `Mary` on 15% of the 1,391 such lines. Gold keeps
the surname alone. The synthetic generator should emit surname-only widow entries and other
records with a missing given name, and uncommon printed street names and abbreviations to copy
verbatim (`Mhtn`, `Goerck`, `Meserole`). Measure with `volume_run_report.py`'s `widow_names` and
`substitutions` before and after. Both need no gold, so this is testable without the panel.

**27. Re-OCR the microfilm, measured before anything is spent.** 38 run-set volumes are BPL
microfilm with no book scan. IA's tesseract delivers about 40% of their lines, and the flagged-page
check found legible microfilm listing pages it read as fragments. `data_prep/reocr_bench.py`
(2026-10-05) scores any OCR of a microfilm page against the book scan of the same printed page,
from the 8 microfilm volumes that are copies of a book scan, and against the gold on 8 gold pages.
That is 48 pages and 3,174 reference lines, with no labelling. **Baseline (IA's microfilm OCR):
19.8% of the book scan's lines reproduced exactly, 53.6% at ratio ≥ 0.8; against the gold 23.9%
and 55.3%.** A candidate engine is scored with
`reocr_bench.py score --candidate <pages.jsonl>`, one `{volume, leaf, lines}` per page. Running
an engine costs money or GPU, so it waits on hadro, and possibly on the `historical-ocr-eval`
session that owns the OCR bench.

**Engine 1 measured 2026-10-05: tesseract 5.5, run locally, at no cost.**
`reocr_bench.py stage` puts the 48 images in the layout `historical-ocr-eval`'s engine runners
read (`engines/run_churro.py` covers Churro-3B, olmOCR-2, PaddleOCR-VL and API providers), and
`import --slug` brings their output back. `score` now also checks the contract:
- `abbr_kept`: abbreviation tokens kept;
- `expanded`: abbreviations spelled out;
- `invented`: entry-shaped lines matching nothing on the page;
- `boxed`: lines with boxes.

| run | close | exact | gold close | gold exact | junk | invented | abbr kept |
|---|---:|---:|---:|---:|---:|---:|---:|
| IA's microfilm OCR | 53.6% | 19.8% | 55.3% | 23.9% | 3.6% | 2.3% | 79% |
| tesseract 5.5, raw (`--dpi 300`) | 57.4% | 22.3% | 60.5% | 28.9% | 6.5% | 3.3% | 82% |
| tesseract 5.5, contrast + unsharp | 74.4% | **29.7%** | 78.6% | **39.6%** | 6.2% | 2.7% | **84%** |
| **tesseract 5.5, Sauvola (w 41, k 0.2)** | **93.7%** | 29.4% | **93.8%** | 37.9% | 5.2% | 2.5% | 74% |
| Sauvola, k 0.1 | 76.1% | 9.4% | 83.9% | 12.4% | 8.2% | 3.6% | 67% |
| Sauvola after 2× upscale | 89.1% | 26.5% | 92.6% | 35.6% | 5.0% | 2.8% | 74% |

Every run keeps boxes and expands next to nothing. **Local binarization is what recovers the
lines.** Tesseract on the raw film frame reports "Empty page!!" without a DPI hint, and Sauvola
takes the book-scan agreement from 54% to 94%. Its cost is small tokens: it glues `n Johnson` into
`njohnson`, drops the corner `c`, and reads `h` as `b`. Those are the tokens the fields rest on,
so its abbreviation retention falls below IA's. Character accuracy stays modest in every run (an
exact line 29–30% of the time), which is what engines 2 and 3 would have to improve. Tesseract
ran as 4 single-threaded processes (`OMP_THREAD_LIMIT=1`), about 5 s a page. The 39 deferred
volumes (~7,750 pages) are ~11 CPU-hours: about 3 hours here, or minutes as a Torch CPU array.

The same pairing measures the ABBYY-8 tier, which is 53 run-set volumes, 8.89M lines and ~208 of
the run's ~348 H200-hours. The ABBYY-8 Brooklyn halves reproduce **87–99%** of their ABBYY-9/11
twins' lines at ratio ≥ 0.8, but only 30–58% exactly. The two weak duplicate halves the run set
skips scored 57–67%. So ABBYY-8 errors are characters, not lost lines. About 3% of number tokens and 10% of word
tokens differ from the better copy. The dominant number confusion is 6 → 0 in Brooklyn's font
(`26` → `20`, `16th` → `10th`), with 8 → `S` second. Two repairs were tested against the twins
and against the panel gold:
- **`S` → `8`** where only a digit can stand (`S3`, `1S4`, `Sth`) is right 89% of the time on the
  twins (583 of 656) and 4 of 4 on the gold. It is applied to ABBYY-8 volumes
  (`fix_digit_s`, `survey_harvest.derive`), and a dry run counts 128,666 fixes across the 53
  ABBYY-8 run-set volumes. **It takes effect at the next re-derive, held until the real-OCR
  panel's run 3 is scored**, so that run's staged inputs stay what it measures.
- **A leading `0` → `6` is rejected.** It is right 67% of the time on Brooklyn, but 0 of 9 on the
  trow1907 gold, where Trow's font turned 9 into 0 (`08th` for 98th). A wrong repair would also
  hide a visible error behind a plausible street.

The leading-zero rate became the tier signal above.

## Larger, and the ones that unblock claims

**10. A whole-volume gold slice.** Hand-label ~200 lines sampled across one volume's *listing*
leaves, and the pipeline gains its first real volume-scale accuracy number. Everything above is
currently measured with proxies or on sampled pages. This is the highest-value expensive item.

**11. Page-type detection.** The model never refuses, so every non-entry that survives filtering
becomes a fabricated person. No line-level rule catches it — `courts of law or equity in` is
lowercase, ASCII, normal height, normal width, on a common left margin. This probably needs a
page-level classifier or a VLM pass on the leaf image, and it is the largest remaining correctness
gap. The plan is [PAGE_TYPE_CLASSIFIER.md](PAGE_TYPE_CLASSIFIER.md); phase 0 has run, and it found
that **advertising in 1906BPL is banded, not paginated — 94% of listing-span leaves are an ad strip,
a clean listing body, and an ad strip.** Ditto-lead density is 0.7% in the top decile of the page,
45% through the middle eight, 0.0% in the bottom decile
([`results/leaf_band_structure_1906BPL.py`](../results/leaf_band_structure_1906BPL.py)). So the unit
is a band within a leaf, not the leaf — and `--interior drop`'s recorded cost of ~172 leaves is
~172 *clean listing bodies* discarded to remove their strips.

**12. ~~Run a whole volume on the 4B, on the HPC.~~ DONE 2026-09-28**, five volumes, 310,932 lines.
See "The first whole-volume 4B run" under stage 6. It produced items 21–24.

**13. ~~Records assembly.~~ DONE 2026-09-28: `postprocess/assemble_records.py`.** Predictions
used to land in a `.txt` and stop. The assembler turns a run into one row per line, in
`data/records/<run>/<volume>.jsonl.gz` and `.csv.gz` (gitignored), with a summary in
`results/records_<run>.json`.

```bash
python3 postprocess/assemble_records.py --root data/volumes_run1 --run 4b-100k+guard   # ~30 s
```

Each row carries:
- **Provenance:** a stable `record_id` (`volume:leaf:n`); the IIIF canvas, the line's `#xywh=`
  box and a crop URL; the printed page (`read` or `inferred`) from the survey's margin fit; and
  the section.
- **The text:** `raw_line`, and the model's eight fields verbatim.
- **Resolutions, beside the fields:** `name_resolved` (surname carried across ditto lines, with
  the source line's `ditto_source` and the carry's review flags), `address_resolved` (#8) and
  `home_address_resolved`.
- **Flags, never filters:** layout `role` (a runover is an entry's tail), `entry_shaped`,
  `non_entry_page` (SURVEY_PLAN.md, "Non-entry pages") and `eval_holdout`.

`usable` is the conservative subset: entry-shaped, a start line, on a listing page, and not held
out.

| run 1, `4b-100k+guard` | rows | usable | printed page known | against the printed count |
|---|---|---|---|---|
| 1906BPL | 194,201 | 166,537 (86%) | 97% | 135,864 surnames carried, 31,501 disputed (23%) |
| Doggett 1845 | 64,580 | 60,372 (93%) | 99% | **0.984 usable per printed name** (61,333) |
| Mercein 1820 | 20,366 | 18,510 (91%) | 99% | |
| Hearnes 1852 (microfilm) | 14,250 | 11,339 (80%) | 99.6% | |
| Smith 1856 (microfilm) | 17,535 | 10,136 (58%) | 82% | |

The microfilm rows are the ones the twin finding replaces: run 2 adds `hearnesbrooklync1852unse`
and 1857BPL, the book scans of the same editions. The summary compares usable records with every
volume's `stated_name_count` wherever the survey found one (27 volumes).

## Explicitly deprioritized

- **The publisher tag.** Null on the 2B *and* the 4B, and the null is stronger on the bigger model.
  `spooner`-style OOV volumes cost nothing measurable.
- **Generator/composition tuning.** Settled by v7 and reconfirmed by v8-250k: more of the same
  distribution does not help. The model copies, it does not sample.
- **More training volume.** Measured negative — 250k made the 0.8B worse on the panel and lost all
  four externals. Capacity was the constraint, not volume.
- **A generic LLM post-OCR correction pass between stages 1 and 4.** Assessed 2026-09-11 against
  CLOCR-C (arXiv 2408.17428), which reports >60% CER reduction and large downstream NER gains from
  exactly this step. It is the wrong step *for this corpus*, for three reasons already measured here:
  - **It would expand the abbreviations the contract requires verbatim.** CLOCR-C's prompts are
    "recover the most likely original text", which turns `bds` into `boards` and `wid` into `widow`.
    `historical-ocr-eval` maintains an `abbr%` metric and a dedicated self-test *because* silent
    expansion is a defect — it corrupts the input to NER and breaks the verbatim link to the page.
  - **It would resolve ditto marks silently.** The model emits `" Wm` verbatim by contract and
    `postprocess/resolve_dittos.py` expands it downstream, where the antecedent is auditable and the
    23.5% cross-line dispute rate is visible. A correction LLM would resolve them invisibly and
    burn the panel (same reason resolving inside the model was rejected).
  - **It adds a fabrication surface upstream, where it is hardest to see.** The model never refuses;
    a hallucinated *corrected line* looks clean rather than garbled, so the existing shape-based
    filters would pass it. CLOCR-C's own failure mode is hallucination on degraded input.

  Cost is the minor objection: 199,012 lines for 1906BPL means running the expensive stage twice.
  What does transfer from the paper is next-step **#14** (its skew finding) and the motivation for
  **#15** — a narrow, non-generative version of the same repair.
