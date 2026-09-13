# Running a volume through the pipeline

**Written 2026-09-10.** End-to-end: an Internet Archive identifier in, structured person records
out. Every number here is measured on this corpus, and where a stage is *not* calibrated it says so.

Companion docs: [HANDOFF.md](HANDOFF.md) is the working record and the reason each decision is what
it is; [TAKEOVER.md](TAKEOVER.md) is the cold-start orientation; [GROUND_TRUTH_HANDOFF.md](GROUND_TRUTH_HANDOFF.md)
is the labeling contract that governs the model's output shape;
[PAGE_TYPE_CLASSIFIER.md](PAGE_TYPE_CLASSIFIER.md) is the plan for next-step #11, phase 0 run.

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
| 5 | **ditto resolution** | `postprocess/resolve_dittos.py` | within-line yes, cross-line partly | seconds |
| 6 | QA | `eval/entry_rate.py`, `eval/evaluate.py` | proxy / gold | seconds |

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
    --out data/1906BPL_lines.jsonl \
    --dump-dropped data/1906BPL_dropped.txt \
    --ditto-review results/ditto_review_1906BPL.tsv
```

No images downloaded, no OCR run, no GPU — IA already OCR'd 291 of the catalog's volumes and that
OCR was measured good enough to use (CER-all 0.067 excluding one dead volume).

**Never read `_djvu.txt`.** It flattens multi-column pages so several entries merge onto one text
line: CER-all **0.723** against **0.159** for the same page rebuilt from `_hocr.html` `ocr_line`
elements. Same words, 4.5× the error, purely from line segmentation.

### What it does, in order

1. **Joins wrapped entries first.** 12.8% of hOCR lines are continuations. Joining *before*
   filtering matters — a continuation like `259 Himrod` is short enough that the text filter would
   drop it, taking the address off the entry above.
2. **Text filter** — page numbers, ALL-CAPS running heads, sub-8-char fragments, non-ASCII garbage.
   Calibrated: keeps 76% on 1906BPL. **It is not an entry detector** and happily passes ad copy.
3. **Geometry filter** — drops lines >2× the page's median line height (`bigtype`) or >1.5× the
   median width (`banner`). Judged against each page's own medians, so one setting spans an 1786
   single-column folio and a 1933 six-column Polk. **Not validated against gold** — no box-level
   gold exists.
4. **Ditto normalization** (see below), applied *at emission*, after every filter has seen the
   original text.
5. **Band marking** — `context.band` = `head` / `body` / `foot` / `null`. See below.

### Measured throughput

| volume | leaves | hOCR lines | joins | candidates | kept |
|---|---|---|---|---|---|
| 1906BPL (ABBYY scan) | 1,240 | 329,989 | 37,196 | 292,793 | **199,012 (68.0%)** |
| micro_IABROOKLYN_0013 (tesseract microfilm) | ~100 | 3,676 | — | 3,460 | **2,889 (83.5%)** |

Cache is `data/ia_cache/`, **~291 MB per volume** against ~1 MB of output. **Discard it per volume
on a corpus sweep** — 291 volumes would be 50–60 GB.

### Ditto normalization — on by default, and the part most worth understanding

A surname-repeat ditto is printed `"`, and ABBYY reads it as `44`. On 1906BPL **`44` is the single
most common leading token in the book — 84,053 of 199,012 lines (42%)** — and the generator never
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
nothing. Note the irony: `entry_rate` measures fabrication at **20.7% on that thin tier against 10.4%
on the dense one**, so this solves page-type for the tier that was already twice as good. See
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

---

## Stage 5 — Post-processing: resolve the dittos

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

**Within-line is deterministic**: 17 hits across 9,830 gold records, zero false positives.

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
against 40 read lines (the obvious surname-shape proxy scores 67.5%). Measured: 1836 tesseract
microfilm **20.7%** not-real vs 1906 ABBYY **10.4%** — the clean tier is 2× better.

⚠️ **It cannot see field-boundary quality.** `is_entry` is `name` non-empty AND an address-shaped
string, so `name='44 Wm elk'` with an empty occupation scores as a perfect entry. Proved by paired
re-measurement: 299 of 500 inputs changed, 3 records recovered an occupation, and **zero rows
changed classification**. Cite it for fabrication; never as record quality.

**`evaluate.py` — only where gold exists.** Judge model changes on **`--report-normalized`**, and
publish verbatim. This project spent three cycles learning that a verbatim gain which vanishes
under normalization is typography, not extraction.

---

## What is NOT in the pipeline yet

- **No whole-volume gold**, so volume-scale field accuracy is unmeasured. The 21-volume panel is
  sampled pages; `entry_rate` is a proxy with a known blind spot.
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

**2. A boundary-sensitive quality proxy.** `entry_rate` is blind to the failure that normalization
fixes, which means **the pipeline currently has no instrument for field-boundary quality at all**.
A proxy scoring "line contains an occupation token AND `occupation_role` is populated" already
exists in `results/ab_ditto44_1906BPL_2b100k_preds/analyze.py` and was validated on the pilot —
promoting it to a real instrument is a small job with high leverage on every future claim.

**3. Make `alpha_run_filter` mark rather than drop.** Removes the structural conflict with ditto
expansion and makes `--apply` safe to reconsider on its own merits.

**4. Re-measure `entry_rate` on the thin tier after normalization.** The 20.7%/10.4% comparison was
taken pre-normalization. It probably will not move (see stage 6), but confirming that on a
*different OCR engine* is the cheap generalization check.

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

## Medium effort, high information

**5. Does the `44` finding generalize?** It is measured on one volume, one OCR engine, one adapter.
The paired design is cheap to repeat — pick a Polk or Trow volume with a *different* dominant ditto
glyph and re-run. **This is the single most load-bearing untested assumption in the pipeline**, since
normalization is now on by default for every volume.

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

**8. Implement the Duncan address slot grammar.** `71 do. do.` is two independent slots; the
grammar is documented in `resolve_dittos.py` but not implemented. ~45 rows in duncan1794, more
across the early volumes. Small but it is currently a known-wrong output on those books.

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

**12. Run a whole volume on the 4B, on the HPC.** The release candidate has never processed a
volume; every whole-volume number in this repo is from the 2B. Rented GPU, hours not days.

**13. Records assembly.** Predictions → a CSV/IIIF-annotated export with `ditto_source` provenance
carried through. This is what makes the output usable by anyone outside the repo, and stage 5's
`*_resolved` fields were designed for it.

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
