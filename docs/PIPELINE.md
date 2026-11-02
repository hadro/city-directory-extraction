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
COPYFILE_DISABLE=1 tar -czf cde-volumes-corpus.tar.gz -s ',^data/volumes_corpus,data/volumes,' data/volumes_corpus
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

**Since 2026-10-20 the carry is narrower and better grounded** (`fb1a020`, `4efc6ae`; #6 has the
measurement). Three opt-ins to `resolve_cross_line`, all on in `assemble_records`, all off by
default so every number above still reproduces:
- **`strict`** — a line sets the carry only if its surname is capitalised and inside its leaf's
  letters, taken from the NEIGHBOURING leaves' votes (`leaf_letter_ranges`; a leaf's own vote
  fails on a big block whose marks dropped — 1906BPL leaf 20 votes J on the Allen block's
  `Jas …` lines). Ad copy (`millions— Try them.`, `until Withdrawn.`) and off-letter given-name
  leads no longer name the dittos after them; they are transparent.
- **`heads`** — the surname block headers ingest drops are put back by position
  (`assemble_records.dropped_headers`, from `<id>_dropped.txt.gz`) and set the carry. New field
  `ditto_header`; `ditto_source` is null there.
- **`markers`** — leading marks found per volume by what follows them (`classify_lead_marks`):
  the Eastern District `E` of 0039/0040/0042 and its misreadings (`Æ © € ®`, a quote), the
  column rule (`| I ! ]`, judged as one), `*`. A marked line sets the carry from the surname after
  the mark, which comes off `name_resolved` into `name_mark`; `district` = Eastern.

1906BPL's disputed share under these rules is **6.6%** (8,975 of 135,864), much of the fall by
construction. The record that is not: at 1,802 printed headers the carry agrees with the header
**41.3% → 79.8%** (`results/carry_rules.py`).

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

### Run 3 (2026-10-06): the real-OCR panel after the ingest fixes

```bash
# predictions unpacked into data/volumes_panel3; all 21 SHA-1 sidecars match the staged chunks
python3 postprocess/copy_guard.py --volumes data/volumes_panel3 --run 4b-100k
python3 eval/ia_panel.py score --run 4b-100k --preds-dir data/volumes_panel3 \
    --out results/ia_panel_run3.json
```

Torch job 19264497, 21 tasks on L40S. This run measures next step 26 (`li` → `h`, side-band
scraps) and the letter-ditto verdicts on the model's real input. 16 sets had unchanged inputs
and kept run 2's predictions; their SHA-1 sidecars matched. 5 were predicted again: boyd1890,
lain, trow1907, and the Hearnes and Polk twins (1,052 lines).

| whole-row EM on IA's line (guarded) | run 2 | run 3 | clean text |
|---|---|---|---|
| all 21 sets, 2,310 rows | 44.5 (48.6) | **47.2 (51.4)** | |
| the 17 sets with clean-text predictions, 1,699 rows | 47.4 (52.1) | **51.1 (55.9)** | 73.7 (80.6) |
| boyd1890 | 24.3 | **73.0** | 90.5 |
| polk1917's twin in Trow 1917 | 8.3 (8.3) | **47.2 (48.6)** | 63.9 |

- **No row went from right to wrong.** In boyd1890, 37 rows were fixed: 16 by the marker and 21
  by scraps stripped from either end of the line. In the Polk twin, 28 were fixed, 23 of them by
  `ii` read as the ditto. The other three re-predicted sets changed 1–4 input lines each and no
  row's score.
- **Compare runs by `context.gold_row`, never by position.** The rebuilt boyd1890 panel lost
  gold row 9 and gained row 74, so row k of run 2 is not row k of run 3. A positional diff shows
  four false regressions.
- **Boyd's 20 wrong rows:**
  - 10 still carry scraps, on pages whose band failed the guards.
  - 4 are commuters' entries with a parenthetical, such as `(label cutter N Y)`. The model
    misses these on clean text too: they are 6 of its 7 wrong boyd1890 rows there. This is a
    convention the model never learned, not OCR.
  - 3 are letter misreads (`Golden`/Colden).
  - 3 are panel pairing errors, where `align` matched the gold row to a neighbour at the same
    house. For example, `Costan William` is paired with `Covert William A` (gold rows 12, 73
    and 74).
- **What the OCR costs is now 22.6 points** of whole-row EM (24.7 guarded), down from 26.3.
  trow1907 is unchanged at 7.4.
- The copy guard fixed 144 fields and broke 6. Its rules were tuned on this panel, so this is
  not a test.

**The held re-derive, applied after scoring (2026-10-06).** Steps, in order:
- `survey_harvest.py --rederive` with `fix_digit_s` and the ditto tail verdicts, on the 70
  ABBYY-8 volumes outside the `defer` tier;
- then `survey_derive.py sections` and `scope` on the same volumes;
- then `run_tiers.py --rescan`.

Brooklyn 1912 p3 (`brooklynnewyorkc19123broo`) is left out: it is being re-OCR'd (step 27), and
that job reads its sections.

Results:
- **S → 8:** 168,902 fixes. The dry run's 128,666 counted run-set volumes only.
- **Ditto tails:** applied to all six letter-ditto volumes, adding 11,754 ditto-led lines.
- **Unchanged:** kept lines in every volume, every section run, and every volume's tier.
- **Leading-zero rates** rose slightly in 34 volumes, because `0S` now reads `08`.
- **On the rebuilt panel**, the repair changes two trow1907 lines, both to the gold's number
  (`S7 Chambers` → `87`, `41S` → `418`). Lines identical to gold stay at 1,399.

Panel run 3's inputs are kept in `data/iapanel_run3/`, with the manifest they were built under,
and staged in `data/volumes_panel3/`.

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

> **Live as of 2026-10-22: two NYU jobs are out** (the canary's 4B pass, and the abbyy8-damaged
> tier's LightOn re-OCR). [BOOKSCAN_HANDOFF.md](BOOKSCAN_HANDOFF.md) is the guide for receiving,
> importing and judging them and for what comes after; #27 below is the full record behind it.

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
> the gate's own ratio). The six ABBYY-8 volumes took their tail verdicts at the post-panel
> re-derive, with `fix_digit_s`, so that panel run 3's inputs stayed what it measured. **Applied
> 2026-10-06:** 11,754 more ditto-led lines across the six (stage 6, "Run 3").
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

**14. ~~Report a median and a per-volume tail in `evaluate.py`.~~ DONE 2026-10-16:
`--by-volume`.** It scores each `--gold`/`--pred` pair separately and prints the per-set table,
the pooled number, the median, and every set more than `--tail-margin` points of row EM below it
(default 15). `distribution()` and `pool()` are reusable, and `pool()` sums the raw `score()`
tallies, so the pooled figure is exactly what a single score over the concatenation gives.

It earned itself on the first run. Over the 25 clean-gold panel sets, `4b-100k`:

| | |
|---|---|
| Pooled row EM | 69.5% |
| Median | 77.6% |
| Worst | **minneapolis 35.2%** — 42 points below the median |
| Also flagged | nyu 56.0% |

minneapolis holds a macro-F1 of 0.804 while its row EM is 35.2%, which is the signature of one
field consistently off rather than a collapse. The self-test is the case the measure exists for:
a small collapsed set among healthy ones, where the pooled mean reads 97.8% and the worst set is
0.0%.

**Followed up 2026-10-17, and the tail is a GOLD defect, not a model one.** Minneapolis 1900
prints a surname once and drops it from the entries beneath ("Cook Ira M", then "Jacob H, …"),
and `harvest_minneapolis.py` RESOLVES that inherited surname into the `name` field. So the gold
asks for a surname that is not in the input line, against the contract that a ditto is emitted
verbatim and expanded downstream by `resolve_dittos.py`, where the antecedent is auditable.
**95 of 230 rows (41.3%) carry a surname absent from their own `raw_line`:**

| minneapolis, `4b-100k` | rows | row EM | macro-F1 |
|---|---|---|---|
| all | 230 | 35.2 | 0.754 |
| surname IS in the line | 135 | **60.0** | 0.797 |
| inherited surname | 95 | **0.0** | 0.696 |

The model scores a structural zero on the 95 because it cannot do otherwise; 35.2 is just that
arithmetic. The converter's own docstring flags this as "[review item #1] … review the `name`
field after", so it is a known caveat that was never measured, and the published board
(`results/eval_table.md`) carries the depressed number for every model in it. Some carries are
also simply wrong ("Mabel Mrs Mary E", "Howard John G" on a page of Abbotts).

**FIXED 2026-10-17, hadro's call.** The gold now records what the page prints — the inherited
surname stripped from `name`, and kept in `context.inherited_surname` rather than discarded, so
a future surname-carry evaluation keeps its target. All 95 rows match their own `raw_line`
afterwards, and `validate_gold`'s 95 standing `name tokens not in raw_line` warnings go to zero.
`harvest_minneapolis.py`'s docstring now says to emit the printed name and NOT to use
`--surname`, so a re-run cannot reintroduce it. Logged in GROUND_TRUTH_HANDOFF's corrections
table; the original is `data/_gold_backup/minneapolis_eval.2026-10-17.jsonl`.

Minneapolis prints no repeat mark at all, unlike polk1917's `"` or trow1913's `-`, so there is
nothing for `resolve_dittos.py` to key on and the surname genuinely is not recoverable
downstream. That is a property of the book, not something the gold should paper over.

| minneapolis row EM | before | after |
|---|---|---|
| v7 | 31.3 | **63.0** |
| 2b-100k | 34.8 | **65.7** |
| 4b-100k | 35.2 | **64.8** |
| v8-250k | 21.3 | **45.7** |

Only those four of the board's 18 models had stored predictions. The rest of that row predates
the correction and is flagged as not comparable in `results/eval_table_notes.md`, which
`results_table.py` now appends to every regenerated table so the caveat cannot be erased by the
next `--out`.

**The panel after the fix: pooled 69.5 → 71.0, worst 35.2 → 56.0, and one set still flagged —
`nyu`, which is a known non-peer** (a third-party CRF parse over uncorrected OCR,
GROUND_TRUTH_HANDOFF "The NYU case, in full"). So both sets the instrument caught on its first
run were the two in the panel that are not hand-built gold, one of them a real defect nobody had
measured. A low set is a question, not a verdict.

Checked at the same time, and clean: `lain` (800 rows) and `tulsa` (1,500) are harvested from
directory-pipeline's aligned JSON by `harvest_own.py`, and a sibling session reported that
alignment can bind the wrong line on dense pages. It does not reach these: the surname and the
address appear in their own `raw_line` on 100% of rows in both sets, so the `#xywh=` join held.
They remain silver by provenance (labels are Gemini's), not by defect.

The original item follows. It currently pools TP/FP/FN across
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
  Run 2's panel inputs are kept in `data/iapanel_run2/`, the files its predictions were made on.
- **Row EM, panel run 3 (2026-10-06):** boyd1890 went from 24.3 to **73.0**, and Polk 1917's
  copy in Trow 1917 from 8.3 to **47.2**. No row went from right to wrong. See stage 6, "Run 3".

**29. ~~Let the copy guard read LightOn's long s as s.~~ DONE 2026-10-16.** On the LightOn panel
(#27) the guard restored the printed "ſ" over the model's "s", breaking 16 of franks1786's fields
and 7 of its durs twin's. `_lower` in `postprocess/copy_guard.py` now folds U+017F to s wherever
the guard compares words — in `_norm` (the alignment), `_squash` (the judgement) and `_invented`.
It is a **comparison only**; no stored text changes, because on IA's Fraktur-read microfilm "ſ" is
a misread f, not an s (docs/POST_OCR_CORRECTION.md). Reading it as s costs nothing there: f/s is
already in CONFUSIONS, so the model's letter stands either way, and a self-test case fixes that.

Re-guarded offline, no GPU (`copy_guard.py --volumes data/volumes_panel_lighton_b5495c9 --run
4b-100k`, then `ia_panel.score_run` with `data/iapanel_lighton_b5495c9/manifest.json`):

| | raw | guarded, before | guarded, after | fields broken |
|---|---|---|---|---|
| franks1786 | 66.1 | 48.2 | **69.6** | 16 → 1 |
| franks1786 in newyorkbrooklynd00durs | 47.3 | 38.2 | **50.9** | 7 → 0 |
| **Pooled** (2,029 rows) | 62.2 | 66.2 | **67.2** | |

The guard's 26 changes on franks1786 fall to 8. No other set moves by a row. The one field still
broken is `streeet` → `street`, a triple letter the model repaired and the guard restores: the
documented trade (a rare printed word moved to a common one), not long s. lain's single break was
there before and is the same kind (`Salvaedore`).

Both standing checks hold:
- **Run 3's IA panel does not move.** All 42 of `data/volumes_panel3`'s guard files are
  byte-identical after the change. U+017F occurs 38 times in the LightOn panel's lines and **zero**
  times in run 3's, so the fold cannot reach them.
- `copy_guard.py --check-panel 4b-100k`: **broken 0** on clean text, 280 fixed over 4,613 rows.

**30. Stop the panel scoring a gold row against a different person's line; and stop the joiner
gluing a display banner onto an entry.** (Handed to another agent 2026-10-24 with #32 (b)-(e): start at
[LINE_ASSEMBLY_HANDOFF.md](LINE_ASSEMBLY_HANDOFF.md).) Found 2026-10-23 on boyd1890 gold row 73 (leaf 105), and
present before and after the same-row fix of that day. Two defects stacked; the first is the cheap,
general one.

**Panel half DONE 2026-10-24** (`volume_run_report.other_person`, a VETO in `align`; LINE_ASSEMBLY_HANDOFF
step 1). The name GATE recommended below was simulated first and rejected: it drops the right
person's line wherever OCR garbled or lost the name. The veto rejects a candidate only on evidence of
another person (a given name that cannot be the gold's, or an unrelated capitalised surname on a line
that has not merely lost it), checks a pair on its first line, and admits a single line longer than
the gold when its head reads as the gold (0.85), so a glued line still claims its row. Measured
against panels rebuilt at the previous commit, in rows (exact after typography):

| panel | matched | exact | dropped / added / re-matched |
|---|---|---|---|
| LightOn pilot, IA's words | 2,066 -> 2,059 | 1,730 -> 1,730 | 7 / 0 / 5 |
| LightOn pilot, fresh tesseract | 2,064 -> 2,056 | 1,715 -> 1,715 | 8 / 0 / 3 |
| production lines (`data/survey_ocr`, 21 sets) | 2,363 -> 2,352 | 1,394 -> 1,394 | 12 / 1 / 2 |

No exact row changed on any panel. Every wrong-person row of LINE_ASSEMBLY_HANDOFF §2 is now unmatched
or matched to the gold's own line (McElroy and Polk 1917 row 27 to their glued lines; Crawford/Susie,
Seabury/Samuel, Ammons/Fred'k, Kaplon, Agen H'y, Fordham/Charles, Rogers/Lewis, Farrel/Brid unmatched),
as are hopehenderson1856 row 6 (`*Hales John` -> its own glued line), smith1855 twin row 82 and lain
row 75. The right person's line is still lost on: destroyed names (`Paley Gears`, `Eyes ase`, `Ed ape`,
`Foote Beitetitn`, lain 571 `" Fre»SaS-,CarD'r'` and 575 `"SeTfcnAni0n'`, both the gold's own line
by LightOn's reading of the page); smith1855 row 175 (another entry's tail before the gold's, name
lost); hopehenderson1856 row 7 (its line is glued under row 6's head, which now takes it); and, on the
pilot, lain rows 141 and 373, where the import put a NEIGHBOUR's name on the gold's own printed line
(`Abrahann George, mason, h 421 Hicks`; `John, clk. h 156 Buffalo` where IA reads `Ahrend Geo.`).
No text rule can tell those from a neighbour's line, and on row 141 another person's ditto line
(`“ Jacob, tailor, h 138 Ten Eyck`, a column away) takes the freed row: the one wrong-person match
the veto creates. Rules beyond the handoff's four refinements, each from a measured row: a line whose
first word occurs later in the gold has lost its head (`Ocean Parkway opp. Brighton race-`, the
run-over of `ABRAMS SMITH, hotel`; `C. fancygoods`); a given name OCR split in two must reread at 0.75
(`Ki chard`, not `C. merchant`). A stricter ditto rule (a ditto line never claims a surname-led gold
row) was measured and dropped: most older gold sets type a printed ditto as the surname (smith1855
`Farrell Dominick` for `— Dominick`). Post-#30 baselines, for every later diff:
`data/iapanel_lighton_post30_{ia,tess}` (work dirs `data/lighton_pilot_pull_{ia,tess}`) and
`data/iapanel_post30` (`ia_panel.py build --panel-dir`, new). The 4B's existing panel predictions
still line up with unchanged rows; a row whose line changed needs a Torch run to score.

**Joiner half DONE 2026-10-24** (`join_wraps` `start_cap`; LINE_ASSEMBLY_HANDOFF step 6; survey, so
in D's import). A line the model read as a start (`cont` 0, source `model`; `sources` now reaches
the joiner beside `cont`, dropped wherever `cont` is) joins on the indent alone only up to the
volume's `start_cap`: the 99th percentile of the indents at which its model run-overs (`cont` 1)
join, measured in a pre-pass (`ia_volume_to_jsonl.start_cap`) over at least 1,000 of them, else no
cap, and stored in the sidecar's `wrap_calibration`. No test on the text; #28's lower threshold
untouched. Joins removed: Trow 1909 vol 1 254 (cap 16.4 line heights over 26,657 run-over joins),
Trow 1903 p1 468 (10.42), 1876BPL 236 (8.13), Hope & Henderson 1856 162 (5.96), Brooklyn 1905 p1 84
(16.68), Longworth 1826 0 (51 run-over joins: no cap). A uniform image-read sample of 40 removed:
12 two entries glued (`Farrell Jno., spinner ...` + `Farrell Joseph, baker ...`; `" Ada hairdresser
...` + `" Albert E salesman ...`), 28 display or ad type (banners, page numbers, `NAMES TOO LATE FOR`
+ `C.`), no real run-over. Pilot on both layers: no row changed, because no pilot volume has 1,000
model run-overs, so the pilot never sets a cap: McElroy's banner stays glued there. Production
Boyd is IA-only (no `cont`); it would be capped only once read whole by the re-OCR.

The row: gold `McElroy John A, news agent, h 84 Bradford ave`; the panel's line `McElroy Bernard
E, bill poster, h 84 Bradford ave`, match 0.622. LightOn and the dump read the page right, as
separate lines: line 50 the entry (x=561), line 51 `LLIOTT, Plumbing, Steam and Gas Fitt` (an ad
banner below, x=891), line 52 the drop-cap `ELLIOTT` (the layer's alone). Then:

1. **The joiner glued the banner onto the entry.** The model read line 51 as a start (`cont` 0), so
   `join_wraps` fell back to its indent rule, and an indent of 330 px is a run-over by that rule.
   `_lines.jsonl.gz` holds `McElroy John A, ... Bradford ave LLIOTT, Plumbing, Steam and Gas Fitt`.
   In production the record's address carries the ad, and the copy guard will not strip it.
2. **The panel builder could not see the right line, and took a neighbour.**
   `volume_run_report.align` (which `eval/ia_panel.py` uses) only tries a line whose key length is
   within max(12, 60%) of the gold's: the gold is ~43 characters, the glued line ~78, so it is
   never a candidate. The greedy match then gives the row the best remaining line at
   `MATCH_MIN` 0.6 or more: Bernard E, who shares the surname and the whole address and is not in
   the gold sample, so he was free. The row is scored as a miss, and on a 4B panel run the model
   is graded on one person's line against another person's gold. These are the "same-address false
   matches" noted for Boyd rows 12, 73 and 74 since run 3.

**Size** (rows whose matched line's first two words differ from the gold's, with match < 0.8;
ditto-led gold left out): `data/iapanel` 55 of 2,206 (smith1855 21, hopehenderson1856 7, lain 6,
smith1856 6); the LightOn pilot panel 15 of 1,963 (lain 9, boyd1890 3). An upper bound: on IA's
text some are the right person under a garbled name (franks1786 row 37, `Qaincey J.` for `Quincey
J.`, 0.789), and hopehenderson1856 rows 6-7 are one miss cascading into the next row.

**Recommended fix, panel (do this first; it touches no production data).** In `align`, a
single-line candidate claims a gold row only if it agrees on the name as well as the ratio: the
gold's leading surname token, and its first given-name token where the gold prints one, each
within a small edit distance of the line's (say ratio >= 0.75 on the token, so `Qaincey`/`Quincey`
passes and `Bernard`/`John` fails). Leave ditto-led gold rows (`" John`, `— Wm`) to the ratio alone,
since their surname is not printed. A row that fails is left unmatched, not given its nearest
neighbour: that is what `matched_pct` exists to show. Also widen the length window for a candidate
that *starts* with the gold (a prefix ratio), so a line with a glued tail can still claim its row
and the defect shows as an inexact line rather than a wrong person. Verify: re-run
`eval/lighton_pilot.py --skip-derive --diff-against <saved panel>` and `ia_panel.py build` against a
saved `data/iapanel`; every changed row should be one of the ~70 above, each now unmatched or
matched to the gold's own person; no exact row should change. Rows dropped from the panel change
the denominators, so report pooled row EM before and after with the matched counts beside it.

**Recommended fix, joiner (narrower and riskier; do it second, measured).** A re-OCR'd line the
model itself read as a start (`cont` 0, source `model`) should not be joined on indent alone when it
looks like display type: two or more of its first three words in capitals or a trade-banner shape
(`Plumbing, Steam and Gas`), or a layer-only line of tall type beside it (the drop cap `ELLIOTT`,
140 px tall here against a ~55 px line). #28 already learned that geometry cannot separate starts
from run-overs (3,521 of 0035's model starts sit in the run-overs' indent band), so this must be a
test on the banner's own shape, not a tighter indent. Measure it on the pilot first
(`eval/lighton_pilot.py`, both `--page-dir`s), and count how many joins it removes on a whole
volume (`reocr_pair.py joins`) before and after: a large number means it is cutting real run-overs.

**31. Make the re-OCR import use more than one core. Steps 1-3 DONE 2026-10-23; step 4 open.**
Measured with the output unchanged: re-dumps of longworthsameric1798newy (IA's words) and
trowsgeneraldire19073trow (tesseract layer) are record-for-record identical to the production dumps
(642 and 1,268 records, decompressed sha1), and `import --ids longworthsameric1798newy,
trowsgeneraldir1904p3trow --workers 2` leaves both sidecars identical but for their `code_at`
stamps. One process: Longworth 1798 18 -> 14 s, Trow 1907 vol 3 (tesseract layer) **1,013 -> 439
s**; then `--workers` volumes at a time (default 6) on top. The original plan follows.
**Do it before importing the `first` and `abbyy8-clean` tiers.** The abbyy8-damaged import (2026-10-23, 35 volumes, ~17,600 pages) took about
7.7 minutes a volume, 4.5 h in all for the dumps, in ONE process at 98% of one core on an 8-core Mac
(4 performance + 4 efficiency). The next two tiers are 75 volumes, about twice the pages: ~6-8 h
serial, ~2 h parallel.

Where the time goes (cProfile, `reocr_pair.page_dump` over 4 pages of trowsgeneraldir1905p1trow,
12.4 s profiled): **91% in `align`**, almost all of it in `fast_sim` -> `difflib` (~50,000
similarity calls a page). `align` fills the whole grid, every model line against every run of 1-3
layer lines in the tile (~60 x 60 x 3 on a Trow tile), though both sides are in reading order and
near one-to-one, so cells far from the diagonal never lie on the answer. About a third of the
`difflib` time is `__chain_b`, the second string re-indexed on every call. The tesseract-layer
volumes pay about three times over: `better_layer` pairs each page against both layers
(`page_rows` twice) and `page_dump` pairs the winner again.

In order, safest first. The first three must leave every output byte-identical. Check by re-dumping
one IA-layer volume and one tesseract-layer volume with `dump --out-dir` and comparing the files
with the production dumps, and `reocr_pair.py --self-test`.
1. **Volumes in parallel** in `reocr_books.import_volumes`: run the per-volume `dump` subprocesses
   N at a time (`--workers`, default 4: the performance cores). Each writes only its own
   `data/survey_ocr/<id>_words.jsonl.gz` and its own sidecar's `reocr` block, and renames its own IA
   dump once, so they do not collide. Keep everything after the dumps (`--rederive`,
   `survey_derive.py`, `survey_adleaves.py features --merge` and `inventory --write`) as it is:
   one call each over all the ids. `features --merge` and `inventory --write` write corpus-wide
   files and must never run concurrently. Keep each dump's output lines together in the log (capture
   per process, print on finish), since the per-volume line is what step 5 of BOOKSCAN_HANDOFF
   reads. Expect ~3-4x. (Pages within a volume in a pool would do the same and also help one big
   volume, but per-volume is the smaller change.)
2. **Index each model line once per tile** in `align`: build one `difflib.SequenceMatcher` per model
   line with it as `seq2` (`set_seq2` once), and vary `seq1` across the layer runs, so `__chain_b`
   runs m times a tile, not n x m x RUN. `ratio()` is symmetric in value only up to difflib's junk
   heuristic, so check the self-test and the byte-identical re-dump; `fast_sim`'s length and
   `quick_ratio` pre-checks stay in front. Expect ~1.3-1.5x on top.
3. **Pair the chosen layer once**: `better_layer` already computes `page_rows` for both layers; have
   it return the winner's rows so `page_dump` does not pair the page a third time. ~1.5x on the
   tesseract-layer volumes only.
4. **Only then, and only measured: a banded `align`.** Restrict cells to |i - j x n/m| <= a band
   (say 8 lines, widened where a tile's n and m differ a lot) to cut `align` ~5x more. This CAN
   change pairings (a model line that skipped many layer lines, as on bleed-through pages), so it
   needs `eval/lighton_pilot.py` on both `--page-dir`s with `--diff-against` saved panels, as the
   same-row fix had (`de9521a`), and the per-volume line counts against the production dumps.

**32. Five line-assembly defects found by reading the abbyy8-damaged import against page images
(2026-10-23, hadro).** (a) is fixed (071e202); (b)-(e) are handed on with #30: the working guide,
baselines and tool (`eval/line_assembly.py`) are in [LINE_ASSEMBLY_HANDOFF.md](LINE_ASSEMBLY_HANDOFF.md). Each was traced to its stage on the page itself; the "old/new" comparisons
run `page_dump` under the code before and after `de9521a` (the same-row fix). Ordered by what they
cost the 4B. **Before this tier is staged, decide what to do about (a)**: it makes one record of
two people.

**(a) FIXED 2026-10-24 for ditto lines** (`reocr_pair.page_dump`'s margin pull). Where the layer
read only a line's tail, respell hung the model's first word on a mid-line word the layer read as
something else ("Too" for "—Kate"), and the pull, which refuses to move a word the layer read, left
it there. A ditto line (always an entry's start) whose first word sits on such a word, 3-30
characters in from the margin, is now pulled to it, the margin read from starts the layer placed
(not model-only lines' synth boxes: Brooklyn 1905's banner ad atop every page put it at x 30). The
existing rule is untouched. Glued-entry proxy: trowsgeneraldire19091trow 1.18% -> **0.39%**,
trowsgeneraldire19073trow 1.00% -> **0.31%** (joins 38,082 -> 36,938 and 31,359 -> 30,482; scoped
lines +1,186 and +950); line starts moved elsewhere: 181 (Trow 1905 p1), 234 (Brooklyn 1905 p1), 542
(Trow 1908 p2), all ditto lines. Pilot: IA's words 83.7 -> 83.7% (no exact row changed), fresh
tesseract 83.0 -> 83.1% (3 gained, 0 lost). Three wider versions were measured and rejected: any
entry-like opening moved centred ads and, by changing the existing rule's "read" test, a quarter
of a Trow part's line starts; a text-width estimate was too coarse at 3 characters. Joins without
a ditto (`Steinbruck Max ... Steinbrugge Edwd`) remain. The original finding:
**The wrap-joiner glues separate entries where the layer missed a line's opening.** Trow 1909
vol 1 leaf 97: `—Julian H agent 90 West R 1908 h Hopatcong N J —Kate B h 733 Prospect av`, `—Robt
clerk h 150 W 105th —Robt B notary public 150 Nassau R 1106 ...`; Trow 1907 vol 3 leaf 463:
`Steinbruck Max police h 510 W 151st Steinbrugge Edwd (estate of) mers 29 Bway`. LightOn read each
entry as its own line (tile c2_h1's raw answer is clean), and the dump flags the second a start
(`cont` 0), so `join_wraps` fell back to its indent rule, and the second line's box starts late:
`—Kate B` at x=1519 where its neighbour `—Katharine H` starts at 1350. The layer missed the line's
opening, `respell` hung the text on the words it did find, and the line looks indented. The
margin pull (`6a5837e`, "pull ONLY where tesseract missed the line's opening") should catch
exactly this and did not. **Size**, by a proxy (a ditto dash opening a second entry mid-line,
`\S\s+[—–]\s*[A-Z][a-z]`, in `_listing.jsonl.gz`): trowsgeneraldire19091trow 1,668 of 140,915
lines (1.2%), trowsgeneraldire19073trow 1,244 (1.0%), against 0.2-0.5% in every other Trow part
checked, the other two tesseract-layer volumes included (1908 p2 0.4%, p3 0.3%). So it belongs to
those two scans ("generaldire", a different series), not to the tesseract layer as such; the
proxy misses joins without a ditto (Steinbrugge), so the true count is higher. Same tree as #28's
warning: do not lower the indent threshold. **Recommended:** find why the margin pull did not fire
on leaf 97 (it reads the margin locally, +-12 line heights, `fc46ac8`), and whether a start flag
plus a ditto or capitalised-surname opening should veto an indent join when the line's box begins
right of its neighbours' by more than the indent but its text begins like an entry. Measure on the
pilot (both `--page-dir`s) and by the proxy on these two volumes.

**(f) The joiner's margin guard measured from a hanging ditto dash. DONE 2026-10-24 for lines that
open like a name** (found while checking (b); LINE_ASSEMBLY_HANDOFF §2 and step 2). `join_wraps`
lets a model run-over (`cont` 1) join at `MODEL_INDENT` 0.5 line heights, measured from the box of
the entry above; Trow hangs its ditto dash in the margin, so an entry at the margin under a ditto
line cleared it, and any false `cont` 1 (a table cell holding two entries, a model line running two
together) glued two people: `— Philippa sec 51 Front h Mt Vernon N Y Abbihl Jacob H h 408 W 150th`.
Now a `cont`-only join of a line that opens like a name (`Surname Given`) is measured from where
the entry's TEXT begins (the first word after its leading marks). Re-derived into scratch:

| volume | joins removed | kept lines |
|---|---|---|
| Trow 1909 vol 1 | 179 (165 net of re-joins) | 149,758 -> 149,918 |
| Trow 1908 p2 | 130 (114) | 140,242 -> 140,368 |
| Trow 1907 vol 3 | 102 (90) | 136,529 -> 136,627 |
| Trow 1903 p1 | 23 (18) | 151,421 -> 151,442 |
| Brooklyn 1905 p1 | 2 | 91,172 -> 91,174 |
| 1876BPL (control; prints every surname) | 0 | unchanged |

A uniform image-read sample of 32 removed joins: 30 two entries glued, 2 wrongly cut (a place-name
run-over `Glen Ridge N J`; `St Nicholas av`, the end of a printed line the dump had split). The
plan's version, every `cont` join measured from the text with no name test, was measured first and
REJECTED: 1,168 joins removed, and of 40 sampled, 22 glue and 18 real run-overs, because on these
respelled pages run-overs print at or near the name's x (`4th av Bklyn`, `& 110 Crosby`) and the
dump's boxes are a line height off in places. Pilot on both layers: no row changed. #32 (a)'s
proxy unchanged (it counts a different glue). Applies at a survey re-derive: D's import does one;
the damaged tier keeps its derive until one is decided (LINE_ASSEMBLY_HANDOFF step 8). Remaining:
glued lines that open with `&` or a given name only (a ditto entry whose dash was lost: `& Klute
plumbers`, `C & Co wines`), which this cannot tell from a run-over.

**(b) The invented heading DONE 2026-10-24; the rest measured, for a Torch decision** (LINE_ASSEMBLY_HANDOFF
step 5; in D's import). 5a: `untable` (hpc/lightonocr_tiles.py, which the import re-runs on every
`.raw.txt`) leaves out a row whose cells are all column words (`HEADER_WORDS`, counted from the
tier's own `<th>` rows: `Name | Address` 30, `Name | Occupation | Address` 26, `... | Notes`, `Name |
Age | Place`, `Name | Details` ...), while still counting it where it decides margins and packing,
so nothing else on any tile moves: over 7,951 table answers (this tier, the canary, the pilot), 171
tiles changed by exactly their heading lines, 177 -> 4 (the old count, 76, used a narrower word
list); pilot on both layers, no row changed. A first version that dropped the `<th>` row before
those counts flipped one Brooklyn tile's margin vote and lost its surnames, which exposed the next
item. 5b, per volume (`line_assembly.py tables --damage`; dashes by a 30-page sample a volume):
- **Cells holding two entries** (a model run-over in a table tile opening `Surname Given` within
  half a line height of the line above's text): 1,754 in 6,318 table tiles, 0.28 a tile, against
  0.16 a tile in plain ones, so ~740 more than plain tiles would hold; Trow 1903 p1-p3 (198, 148,
  116) and Brooklyn 1905 p1/c1905 (76, 83) lead. #32 (f) takes apart the ones under a ditto line.
- **`, ` invented by the field-split join**: 40,242 across the tier (Trow and Brooklyn print no comma
  after a name: `Abbihl Jacob H, h 408 W 150th`).
- **Ditto marks lost with a surname column**: untable drops a column of mostly 1-3 character cells
  as the next column's sliver, and a column of `“` dittos with a few surnames qualifies: 408 marks
  and 25 surnames, Brooklyn 1905 p1 237, c1909 71, c1905 66, Trow 1909 p2 34. Keeping such columns
  on the Mac was tried and rejected the same day: real slivers also hold the next column's dashes
  and surnames (`, B`, `, Brooklyn` appended to entries), and forcing field split joined a surname
  heading to its entry.
- **Dashes the layer saw that the cell dropped**: no more than in plain rows (table rows 0.05-1.2%,
  plain 0.05-2.2%); Trow 1909 vol 1 loses ~2% of its plain rows' dashes too, a `dittos` matter on
  its tesseract layer, not a table one (fixed: (g)).
Recommendation for 5c: the damage worth a re-read is the two-entry cells and the commas, on Trow
1903 p1-p3 and Brooklyn 1905 p1/c1905 above all (20-26% of their tiles in table mode). Re-read with
table output banned in decoding (vLLM `bad_words` on `|` and `<table`), first on the bench's 10
table tiles against gold, then this tier's 6,318 and D's table tiles in one job, once D's table
rate is known. **D's 41,904 table tiles DONE 2026-10-30 (round 11, recorded in #27 after the
table test): a clear gain, two-entry cells -39 to -43% on Trow 1915/1917/1922-23; banning tables
pushes 0.43% of tiles into a figure description, which the import now drops (`figure_only`).
This tier's 6,318 are next (a re-download at NYU).** The original finding:
**(b) LightOn in table mode merges entries in one cell and drops ditto dashes.** Same leaf 97,
tile c1_h1 (a Markdown table): `| Philippa sec 51 Front h Mt Vernon N Y Abbihl Jacob H h 408 W
150th |`, and `| Chas I ice 314 W 16th ... |` for a printed `—Chas I ice ...`. The import cannot
split what the model wrote as one cell. Table mode ran 20-25% of tiles on five volumes of this
tier (Brooklyn 1905 p1 and c1905, Trow 1903 p1-p3; see #27). **Recommended:** count, per volume, the
table-mode tiles whose cells hold two entries (a mid-cell `Surname Given` after an address), and if
it is more than a handful, re-read those tiles on Torch with a prompt or sampling that discourages
tables (a few hundred tiles, minutes of GPU), rather than trying to split cells on the Mac.

**(c) DONE 2026-10-24, narrower than recommended** (LINE_ASSEMBLY_HANDOFF §2 and step 3; in D's
import). Two causes on leaf 95, two changes in `reocr_pair.py`:
1. `split` gave words the layer never read to the longer piece by text likeness (`Fire Ins Co S4
   William` to a run-over whose first read word sits at the indent). `room_cuts` now puts them
   where the print has room: first where the layer saw print it could not read before line t+1's
   first read word (back only as far as the unread words could reach: a `«` in the margin 27
   characters out is not the line's opening, Brooklyn 1905 p1 leaf 163), then the end of line t
   up to the column edge. In that order because empty paper after line t is only room: where the
   model ran two entries together, line t is the first one's short last line (Trow 1909 vol 1 leaf
   245, `h,` + `—Edwd A salesman h 1537`). An image-read sample of what it changes at the survey: 10
   of 12 rejoin a run-over its entry had lost (`—Wilber W lawyer & notary` + `99 Nassau R 402 h New
   Rochelle N Y`).
2. `respell` laid unread words out at the line's own character width, inflated where ABBYY 8's
   boxes abut. Capping that width at the page's `char_w` (the recommendation) was measured and
   REJECTED: it moved 51,834 of Trow 1909 vol 1's line starts (mostly unread ditto dashes) and a
   sample of 24 survey-level changes read ~11 better, ~10 worse (a dash laid too far left had been
   keeping false run-overs below it from joining; an off-page line was what dropped a pairing
   failure's four-entry composite, leaf 681). Instead, only a leading run that would start left of
   its tile begins at the tile's edge, and only where it fits there at `char_w` and does not open
   with a ditto mark (a run that does not fit is not the line's text; a hanging dash belongs
   outside the column).
Leaf 95 now reads `Aabv ...` at the tile edge, `Aachen & Munich Fire Ins Co S4 William` + its
run-over `R 902, 95 William & 871 Brook av` (x 281, was -64), `Aal Siegfried` at the edge (was -43).
Lines off the page: Trow 1909 vol 1 107 -> 94, Longworth 1826 11 -> 9 (the rest open with a dash or
do not fit). Starts moved: 1,909 (Trow 1909 vol 1), 958 (1905 p1), 1,212 (Brooklyn 1905 p1), 27
(Longworth 1798), 64 (Longworth 1826). Survey, against #32 (f) alone: joins -53 / kept +99 (Trow
1909 vol 1), -42 / +30 (Brooklyn 1905 p1), -12 / +25 (Longworth 1826); samples on Trow 1909 vol 1
(12: 8 better, 4 neutral, 0 worse, e.g. leaf 161's two composites now six entries) and Brooklyn (12:
better or neutral). Pilot: IA's words no row changed; fresh tesseract 3 inexact rows re-read, no
exact row lost or gained. The original finding:
**`respell` places unmatched words left of the column, and the banner filter then drops the
line.** Trow 1909 vol 1 leaf 95, `Aal Siegfried clerk h 2 W 118th`: IA's words have nothing under
the name ("clerk h 2 W llStb" only), so `respell` runs `Aal Siegfried` leftwards from the first
matched word at a character width inflated by the garbled words, to x = -43; the line is then too
wide and `survey_harvest` drops it as `banner`. Present before and after `de9521a` (lines off the
page's left edge: Longworth 1826 11 and 11, Trow 1907 p3 47 and 47; 107 of 195,359 in Trow 1909 vol
1), about 0.05%. **Recommended (cheap, safe):** clamp a line's words to its tile's left edge (each
row already carries `x0`), and cap `respell`'s per-character width at the page's median `char_w`.
A re-import applies it; no GPU.

**(d) DONE 2026-10-24, as LINE_ASSEMBLY_HANDOFF §2 rediagnosed it** (a side banner's glyph inside an
entry's run, not a hyphen tail; step 4; in D's import). `reocr_pair.strays`: an inner printed line
of a model line's run whose layer text pairs with none of the entry's words, while what `split`
gave it is in a neighbour's layer text (`bers` in `bers Mhtn`), gives it back and is kept as a layer
row AFTER the entry's rows, so the entry's printed lines stay together for the joiner. Leaf 563 now
reads `Dornheim Chas lithographer 4 New Cham-` + `bers Mhtn h 155 Cornelia` (closed up by the joiner),
`U)` after. It reaches beyond the hyphen: Brooklyn 1905's banners split entries all down its pages.
Against step 3: survey joins +298 / kept -193 (Brooklyn 1905 p1), +29 / -17 (Trow 1909 vol 1), and
image-read samples of the derived differences, 12 of 12 (Brooklyn) and 5 of 6 (Trow, the other an
ad) an entry rejoined with its run-over (`CREIGHTON JOHN B sec Brooklyn League 44 Court h 148
Monroe`, `Otto razors 8 Reade Mhtn h 1010 Liberty av`); short fragments beside their run-over
(`line_assembly.py fragments`) 336 -> 273 and 157 -> 146 (most of the rest are real text the layer
held apart: `Mhtn`, `h`, `ton`). Pilot: IA's words one row better (lain 597 `... h 1875 Atlan-` ->
`... h 1875 Atlantic av`), fresh tesseract none changed; no exact row on either. The original finding:
**(d) A hyphenated word's tail, set as its own layer piece, is dropped as `short`.** Brooklyn 1905
p1 leaf 563: LightOn read `Dornheim Chas lithographer 4 New Chambers Mhtn h 155 Cornelia`; IA's
layer has `... 4 New Cham-`, then `bers` as a separate piece (x 338-401), then `Mhtn h 155
Cornelia`, so `split` gives `bers` a row of its own and the survey's `short` filter drops it,
leaving `... 4 New Cham-` / `Mhtn h 155 Cornelia`. `bers` and `Mhtn ...` miss the same-row rule by
half a pixel (middles 12 px apart, limit 11.5). Unchanged by `de9521a`. **Recommended:** a model
line's piece too short to stand (under ~5 characters, no digit) joins the neighbouring piece of the
same run rather than becoming a row; or, more simply, `split` never hands a single short fragment
its own row when the run has a longer neighbour on either side.

**(e) Counted 2026-10-24 and left, by LINE_ASSEMBLY_HANDOFF step 7's own rule** (its §2: mostly a
broken layer, the tilt part small). `line_assembly.py samerow` counts consecutive model lines of a
dump on one printed row (overlapping vertically by half the shorter height or more, the second
starting within 6 characters of the first's end): Longworth 1826 48 of 26,637 pairs (de9521a's
measure said 41), Trow 1907 p3 232 of 129,098, 1876BPL 174, Doggett 1845 25, Trow 1909 vol 1 735 of
169,041, Brooklyn 1905 p1 458 of 92,327, Trow 1905 p1 99, Longworth 1798 38: 0.05-0.5%, much of it ad
type set side by side. And these are not the tilt case: with equal heights, overlapping by half is
the same-row rule's own test, so such pieces were row-mates that no one model line covered (a
pairing matter); tilt can only leave a piece out of its row with unequal heights. The original:
**(e) The same-row rule assumes a level line; on a tilted page a right-hand piece joins the wrong
row.** Longworth 1826 leaf 409 (IA's words, badly garbled there): the printed line `Eakins John,
carpenter & grocer 219 Hester h. Rhynder` is three layer pieces, and the right-hand one sits 15-20
px off its left partners; the rule (middles within half the shorter height) groups some pieces with
the line above or below. Grouping reordered two pieces (`ilU carpenter &` before `219 Hester ...`),
and `align`, a global best path over the tile, shifted three lines up: `Eager & Tompkins, grocers
162 Spring`, one line before `de9521a`, became `Eager` / `& Tompkins ...`, and `Eakins Archibald`
went model-only. Caused by `de9521a`; rare (it needs a garbled layer and a tilted page), and the
volume's net is strongly positive (1,118 split lines repaired, 438 fewer unpaired layer lines, 11
more model-only). **Recommended:** compare a piece's middle with its row's anchor *after*
correcting for the column's measured line slope (fit it from the pieces' left and right ends, or
take `tiles`' angle when it is nonzero), and do not reorder pieces between rows whose membership
is borderline (within, say, 20% of the limit): keep the old top-to-bottom order there.

**(g) DONE 2026-10-25: firms under a firm name lost their ditto dashes on a dash page** (found by
5b's dash count; in C's re-import and D's import). `reocr_pair.dittos` follows a page's surname
chain and lets the chain overrule a dash the layer read when the word after it fits the chain. But
firms under a firm name are alphabetical too: Trow 1909 vol 1 leaf 149 prints, under `American`,
`—Round Bale Press Co`, `—Rubber Co`, `—Rug Co`, `—Safe Deposit Co`; once one of them was taken for
the head, the rest followed it and lost their dashes. Now, on a page where tesseract's dash leads a
tenth of the entries or more (`DASH_SHARE`, and at least 5), a dash glued to the word as tesseract
read it is a ditto whatever the chain says; the chain itself does not move. The gate is needed: a
first version without it made false dittos where a page prints every surname, from specks and star
marks (`—Alexander Malcolm` on 1876BPL 59 times, `*Townsend` on micro_IABROOKLYN_0035 17, Brooklyn
1905 p1's ad lines 7). Per page, glued-dash shares run 25-71% on Trow and 0.7-2.1% on those two.
Against the production dumps (629b27f), by line, the rest of the text identical:

| volume | ditto gained | ditto lost |
|---|---|---|
| Trow 1909 vol 1 | 788 | 20 |
| Trow 1903 p1 | 167 | 2 |
| Brooklyn 1905 p1, 1876BPL, micro_IABROOKLYN_0035 | 0 | 0 |

Image-read: 38 of 38 sampled gains print the dash (`—Printing Press & Mfg Co`, `—Ladies Waist Co`,
`—Cornelius J clerk`); of the 22 losses, 21 are heads the old chain had wrongly dittoed, and one
(`Stamp Co 79 Nassau`) may be wrong. Pilot on both layers against `s6`: no row changed apart from
the 13 lain gold rows trimmed the same day (GROUND_TRUTH_HANDOFF).

**(g) widened 2026-10-26, after C's re-import showed what the first version did to the joiner.**
C's 39 volumes re-imported at c07fe78 gained 25-115 joins a Trow part (Trow 1907 p2 40,793 ->
40,907). A line that gains its dash gains a box one dash left of its name, and a line under it
whose dash the layer did not read, its first word respelled a line height right of the name
margin, cleared the joiner's 3.0 (3.0-3.75 line heights from the dash box, 1.0-1.4 from the name):
`— Kaufman real estate 34 W 116th` + `Kever barber h 229 Henry`. 89 of 1907 p2's 104 new joins are
that. The lower lines are dittos the chain kept as heads, in two ways, and each is now a ditto:
1. **A dash tesseract read standing alone** (it passes `DASH_W`/`DASH_FLAT`) counts as the glued
   one does: under a surname that shares the given name's first letters (`— Max` under a `Ma`
   surname, leaf 803) the word follows the chain, and the chain overruled the dash.
2. **The given name of the ditto line just above**, with no dash evidence at all (the layer read
   `ax`), on a dash page: a second entry under that name (`— Moses clerk h 111 E 96th`, `Moses
   real estate h 268 E Bway`). It was "ambiguous" and kept a head.
Against the c07fe78 dumps, by line:

| volume | ditto gained | ditto lost | joins (before (g) / c07fe78 / now) |
|---|---|---|---|
| Trow 1907 p2 | 526 | 84 | 40,793 / 40,907 / **40,702** |
| Trow 1909 vol 1 | 157 | 0 | 36,530 / 36,548 / 36,538 |
| Trow 1903 p1 | 164 | 9 | 36,297 / 36,322 / **36,264** |
| Brooklyn c1912 | 132 | 21 | 8,850 / 8,872 / 8,857 |
| Brooklyn 1905 p1, 1876BPL, micro_IABROOKLYN_0035 | 0 | 0 | |

Image-read, uniform: 24 of 24 gains print the dash (`—Mfg Co faucets`, `—Hungaria`, `—Cath
dressmkr`), and 24 of 24 losses are heads printed without one (`Manookian Mousa`, `Pines Abraham`),
which a dash line taken for a head had put out of the chain's reach; rule 2 alone, 24 of 24. Of 24
derived-line differences (1907 p2 18, 1903 p1 6), 22 take apart glued entries (`— Thos artist` +
`Thos A plumber` + `Thos C butcher`) and 2 make a new one, where a dittoed line's dash hangs left of
a line whose own dash box the layer put late (`— Francis real estate` + `— Francis tailor`).
Pilot on both layers against `s8`: no row changed.
The re-import at 78c43be then moved Trow 1905 p1's listing start from leaf 117 (page 17: title,
abbreviations, then the first A entries) to 119. Two of the page's lines had become dittos,
`Aalholm Jos J` and the abbreviation `Atty`, whose layer tokens `-'Atlbolm` and `-'Attjr` pass
`tlead`'s standalone test on the whole word's box; without their A keys the page fell from 13 of
52 to 11 of 50 under `extend_edges`' 0.25. So "standing alone" is now `lone_dash`: the dash run
followed by nothing, by a mark Trow sets after its ditto (`—,` `—(` `—&`), by a speck read as `.`,
or by a lone `'`. Measured against 78c43be on four volumes: 6 dittos taken back, 5 of them heads
(`Aalholm`, `Atty`, `Oak` read `~>ak`, `Piemullo` and `Plate` read `-■`), one a real ditto
(`—Bertha pres`, Trow 1909 vol 1). A dashes-only test was tried first and rejected: it took back
17, 11 of them real (`—, Breitman & Co`, `—(apartments)`, `—Potito` read `-'`).

**Open: the joiner still glues a lost-dash line under a dash-led entry** (found with the above).
On Trow 1907 p2, 915 joins of a model-read start (`cont` 0) under a line that opens with a mark sit
under 3.0 line heights from that entry's TEXT; an image-read sample of 32 held 20 glued entries, 3
ads and 9 real run-overs (`Canaan Ct`, `Ridge N J`), so a text-measured floor would cost run-overs;
a floor of 1.75 suits Trow and not Brooklyn 1905, whose run-overs sit at 1.5-1.8 from the text
(`Mhtn h 50 Willow`), where Trow's glue sits. An entry-shaped text test (a capitalised word, three
or more tokens, a digit) fails there too (10 of 16 Brooklyn removals were run-overs the model wrote
as lines of their own). The model's `cont` separates them on Trow (9 of 10 run-overs `cont` 1, 6 of
6 glue `cont` 0) but not on Brooklyn. What is left is mostly a lost-dash given name the chain kept
"ambiguous" (2,156 such lines on 1907 p2, about 6 in 30 dittos; the rest ads, display heads and
run-overs, so "ambiguous on a dash page" is no rule).

**Open, found by the restage of 2026-10-25: `calibrate_indent` flips on a knife edge.** Re-importing
the 39 volumes of the 4B package with (c)-(f) moved a few dozen of 1876BPL's line pairs, and its
trough fell from 5.13% of the run-over mode to 4.98%, under `CAL_TROUGH_SHARE`'s 5%: the wrap
threshold went 3.0 -> 1.5 and added 3,497 joins. An image-read sample of 32: 12 real run-overs, 8
harmful (each listing page's running head, `858 STE`, glued onto its first entry; banners onto
entries; two entries), 12 neutral. Doggett 1845's trough moved between two near-equal bins (1.75
-> 1.5). Both are held where they were (`survey_harvest.WRAP_PINS`) and the package was staged so.
**Before D's import:** give the rule hysteresis (decline within a band around 5%, and prefer the
earlier trough bin on a near-tie), list every volume whose sidecar sits in that band, and consider
whether a re-OCR'd volume, whose model run-overs join on `cont` anyway, should lower its threshold
at all (#28: model starts share the run-overs' band). A running head should also never take a run-
over: it is the first line of a leaf, and `join_wraps` joins before the filters that would drop it.
**NOT done before D's import (2026-10-29), so do it before D's re-import after round 11:** that
import moved five thresholds -- 1869BPL and 1871BPL 3.0 -> 1.75, 1879BPL 1.25 -> 1.5, Trow 1915
1.5 -> 3.0, Trow 1917 1.75 -> 3.0 (Trow 1915/1917's joins fell 13%, BPL 1869/1871's rose ~6x
with `cont`). Each wants the image-read sample above before it stands.
**DONE 2026-10-29.** Each move read on a uniform sample of the joins only the lower threshold
makes (scratch `ratio_joins.py` + contact sheets through `iiif_frame.crop_url`, which Trow
1915/1917's camera frames need). The verdicts split, so no single rule decides: Trow 1915 and 1917
had gone to 3.0 because LightOn reads their `"` dittos (mark share 4% -> 41%), and 21 of 21 joins
that lost were real run-overs ("291 Bway R507", "jail h1431 Longfellow av"); Brooklyn c1910 (in C)
went 2.0 -> 3.0 the same way and was RIGHT to (4 of 4 entry joins at 2.0 glued two ditto entries:
its layer's box starts after the `"`, Trow's includes it). 1869BPL/1871BPL (mark share under 5%,
3.0 -> 1.75): 6 run-overs, 3 harmful (Eastern District `E` lines glued, a banner), 4 ad lines --
back to 3.0. 1879BPL 1.25 -> 1.5 was right (5 of 5 joins only 1.25 made glued the running head
onto the page's first entry). All six are in `survey_harvest.WRAP_PINS` with that evidence.
`calibrate_indent(prev=)` now has hysteresis (CAL_BAND 4.0-6.25% around both 5% gates, CAL_TIE 10%
on the trough bin), and `derive` prints `!!` for any volume whose threshold moves. The four D
volumes re-derived under the pins: Trow 1915 joins 270,985 -> 348,073 (scoped 1,068,146 ->
1,034,236), 1917 315,346 -> 397,184, 1869BPL 21,316 -> 19,453, 1871BPL 24,245 -> 21,394.
Found on the way: (1) a page's running head is joined onto its first entry whenever the threshold
is low enough (1879BPL at 1.25) -- **DONE 2026-10-29 (2e12fad)**, `join_wraps` refuses a run-over to
a page's first line when it is RUNNING_HEAD-shaped; at current thresholds it removes 25 joins over
eight volumes, all ad banners joined to ad fragments, so it is a safety net. And the browsing
report of the same day, a printed page of 45 for a page printing 445 (Brooklyn 1909 p1 leaf 901):
**DONE (427d31b)**, `survey_folios.repair_leading` puts back a dropped leading digit from the
sequence (1,970 leaves in 31 volumes, 198 of 203 agree with IA's read numbers, three wrong repairs
read on the page and guarded against: street guides that restart at 1); `printed_page_how`
gains `repaired`; (2) Trow's firm entries under a surname print
"—, Goldfarb & Metzger" (= Blumner, Goldfarb & Metzger), and where the dash is lost the line
opens ", " -- 7,930 such starts, 200-330 a Trow part, each naming the firm without its surname:
a #32 (g) lost-dash case for the comma form. **(2) DONE 2026-10-29 (6e2621c)**: `dittos` writes the
mark back at import (FIRM_COMMA on a dash or quote page, no evidence needed: a printed line opens
on a comma no other way; Trow 1910 p1 dry run: its 223 comma lines and nothing else), and
assemble_records restores it for the carry with the comma kept ("Hammel, Riglander & Co"), so C's
records are right without a re-run. With it, "•" became a fixed lead marker (#33).

**33. A run-over LightOn wrote as its own bulleted line stays a separate record (found 2026-10-29,
hadro, browsing).** `micro_IABROOKLYN_0043` leaf 110 (reocr tier): "PAYSON HENRY, Fire Insurance
agent, office Peck" / "• Slip ferry, h. 163 South 5th" -- the office is at Peck Slip ferry. Two
records, neither usable, the second named "-Slip". In the dump the second line is `model`, `cont`
0: LightOn's answer (`..._0110_c0_h0_lightonocr-3-1b-greedy-torch.txt`) writes "• Slip ferry" as a
new list item. Its indent is 277 px, ~3.6 line heights over the volume's 3.0, so the indent alone
would join it, but #30's `start_cap` keeps a model start from joining past the volume's run-over
reach, and `mark_continuations` (the split-entry pass, #28) did not flip it. To find out: which
guard refused it there (the leading "•"? `entry_shaped` on the ALL-CAPS line above? the leaf's
first entry?); then count, per re-OCR'd volume, model starts that open with a bullet ("•", "·", a
lone "-") and do NOT fit the alphabet between their neighbours -- a run-over's first word ("Slip"
after "PAYSON", before "Peacock") rarely does -- and read a sample against the images. Like the
ditto bullets (#27 "Dittos"), LightOn's bullet is list markup, not evidence of a new entry.
**CLOSED 2026-10-29, not fixable by rule.** The dot is PRINTED (or a film speck) and LightOn
copied it; it is not list markup (`BULLET` in reocr_pair matches only Markdown's "- "). The pass
never proposed the join: no grammar signal fires ("office Peck" is no ENTRY_TAIL, "• Slip" no
ENTRY_HEAD), and the dot leaves `name_key` empty, so the alphabet cannot speak either. Sized over
every re-OCR'd dump: 358 model starts open with a dot glyph (• · ∙ ● ▪ ◦), 209 not fitting the
alphabet. Read on the page (8 legible of 10): 7 are REAL entries, because Trow prints "•" before an
advertiser's name ("•Steil Dederick, produce", "•FORD FRANCIS W., city surveyor", "•VALLEAU MFG.
CO.", "•Berkefeld Filter Co 4 Cedar"); 1 is a speck before a run-over ("•Bklyn"). Joining dot-led
lines would glue far more than it saves. Two by-products: (1) Trow's "•" is an advertiser mark and
belongs with assemble_records' `name_mark` (strip it from name_resolved, as `*`); (2) a wider
first count, which let "," and "." lead, found the Trow firm-entry lost dash recorded under #32.

**34. Records whose name_resolved has no surname, and the carry they poison (found 2026-11-01,
hadro, tracing the residents of 596 Franklin av in the address finder, `space/`).** The trace of
"Saddington Wm S" also traced "Wm S", which matches 35 lines in 13 volumes, every one a ditto line
that kept its given names alone. Over the 5.41M rows of the address finder's Parquet (holdouts
and the run-1 Doggett copy out), **22,846 named lines (0.43%; 16,652 `usable`) resolve to a name
that opens with a given name the census list never has as a surname** (Wm, Jas, Chas, Robt,
Saml, Thos, Hy, Margt, Cath ...: `data_prep/names/given_harvested.tsv` with count >= 20, less
`surnames.tsv`; John, James and the like are not counted, so it is a floor). Upington's Brooklyn
1905-1910 run 1.5-2.0% a volume (3,118-3,796), Trow 0.09-0.46%, the early volumes under 0.1%.
Three ways, all in `resolve_dittos` (`can_set_carry`, `resolve_cross_line`):
1. **The mark lost or misread, and the line keeps its given names** (13,750 open on a letter,
   `Wm S printer h 45 Fort Greene pi`; misread marks such as 1906BPL's `•* Wm S letter carrier h
   596 Franklin av`, where `•` is now the advertiser mark (#33) and `*` is not a ditto). The strict
   gate makes such a line TRANSPARENT, so the carry is right below it, but the line itself never
   takes the carried surname.
2. **A given name inside the leaf's letters sets the carry** ("Robt" on an R page passes both of
   `can_set_carry`'s tests), and every ditto under it is wrong: `" Wm E cottongds 54 Leonard` ->
   "Robt Wm E", `" Hy smith` -> "Cath Hy", `" Thos C clk` -> "Thos Thos C". Most of the ~9,100
   ditto-marked lines with a given name where the surname goes (7,048 open on `"`).
3. **A first-letter misread across a page fails the leaf-letter gate for real surnames.** 1906BPL
   leaf 575 reads K as R (`Rerby Chas`, `Rerans Frank L`, `Rerbel Benj`); each is transparent, so
   the carry runs on from `Keohan` 47 lines up and `" Frank E ins 1 Madison av` comes out "Keohan
   Frank E" (Kerby in every other year). 1906BPL is run 1's IA text, which D replaces, but the
   gate is the same everywhere.
The OCR side is known and separate (table-mode tiles drop ditto columns, BOOKSCAN_HANDOFF; #32
(g) restores tesseract-read dashes at import for the re-OCR'd Trow parts); this is the assembly
side, and covers every tier. **Plan:** (a) a given-only name cannot set the carry; (b) a line with
no ditto mark that opens on a given-only name, under a carry, takes the carried surname and a new
`ditto_flags` entry `mark_lost`; (c) maybe: let the leaf-letter test accept a lead whose first
letter is a common OCR confusion of the leaf's (K/R, E/F, C/G), measured before it is kept.
Measure each against `results/carry_rules.py` (agreement with the printed headers) and the gold
before re-assembling the tiers; then rebuild `browse.db` and `data/space/records.parquet`.
**(a) + (b) BUILT 2026-11-01 and RE-ASSEMBLED the same day** (run 1, reocr, damaged tiers):
`usable` and `named` unchanged in every tier; `mark_lost` 2,764 (run 1) / 780 (reocr) / 9,447
(damaged); carried dittos reocr 35,025 -> 35,830, damaged 3,388,579 -> 3,398,026. The summary's
`disputed` keeps its meaning (cross_leaf / letter_conflict only; `mark_lost` is counted apart) and
moves 1,995 -> 2,134 and 170,205 -> 172,263, the new carries' own page and letter flags.
Re-counted the same way as the 22,846 above (browse.db and the address finder's Parquet rebuilt):
**5,469 named lines (0.10%) now open on a given-only name, 4,066 `usable` (were 22,846 / 16,652)**.
596 Franklin av traces cleanly: 1906BPL's `•* Wm S letter carrier` is Saddington Wm S, and no
"Wm S" trace; its `" Frank E` (leaf 575) is still wrong, "Keough Frank E" now -- way 3, open.
The build, as measured before it: `resolve_dittos.given_only_names()` (55
names: given_harvested >= 20, less surnames.tsv, less `NOT_GIVEN_ONLY` -- titles, `Virginia`
which heads the "Virginia Iron, Coal & Coke Co" block, and given names the city printed as
surnames too, Leon, Felix, Elias ...), passed as `resolve_cross_line(given=)`; default empty, so
every earlier number reproduces. `assemble_records` passes it. `carry_rules.py` (now over the
damaged tier too, 82 volumes) against strict + heads: **13,009 lines take the carry
(`mark_lost`), 6,022 dittos change surname** (1906BPL 2,753 + 120; Upington's 1905-1910
1,137-1,617 each). Agreement with the printed headers 81.94 -> 82.14% (n = 31,040; 20 volumes up,
none down) -- headers open blocks, where this rarely acts, so it is a floor test, not the gain.
Read on the page (8 at random, context crops): 2 confirmed (`—Thos h 119 E 95th` under the
printed THORP header, was "Thos"; `" Wm H acct` in the Janes block, was "Jas"); 5 replace a
given name or nothing with the block's carry, whose head is above the crop; **1 wrong**: Brooklyn
c1905 leaf 1105 is a block of lost-mark lines whose given names are also surnames (`Webster M`,
`Wellington`, `Western W`, `Wilbur`), so `Wilbur` still sets the carry and `Wm brass` becomes
"Wilbur Wm" (it was "Wm"). Known costs: ad copy opening on a listed name takes a surname too
(`Charlotte Russe` -> "Murphy Charlotte Russe"; not entry-shaped, so not `usable`); a given
name under the 20-count cut still sets the carry (`Susan`, `Marg’t`). Open: (c), and a block of
lost marks whose given names are surnames as well (the Wilbur case; maybe the given-name ORDER
inside a block, which is sorted by given name, can tell it from a run of surnames).

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

> **Headers put back, and the carry gated — 2026-10-20 (`fb1a020`; `results/carry_rules.py`).**
> Found from the browser (`browse/`), not from this item: `" Harry engineer` came out
> `millions— Harry`, its surname planted by an ad at the foot of 1906BPL leaf 26, because leaf 27's
> `ANDERSON` header — the line that names the column — is one of the drops above. So
> `resolve_cross_line` gained `heads` (the dropped headers, placed by position, no follower test)
> and `strict` (only a capitalised surname inside its leaf's letters may set the carry); Stage 5
> describes both.
>
> **The 2026-09-13 measurement above understated the headers**, because it counted only the
> ditto right after one (1,392). A header names every ditto down to the next surname line:
> **42,470 of 1906BPL's 135,864 carried surnames now come from one.** No gold holds the carried
> surname for these volumes, but a printed header IS that fact, so at every header the carry was
> asked what it would have said without it:
>
> | | 1906BPL | Brooklyn 1912 | all 44 volumes |
> |---|---|---|---|
> | carry agrees with the printed header (n = 1,802) | 47.8% → **84.8%** | 17.0% → **60.9%** | 41.3% → **79.8%** |
> | disputed share (largely by construction) | 23.2% → 6.6% | 39.0% → 5.5% | 26.3% → 6.4% |
> | ditto rows whose surname moved | 33,349 | 16,515 | 50,128 |
>
> Twelve moved rows drawn at random all came off junk (`Wallabout`, `Corner`, `Street.`, a given
> name whose mark dropped); of six read on the page four were confirmed, one unreadable, one
> wrong and fixed (ENNIS over the OCR'd `iimnis Adam`, which is why there is no follower test).
> Two first drafts of the letter test failed on real pages and are recorded in
> `leaf_letter_ranges`: the leaf's own vote, and one sorted run per volume (micro_IABROOKLYN_0036
> prints a second alphabet). **Known cost:** an entry whose first letter the OCR lost (`rntzen` =
> Arntzen) is refused as lowercase, so its dittos take the surname before it — 184 rows in
> 1906BPL. **Still open:** the column-break reset this item proposed, and the implied-surname
> detector above — `strict` catches a mark-less given name only on an off-letter leaf (`Geo` on
> an A page), not `Jas` under a J surname.

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

| **merge: Sauvola's lines, the higher-confidence reading of each** | 92.2% | **34.5%** | 93.0% | **43.9%** | 5.2% | 2.7% | **80%** |

The merge (`reocr_bench.py merge --rule conf`) keeps every line the Sauvola run found. Where the
contrast run read the same printed line (boxes overlapping, texts ≥ 0.6 alike), the merge takes
whichever reading tesseract was more confident of. That brings back the small tokens Sauvola
drops, a point above IA's abbreviation retention, at a cost of 1.5 points of line recovery.
Adding lines only the contrast run found changed nothing. **That merge is engine 1's result:
92% of the book scan's lines against IA's 54%, and 44% of the gold lines exactly against 24%.**

**Engine 2 measured 2026-10-06: Churro-3B, a 3B vision model trained on historical documents,
on the M2's GPU** (`historical-ocr-eval/engines/run_churro.py --device mps`, unmodified;
`reocr_bench.py import --slug churro-3b --from-raw`).

| run | pages | close | exact | gold close | gold exact | junk | invented | abbr kept | boxed |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| IA's microfilm OCR | 48 | 53.6% | 19.8% | 55.3% | 23.9% | 3.6% | 2.3% | 79% | yes |
| tesseract merge | 48 | 92.2% | 34.5% | 93.0% | 43.9% | 5.2% | 2.7% | 80% | yes |
| Churro-3B, body lines | 42 | 95.3% | 63.6% | 94.9% | 77.3% | 3.4% | 3.0% | 94% | no |
| **hybrid: merge's lines and boxes, Churro's text** | 48 | **96.1%** | 59.0% | 95.7% | 76.6% | 4.7% | 2.6% | 92% | yes |

- **Churro reads characters far better**: nearly double the merge's exact lines, and 94% of
  abbreviations kept. Its "descriptive lines" ("Single page from a printed directory.") were not
  hallucinations. Churro answers with an XML document whose `<Metadata>` describes the page,
  and the runner's flattening kept that as text. `body_lines` keeps only the `<Body>`'s `<Line>`s,
  which takes junk from 7.4% to 3.4%, below IA's. Sampling was never the lever: the checkpoint's
  defaults are near-greedy (temperature 1e-6, repetition penalty 1.05).
- **It gives no boxes, and on dense pages it does not finish.** 6 of 48 pages hit the runner's
  15-minute cap: every Brooklyn 1857–58 page and one Smith 1855 page. Pages took ~5 minutes at
  ~50 lines and 10–29 minutes at ~140 lines on the M2, so the 39 deferred volumes (~7,750 pages)
  are not a laptop job.
- **The hybrid** (`reocr_bench.py hybrid`) keeps the merge's lines and boxes and takes Churro's
  reading of each line it also read, falling back to the merge where Churro timed out. That gives
  the best line recovery, Churro-level accuracy, and a box on every line.

**Engine 3 measured 2026-10-14, with the `historical-ocr-eval` session: LightOnOCR-3-1B
(Apache-2.0), and it replaces Churro.** Four things changed how the engines are compared:
- **The references are entries.** The gold and the book scan's lines are wrap-joined and
  de-hyphenated ("Graham av. n. Mar-" + "shall" -> "Marshall"), so a printed-line engine paid for
  every run-over. `data_prep/reocr_pair.py score` joins each engine's lines the way the reference
  does (guided by it, never changing a character) and writes E marks one way.
- **The pairing replaces the hybrid.** `reocr_pair.py` aligns each model line to a run of 1-3
  tesseract lines in the same tile (an in-order alignment), splits its words back over those
  printed lines, keeps tesseract's hyphen, and puts back the "E" (Eastern District) mark tesseract
  saw (a small or glued token). The hybrid's continuation lines had kept tesseract's text.
- **Tiles.** Each column is cut in two at the whitest pixel row near a gap between lines
  (`reocr_columns.py stage --tiles halves`), kept at native resolution.
- **Post-passes** (`reocr_pair.py post`): an 1840s "[x" turnover goes back to the entry above, and
  a fraction glyph after a digit becomes "1/2" as the gold writes it.

On the 42 pages both engines finished (8 gold pages, 532 lines; 2,503 book-scan lines):

| run | gold exact | gold close | book exact |
|---|---:|---:|---:|
| **LightOn-1B, half tiles, paired + post** | **93.4%** | **100.0%** | **75.5%** |
| Churro-3B, whole page, paired + post | 91.5% | 99.4% | 72.5% |
| the hybrid (Churro, before this) | 82.9% | 97.0% | 69.8% |
| tesseract merge | 38.9% | 95.5% | 34.4% |

LightOn reads 104 book-scan lines Churro misses against 48 the other way (exact McNemar
p = 6.5e-06); gold leans the same way (24 / 14). The pairing costs nothing and beats the hybrid
for either model (Churro 36 / 1, LightOn 58 / 12 discordant gold lines). Greedy decoding matched
three sampling seeds on gold (93.6% against 93.4% for each, 0-1 discordant lines), so production
is greedy and reproducible. E marks: 83% found, 94.5%+ of those written are real; nearly every
miss is a mark tesseract never saw. A pixel test at each line's left end raised that to 88% with
a few false marks, so it is not in v1.

Failure modes found, each handled:
- **Table mode.** On ~6% of tiles LightOn writes a table with an invented caption. The runner's
  `untable` drops the invention and rejoins field-split rows. The table may also come as HTML (7 of
  410 saved answers), with a column of one-letter cells beside every entry: the next column's
  sliver past the rule ("H", "S"), or row numbers it invented. `untable` reads HTML rows too and
  drops such a margin column (2026-10-14). The import flattens every answer again from its
  `.raw.txt` with the runner's own `to_lines`, so the fix reaches answers made before it.
- **Bleed-through loops.** The reverse page shows through and the model repeats to the token cap
  under any seed. The tile is read once more on its darkest 10% of ink (`bleed_retry`, digits less
  sure), else cut back to before the loop (`loop_truncated`).
- **Churro invents E marks** (67 written for 40 printed) and reads worse on native-resolution half
  tiles than on its 2,500-px column crops.
- **The half cut.** Where tesseract's boxes span two rows, cutting at the gap between box rows put
  1 line in one half and 83 in the other; the cut is now made by ink.

**A no-gold screen of the 39 deferred volumes** (none is on the bench: 2 pages each, 188 tiles)
found no collapse. LightOn wrote 0.83-1.06 lines and 0.91-1.16 characters per tesseract line, and
the 1820s single-column volumes read as cleanly as the bench. One tile looped on bleed-through,
and the long lines it flagged were advertisements printed as prose.

**The Torch run** (`hpc/39_lightonocr_setup.sh`, `hpc/39_lightonocr.sbatch`) uses
`hpc/lightonocr_tiles.py`: historical-ocr-eval's runner, vendored with its pinned library versions,
reproducing a bench tile byte for byte. Its first task re-reads the 138 bench tiles and the screen
pages' production tiles on CUDA in bf16. That scores gold under the deployed setup and checks
greedy's loop rate on the unseen volumes before the 7,947 pages run.

**When the answers come back** (slug `lightonocr-3-1b-greedy-torch`):
1. Task 0: `reocr_pair.py bench <slug> --kind halves`, `post <slug>-halves-paired`, then `score`
   it beside `lightonocr-3-1b-halves-paired-post` (the M2's reading) and Churro.
   **Done 2026-10-15** (job 19897894_0, an L40S, 326 tiles in 25 minutes):
   - Scores: 93.6% of gold entries exact and 100% close; 75.5% of book-scan entries exact. That
     is one gold line better than the M2's 93.4%, none worse.
   - Outcomes: 0 failed, 0 empty. The one loop (0047 leaf 90) was rescued by the bleed retry.
     Table mode came up on 10 of 138 bench tiles and 4 of 188 screen tiles.
   - Screen pages: 278 dittos on 1912 against the M2's 280, and the gate admits "—".
   - Cost: median 4.05 s a tile, so the 20,712 tiles take about 28 L40S-hours, 24 minutes a task.
   - Two packaging gaps NYU worked around, now fixed: the setup script links `$PROJECT/bin/uv`,
     where the job looks for uv when its PATH has none; and tars made on the Mac take
     `COPYFILE_DISABLE=1`, since the tiles tar carried a `._` AppleDouble file per tile.
2. After the full run: `reocr_pair.py dump <slug> --root data/reocr_halves` writes each volume's
   word dump, keeping IA's as `<id>_words.ia.jsonl.gz`. Then `survey_harvest.py --rederive --ids
   <the 39>` and `survey_derive.py` re-read the volumes.
   **Done 2026-10-15** (job 19954791, 70 tasks on L40S, 28.9 GPU-hours):
   - Answers: 20,691 of 20,712 tiles. The 21 empty ones keep tesseract's lines; greedy would
     read them the same way again, so they were not retried. 44 tiles looped: 39 were rescued
     by the darkest-ink retry, 4 cut back.
   - Survey totals: kept lines 268,422 to 566,402, and scoped listing lines 220,682 to 518,537.
     The largest gains are where IA's OCR had failed: 1912 8,736 to 53,883; 0039, 0040 and
     0042 each 8–16k to 52–60k.
   - Ditto: 1912's gate admits "—" (24,204 lines). Listing bounds are unchanged; 10 of the 78
     page claims moved, none of them written to the CSV.
   - Three forms the bench had not shown, fixed in the import:
     - LightOn's glyphs for the small E (4,567 lines of 0039, 0040, 0042);
     - turnovers on lines of their own (~300 lines);
     - 1912's firms under a surname ("— & Oest"), which had lost their dash and let the gate
       admit "&".
   - The run-health summary flags 0022 (16% table mode) and 0047 (bleed-through, 3% looped).
   - Tiers (hadro, 2026-10-15): the 39 left `defer` for a tier of their own, `reocr` (505,965
     lines, ~12 H200-hours), which stages with the first tier: `prep_volumes.py --corpus --tier
     first,reocr`. `defer` is now empty.

**Beyond the microfilm: a pilot on the real-OCR panel (2026-10-15, hadro).** Should the other
tiers be re-OCR'd too? LightOn read the gold pages of the panel's 16 IA book-scan volumes on
the M2. The pages went through fresh tesseract and half tiles, then the production import,
`survey_harvest.derive` and `eval/ia_panel.build`, into `data/iapanel_lighton/`. The driver
is `eval/lighton_pilot.py` (since 2026-10-16). The staging tools and the dense-page re-cut stayed
in that session's scratch; their output is in `data/reocr_pilot*`.

Lines against gold, with typography set aside (curly vs straight quotes, one leading ditto
form), over 2,029 rows:

| | IA's OCR | LightOn |
|---|---|---|
| Pooled, exact | 59.1% | 82.0% |
| Pooled, CER | 0.023 | 0.011 |
| trow1907 (ABBYY-8 damaged) | 10% | 87% |
| Polk 1917 in Trow 1917 (ABBYY-8 clean) | 46% | 73% |
| Lain 1897 (ABBYY-9) | 70% | 83% |
| lain1876 | 60% | 95% |
| rode1851 | 64% | 98% |
| ogden1839 | 28% | 93% |
| mercein1820 | 53% | 92% |
| duncan1794 | 26% | 81% |
| Smith 1855 (book scan) | 77% | 92% |
| Smith 1856 (book scan) | 68% | 83% |
| franks1786 (long s) | 2% | 43% |

historical-ocr-eval scored the same engine on its 18-volume ranking panel (2dc7296). Leaving out
two badly cut pages: CER-all 0.024, match 99.3%. Gemini on the same volumes is 0.145 as run, and
0.027 on the lines it does not refuse.

What a book-scan batch needed, done 2026-10-16 (hadro asked for all three):
1. **Columns on dense pages** (d544fd5). The old cropper treated M&B's repeated-surname stripe
   as a banner and dropped it, and split Polk's columns at their `"` stripe. Book scans now use
   `reocr_volumes.gutter_columns`:
   - A gutter is a valley in how many words cross each x, measured off the top and bottom ads.
   - A stripe's white strip is told apart by its straight left side.
   - Staging takes each volume's most common count (ties to the larger, `columns.json`) and cuts
     every page to it, unless a forced gutter runs through text.
   - The pilot's 63 pages: the right count on 60. With the volume's count, the dense pages cut
     no entry words.
   - The import reads the staged boxes (`boxed_lines`): identical to `column_lines` on 1,000 of
     1,000 microfilm pages.
   - The microfilm volumes keep the old cropper (`column_method`).
   - The pilot's polk1933bk and queens1933 cuts were wrong because they forced 3 and 4 columns;
     those pages print 5.
2. **Camera frames and line geometry** (d24fa33, 6a5837e, fc46ac8).
   - `reocr_volumes.page_job` stages Trow 1915/1917 upright: turned by −rotateDegree and cropped
     to scandata's cropBox (`iiif_frame.upright`), checked by eye both ways.
   - The import now:
     - moves an entry start (by LightOn's reading) to its column's margin, but only where
       tesseract missed the line's opening (6a5837e). Moving every start broke Smith 1855
       (92% → 84%): LightOn sometimes writes a run-over as a line of its own ("Brunt"), and
       the move took away the indent that joins it to its entry.
     - reads that margin off the entry starts within 12 line heights (fc46ac8). Trow 1917's
       camera frame is skewed about a degree: its first column's edge runs from x 196 at the top
       to 122 at the foot. One margin for the whole column put the moved starts in blank paper.
       The starts tesseract read then looked indented and were joined on as run-overs.
     - clamps normal-width words in boxes three rows tall;
     - keeps unread words inside the column's tile.
   - Polk 1917 in Trow 1917: 59 → 70 of 72 rows, 73% → 84% exact, CER 0.033 → 0.011. Smith 1855
     stays at 92%.
   - The pilot re-run under fc46ac8: pooled 82.3% exact, CER 0.010, over 2,062 rows. Against the
     table above, only Polk 1917 moves by more than a row.
   - It also recovers lines on the microfilm (0040's trial: 54,621 → 56,254 kept), so the 39
     volumes were imported again under fc46ac8: kept lines 566,403 → 576,992, scoped
     518,537 → 529,126. Against a single margin for the whole column, the totals move by 26.
     The joins change, though: on 1912, by LightOn's reading, there are 72 fewer false joins
     and 49 fewer real ones.
3. **Batched decoding** (822de99): `hpc/lightonocr_vllm.py`, run by `hpc/39_lightonocr.sbatch` with
   `ENGINE=vllm`; setup with `ENGINE=vllm bash hpc/39_lightonocr_setup.sh` (vllm 0.30.0).
   - Unchanged from the per-tile runner: tiles, resize, prompt, greedy decoding, cap, loop
     handling and output files, many tiles at a time.
   - **Parity run DONE 2026-10-16** (NYU job 20083721_0, L40S, the same card as the `-torch`
     task 0; answers under slug `lightonocr-3-1b-greedy-vllm`). **Batched decoding is trusted.**

     | the same 326 tiles | per-tile (`-torch`) | vLLM |
     |---|---|---|
     | gold entries exact (532 lines) | **93.6%** | **93.6%** |
     | book entries exact (3,174) | 74.6% | 74.4% |
     | E marks found / written | 173/210, 183 | 173/210, 183 |
     | decode | 1,504 s (4.61 s a tile) | **189 s (0.58 s)** |
     | failures, loops, bleed retries | 1 loop, 1 retry | 0, 0 |

     Greedy is **not** bit-reproducible across the two: 105 of 326 tiles differ. But the
     differences are a wash — on gold, 5 lines right where the other is wrong and 5 the reverse,
     and 354 changed lines one way against 364 the other. Most are a straight vs curly
     apostrophe or a comma; a few are real misreads in both directions ("26 Grafton" /
     "26 G. Smith"). A LaTeX-style fraction (`165$frac{1}{2}$`, which `fractions()` does not
     catch) appears once under `-torch` and twice under `-vllm`, so it is a model quirk, not an
     engine one.
   - **A caveat NYU raised, and it is real.** vllm 0.30.0 declares `transformers>=5.10.4` with no
     upper bound; its `pixtral.py` imports `PixtralRotaryEmbedding`, renamed by transformers 5.19,
     so the first attempt died before the engine started. They pinned `transformers==5.14.1` (5.19
     would not have worked). So `-vllm` ran under 5.14.1 and `-torch` under 5.19.0, and the
     comparison above is engine *and* library. Since the two agree to within noise, the
     confound does not change the conclusion — it would only matter if they had disagreed.
   - **Cost.** At 0.58 s a tile the 20,712-tile corpus is ~3.3 GPU-hours of decode against the
     28.9 the `-torch` run cost. Engine init is ~199 s per task and fixed, so the 70-shard layout
     adds ~3.9 h of it: **~7.2 GPU-hours as sharded, ~3.9 at ten shards of ~2,000 tiles.**
     Re-shard before any further re-OCR.

**End to end: the 4B on the LightOn panel (NYU job 20035169, 2026-10-16).** NYU ran `4b-100k` over
the pilot panel as staged on 2026-10-15: 17 sets, 2,029 rows, built with b5495c9's import.
That staging had since been overwritten by the restage under fc46ac8, so it was rebuilt from
b5495c9 in a worktree:
- 15 of 17 chunks match the SHA-1s NYU recorded, byte for byte.
- Polk 1917 and trow1907 do not; the `"` ditto rule changed between the pilot run and its commit.
  Their rows still line up (59 and 68), and every prediction's words are in its row's line but
  one, whose gold row is the same.

Panel rows are in `data/iapanel_lighton_b5495c9/`, predictions in
`data/volumes_panel_lighton_b5495c9/`, and the score in `results/ia_panel_lighton_run1.json`.
Whole-row EM below is guarded (copy guard). "Clean" is the 4B on gold's own text, a ceiling for
the OCR. IA's figures are panel run 3's.

| Set | IA's OCR | LightOn | Clean |
|---|---|---|---|
| **Pooled, guarded** (2,012 / 2,029 rows) | **55.2** | **67.2** | |
| Pooled, raw | 50.7 | 62.3 | |
| Pooled, the 1,969 gold rows both deliver | 55.7 | 66.6 | |
| trow1907 | 7.4 | 60.3 | 83.8 |
| ogden1839 | 35.0 | 85.5 | 92.7 |
| mercein1820 | 63.3 | 86.7 | 90.0 |
| duncan1794 | 50.0 | 79.3 | 81.0 |
| lain1876 | 67.0 | 85.4 | 85.4 |
| rode1851 | 54.7 | 75.5 | 75.5 |
| boyd1890 | 73.0 | 88.0 | 90.7 |
| Lain 1897 | 63.9 | 67.1 | 78.2 |
| Polk 1917 in Trow 1917 | 48.6 | 54.2 | 64.4 |
| Smith 1855 / 1856 (book scans) | 48.6 / 50.2 | 53.0 / 55.5 | — |
| hopehenderson1856 (0035, microfilm) | 0.0 on 7 rows | 58.2 on 55 | 65.5 |
| franks1786 (long s) | 26.8 | 69.6 | 83.9 |

What it shows:
- No set does worse. On lain1876, rode1851, doggett1846 and duncan1794, LightOn input matches
  clean text, or comes within two points of it. There the OCR has stopped being the limit, and
  the model is.
- The copy guard broke long s on LightOn input. LightOn writes "ſ"; the 4B writes "s", as gold
  does; the guard then restored the printed "ſ". franks1786 lost 16 fields to it, 66.1 → 48.2,
  and the durs twin 7. **Fixed the same day (#29):** the guard folds ſ to s when it compares, and
  franks1786 is 69.6, pooled 66.2 → 67.2. The table above is after that fix.
- The restaged panel (fc46ac8, 2,062 rows) adds 11 of Polk 1917's rows. Scoring them needs
  another 0.1 GPU-hour job.

Still open:
- Long s stays weak **in the OCR** (franks1786, 43% of lines exact), which is a separate problem
  from the guard's handling of it (#29, done).
- A printed line tesseract splits at a wide gap stays two lines. Trow 1907's "Jucker Bernard
  designer 260 W" loses "Bway" this way. On the pilot pages, most such splits are running heads
  and ads, not entries.
- Row EM for #28 (the joiner taking LightOn's reading) needs another stage-B run; the change is
  measured on gold at the line level only.

Cost at the full run's 0.19 L40S-seconds a line, one tile at a time, before batching:

| Tier | Lines | L40S-hours |
|---|---|---|
| abbyy8-damaged | 4.0M | ~210 |
| first | 5.5M | ~290 |
| abbyy8-clean | 5.1M | ~270 |

(Batched decoding, item 3 above, cuts these about eightfold: at the parity run's ~0.02
L40S-seconds a line the three tiers are ~80–120 GPU-hours, against ~566 for the 4B extraction
that reads them. That is an extrapolation from microfilm tiles; the canary below measures it.)

**DECIDED 2026-10-20 (hadro): re-OCR the book-scan tiers BEFORE the 4B reads them.** Extracting
IA's text first would pay for the 4B twice. Order: a four-volume canary, then abbyy8-damaged,
then first and abbyy8-clean.

**Book scans need no tesseract: IA's own words are the layer (2026-10-20).** The microfilm ran
tesseract because IA's OCR of the film was dead. A book scan's ABBYY OCR is damaged in its
characters, not its geometry, so its words can carry LightOn's text. Measured on the pilot with
the same LightOn answers and tiles, only the word layer swapped
(`data/reocr_pilot_pages_ia`, IA's words with side bands stripped):

| | fresh tesseract | IA's words |
|---|---|---|
| Pooled, exact (typography aside) | 82.8% (2,062 rows) | **83.6%** (2,067 rows) |
| Polk 1917 in Trow 1917 | 84.3% | 88.9% |
| Lain 1897 | 84.0% | 85.8% |
| ogden1839 | 92.9% | 95.0% |
| boyd1890 / Smith 1855 / trow1907 | 96.0 / 92.4 / 88.2 | 94.6 / 91.8 / 86.8 |

33 rows gained, 11 lost. The losses are Boyd's known same-address false matches, two run-overs
left unjoined, a neighbour column's scrap and a doubled "N J". It took two fixes in
`reocr_pair.py`, neither of which moves a tesseract-layer row (the baseline panel is unchanged
but for a few box edges):
- **The volume's confirmed ditto forms are evidence** (`confirmed_marks`, from
  `ditto_decisions.json`). ABBYY-8 reads Trow 1917's `"` as "ii" (188 of leaf 688's entries) or
  "n", and without them Polk 1917 lost every ditto: 84% → 12% exact. A standalone first token in
  the set counts as a quote mark under the same page gate. None of the 39 microfilm volumes has
  decisions, so their import cannot change.
- **`respell` lays a name over garbled words where they are**, not leftwards from its first
  anchor. ABBYY read Lain 1897 leaf 45's "Allenburg Chas." as `i !^U«S-£has-`; the name was
  placed 140 px left of the column's margin and the joiner glued three entries into a line the
  banner filter dropped (5 gold rows).

So the book-scan path has no CPU stage at all: `data_prep/reocr_books.py pages` writes each listing
page's record from IA's dump (side-band scraps stripped first, as the ingest strips them, since
after pairing they carry the model's text at confidence 90) beside its image from the volume's
`_jp2.zip`, and `reocr_columns.py stage --pages data/reocr_books` cuts the tiles. And the
three remaining tiers' images are ~75 GB of zips (114 volumes, ~100k listing pages, measured off
IA's file lists), which the Mac cannot stage, so the full run cuts its tiles on Torch.

`gutter_columns` also cut the longest entries short: the outer edges were the text's 1st/99th
percentiles, and 0.14–0.35% of the canary's words fell outside every tile, mostly an entry's last
address word ("h. 26 Whitehall" on Longworth 1826, where ABBYY had boxed only "Whit*"). The outer
columns now reach the ends of the lines that start inside the text, plus `OUTER_SLACK` characters
(1 left, 6 right), within `OUTER_REACH` of a column, and on the left within `OUTER_LEFT` = 3
characters, since further out is the verso's show-through. Words outside every tile on the right:
1876BPL 1,245 → 62, Doggett 645 → 0, Longworth 603 → 56, Trow 1907 p3 463 → 2; what is left is
specks. A sliver of a side-banner advertisement can now come inside a tile (Boyd): look at Boyd's
tiles before its tier runs.

**The canary, staged 2026-10-20 and not yet sent:** Doggett 1845 (first; prints 61,333 names; run
1 read it from IA's text at 0.984 usable records per printed name, so it is a before/after),
1876BPL (first; 114,724), Longworth 1826 (abbyy8-clean; 27,000) and Trow 1907 p3 (abbyy8-damaged;
the trow1907 gold's edition). 2,304 pages, 8,908 half tiles at the volumes' catalog column counts
(2, 2, 1, 3), 5 shards of ≤2,000 in `data/reocr_books_halves/`, packed as
`cde-lightonocr-books-canary.tar` (4.07 GB, sha256 af1d21d9…72aa). The densest tile holds ~3,800
characters (~1,900 tokens of the 4,096 cap). Runbook artifact
https://claude.ai/artifact/9jx1ZeAycJR572kHrWdYv5 (private; share before sending). When the
answers land: `reocr_pair.py dump lightonocr-3-1b-greedy-vllm --root data/reocr_books_halves
--page-dir data/reocr_books --ids <the four>`, `survey_harvest.py --rederive --ids`,
`survey_derive.py`, then stage the four for the 4B (~240k lines, ~9 GPU-hours). Its done-criterion
is records per printed name against the three stated counts, and Doggett 1845 against its own
0.984 from IA's text.

**THE CANARY CAME BACK 2026-10-21 (NYU job 20525205, 5 L40S tasks) and is imported.** 8,907 of
8,908 tiles answered, 9 loops (0.10%; 8 in Trow 1907 p3), **0.53 s a tile** (1876BPL 0.40, the
Doggett task 0.71), engine load 77-82 s, ~1.6 GPU-hours. At that rate the three tiers' ~470k
tiles are **~70 GPU-hours** of decoding. The one EMPTY tile (1876BPL leaf 905 c1_h1) is LightOn
writing 36 entries as ONE Markdown table row, which `untable` cannot split; the tile keeps IA's
lines. 1876BPL went to table mode on 796 of 4,042 tiles (20%), because Lain prints an ad down the
page edge and LightOn sets its scraps in a second cell ("G"); the flattening keeps the entries.
LightOn's own notes ("Type: table", "Advertisement", "Figure – ...") reach the listing 23 times,
all in 1876BPL.

Imported (`reocr_pair.py dump`, `--rederive`, `survey_derive.py` bounds/pages/sections/scope,
`survey_adleaves.py` features merged + inventory). Listing bounds and printed-page claims did
not move. Scoped listing lines, IA's text -> LightOn's:

| | IA | LightOn | per printed name |
|---|---|---|---|
| Doggett 1845 (61,333) | 61,631 | 61,309 | 1.005 -> **1.000** |
| 1876BPL (114,724) | 118,019 | 120,878 | 1.029 -> 1.054 |
| Longworth 1826 (27,000) | 25,500 | 26,464 | 0.944 -> **0.980** |
| Trow 1907 p3 (no count) | 33,522 | **104,621** | |

1876BPL's excess is mostly the margin advertising, now read cleanly as lines of its own ("WM.
KNABE & CO.", "New York House and Warerooms,"); they are not entry-shaped, so `usable` should drop
them after the 4B, which is the number that counts. Its wrap calibration also stopped calibrating
(1.5 -> 3.0, "runover mode not isolated"), and joins went 21,102 -> 18,046; LightOn joins most
run-overs itself (leaf 500 reads cleanly).

**Trow 1907 p3: IA's OCR had failed page by page, and IA's words could not be the layer there.**
Leaf 167 holds ~400 printed entries; IA read 243 words. Over IA's words, 69,270 of the volume's
LightOn lines came out `model-only` (no OCR words under them: synthesized boxes, no indent, a crop
that is not the line) against 53,894 paired. So the import now takes a **second word layer per
page**: `reocr_books.py tesseract` runs the microfilm's recipe on the staged images
(`data/reocr_books_tess/`), and `dump --alt-page-dir` keeps IA's words unless tesseract leaves
`ALT_MIN`/`ALT_GAIN` fewer model-only lines (`better_layer`). On p3 it chose tesseract on 381 of
383 pages: model-only 69,270 -> 2,621, paired 53,894 -> 131,784. ~45 min of tesseract for 383
dense pages on the Mac (6 workers).

**How much of the full run needs it: about 4% of pages, mostly ten volumes.** A gold-free proxy,
IA's lines per page against what the page's text area holds (columns x text height / 1.3 word
heights), separates the canary cleanly: medians Doggett 1.04, 1876BPL 1.10, Longworth 1.05, Trow
1907 p3 **0.42** (283 of 383 pages under 0.5). Over the three tiers' 73,826 residential pages,
3,028 are under 0.5: first 1,208 (2.8%), abbyy8-damaged 1,562 (8.7%), abbyy8-clean 258 (2.0%).
Volumes with a median under 0.8 or over a tenth of their pages under 0.5: Trow 1907 p3, 1908 p2
(376 of 511), 1908 p3, `trowsgeneraldire19073trow`, `trowsgeneraldire19091trow`, Trow 1914 p2
(`trowsgeneraldire19142trow`, abbyy8-clean), Bronx 1871 (three village directories; possibly a
layout effect), and Trow 1863 and 1876 (medians 0.70, few pages under 0.5, probably the proxy's
line pitch). So the tesseract fallback is ~5,000 pages, not a corpus-wide CPU stage; it can run
on the Mac from those volumes' zips (~7 GB) or on Torch. The scan also found `gutter_columns`
raising IndexError when an upright-turned box stands past the page edge (Trow 1859 leaf 249,
Longworth 1801 leaf 273), which would have stopped their staging; the text edges are now clamped
to the page.

**The canary's 4B pass, staged 2026-10-21:** `data/volumes_books_canary`, 19 tasks of 20,000,
312,660 lines (Trow p3 now 104,593 of them; 47 non-entry leaves skipped), ~6.9 GPU-hours with the
kernels. Packed as `cde-volumes-books-canary.tar.gz` (unpacks to `data/volumes`). When the
predictions land: verify the 19 `.sha1`s, `copy_guard.py --volumes data/volumes_books_canary`,
`assemble_records.py --root data/volumes_books_canary --run 4b-100k+guard`, then usable records per
printed name against the three counts, Doggett 1845 against run 1's 0.984.

**The canary's 4B pass, back 2026-10-23** (NYU job 20632142, all on L40S, `venv-kernels` at batch
64: 11.58 rows/s overall, 11.9 median on full chunks, 7.50 GPU-hours). 19 of 19 `.sha1`s and line
counts match. Guarded and assembled into `data/records_canary`, summary
`results/records_books_canary.json`:

| volume | rows | usable | usable per printed name |
|---|---|---|---|
| Doggett 1845 | 60,997 | 60,187 | **0.981** (0.984 on IA's text, run 1): holds |
| 1876BPL | 120,627 | 112,370 | **0.979**: the margin ads do not inflate it |
| Longworth 1826 | 26,443 | 23,195 | **0.859**, against ~0.95 expected |
| Trow 1907 p3 | 104,593 | 98,767 | no count; 2.9x IA's 33,522 scoped lines, a 25-record sample reads right |

Longworth's gap is not fabrication. **(1) Same-row splits:** IA's layer cuts one printed line in two
at a wide justified space ("Dyckman William, shoemaker" | "rear 230 Spring", leaf 409, same
baseline), LightOn reads it whole, and `pair_tile` spreads the whole line back over both pieces, so
the record is cut short and its tail becomes a nameless `other` row: 601 such pairs in Longworth
(~1,150 unusable rows), 626 in Trow 1907 p3, 47 in 1876BPL, 1 in Doggett. Fixed in the import
before the abbyy8-damaged tier (below). **(2) `entry_rate.is_entry`** rejects 1826 addresses with
no house number that `CONNECT` misses ("King n. M'Dougal": the apostrophe; "Greenwich",
"h. Harlem", "French Tanyards"): ~400 start rows with a non-empty address. Ad copy does reach
`usable`, but little: ~150 records of repeated running lines in 1876BPL ("EXTRA CHOICE TEAS, 50
Cts. Per Lb." x57) and ~240 in Trow 1907 p3, about 0.2%. LightOn's Markdown notes reach none.

**The same-row fix (`de9521a`).** `boxed_lines` groups a column's side-by-side pieces into rows
(middles within half the shorter's height, heights within 2x) and orders them left to right;
`pair_tile` joins a row's pieces only where ONE model line covers them, so the ~30,000 specks and
margin marks beside lines in a Brooklyn volume stay apart. Canary re-dump, same-row model-line
pairs: Longworth 1826 1,159 -> 41 (1,973 fewer lines), Trow 1907 p3 1,347 -> 292. Pilot, exact
against gold: IA's words 83.6 -> 83.7%, fresh tesseract 82.8 -> 83.0%, no row lost on either. The
first version lost two Ogden rows, because a three-line margin bracket joined the middle line's
row and pulled it above the line before; the height rule is what fixed that. The canary's own
dumps and its 4B pass predate the fix; re-import those four before they are staged again.

**abbyy8-damaged tier imported 2026-10-23** (NYU's answers: 96,378 tiles, 16 EMPTY, 0.24%
looped; 151 bleed-retried keep a `.loop.raw.txt`, 79 truncated keep none). The four volumes whose
IA OCR failed page by page got the tesseract layer on the Mac first (`reocr_books.py tesseract`,
1,923 pages, ~45 min a volume), taken page by page by `better_layer`. historical-ocr-eval
suggested Indra instead (~10x faster on CPU, clean detection on Trow but for word-space cutting,
which the same-row fix absorbs); no head-to-head against tesseract exists and its weights are
OpenRAIL-M, so tesseract stays until a tier needs far more pages. `facts --against HEAD`:

| | scoped lines before -> after | model-only |
|---|---|---|
| trowsgeneraldir1908p2trow (tesseract layer) | 43,595 -> **139,654** | 1.9% |
| trowsgeneraldir1908p3trow (tesseract layer) | 57,655 -> **130,727** | 1.2% |
| trowsgeneraldire19073trow (tesseract layer) | 40,654 -> **123,804** | 3.9% |
| trowsgeneraldire19091trow (tesseract layer) | 38,110 -> **140,670** | 3.1% |
| the other 25 Trow parts | within +-1.5% each | 0.7-1.4% |
| Brooklyn 1905 p1, c1905, c1909, c1910, 1909 p1 | +4 to +5% | 6.2-8.0% |
| Brooklyn 1910 p2, c1912, c00, 1912 p3 | -1 to -3% (joins 4-5x: LightOn's `cont` joins run-overs IA left apart) | 5.2-6.0% |
| Longworth 1798 | 8,874 -> 9,026 | 2.0% |

No volume is over the 10% model-only flag. The 1903 edition prints 405,264 names for all three
parts: scoped lines 409,787 -> 412,719 (1.018 per name). **Three listing starts moved, each a
correction:** Trow 1903 p1 31 -> 33 and 1907 p1 105 -> 107 (the old start was the abbreviations /
"Names Received too Late" page), and Trow 1909 vol 1 161 -> 95, where IA's failed OCR had lost the
whole early A section (leaves 97-159, ~9,000 lines; flags `sparse`, `edge-disagreement` gone). Its
new start, 95, is that same abbreviations page, so it is probably two leaves early.

Table mode ran high on five volumes, a layout effect: Brooklyn 1905 p1 and c1905 ~25% of tiles,
Trow 1903 p1-p3 ~20% (bench: 10 of 138). LightOn reads a plain listing column as an HTML table
with an invented header; `untable` recovers one entry per line, with two side effects: the ", "
it restores at a field cut lands after the NAME in these styles ("Dorfman Dora, dry gds 50 Livonia
av"; the page prints no comma), and an HTML `<thead>` row survives as a line: 76 in the tier
("Name, Address" 34, "Name, Occupation, Address" 20). Neither has an address shape, so they should
not reach `usable`; both are fixable by re-import alone (it re-flattens from `.raw.txt`). The two
Brooklyn 1905s also leave the most IA lines unpaired (38-40k against 17-28k): partly specks, perhaps
entries table mode dropped; read a few pages against their images before the 4B.

**Staged for the 4B 2026-10-24:** `data/volumes_books_damaged_v2`, 39 volumes, 4,671,559 lines,
258 tasks of 20,000, ~103 GPU-hours at 12.6 rows/s; `cde-volumes-books-damaged-v2.tar.gz` (152 MB,
sha256 39b19059...8610), `code_at` da3ca91 (the "-dirty" is untracked files). All 35 of the tier's
volumes, every one rebuilt with the same-row fix (de9521a) and the ditto pull (071e202), plus the
canary's four again, to measure those fixes in records against job 3 (Longworth's scoped lines
26,464 -> 25,879 as split tails rejoin their entries). A first, 37-volume staging held back the two
"generaldire" Trow volumes until #32 (a) was fixed; it was never sent and is deleted. Runbook: the
damaged-tier page, https://claude.ai/artifact/L5hhRFvo22384GUDwNkQZa, "Next job". Predictions come
back into `data/volumes_books_damaged_v2/` (never `data/volumes/`); assemble into a separate `--out`
so job 3's `data/records_canary` stays the before.

**C, the 4B over the damaged tier, back 2026-10-29** (sent as v4, staged at 657e9c4; NYU job
21014769, all 258 tasks on L40S, `venv-kernels` at batch 64, 11.4 rows/s overall, 114 decode-hours).
All 258 predictions match their chunks (sha1 and count, 4,678,164). Installed into
`data/volumes_books_damaged_v4/` (logs in `logs/` there), guarded, assembled to
`data/records_books_damaged/`, summary `results/records_books_damaged.json`: 4,284,970 usable of
4,678,164 rows. Against job 3 (usable per printed name): Doggett 1845 0.981 -> **0.982** (IA run 1
0.984), Longworth 1826 0.859 -> **0.897** (the split tails rejoined; still short of ~0.95), 1876BPL
0.979 -> 0.982, Trow 1907 p3 usable 98,767 -> 99,690. The 1903 parts: 390,604 usable for 405,264
printed names (0.964). Glued-entry proxy on the two "generaldire" volumes 0.36% and 0.28%, the Trow
floor (siblings 0.20-0.35%): #32 (a) held.

**D, the LightOn re-read of `first` and `abbyy8-clean`, imported 2026-10-29** (NYU jobs 21115799 and
21115800, L40S, vLLM; 198,811 tiles in 61 volumes, 63 EMPTY, 0.23%/0.43% looped). 14 BPL volumes
were not cut: the pinned Pillow 10.4.0 (openjpeg 2.5.2) cannot decode 802 of their 12,908 pages
(1866BPL 81%, 1867BPL 28%), the Mac's copy fails them too, and Pillow 12.3.0 (openjpeg 2.5.4) reads
them all. Where both decode, the pixels AND the quality-92 JPEG bytes are identical (checked on
1866BPL), so those 14 are tiled under 12.3.0 with no parity question (hadro, 2026-10-29). The import
(`reocr_books.py import --ids <61>`, 6 workers, 3 h 18 min) moved scoped lines 8,610,756 ->
8,605,974; listing bounds moved once (Flushing c00 end 171 -> 169). Two patterns, both checked:
- **Joins up, lines down where IA's joiner missed run-overs.** Trow 1922/23 p1/p2 joins 17.6k ->
  142k and 18.8k -> 159k, scoped -16%; BPL 1858-1871 joins ~6x, scoped -8 to -14%; Trow 1865/66
  (bub_gb) -5%. 1862BPL leaf 256 against its image: one line a printed entry, every run-over joined.
  A `"` ditto opening a second entry mid-line: 0.16% of 1922/23 p1's lines, 0.02% of 1917's. A line
  repeating its own entry after `, ` (LightOn table cells): 1,081 in all 61 volumes, under 0.1% each.
- **BPL 1878-1887 scoped lines per printed name rose 1.00-1.04 -> 1.04-1.08:** the margin ads,
  as 1876BPL's 1.054 that came to 0.982 usable after the 4B.
The coverage flags on Trow 1859/1863/1876 were the proxy's line pitch: model-only under 1%. The
model-only flag (>10%) asks the tesseract layer for **Trow 1914 vol 2 "19142"** (64.5%; IA's OCR
failed, 206 of 489 pages under 0.5), **Flushing 1891/92** (12.5%) and **Ogden** (16.8%). **Ogden's
show-through versos are back in scope:** the entry-shape flag held 135 leaves on IA's text and 58 on
LightOn's, which reads the reversed text, loops on it (90 of its 506 tiles; NYU's 50 EMPTY are
also versos) or invents ("Table of Contents / 1. Books ..." on leaf 112): 3,548 scoped lines on even
leaves. Keep Ogden out of any staging until its versos are excluded by leaf. **Done the same day:**
Ogden's versos are non-entry by leaf parity (eec4bf0, `survey_adleaves.SHOW_THROUGH`; rectos 1.8%
model-only, so no tesseract layer). The tesseract layer re-import: **Trow 1914 vol 2** model-only
64.5% -> 6.0%, scoped 168,717 -> 175,786 (IA's own OCR: 56,076; its twin 1914 p2 187,541).
**Flushing 1891/92** is unchanged: `better_layer` kept IA's words on all 92 pages, because its
12.5% model-only are not a failed layer but banner and margin ads LightOn reads and IA's words
lack ("SEWING MACHINES.", "Easy payments accepted,", and one LightOn note, "Note: The vertical
text on the right side ..."). 409 of its 3,442 scoped lines are such copy, 36 of them entry-shaped:
BOOKSCAN_HANDOFF proposal 2 (margin ads), to read in its records after the 4B.
**Table mode: 41,904 of 198,811 tiles (21%)**, ~50% on Trow 1915 and 1922/23, 42% on 1917, 17-33%
on BPL 1878-1887. `line_assembly.py tables --damage`: two-entry cells barely above plain tiles' rate
(1922/23 p1 0.58 a table tile vs 0.39 plain; 1915 0.43 vs 0.36; BPL table tiles below plain), but
the invented `, ` after the name runs 28,494 on 1915, 24,437 on 1917, 12,548 on 1922/23 p1, and
ditto marks lost 1,239 (1922/23 p1), 722 (1917), 678 (1915). **The table test (NYU job 21116104,
`hpc/lightonocr_vllm_notables.py` with NYU's `SamplingParams` subclass fix)** re-read task 0 with
`|` and `<table` banned: no output holds either; gold entries 93.6 -> 93.4% exact (one line), book
74.4 -> 74.1%; on the 9 bench pages with table tiles 94.4 -> 94.0% gold, book exact 78.5 -> 77.5%,
close 99.1 -> 99.8%. Safe, but the bench holds none of the damage above, so it cannot show the gain.

**Round 11, imported 2026-10-30** (NYU jobs 21406288/89 re-read, 21406291 cut, 21406439 read; all
L40S, 14.6 GPU-h; sha256s checked, every path under `data/reocr_tiers/`, nothing overwritten). (a)
**The 41,904 table tiles re-read with tables banned** (`-vllm-notables`), exactly the shard lists,
0 EMPTY, 514 looped (1.9% on Trow 1915/1917/1922-23, 3x the first read, NYU's flag). The loops cost
nothing against the table reading: those 514 tiles give 32,523 lines for the first read's 30,157.
In all, +5.8% lines and ditto-bearing lines 776k -> 1.27M. **But the ban pushes 182 tiles (0.43%)
into a figure description**: `<figure> ### Figure – Bank of New York Organized 1839 *Type: other*
... names such as "Marie Mrs midwife r40 Macdougal," ...` (Trow 1915 leaf 1467), the whole tile's
entries as one quoted paragraph, 7,722 of the first read's lines. Not new: **the first read has 537
(0.27% of 198,874 tiles), already in D's import, and the 14 BPL volumes 178**; 1,018 of 1,019 hold
nothing outside the figure. `reocr_pair.figure_only` now treats such an answer as no reading (the
first answer under `--prefer`, else the layer's words, as an EMPTY tile), and `tile_slug` also keeps
the first answer where the re-read has under half its characters (56 tiles: early stops, 1879BPL
leaf 508 2 entries of 28; 1885BPL leaf 29 the ad banner only). (b) **The 14 BPL volumes** cut under
Pillow 12.3.0 (all 802 failed pages now cut; 50,792 tiles, 0 EMPTY, 0.20% looped) and read whole
under `-vllm-notables`.
Imported: `import --ids <D's 61> --prefer lightonocr-3-1b-greedy-vllm-notables` (4 h 10 min; Trow
1915/1917's dumps alone ~2.5 h), then `import --ids <the 14> --slug lightonocr-3-1b-greedy-vllm-notables`
(1 h). **No listing bounds moved** in any of the 75. On the 18,140 leaves holding a re-read tile
(the before dumps saved first): lines 6,789,481 -> 6,805,176, lines read from the layer 261,957 ->
224,609, ditto-led lines 2,412,274 -> 2,518,318 (Trow 1917 +44k, 1915 +32k, 1922/23 p2 +17k); every
other leaf unchanged (5,835,283 -> 5,835,021). `tables --damage`'s **two-entry cells: 1915 3,987 ->
2,326, 1917 3,360 -> 2,058, 1922/23 p1 2,299 -> 1,412, p2 2,673 -> 1,523** (plain tiles' base rate
flat, 3,164 -> 3,156 on 1915); the glued-ditto proxy fell in every volume (Trow 1914 vol 2 534 ->
418). Trow 1922/23 joins 141,778 -> 134,071 and 159,374 -> 149,976 (the table reading's glued lines
now come apart). The invented `, ` cannot arise without tables. **A clear gain**, so the damaged
tier's 6,318 table tiles are worth the same re-read (its zips are pruned at NYU: a re-download).
The 14 BPL volumes (IA OCR -> LightOn): 1863-1868BPL joins ~2-3k -> 11-17k, scoped -6 to -10%, as
BPL 1858-1871 in D; 1868BPL scoped per printed name 1.158 -> 1.067, 1875BPL 1.031 -> 1.054 and
1889BPL 1.028 -> 1.054 (margin ads, as 1876BPL); model-only 0.3-6.5%, none flagged. **1875BPL's wrap
threshold moved 1.5 -> 3.0** (joins 20,097 at 1.5, 17,071 at 3.0): 13 sampled listing joins only 1.5
makes, read on the page, 6 harmful (two entries glued, two running heads onto a first entry), 3 real
run-overs, 4 ads or scraps; right, and pinned (`survey_harvest.WRAP_PINS`). Found on the way:
**join_wraps' running-head guard sees only a page's first line**, and on BPL pages with margin ads
the head ("414 JAH—JAM") comes ~100 lines into reading order; harmless at 3.0, open.
**What a re-import would cost the 4B**, measured on D's (the before dumps against the after, per
volume, the model's whole input `(publisher, year, raw_line)` as a multiset): 93.2% of 8,581,037
listing lines unchanged; 99.8% on leaves without a re-read tile, 88.5% on those with one (Trow
1922/23 78-80%, 1915/1917 85-87%). The damaged tier's figure fix and survey drift are the "without"
case: ~1% of its 4.68M lines, so a delta 4B job (stage only lines with no earlier prediction, reuse
the rest: the 4B is greedy and sees nothing but that input) is ~1-2 GPU-h against ~103. WRITTEN
2026-10-31 (bef90f5): `hpc/delta_volumes.py stage` stages only a new staging's unseen prompts,
`merge` writes every chunk's prediction file and sha1 from old + delta records, so copy_guard and
`assemble_records.load_run` run unchanged. The k-th copy of a prompt takes the k-th old record,
because copies decode differently in different batches (8 of 20,000 records in 1876BPL's first
chunk); with that, an unchanged volume merges byte-identical, and the v4 staging against itself
reuses all 4,678,164 lines. `35_volumes.sbatch` now takes `VOL`; ship it with the first delta
package (NYU's copy has the fixed `$DATA/volumes`).

**THE FULL BOOK-SCAN RE-OCR, STAGED ON TORCH (built 2026-10-22).** The tiers' images are ~75 GB,
which the Mac cannot hold, so Torch fetches and cuts them, and only words and answers cross:

| step | where | what |
|---|---|---|
| `reocr_books.py records --tier <t>` | Mac | `data/reocr_books_records/<id>.records.jsonl.gz` (IA's words per listing page, side bands stripped) + `volumes_<t>.tsv` (each volume's `_jp2.zip`/`.tar` and size on IA); volumes with a sidecar `reocr` block are left out |
| `hpc/41_books_download.sh <tsv>` | Torch DTN (dtn012) | the archives into `data/reocr_zips/`, 4 at a time, `curl -C -`, renamed only at full size |
| `hpc/42_books_tiles.sbatch` (`hpc/books_tiles.py`) | Torch CPU array, one task a volume | pages from the archive -> `reocr_columns.stage` -> `data/reocr_tiers/<id>/` (tiles, boxes.json, columns.json, STAGED); page images deleted after |
| `hpc/books_shards.py <tsv>` | Torch login | shards of 2,000 unanswered tiles across volumes, `tasks_<t>.txt` |
| `hpc/39_lightonocr.sbatch`, `ENGINE=vllm` | Torch GPU | unchanged |
| `hpc/books_pack.py <tsv>` | Torch login | one tar of answers + boxes per finished volume, `answers_<t>/<id>.tar` |
| `reocr_pair.py dump --root data/reocr_tiers/<id> --page-dir data/reocr_books_records` | Mac | `page_record` reads the records file; then `--rederive`, `survey_derive.py`, adleaves, staging |

Checked end to end on Longworth 1826 before anything shipped: the Torch-path tiles have the
canary's boxes (970 of 970) and pixels (identical), and the import from the packed tar is
byte-identical to the canary's (1,146 of 1,146 dump records); the download script fetches, skips
and resumes; the tile job runs with `uv` offline from the login-node cache. `books_tiles.py` pins
Pillow 10.4.0 and numpy 2.0.2, the Mac's.

**Trow 1915/1917's `_jp2.tar` holds pages IA has already cropped and turned** (leaf 688: 3273 x
4516, the frame of IA's words), not the camera frames IIIF serves (5616 x 3744). Turning them
upright again, as the IIIF path must, would have cut every tile from the wrong place, so
`convert` now checks every page image against its word record's `page_size`, turns it only on a
mismatch in a camera-frame volume, and stops the volume if it still does not match.

**abbyy8-damaged, packaged first:** 35 volumes (Trow 1907 p3 done in the canary), 17,647 listing
pages, 21.8 GB of zips (~1-1.5 h on the DTN at four streams), ~95k tiles, **~14 GPU-hours** of
LightOn in ~48 tasks. Five of its volumes are in the coverage scan's failed-OCR list (Trow 1908
p2/p3, 1907 "19073", 1909 "19091", and 1907 p3 done); their pages get the tesseract layer on the
Mac at import, from their zips (~3 GB).
Packed 2026-10-22 as `cde-books-damaged.tar` (358 MB, sha256 1f8d8fa7...7291: `data_prep/*.py` at
6002d70, the five hpc files, `results/iiif_frames.json`, Trow 1915/1917 scandata, the 35 records
files + TSV). Runbook artifact https://claude.ai/artifact/L5hhRFvo22384GUDwNkQZa (private; share
before sending). **When the answers land**, per volume: untar at the repo root (it recreates
`data/reocr_tiers/<id>/` with boxes and answers), `reocr_pair.py dump lightonocr-3-1b-greedy-vllm
--root data/reocr_tiers/<id> --page-dir data/reocr_books_records --ids <id>` (for the five
failed-OCR volumes, first `reocr_books.py pages` + `tesseract` from their zips, then
`--alt-page-dir data/reocr_books_tess`), `survey_harvest.py --rederive`, `survey_derive.py`, then
the adleaves merge as for the canary.

**Assembly changed under it on 2026-10-20** (`fb1a020`, `4efc6ae`: the surname carry, the dropped
headers, the leading markers — Stage 5). Nothing sent to NYU depends on it; only the assemble
after the 4B does. `usable` is untouched, so the done-criterion stands — Doggett 1845 assembled by
the new code is still 0.984. But `name_resolved`, the summary's `ditto` block and the new fields
are not comparable with anything assembled before `fb1a020`: for a before/after, re-assemble the
"before" with the same code (its predictions are on disk; ~1 min). On arrival, check two things
per volume: that the harvest has rewritten `data/survey_ocr/<id>_dropped.txt.gz` from the re-OCR'd
lines (`dropped_headers` reads the headers from it; a missing file just means none), and the
summary's `ditto.lead_marks` — marks are re-detected per volume, and LightOn may print a mark
differently from ABBYY.

The dump keeps IA's records for the leaves not re-read. For each re-read leaf it pairs the tiles
(a tile without an answer keeps tesseract's lines), runs the post-passes, and spreads every
line's text over tesseract's word boxes (`respell`: similarity anchors, so "capmker" still
anchors "capmaker"). A line tesseract never saw gets boxes under its neighbour. Lines read twice
are paired too: between two paired lines, tesseract's unpaired readings and the model's are the
same printed lines (`fill_gaps`). Without that, bleed-through garbage stayed beside the model's
line for it (0047: tesseract-only lines 38 -> 7). Model words carry confidence 90, a bleed-retry
tile's 30, and the record carries per-line `sources`.

A dry run on the screen pages took the survey's own filters from IA's 0 candidate lines to 136
and 147 on two 0039 pages, and from 1 to 144 on a 1912 page.

**Dittos** (`reocr_pair.dittos`, 2026-10-14, with historical-ocr-eval). LightOn writes 1912's
ditto dash as a Markdown bullet ("- LeGrand T h 453 Washn av"), but bullets are list markup:
it bullets new surname heads on the same page, and whole lists in volumes with no dash at all.
Tesseract misses most real dashes. Both errors cascade under the downstream surname carry, so
each entry is decided from evidence plus alphabetical order:
- Evidence: tesseract's dash glued to the name ("—John H"), or standing alone and dash-shaped.
  Or LightOn's bullet, on a page where bullets meet tesseract's dashes.
- An entry with evidence is a ditto ("— " written) unless it continues the chain of heads (same
  first two letters, or same first letter and no given name).
- Never a ditto: capitals, run-overs, and a head tesseract read cleanly that is no given name.
- Checked by eye on 1912 leaves 291 and 671 (the 340 lines tesseract boxed): each of the 265
  dittos among them is printed with a dash. The other 15 of the 280 are lines only LightOn read,
  inside dash runs. One printed ditto is missed: LightOn wrote "Smalt M" for "—Wm M".
- On the plain-list screen pages (~4,100 entries) one ditto is written, for the printer's fist
  before an ad.
- 0035 prints its own long "——" ditto, which the shape test lets through.
- An entry's printed "*" is glued to the name, as the gold writes it ("*Dixon"); spaced, the
  survey's gate had admitted "*" as 0035's ditto.
On the screen pages' own lines that gate admits "—" for 1912 (60% of lines), and dry-run derives
admit it for 1912 from two re-read leaves and nothing for 0035.

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
  ABBYY-8 run-set volumes. It was held until the real-OCR panel's run 3 was scored, so that
  run's staged inputs would stay what it measured. **It was applied on 2026-10-06: 168,902
  fixes in 70 volumes** (stage 6, "Run 3").
- **A leading `0` → `6` is rejected.** It is right 67% of the time on Brooklyn, but 0 of 9 on the
  trow1907 gold, where Trow's font turned 9 into 0 (`08th` for 98th). A wrong repair would also
  hide a visible error behind a plausible street.

The leading-zero rate became the tier signal above.

**28. ~~Join a re-OCR'd page's run-overs by LightOn's reading, not by indent.~~ DONE 2026-10-16**
(the 39 volumes re-imported; row EM still needs a stage-B run). The measurement below is the
BEFORE picture; what was built and what it is worth on gold follow it.

How it worked before:
- The import splits each LightOn entry back over tesseract's printed lines, by design ("the
  downstream wrap-joiner sees what it always sees", `reocr_pair.py`'s docstring).
- The survey's `join_wraps` then re-joins them by indent alone: a line joins the entry above when
  it sits more than `indent_ratio` line heights in.
- All 39 re-OCR'd volumes keep the 3.0 default. `calibrate_indent` declines each one, for ditto
  marks or for no isolated run-over mode.
- Their run-overs sit about 2 line heights in (1912: 2.0–2.25).

So most of them stay apart. By LightOn's reading (`reocr_pair.py joins
lightonocr-3-1b-greedy-torch --root data/reocr_halves`):

| The 39 volumes | Lines |
|---|---|
| Run-overs joined | 4,819 |
| Run-overs left apart | 26,462 (21,933 of them 1.5–3.0 line heights in) |
| Entry starts glued onto the line above | 7,097 |

Hope & Henderson 1856 (0035) alone leaves 9,778 apart. An entry left apart loses its tail,
usually the address, and the tail can come back from the model as a person. On the LightOn
panel, 5 of hopehenderson1856's 31 inexact rows are cut short this way ("Hagerty James, glass, 92
John, N. Y. h. 27" without "Hicks").

**What the import knows.** `pair_tile` marks each printed line it fills: `start` is False where
the model read the line as part of the entry above. `page_dump` drops the flag; `page_dump(...,
with_starts=True)` returns it, and `joins` reads it that way.

**What was built.**
1. `reocr_pair.py dump` writes the flag: each re-OCR'd record gains `cont` beside `sources`, 1
   where the model read the printed line as part of the entry above. It is 1 only for a line the
   model read — a tesseract line (a tile with no answer) carries no reading and is 0, so the
   joiner keeps the indent rule for it. Consumers that read only `lines` are unaffected, and the
   re-dump leaves `lines` and `sources` byte-identical (checked on 0035 by SHA-1).
2. `WordDump.page_cont` hands it to `sweep`, which hands it to `join_wraps`. There `cont` LOWERS
   the floor to `MODEL_INDENT` (0.5 line heights) rather than replacing the indent.

**Why the floor, and why the indent rule stays** — the two model errors the sketch predicted,
both real, measured on the re-OCR bench's 48 reference pages (3,174 reference entries):

| | |
|---|---|
| A model line that is exactly one reference entry | 2,146 |
| A reference entry split over two model lines | 101 (3.2%) |
| A model line holding two or more entries | 19 (0.6%) |

So the model's reading is good but not sufficient in either direction. The 101 splits are why the
indent rule stays as a fallback. The 19 merges — one is five consecutive Boyds in one line, and
`pair_tile` marks every printed line after the first a run-over — are why a line at the column
margin never joins on `cont` alone. Those two are well separated by indent. On 0035, every line
under the entry above:

| indent, line heights | model run-overs (10,694) | model starts (39,695) |
|---|---|---|
| below 0.25 | 322 (3.0%) | 33,563 (84.6%) |
| 1.5 – 2.0 | 7,107 (66.5%) | 3,521 (8.9%) |

0.5 admits 96.6% of the run-overs and holds back the margin cluster.

**Sketch items 3–5, settled:**
- **3 (the flag following its line).** `strip_side_bands` returns one line per line, so the flag
  rides along; `split_merged_columns` re-cuts and re-orders, so the flag is dropped for a leaf
  that splits and that leaf joins on the indent alone, counted as `cont_dropped_leaves`. A
  length mismatch drops it too. On 0035 it never fired: the 3 split leaves are IA leaves, not
  re-OCR'd ones.
- **4 (the margin pull).** Kept. It is no longer what prevents a false join, but it still puts an
  entry start's box where the print starts — boxes the survey keeps and the records cite — and
  the margin it establishes is what `MODEL_INDENT` is measured from. Removing it is a separate,
  separately measurable change.
- **5 (`calibrate_indent`).** Re-OCR'd leaves still feed it, and it still refuses them — and the
  table above is now a reason it *must*. 3,521 of 0035's model starts sit in the 1.5–2.0 band
  with 7,107 of its run-overs. Lowering that volume's threshold to reach them would glue about
  3,400 real entries to rescue the handful the model mislabelled. Geometry cannot separate the
  two on these volumes; that is what the flag is for.

**On gold.** `eval/lighton_pilot.py --diff-against` a saved copy of `data/iapanel_lighton`, over
all 17 sets, 2,062 rows. Pooled line-exact **82.3% → 82.6%**, CER 0.010. **Seven rows changed and
not one went backwards** — six newly exact, one improved but still inexact for an unrelated comma:

| set | was | now |
|---|---|---|
| hopehenderson1856 (0035, microfilm) | 48.3% | **50.0%** (CER 0.031 → 0.028) |
| lain (1897BPL) | 83.1% | **83.6%** |
| trow1907 | 86.8% | **88.2%** |
| Smith 1855 — the trap, whose run-overs LightOn writes apart | 92.4% | 92.4% |

Each gain is an entry that had lost its tail: "h 562 Laf" + "av", "h 820" + "Pres't", "h 15" +
"E 129th", and 0035's "cor. Sara-" + "toga av." closing up its hyphen.

**0035's four remaining cut-short rows are two OTHER defects**, not this one. Traced line by
line on leaf 205:
- **Three** ("h. 27" + "Hicks", "h. 30" + "Front", "n. W." + "Baltic") are all the same model
  error: **LightOn wrote the run-over as a line of its own**, so `cont` says start and only the
  indent could join them. "Hicks" sits at 2.13 line heights, under the volume's 3.0, and item 5
  above is why that threshold cannot simply be lowered. "Front" and "Baltic" are worse: they are
  model-only lines tesseract never saw, so `synth_line` gives them a box at the tile's left edge
  and their indent comes out *negative* (−0.30, −0.41). Placing that box at a run-over indent
  instead would be a fair fix to the line's provenance, but it would **not** rescue the row —
  a correct run-over box sits near 2.0, still under 3.0.

  So the open lead is upstream, in the import rather than the joiner: **merge the model's own
  split entries before `pair_tile` spreads them over printed lines.** The bench sizes it at 101
  of 3,174 entries, and `joined()` already performs exactly that merge when a reference is there
  to guide it. Doing it without a reference needs its own design and its own gold.

  **A first attempt at that was built and REJECTED on 2026-10-16. Read this before trying
  again.** The rule: merge when the line ends where an entry cannot end (a connector, a bare
  house number, a residence marker, a direction, a hyphen) or the next begins where one cannot
  begin (a residence marker, a street type, lower case). Against the bench's hand gold it looked
  excellent — **29 of 30 splits found, 0 false merges in 456 whole entries.** On the pilot panel
  it was a net loss, and the way it failed is the lesson:
  - Rows delivered fell **2,062 → 2,053**: nine gold rows vanished, glued into a neighbour.
  - boyd1890 96.0 → 94.7, rode1851 98.1 → 96.2, Smith 1855 92.4 → 91.8.
  - Boyd's row 13 lost its surname to the entry above: "Harding James, driver, h 161 Broadway"
    came out "James, driver, h 161 Broadway".
  - Lain 1897 cascaded. Its lines trail an E-mark scrap (`…h 399 17th, " E`), the tail test read
    that final `E` as a direction, and each merge pulled in the next entry: five gold rows gone,
    one replaced by a different person entirely.
  - hopehenderson1856, the volume it was built for, did not move — the pilot copies 0035's
    production lines (`TORCH_READ`), so that set never tested it.

  Three things to take from it. The bench's 532 hand-gold lines are too few and too clean to
  clear a merge rule — 0 of 456 there became 9 lost rows on 2,062. **A false merge costs a whole
  entry and cascades**, while a missed join costs a tail, so the rule must be far more
  conservative than its recall suggests. And the obvious guard is the one that was missing:
  **never merge when the next line opens with a plausible surname** (capitalised, alphabetic,
  not a street type) — that alone would have blocked Boyd and Lain. The scratch rule is not in
  the repo; the measurement is here so the next attempt starts from it.
- **One** ("Hagarman Barnes R., clothing," + "102 Fulton,") is the wide-gap split already listed
  under "Still open": the two halves sit side by side on one printed row and fail `join_wraps`'
  horizontal-overlap test, so no rule reaches them.

The earlier estimate that five of hopehenderson's inexact rows were cut short *by the indent
rule* was a wrong attribution; the ones the model's reading could fix are fixed.

**The 39 volumes, re-imported 2026-10-16** (`reocr_pair.py dump`, `survey_harvest.py --rederive
--ids`, then `survey_derive.py` bounds, pages, sections and scope):

| | before | after |
|---|---|---|
| Wrap joins | 26,033 | **50,986** (+24,953) |
| Kept lines | 576,992 | 558,617 (−18,375) |
| Scoped listing lines | 529,126 | 510,752 |

The kept count falls because each join turns two lines into one — a tail that used to come back
from the model as a person named "Hicks" is now the end of its entry. 0035 alone goes from 2,327
joins to 11,916, and its `short` drops fall 9,962 → 7,446: those were the orphan tails.
40,710 lines carry the flag over 7,917 pages, 9 of which lost it to a column split and joined on
the indent as before. **No volume's listing bounds or printed-page claims moved.**

**Against the printed name count** — the one external truth available for these volumes without
a GPU. Two of the 39 state their own count:

| | printed names | scoped lines before | after |
|---|---|---|---|
| 0039 | 50,000 | 54,348 (**1.087** per name) | 51,892 (**1.038**) |
| 0046 | 7,345 | 6,083 (0.828) | 6,058 (0.825) |

0039's excess over its printed count falls by 2,456 lines — the whole of its reduction, so
essentially every join there removed a line that was never an entry. It lands beside Doggett
1845's 1.004–1.038. 0046 *under*-counts by 17%, an OCR recall problem this change cannot touch,
and with 200 flagged run-overs it barely moves. The round 50,000 is a publisher's figure, so
read the direction, not the third digit.

**Done when:**
- ~~No pilot set regresses.~~ None did, and six rows became exact.
- ~~The 39 volumes are imported again.~~ Above.
- A stage-B run on the panel still has to measure the row EM.

**THE `reocr` TIER RAN AND IS SCORED (2026-10-19).** 52 tasks, 498,390 records for 498,390 lines,
all 52 `.sha1` sidecars verified against the staged chunks on both sides, no `.partial` files,
every log reporting `Qwen/Qwen3.5-4B`. Predictions in `data/volumes_reocr/`, guarded, assembled
to `data/records/4b-100k+guard/`, summary `results/records_4b-100k+guard.json`.

- **Cost: 19.8 GPU-hours at 7.00 rows/s**, against the ~11.7 this file predicted. **The 11.88
  rows/s in `prep_volumes.py` does not reproduce and should not be used for planning.** It came
  from one H200 task in September; the two H200 tasks here ran at 7.13 and 7.57. NYU moved tasks
  2-51 to L40S after h200_public stalled (927 jobs pending on a 24-GPU partition cap) because the
  extractor runs the same speed on either card. At ~7.2 rows/s the remaining tiers are **~213 /
  198 / 155 GPU-hours (first / abbyy8-clean / abbyy8-damaged), ~566 in all, not the ~129 / 120 /
  94 recorded under "Tiers" above.** (Corrected 2026-10-20: this line said "~215" for all three,
  which is the first tier alone.)
- **The GPU split is benign.** This was the first tier spread over two card types, so Brooklyn
  1912 — whose three chunks ran H200, H200, L40S — was checked: 30.9 / 31.2 / **30.7** bytes a
  record, 2.98% / 2.92% / **2.95%** empty names, 100% of records parsing all eight fields in all
  three. Worth checking, since greedy decoding turned out not to be bit-reproducible across
  vLLM versus the per-tile runner (#27).
- **The copy guard changed 32,941 of 498,390 records (6.61%)**: 32,972 restorations and 1,431
  invented given names dropped. Brooklyn 1912 took the most at 6,559.

**⚠️ THE PRINTED-NAME MEASUREMENT IS CONFOUNDED BY OUR OWN `role` FLAG — do not quote 0.715.**
`usable` requires `role == "start"`, and `layout_roles` assigns that from the box alone. On these
microfilm frames it inverts: leaf 93 of 0039 has both of its column margins correctly detected as
peaks (45 entry rows each), and **the 45 rows sitting AT each margin are labelled `runover` while
the 10-12 slightly left of it are labelled `start`**. The texts settle it — `E Ackerman William,
driver, h. 85 S. 7th` and `Ackerson Theador, ship carpenter, h. 206 High` are complete entries,
not tails. It is scattered over 406 of 423 leaves rather than failing whole leaves, and across
the 39 volumes **39,906 entry-shaped rows (8.0%) are discarded by `usable` on this flag.**

| | usable | + entry-shaped runovers |
|---|---|---|
| 0039 (stated 50,000) | 35,748 → **0.715** | 44,541 → **0.891** |
| 0046 (stated 7,345) | 5,284 → 0.719 | 5,357 → 0.729 |

So **#28's end-to-end number is between 0.715 and 0.891 per printed name**, and the uncertainty
is in our role labelling rather than in the extraction. Doggett 1845's 0.984 is the benchmark.
Two things are NOT the cause, both tested: the small "E" mark (runover rows are 1.1% E-marked
against starts at 20.6%, so if anything the reverse) and a whole-leaf margin failure (zero leaves
have ≥80% of their entry rows called runover).

**0046's shortfall is a different and real problem.** Only 73 of its rows are entry-shaped
runovers, so the flag does not explain it: it has 5,978 rows for 7,345 printed names. That is OCR
recall, consistent with the 0.825 scoped-lines-per-name measured this morning — this volume is
missing lines, not mislabelling them.

**FIXED 2026-10-20, and it was a hanging mark, not multi-column geometry.** `layout_roles`
seeded each column's margin on the 10th percentile of x. A mark that hangs LEFT of the text
margin puts a minority of lines there, the p10 seed lands among them, the fit pins the margin to
the mark, and every ordinary entry then measures past `START_MAX` and comes out `runover`. The
seed is now the column's MODAL left edge -- the text margin by construction, since a hanging
mark is a minority and a runover indent is a minority -- and `OUTDENT` goes -25 → -40 so the
hanging line itself stays a `start`. The hang measures a median 52-56 px over 2,057 leaf-columns
of 0039/0040/0042, p90 60-70, i.e. 21-27.5 per-mille; a column gutter is ~500 away.

A regression test in `volume_run_report._self_test` carries leaf 93's real geometry (45 entries
at the margin, 14 `E `-marked hanging 55 px left, 2 genuine runovers) and **fails on the old
code**, which called all 45 margin entries `runover` and the 14 marks `start`.

**It is not a microfilm problem.** Three populations have a hanging mark and all three gain:
the Eastern District `E` of 0039/0040/0042, **1906BPL's `"` ditto**, and Smith 1856's microfilm.
Volumes without one do not move.

| | usable before | after |
|---|---|---|
| 0042 | 35,209 | **49,025** (+13,816) |
| 0039 | 35,748 | **43,033** (+7,285) |
| 0040 | 36,441 | **42,549** (+6,108) |
| the 39, total | 414,274 | **444,786** (+30,512) |
| 1906BPL (run 1) | 166,537 | **173,899** (+7,362) |
| Smith 1856, microfilm (run 1) | 10,136 | 11,084 (+948) |
| **Doggett 1845 — no hanging mark** | 60,372 | 60,369 (**−3**, ratio holds at 0.984) |

Nearly 39,000 real records recovered across both runs. A sample of 1906BPL's newly usable rows:
`" Pierce contractor 498 Leonard h 21 St Francis pi`, `" Conrad barber h 998 DeKalb av`,
`Neufield Jos bldr h 305 Hinsdale` — entries, not advertising. (A 60-leaf sample suggested ad
copy and was unrepresentative; over the full volume 8,087 of 8,275 moved rows are entry-shaped.)

**#28's end-to-end number, at last: 0039 goes 0.715 → 0.861 usable records per printed name**,
against Doggett 1845's 0.984. **0046 barely moves, 0.719 → 0.722**, which is the control: it has
no hanging mark, so it was never affected, and its shortfall is genuine OCR recall — 5,978 rows
for 7,345 printed names.

⚠️ `data/records/4b-100k+guard/` also holds run 1's five volumes (310,932 rows). Never glob that
directory for a per-run total; select the volumes you mean.

**⏸ THE ORIGINAL PLAN, kept for the parts still open (job 20310742, sent 2026-10-18).** 52 tasks,
498,390 lines, staged at `58ee8ec` as `cde-volumes-reocr.tar.gz`. The canary (20304867_0) came
back correct but slow: **7.13 rows/s on an H200** against the 11.88 measured once on gh129, so
the run costs ~18.7 GPU-hours rather than ~11.7. NYU went ahead; we issued no stop order,
because the output is right and only GPU time is at stake. Their notes and the canary log are in
`~/Downloads/to_josh_20261019a`.

In order, on arrival:
1. **Install and verify.** Predictions into `data/volumes_reocr/` (never over another staging —
   PIPELINE #27's lesson). Check all 52 `.sha1` sidecars against `manifest.json` and that each
   file's record count equals its chunk's line count.
2. `postprocess/copy_guard.py --volumes data/volumes_reocr --run 4b-100k`
3. `postprocess/assemble_records.py --root data/volumes_reocr --run 4b-100k+guard`
4. **#28's real done-criterion, which the panel cannot give.** Compare usable records per
   printed name against the two volumes that state their own count: **0039 claims 50,000** and
   **0046 claims 7,345**. Before any of this work 0039's scoped lines ran 1.087 per printed name
   and 1.038 after the first pass; this import should move it again. Doggett 1845's 1.004 is the
   benchmark.
5. **Re-measure the thin tier's fabrication rate.** The 30.1% that sizes the case for a learned
   page-type classifier (PAGE_TYPE_CLASSIFIER "STATUS 4", and hadro's question about a
   calibrated decision model) was measured on IA's dead OCR of these same volumes. This run is
   the first chance to replace it. Until then that number is not evidence about the re-OCR'd
   corpus.

Also waiting on NYU, neither blocking: their **option 2** A/B (2,000 lines from each of two
chunks plus `BATCH=64`, on one node) to separate node from data from batch size — the 11.88
figure is n=1 against the canary's n=1; and **option 3**, installing flash-linear-attention and
causal-conv1d, which is probably the real speed-up but changes the inference environment and so
needs a parity check against the canary chunk. Do option 3 deliberately before the next large
run, not during one.

**Options 2 and 3, packaged 2026-10-20 (hadro), not yet sent:** `hpc/36_kernel_test.sbatch` +
`cde-kernel-test.tar.gz` (281 KB: `data/kernel_test/`), the second job on the book-scan canary's
runbook (https://claude.ai/artifact/9jx1ZeAycJR572kHrWdYv5). NYU's own logs settle the premise:
both the 11.88 and the 7.13 H200 runs print transformers' "fast path is not available", so the
linear-attention layers run in plain PyTorch. One job on one GPU reads the same lines in the
current overlay and in a copy with flash-linear-attention (>=0.2.2) and causal-conv1d: 5,000 lines
of the canary chunk at batch 32 and 64 in each (speed; decode timed from the "loaded" line), and
the LightOn panel at fc46ac8 (17 sets, 2,062 gold rows, concatenated in `tasks.txt` order;
`panel_sets.tsv` splits them back) at batch 32 in each (parity). transformers 5.13 falls back one
kernel at a time (`modeling_qwen3_5`: fla's delta rules and gated norm, causal-conv1d's
convolution), so fla alone is a partial fast path, and it reports either as usable only with a
GPU. **When the results land:** split `panel.{current,kernels}.b32.txt` by `panel_sets.tsv` into
`iapanel_<set>/chunk_000.preds_<run>.txt` under a scratch preds dir, guard them, and score both
with `eval/ia_panel.py score` against `data/iapanel_lighton_fc46ac8` (job 20077014 scored 67.0
pooled guarded there; the current overlay re-run is the same-node control, since the panel is
concatenated and so batched differently). Pass = the kernels' row EM within noise of the
current overlay's, with flips symmetric; then the canary's 4B job is the first to use them.

**RESULT 2026-10-21, NYU job 20524162 (one L40S, gl044): GO, flash-linear-attention alone.**
- **NYU does not run in an overlay**: their `hpc/env.sh` has `USE_CONTAINER=0`, so `run_in_env`
  activates `$VENV` and ignores `OVERLAY`, and the script as written would have compared one
  environment with itself. They built `$PROJECT/venv-kernels` from a `uv pip freeze` of the
  production venv (80 packages identical: torch 2.13.0+cu130, transformers 5.14.1, triton 3.7.1)
  plus fla 0.5.2, and ran a copy of the script that switches `VENV` (both freezes and the copy are
  in `data/kernel_test/out/`). `hpc/env.sh` now reads `VENV="${VENV:-$PROJECT/venv}"` so a job can
  choose it, as NYU asked.
- **causal-conv1d would not install**: no prebuilt wheel for torch 2.13 / CUDA 13.0 / cp312, and
  no `nvcc` on Torch's login nodes or as a module. So the warning still prints; the delta rules
  and the gated norm are fla's.
- **Speed** (decode only, 5,000 lines of the reocr canary chunk): current 7.58 rows/s at batch 32,
  7.61 at 64; kernels 8.61 at 32, **12.59 at 64 (1.66x)**. Batch size alone does nothing without
  the kernels, which answers option 2: the plain-PyTorch delta rule was the bottleneck. Panel,
  batch 32: 7.26 -> 9.33.
- **Parity on gold** (`data/kernel_test/scores.json`; the setup reproduces job 20077014's 66.99):
  guarded pooled row EM **67.03 current, 67.21 kernels**, no set worse. 8 of 2,062 guarded records
  differ; 4 flip whole-row exactness, all 4 toward the kernels ("Empel" -> "Empel Abr"), 0 the
  other way. Byte-identical records, kernels against current at batch 32: 99.2% (speed b32),
  99.3% (b64), 99.1% (panel), against 99.4% for batch 32 vs 64 with no kernels, so the kernel
  differences are the size of batch noise.
- At 12.6 rows/s the remaining tiers are **~315 GPU-hours, not ~566**. The next 4B jobs run with
  `VENV=$PROJECT/venv-kernels BATCH=64`. Parity was measured at batch 32; batch 64 was checked
  only byte-for-byte (99.3%), which is the batch noise above.

Two fixes of our own, both small and both deferred to the same moment:
- **The runbook artifact's stash step is incomplete.** It tells NYU to stash `tasks.txt` and
  `manifest.json` before unpacking, but the tar overwrites **`staging.json`** too; NYU caught it
  and stashed it anyway. Fix https://claude.ai/artifact/VuDtqkwxhHS2ax5BYzrB8h before the next
  package goes out.
- **Re-shard before any further re-OCR.** `reocr_columns.py stage --per-shard` produced 70
  shards of ~296 tiles; vLLM's engine init is a fixed ~199 s a task, so that is ~3.9 GPU-hours of
  startup against ~3.3 of decode. Ten shards of ~2,000 tiles takes the corpus from ~7.2 to ~3.9
  GPU-hours by NYU's projection (their arithmetic from one shard, not a measurement). This is our
  setting, not theirs — nothing for NYU to change.

**Do NOT spend time on length-sorted batching.** NYU suggested it from the corpus mean of 39.0
chars against the canary chunk's 27.9, reasoning that a 700-char line pads its batch of 32. The
tail is not there: p99 is 74 characters, 19 lines of 498,390 exceed 200 and 7 exceed 400. The
canary volume (Brooklyn 1912) is simply the short one. And the longest lines are not wrap joins
at all — they are LightOn repetition loops ("North 6th & 5th & 6th & 7th & 8th &" counting up to
the cap), six lines, every one in `micro_IABROOKLYN_0045`, whose loop detection missed them.

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
  the source line's `ditto_source` — or `ditto_header`, the dropped header it came from — and the
  carry's review flags), `address_resolved` (#8) and `home_address_resolved`. A leading marker
  comes off `name_resolved` into `name_mark`, and `district` is `Eastern` for the Eastern
  District's mark or section (Stage 5; from 2026-10-20).
- **Flags, never filters:** layout `role` (a runover is an entry's tail), `entry_shaped`,
  `non_entry_page` (SURVEY_PLAN.md, "Non-entry pages") and `eval_holdout`.
- **Which staging:** `root`, the `--root` the volume was assembled from (from 2026-10-20). One
  run directory can mix roots — `4b-100k+guard` holds run 1's five volumes and the reocr tier's
  39 — and this is the only thing on a row that says which.

**To look at them:** `bash browse/serve.sh` serves every record file in a local Datasette
(`browse/README.md`) — filters, facets, search, the line's IIIF image and its page with the line
outlined, and the volume metadata from the catalog. `python3 browse/build_db.py` refreshes it after
an assemble.

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

The table is run 1 as assembled on 2026-09-28. Since then `layout_roles` (`66a9949`) moved
1906BPL's usable to 173,899 and Smith 1856's to 11,084, and the 2026-10-20 carry (#6) took
1906BPL's disputed share from 23% to 6.6%. That carry, the headers and the markers change
`name_resolved` and the summary's `ditto` block, **never `usable`**: Doggett 1845 is still 0.984.

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
