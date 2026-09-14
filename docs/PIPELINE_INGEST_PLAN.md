# Plan — ingest `directory-pipeline` output into `{raw_line, context, record}` JSONL

**For:** an agent working across two repos.
**Status:** not started. Written 2026-09-14.
**Sibling of:** `data_prep/ia_volume_to_jsonl.py`, which does the same job from IA's own hOCR.
Read that file's module docstring first — this plan assumes its vocabulary (`text_reject`,
`geom_reject`, `join_wraps`, `--dump-dropped`, `page_size`) and reuses most of its machinery.

**Proposed artifact:** `data_prep/pipeline_volume_to_jsonl.py`.

---

## Why

`ia_volume_to_jsonl.py` reads **IA hOCR**. That is free, needs no GPU, and covers any IA volume —
but it is the *scan vendor's* OCR, and `docs/HANDOFF.md` records that for microfilm tiers it is
tesseract-on-Fraktur-misread.

Meanwhile `~/github/directory-pipeline/output/` already holds, un-ingested:

| | measured 2026-09-14 |
|---|---|
| output dirs with aligned or surya pages | **94** |
| pages with a `_aligned.json` (model text + line boxes) | **19,748** |
| pages with a `_surya.json` (boxes, dims, per-line confidence) | **11,006** |
| distinct OCR engines represented | **9** |
| dirs with ≥100 aligned pages | **18** |

That is a corpus the size of several volume sweeps, already paid for, that this repo cannot read.
It also reaches material the IA path **structurally cannot**:

- **Non-IA sources.** `tulsa_1921`/`tulsa_1922` (933 + 833 pages) are CONTENTdm
  (`p15020coll12:2453_left`), and there are NYPL and LoC dirs. No IA identifier, therefore no IA
  hOCR, therefore no `ia_volume_to_jsonl.py` path at all. Tulsa is a **panel volume** — the repo
  scores `tulsa_eval.jsonl` (1,500 rows, and **131 populated `race_designation` rows, the most of
  any eval set — next is NYU at 33**) and has no way to sweep the rest of the book.
- **Better text.** `_aligned.json` is a hybrid: **surya's line boxes carrying a frontier model's
  text.** Verified on `hearnesbrooklync1852unse` leaf 175 — the surya and aligned boxes are
  byte-identical (`[328,176,1218,211]`), only the text differs.
- **An OCR confidence signal.** `_surya.json` carries per-line `confidence` (0.9264, 0.956, …).
  Nothing in `data/` has ever had one.
- **Multi-engine agreement.** In `green_books_and_related`, **1,814 of 4,024 pages** carry two
  independent model transcriptions of the same boxes. That is free disagreement-detection.

---

## The one hard rule: leakage

Same rule as `NAME_HARVEST_PLAN.md`, and **it bites harder here**, because these dirs contain the
exact gold pages.

Verified: `lain_eval.jsonl` (800 rows, `REVIEW:`-flagged **EVAL HELDOUT**) is built from 1897BPL
leaf 0028. That leaf is present in
`lain_healy_s_brooklyn_directory_for_the_1897BPL/`, aligned **three times over** —
`apple-vision`, `chandra-ocr-2`, `gemini-3.1-flash-lite-preview`. `1876BPL` (`lain1876_eval.jsonl`)
likewise has an output dir.

**The rule:**

1. **Hard-exclude whole volumes** flagged EVAL HELDOUT: NYU Trow Manhattan 1850/51, Lain & Healy
   Brooklyn 1897 (`1897BPL`).
2. **Everywhere else, exclude at page level.** Every `data/*_eval.jsonl` row carries
   `context.image`. Build the exclusion set by reading those strings and matching the **leaf**, not
   the filename prefix (see trap 1 — they differ, and for 1897BPL they differ *on the gold page
   itself*: eval `…_0028.jp2.jpg` sits at prefix `0029`, while pipeline prefix `0028` is leaf
   `0027`). Match on the `_<LLLL>.jp2` segment.
3. `--require-leakage-check` should be the **default**, with an explicit `--allow-eval-pages` escape
   for someone deliberately rebuilding gold. A silent default that leaks is how a panel stops
   meaning anything.

---

## What is genuinely different from the IA path

Six of these are mechanical. **Trap 3 and trap 6 are the ones that will produce plausible, wrong
data if skipped.**

### 1. The `<NNNN>` filename prefix is NOT the leaf number

```
0231_hearnesbrooklync1852unse%2F…%2Fhearnesbrooklync1852unse_0235.jp2_gemini-2.0-flash_aligned.json
^^^^ running index                                            ^^^^ actual leaf
```

It tracks the leaf through index 187, then drifts as absent leaves accumulate. **397 of 584 files**
in the Hearne volume have prefix ≠ leaf, ending at a 4-leaf gap. Parse the leaf from the trailing
`_<LLLL>.jp2` segment. Never from the prefix.

### 2. Filenames are URL-encoded and carry the model

```
<idx>_<ident>%2F<ident>_jp2.zip%2F<ident>_jp2%2F<ident>_<leaf>.jp2_<model>_aligned.json
```

…but only for IA-sourced dirs. Tulsa is `0369_p15020coll12:2807_right_gemini-3.1-flash-lite_aligned.json`
— no `%2F`, no `.jp2`, a `:` in the id, and a `_left`/`_right` **spread-half** suffix. The parser
needs both shapes and must fail loudly on a third rather than guessing.

### 3. ⚠️ `page_size` — three coordinate spaces, and the file records the wrong one

Measured on Hearne leaf 175:

| space | dims | where |
|---|---|---|
| `_aligned.json` → `bbox`, `_surya.json` → `bbox` | **1800 × 3194** | the downloaded **JPEG** |
| `_aligned.json` → `canvas_width`/`canvas_height`, `canvas_fragment` `xywh=` | **1978 × 3510** | the **IIIF canvas / jp2** |
| what `ia_volume_to_jsonl.py` writes to `context.page_size` | jp2 space | IA hOCR |

The scale factor is 1.0989 in both axes (`bbox` x37 → frag x41; w1208 → w1327).

**`_aligned.json` does not record the JPEG dimensions it measured `bbox` in.** It records only the
canvas dims. So the obvious move — copy `canvas_width`/`canvas_height` into `page_size` — is wrong
by **9.9%**: small enough to survive a spot check, large enough to put a crop a full line off by
mid-page. That is precisely the "plausible-looking lie" `ia_volume_to_jsonl.py` warns about, and it
is pre-loaded here.

**Get `page_size` from `_surya.json`'s `image_width`/`image_height`** (verified 1800 × 3194). When
the surya sidecar is absent — and it is for **`_ocr_backups` (6,862 aligned, 0 surya)** and
`the_brooklyn_city_directory_01015253` — read the JPEG's SOF header. If neither is available,
**write `page_size: null` and do not guess**; a null is honest and downstream can skip it.

Also note this makes a *fourth* wrinkle: a pipeline-derived row and an IA-derived row for the same
`ia_id` + `leaf` will have boxes in **different spaces**. Record the space explicitly —
`context.bbox_space: "jpeg"` vs `"jp2"` — or the two can never be safely merged.

### 4. Model selection is a real choice, not a default

Nine engines across the corpus:

| model | pages | | model | pages |
|---|---|---|---|---|
| `gemini-2.0-flash` | 10,897 | | `gemini-3-pro-preview` | 108 |
| `gemini-3.1-flash-lite` | 4,208 | | `apple-vision` | 99 |
| `gemini-3-flash-preview` | 3,679 | | `chandra-ocr-2` | 63 |
| `gemini-3.1-flash-lite-preview` | 654 | | `gemini-2.5-flash` | 36 |
| | | | `gemini-3.1-pro-preview` | 4 |

Needs `--model <name>` plus a `--prefer` precedence list for mixed dirs, and `context.ocr_model`
recorded on **every** row. `docs/SURVEY_PLAN.md` (lines 377–379) already treats the OCR engine as a
first-class corpus variable — ABBYY-8 71 volumes, tesseract-microfilm 49, ABBYY-9 39, none 21,
ABBYY-11 4. A model field that is absent on some rows and present on others is an unanalysable
confound later, for zero saving now.

### 5. The alignment is many-to-one in places

On Hearne leaf 175, surya emits `"163"` and `"BROOKLYN CITY DIRECTORY."` as two lines; the aligned
file emits one line, `"BROOKLYN CITY DIRECTORY. 163"`, carrying **only the second box**. So an
aligned `bbox` does not always cover all of its own text. Harmless for the running head that
`text_reject` drops anyway, but it means **boxes are a lower bound on extent** — do not treat an
aligned box as a tight crop without checking.

### 6. ⚠️ Bracket-overflow: a wrap convention the IA path has never seen

Hearne sets a word that will not fit at the **right margin of a neighbouring line**, in an open
bracket. **235 lines** in this volume:

```
   Abbott John D, merchant 297½ Pearl NY h 334 Atlantic n
>> Abbott Mary Ann, widow 41 Little [Hoyt          → "…334 Atlantic n Hoyt"   (attaches UP)

   Arcularius Letitia, widow of P I, Pacific n Powers [Hook
   Arkleburg James, shoemaker Commerce n Richard st Red   → "…Richard st Red Hook" (attaches DOWN)
```

**It goes both ways.** The bracketed word belongs to whichever *neighbour* is syntactically
incomplete — dangling on `n`/`c`/`b`/`op`/`and`, or on a bare house number (`h 111` + `[Union`).
Only **37 of 235 (16%)** have an unambiguous dangling connector on the line immediately above; the
rest need the line below, or judgement.

Untreated this corrupts **two** entries per occurrence: the real entry silently loses its
cross-street (often the entire address, since Hearne addresses are relational), and its neighbour
gains a junk `[Word` token.

**Recommendation: detect and flag, do not auto-resolve.** Emit `context.bracket_overflow` with the
token and the inferred direction (or `null` where ambiguous), leave `raw_line` as printed, and let a
later stage decide. This follows the `band` precedent — *"MARK, never drop … Downstream decides;
this only records."* An 84%-confident heuristic applied silently would manufacture ~38 confidently
wrong addresses in one volume, which is the `deep_indent` failure mode exactly.

Whether other publishers use the convention is **unmeasured** — check before generalising the
regex. It may warrant a `--bracket-overflow` flag keyed off the style profile.

---

## What ports over unchanged (verified, not assumed)

Run against Hearne leaf 175's aligned lines, importing the real functions:

| stage | result |
|---|---|
| `text_reject` | 45 lines → **44 kept**, 1 `allcaps` (the running head). Correct. |
| `page_geometry` | `med_h=52`, `body_width=1113`, `ad_score=0.000` on a clean listing page |
| `geom_reject` | **0 drops** — no `bigtype`, no `banner` false positives |
| `join_wraps` | leaf 27: 34 raw → 32, **2 joins**, and the hyphen case closes up correctly: `…h 135 Jorale-` + `mon n Court` → `…h 135 Joralemon n Court` |
| `*` race marker | `*Ephenette Louis Alphons, segar maker Navy c Tillary` survives **both** filters |

So the filter stack transfers. The work is the **reader** in front of it, not the filters.

Volume-wide wrap counts for sizing: **418** hyphen-wrap lines, **235** bracket-overflow lines, in
27,263 OCR lines.

Ditto normalization should be **off by default** for Hearne (its style profile records
`markers.ditto: null`) but kept available — other pipeline volumes (Polk, Trow) are ditto-heavy.

---

## Steps

1. **`data_prep/pipeline_volume_to_jsonl.py`**, PEP-723 self-contained with `--self-test`, matching
   the house pattern. Import — do not fork — `text_reject`, `join_wraps`, `page_geometry`,
   `geom_reject`, `left_margins`, `margin_reject`, `tag_publisher`, `lookup_master`,
   `ditto_lead_candidates`, `normalize_ditto_lead`, `leaf_bands`, `EMPTY_RECORD` from
   `ia_volume_to_jsonl.py`. If that means lifting them into a shared `data_prep/_lines.py`, do that
   as a **separate, behaviour-free commit first** so the refactor and the new reader are reviewable
   apart. The IA path's measured keep-rates must not move; `--self-test` on both proves it.

2. **The reader.** Replace the `Item` class (network, cache, Range requests, pageindex) with a
   local directory walk. Per page: locate `_aligned.json` (by `--model`/`--prefer`), pair it with
   its `_surya.json` sibling for `page_size` + `confidence`, parse ident/leaf/half from the
   filename, fall back to the JPEG SOF header for dims, else `page_size: null`.

3. **Context schema.** `ia_id` and `leaf` become **optional** — Tulsa has neither. Add:

   ```
   source_dir        directory-pipeline output dir (provenance)
   source_page       the page id as the pipeline knows it ("p15020coll12:2453_left")
   ocr_model         "gemini-2.0-flash" | ...          (never omit)
   bbox_space        "jpeg" | "jp2"                     (never omit)
   ocr_confidence    surya per-line float, or null
   page_half         "left" | "right" | null            (spread splits)
   bracket_overflow  {token, direction} or null
   ```

   Keep `publisher`, `directory_year`, `bbox`, `page_size`, `band`, `raw_line_original` exactly as
   the IA path writes them, so the two files stay interchangeable downstream.

4. **Leakage guard**, default-on, per the hard rule above.

5. **Validate before trusting — the non-negotiable step.** `--dump-dropped` must exist and someone
   must *read it* before a model is run over the survivors. `ia_volume_to_jsonl.py`'s docstring
   records this project paying for that lesson three times, and the `banner` post-mortem records
   the fourth. Report keep-rate whole-volume, not on a handful of leaves — the six-leaf `banner`
   check is the cautionary tale.

6. **First target: `hearnesbrooklync1852unse`.** 584 pages, every stage complete, and the volume is
   now fully documented in `style_profiles/hearne_brooklyn_1850s.md`. It also settles an open
   item — the **312 asterisked lines** are the harvest source for the `race_designation` gap
   recorded in `HANDOFF.md` (the current `hearne1852_eval.jsonl` has 52 rows, 0 asterisks, 0
   populated `race_designation`, and comes from a different physical volume).

7. **Second target: `tulsa_1921`.** Different everything — CONTENTdm ids, spread halves, no IA
   identifier, a panel volume with existing gold to sanity-check tone and format against. If the
   reader handles Hearne and Tulsa, the schema is right.

---

## Open questions

- **Is bracket-overflow Hearne-only?** Unmeasured. Cheap to check across the 18 dirs with ≥100
  aligned pages; do it before hard-coding the regex.
- **Does `geom_reject` still earn its place?** It was calibrated on hOCR, where ads and headings
  differ in *set size*. Model OCR on surya boxes may separate differently — and on Hearne leaf 175
  it dropped nothing at all, so its value here is **unproven, not demonstrated**. Measure keep-rate
  with and without before leaving it on by default.
- **What is the per-line `confidence` actually worth?** No threshold is justified yet. Record it;
  do not filter on it until someone measures a cut against read pages.
- **Multi-model disagreement** — 1,814 green-books pages have two transcriptions of identical
  boxes. Worth its own measurement (is disagreement a usable error proxy?), but it is a *second*
  project. Do not let it into v1.
- **Does any of this beat IA hOCR on a volume where both exist?** Hearne has both. That is a
  head-to-head nobody has run, and it is the honest justification for the whole path — or the
  finding that kills it. Run it early.
