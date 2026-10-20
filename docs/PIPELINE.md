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
  extractor runs the same speed on either card. At ~7.2 rows/s the remaining tiers are **~215
  H200-hours, not the ~129 / 120 / 94 recorded under "Tiers" above.**
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
