# Handoff — city-directory-extraction

> Working state as of 2026-07-19. Read this first if resuming in a new session.
> Companion docs: [plan.md](plan.md) (full rationale/roadmap), [../README.md](../README.md) (how-to).

## TL;DR — where we are right now

We're fine-tuning a small **Qwen3.5** model to turn one historical city-directory line into a
structured 8-field record (synthetic-train / real-gold-eval), aiming to match a Gemini baseline,
then release to HF. **The 0.8B run is competitive with Gemini per-field but Gemini still leads
overall** (see the metric nuance below) — after fixing an eval-loader bug.

**Measured on NYU gold (500 rows, YAML).** Scoring note: `macro-F1` = avg over fields the gold
actually has; `micro-F1` = frequency-weighted overall (see `evaluate.py`). Both matter — and they
disagree:
| model | macro-F1 | micro-F1 | whole-row EM | notes |
|---|---|---|---|---|
| GLiNER zero-shot (floor) | 0.381 | 0.594 | 8% | |
| qwen-2b (pipe, 20k×1) | 0.281 | 0.375 | 0% | bad — pipe shift + undertrained |
| Gemini 3.1-flash-lite (bar) | 0.672 | **0.910** | **70%** | leads on micro + EM |
| **qwen-0.8b-yaml (100k×3), fixed** | **0.760** | 0.755 | 26% | edges Gemini on macro only |

**The honest read:** we **edge Gemini on macro-F1** (0.760 vs 0.672 — we do relatively better on
*rare* fields like spouse/race) **but Gemini dominates micro-F1 (0.910 vs 0.755) and whole-row EM
(70% vs 26%)** — i.e. the high-volume `name`/`address` fields and complete-row correctness, which
are what matter most for replacing Gemini in the pipeline. So: **not "we beat Gemini" — Gemini is
still ahead where it counts.** In-distribution (synth_dev) the model is ~perfect (macro ~1.0); the
synthetic→real gap is concentrated in `name`/`address`.

> **The eval-loader bug (2026-06-18):** the first scores looked *broken* — NYU macro **0.358**
> (below the GLiNER floor). Root cause was NOT the model or data: eval loaded
> `AutoModelForCausalLM` (text-only) while training (`SFTTrainer(model="id")`) auto-loaded the FULL
> multimodal Qwen3.5 (vision tower). `all-linear` adapted the vision tower too, so the adapter keys
> were multimodal-nested; grafting them onto the text-only eval model failed *silently* ("missing
> adapter keys") → **every eval ran on the bare base model.** Fixed in `qwen_predict.py` by loading
> `AutoModelForImageTextToText` first. Same weights, fixed loader → 0.358→0.760 macro on NYU.

**Project reframe (2026-06-18):** the goal is now **ONE NYC-comprehensive model** — parse NYC
directories ~1786–1925 across all boroughs + publishers (Trow, Lain, Polk, Doggett, …) — with
**cross-city transfer as a *measured* stretch** (hold out Tulsa/Minneapolis). Not per-publisher
models: the failures are training-coverage gaps, not capacity limits (one model already handles
Tulsa≈NYU). Full rationale + waves: `~/.claude/plans/i-want-to-slightly-golden-frog.md`.

**Immediate next action:** **#1 — close the synthetic→real gap**, concentrated in `name` (model
*regularises* unseen surnames to the ~54 it was trained on → Lain name-F1 0.33). **Tooling is now
built & committed** (`605d82f`): the generator draws from 40k real census surnames + names harvested
from the actual directories (was 54). Remaining: (a) your other agent expands `master_directories.csv`;
(b) run the page-sampler → pipeline OCR/extract → `harvest_names.py` to fold real names in;
(c) add a publisher/era context tag, regenerate, retrain (`rtx-pro-6000` b64 + `--packing` +
`exclude_modules=["visual"]`, ~$6), re-run the eval panel. See §"Next steps".

## Full-panel scores — v2 run (2026-07-19): the coverage fixes landed

**`hadro/city-dir-08b-yaml-v2`** = 0.8B / 100k **regenerated** synth (era-gated NYC features
measured from the gold panel + style cards — dittos, marker-kept sole addresses, widow variety,
abbreviation periods, surname commas, 1920s addresses, ALL-CAPS persons; commit `69826ac`) /
yaml / 3 epochs / batch 64 / **unpacked** (config-identical to v1 so deltas are attributable to
the data) / rtx-pro-6000 / **$7.23, 2.63 h** (`exclude_modules` verified — 0 visual adapters,
the adapter is finally text-only). Scored panel + externals locally on the M2 (~2.5 h, label
`qwen-0.8b-yaml-v2`; per-set preds `data/preds_v2_*.txt`; v1-matched row counts).

**Panel-wide field F1 (weighted by gold non-empty n), v1 → v2:**

| field | v1 | v2 | Δ |
|---|---|---|---|
| name (n=1169) | 0.45 | **0.76** | **+0.32** |
| spouse_name (162) | 0.63 | **0.90** | +0.27 |
| address (1166) | 0.43 | 0.54 | +0.11 |
| occupation_role (851) | 0.77 | 0.82 | +0.04 |
| home_address (164) | 0.00 | 0.00 | gold wobble — see below |

- **Trow dittos SOLVED** (the predicted #1 lever): trow1913 name 0.02→**0.90**, trow1907
  0.19→**0.90** (EM 6→41%). Whole-row EM rose on 14/18 volumes (duncan1794 0→66%, mercein1820
  18→70%, boyd1890 47→79%, hope&henderson 2→45%).
- **Externals:** lain 0.675→**0.849** macro (the original name-gap poster child), tulsa
  0.791→0.851 (**no** NYC-focus regression), minneapolis 0.592→0.611, ftd ~flat. **NYU micro
  0.755→0.827, EM 26→44%** (Gemini bar: 0.910 / 70% — gap roughly halved); NYU macro
  0.760→0.659 — a convention conflict, not a capability loss (below).

**Three leftovers, precisely diagnosed:**
1. **home_address 0.00 = gold-side convention wobble, NOT a model failure.** NYU gold strips
   the `h` marker (model matches it → 0.69 there); panel gold mostly KEEPS it → every panel row
   mismatches. Reconcile via `validate_gold` + a convention decision **before** the next
   retrain — it's a free lift on n=164.
2. **NYU spouse 0.60→0.00 = verbatim vs normalized; v2 is arguably right.** Raw `widow of
   Joseph` → v2 copies verbatim (panel contract conv #1/#9); NYU's labels normalize to `wid
   Joseph`. v1 only "won" because its generator could emit nothing but `wid X`. Same class as
   the employer conflict; fix = publisher/context tag or a scoring-time translation for the
   NYU set. This (n=38) plus race (n=6) is the entire NYU macro drop.
3. **Dense late-Polk is the remaining hard core:** polk1917/1925 + queens1933 at name ≤0.37,
   address ≤0.13, EM 0% — quote-ditto training helped only marginally; the terse,
   abbreviation-dense, employer-rich style is Wave-1 publisher-parameterization territory.

Also observed: rare **given** names still regularize (`Philenah`→`Philip`) — give the
given-name pool the census treatment next cycle, like the surname fix.

**Gemini bar on the panel (2026-07-19, first time):** gemini-3.1-flash-lite, same
lines/schema/prompt, all 18 volumes (preds `data/preds_gemini_*.txt`). **qwen-v2 wins 17/18
volumes on macro** and every line-weighted aggregate: macro **0.656 vs 0.555**, micro **0.754
vs 0.695**, whole-row EM **38.6% vs 23.2%**. The NYU story INVERTS on our contract: Gemini's
EM collapses on convention-heavy volumes it was never told about (boyd 4% vs 79, lain1876 6%
vs 54, hope&h 2% vs 45 — it resolves dittos/normalizes instead of copying verbatim). Gemini
still wins occupation_role (0.90 vs 0.82) and the one dense volume doggett1846. Both score
0.00 on home_address (more evidence the gold marker wobble penalizes everyone — fix the gold)
and 0.00 race (n=7). Both are EM=0 on the late-Polk core — that floor is task difficulty, not
a qwen-specific gap. Honest caveat for the writeup: our model *trained on* the labeling
contract while Gemini is zero-shot on it, so part of the gap is contract knowledge — which is
also the point of the fine-tune, and matches how each would actually run in the pipeline.

**PRIMED re-run (same day) — the caveat above was load-bearing; the headline flips.** The old
FIELD_GUIDE taught Gemini the stale NYU-era contract (worst: "drop the NYC 'h.' label", no ditto
rule). Updated it to the current gold contract (`gemini_baseline.py`, label
`gemini-3.1-flash-lite-primed`) and re-ran: **macro 0.691 / micro 0.821 / EM 48.5% — primed
Gemini retakes the panel lead** (14/18 volumes) over qwen-v2 (0.656/0.754/38.6%). So the 17/18
result was substantially a stale-prompt artifact; **cite only the primed bar**. The
contract-parity field split is the real story: **qwen-v2 still wins name (0.76 vs 0.72) and
spouse (0.90 vs 0.85)** and the earliest volumes (franks/duncan/hearne/boyd); **primed Gemini
wins address 0.77-vs-0.54** (the info IS in the lines — qwen's address gap is real capability,
now the #1 model gap), occupation (0.94 vs 0.82), employer (0.58 vs 0.51). In-prompt ditto
compliance largely works zero-shot (lain1876 EM 6→76%; trow1913 0→53%) and primed Gemini even
cracks the late-Polk core best (polk1917 EM 12%, macro 0.518). home_address ≈0.00 for ALL
three systems — the gold marker wobble reconfirmed a third way; fix the gold first. Roadmap
read: (1) gold home_address reconciliation, (2) address realism is the next synth target
(late-Polk especially), (3) name/verbatim-copying is the fine-tune's durable edge.

**Gold home_address reconciliation DONE (2026-07-19):** 159 rows across 16 gold sets stripped
to the bare-address rule (conv #8 amended in GROUND_TRUTH_HANDOFF).
Re-scored all existing preds against the corrected gold (predictions unchanged — scorer only).
The fix lifted BOTH systems ~+0.08 macro exactly as predicted; relative standing unchanged.
**Completed same day (cycle-three session): the FUSED-marker tail** — the first sweep only
caught spaced markers; 29 fused rows (`h502 W149th`-style; trow1913 21, polk1925 4, polk1917 2,
queens1933 1, polk1933bk 1 `r`-fused) swept to bare, and `validate_gold.py` now ERRORs on
marker-leading home_address (leading `r` = WARNING only; may be `rear`). Also fixed 4
polk1933bk rows verified against the page images: 3 raw_line wrap-joins glued without a space
(`avand`/`Lexav`/`r640` — fake fusions; conv #15 amended) + 1 field slip (`E26th`→`E 26th`).
**Final corrected panel aggregates (cite these): qwen-v2 macro 0.736 / micro 0.779 / EM 44.6% /
home F1 0.69 / addr 0.54; primed Gemini 0.794 / 0.849 / 56.8% / home 0.89 / addr 0.77.** The
fused sweep widened primed Gemini's lead (its residual home penalty was gold-side); qwen's home
gap is now content errors on dense fused lines — same root as the address gap. Panel gold is
validator-clean (0 errors, 11 benign warnings). Gold sets are gitignored — corrected copies in
`data/` (user keeps Time Machine backups; pre-sweep copies in session scratchpad).

## RESUME HERE — cycle four (2026-07-19 late): v3 SCORED — first macro lead; two 1-line fixes queued

**Cycle three completed end-to-end.** `hadro/city-dir-08b-yaml-v3` = 100k v3 synth
(`synth_train_v3.jsonl` on the hub; publisher tags + all cycle-three features) / yaml / 3 ep /
b64 / unpacked / rtx-pro-6000 / **$7.35, 2h40m** (job `6a5d262e…`, `done ->` verified;
loss 0.0035). Panel + externals scored locally (preds `data/preds_v3_*`); **fresh primed-Gemini
bar re-run under the new publisher-tag prompts** (label `gemini-3.1-flash-lite-primed-pub`,
preds `data/preds_gemini_pub_*`): 0.790/0.844/58.0% — statistically identical to the old primed
bar, so the tag gives Gemini nothing (it's conditioning leverage for the fine-tune only).

**The v3 board (18 vols / 1169 lines, line-weighted; cite this):**
| | macro | micro | EM | name | addr | home | occ | spouse | emp |
|---|---|---|---|---|---|---|---|---|---|
| qwen-v2 | 0.736 | 0.779 | 44.6% | 0.76 | 0.54 | 0.69 | 0.82 | 0.90 | 0.51 |
| primed-pub Gemini | 0.790 | **0.844** | **58.0%** | 0.73 | **0.78** | **0.87** | **0.91** | 0.75 | **0.55** |
| **qwen-v3** | **0.798** | 0.840 | 54.8% | **0.78** | 0.74 | 0.83 | 0.84 | **0.91** | 0.54 |

**First fine-tune macro lead on a current-contract bar; micro a tie; Gemini keeps EM + volume
wins (13–5).** Address +0.20 (fused-token volumes 0.82–0.94: trow1913 0.93, polk1917 0.82,
polk1925 0.93), home +0.14. Publisher-conditioned features all landed: ogden `*` → macro 0.93 /
EM 89%; duncan `do.` → EM 71%; mb1931 EM 89%. **Externals up despite NYC-first mix:** tulsa
0.851→**0.889**, lain 0.849→0.864, minneapolis 0.611→**0.795** (unseen-city transfer — the
anti-overfit signal), synth_dev 0.992, NYU 0.594/0.830/44.6% (secondary; known spouse/race
convention conflict). **FTD 0.527/0.485/6.5% — DECISION: milestone-only from now on** (2k rows
≈ ⅓ of local scoring wall-clock for a number the loop never acts on; keep for the release card).

**Cycle-four worklist, in order of ROI:**
1. **DONE (fixes + regen; RETRAIN PENDING): the two one-line generator fixes.** (a) early-era
   year draw now starts 1786 and ≤1787 is 100% franks (Duncan starts ~1791) — 408 franks rows
   in the v4 100k (was ZERO in v3: the draw started 1790 so the ≤1787 gate was unreachable;
   franks1786 addr stayed 0.16). (b) **neighborhood-comma**: raw now prints `, {nbhd}` at 0.8p
   (render-side only; record stays comma-free per conv #3) — 800 comma raws in the v4 100k.
   44/54 polk1933si + most queens1933 v3 address misses were this comma; expect both EM=0
   volumes to flip. v4 data regenerated (same seeds 13/99/7), stats-gated, verbatim audit
   0/20k (comma-tolerant). **Next: upload `synth_train_v4.jsonl` + retrain (~$7, same config)
   + re-score panel (Gemini bar does NOT need re-running — its prompt is unchanged).**
2. **Occupation vocab harvest** (0.84 vs Gemini 0.91): extend `harvest_names.py` to
   trades/streets from sampled pipeline OCR — automated, pennies, no hand-labeling.
3. **Targeted gold** (user, in parallel): deepen polk1917/polk1925/queens1933 (per-set home
   n=3–6 → de-noise the exact fields cycles are steering on); ONE Longworth volume (12% of
   NYC training rows, zero eval coverage 1797–1817); a second Trow year as overfit guard.
4. Small gold QA: polk1933si `h33 LaForge Av PR` capitalizes `Av` against its raw (drift
   warning class); ~10 si OCR-copy slips (Benzer/Benziger) worth a page-image pass someday.

## Original cycle-three worklist (all pre-retrain items complete)

**State:** v2 trained/scored ($7.23); primed-Gemini bar established (0.794/0.849/56.8% vs qwen-v2
0.736/0.779/44.6% on fully-corrected gold — fused-marker sweep landed 2026-07-19); address
(0.54 vs 0.77) + home content on dense lines (0.69 vs 0.89) are the proven model gaps.
**Address error analysis done** (over `data/preds_v2_*` on the 7 worst volumes) — failure modes:
1. **Fused-token spacing = the dominant miss** (~283 "other-rewrite" rows): late-Polk print jams
   marker+number and direction+ordinal together (`r205 W141st`, `h2378 Bathgate av`); gold keeps
   it VERBATIM, the model re-spaces (`r 205 W 141st`) or mangles (`h2378`→`237-8`). The synth
   generator only ever emits spaced forms. Same lesson as dittos, at the character level.
2. house-number errors n=50 (franks1786 alone 23/56 — the 1786 number style needs its own look).
3. Room/office codes (`R2`, `R 309` → dropped or `Rd`) + out-of-town homes (`h Schenectady N Y`
   truncated) — small counts, easy synth adds.
4. split-into-home is ~solved (6 rows).

**Cycle-three `synth_persons.py` worklist:** fused marker+number (`r205`,`h2378`) + fused
direction+ordinal (`W141st`) at high p in late-era addresses — **fusion is publisher-specific**
(page-verified: polk1933bk fuses marker+number but spaces `E 26th`; trow1913 fuses both), so key
it off the context tag; franks-era number forms; room codes; out-of-town home values; PLUS the
deferred batch: publisher/era context tag (generator + gold contexts + BOTH predictor prompts in
one migration — retire `dialect`), NYC employer patterns (conv #7/#13), `*` race markers (safe
once tag exists), census given-name pool (Philenah→Philip), `--mix-weight 0.75`. Then regenerate
(`--stats` gate), retrain (rtx-pro-6000 ~$7 or Modal free — see TRAINING_OPTIONS.md), re-score
panel + primed Gemini. Target: address 0.54→0.70+, panel aggregate within reach of the primed bar.
**Done this session (2026-07-19):** (a) validator conv-#8 check + fused-marker sweep + polk1933bk
page-verified fixes (see the reconciliation section above); corrected gold backed up via the
user's Time Machine; (b) **the publisher/era tag migration LANDED** — prompt tag is now
`[publisher=trow; year=1913/14]` in all four builders (sft_qwen, sft_unsloth_smoke, qwen_predict,
gemini_baseline + a FIELD_GUIDE line), `context.publisher` in the generator (era-consistent
`_nyc_publisher`; tulsa profile tags `polk`; split years now slash-form matching gold), all 23
`data/*_eval.jsonl` migrated (panel by volume; tulsa→polk, nyu→**doggett** — the 1850 file's NYPL
uuid matches Doggett's 1850/51 in the master, not Trow; lain→lain, minneapolis→davison,
ftd→bottin), validate_gold requires `publisher` + ERRORs on retired `dialect`, make_gold_tool
auto-resolves publisher from the master CSV, harvest_own `--publisher` is now REQUIRED (no
default → no more lain-style mislabels). **Caveat:** v1/v2 adapters trained on the old
`[dialect=…]` tag — never re-predict them against migrated gold (their existing preds files
remain the canonical v1/v2 numbers); v3 onward uses the new tag. NYU = secondary external
check only.

## Full-panel scores — first run (2026-06-29)

First time the `qwen-0.8b-yaml` adapter (`hadro/city-dir-08b-yaml`) was scored across **all 18
per-volume gold sets** (1786–1933/34). Ran **locally on a 16 GB M2** — base `Qwen/Qwen3.5-0.8B`
was already cached (1.6 GB); `uv run eval/qwen_predict.py --target yaml` loads it as
`AutoModelForImageTextToText` (the multimodal class — avoids the silent eval-loader bug), MPS with
`PYTORCH_ENABLE_MPS_FALLBACK=1`. ~1.5 h for 17 vols (per-file model reload dominates). Raw per-row
metrics in `results/scores.jsonl` (label `qwen-0.8b-yaml`); macro table in `results/eval_table.md`.

**Panel-wide per-field F1** (recall-weighted by gold occurrences — the two highest-volume fields are
both the weakest, which is why overall scores stall):

| field | F1 | gold n | note |
|---|---|---|---|
| is_business | 0.89 | 1669 | fine |
| occupation_role | 0.70 | 1321 | ok |
| employer | 0.53 | 66 | weak (sparse) |
| **name** | **0.52** | **1669** | major drag — highest-volume field |
| spouse_name | 0.37 | 200 | weak |
| **address** | **0.44** | **1666** | major drag — highest-volume field |
| **home_address** | **0.07** | **303** | near-total failure |
| race_designation | 0.00 | 13 | never emitted |

**Per-volume spread:** best = `mb1931` macro **0.77** (terse M&B style: *no* ditto/spouse/home — the
model wins exactly where the hard features are absent). Worst = dense late-Polk Manhattan `polk1917`
**0.336** / `polk1925` **0.339** (name F1 .04/.00, address .08/.03). Every **EM=0%** volume
(polk1917, polk1925, polk1933bk, polk1933si, queens1933, trow1913, duncan1794) is ditto-heavy.

**Four systematic gaps — coverage, not capacity (priority order):**
1. **Surname-repeat ditto marks kill `name`.** Confirmed by spot-check: the model strips the leading
   `"`/`-` from every continuation row (`" Jno H`→`Jno H`, `" Louis`→`Louis`). name is exact-match, so
   every ditto row scores 0 → name F1 .00–.26 and **whole-row EM=0** on all dense Polk/Trow volumes.
   `synth_persons.py` never emits ditto names (rule #12 in GROUND_TRUTH_HANDOFF). **Biggest lever.**
2. **`home_address` near-zero (0.07, n=303)** — model collapses the second `h.` into `address`;
   generator under-produces the two-address pattern.
3. **`address` weakest on 1930s + earliest eras** — hyphenated outer-borough house nos (`24-12`) +
   neighborhood codes (`LIC`/`JH`) and 1786-era formats are out-of-distribution (polk1933*/queens1933
   address .02–.12; franks1786 .11).
4. **`race_designation` = 0** — never emitted (small n; clean synth fix).

**Conclusion — stop adding breadth; fix synth coverage.** The failures repeat across volumes and map
to specific missing synthetic features (ditto entries, home_address density, hyphenated/neighborhood
addresses, race marks), not to model capacity. Next: inject these into `synth_persons.py` (start with
ditto), regenerate, retrain, re-score this panel. The 18-volume panel is now the regression harness.

## Project in one paragraph

Replace the Gemini NER step in the sibling `directory-pipeline` repo for the city-directory
**persons** shape. Union schema (8 fields): `name, is_business, spouse_name, race_designation,
occupation_role, employer, address, home_address`. **Target = one NYC-comprehensive model** across
boroughs × publishers × eras (1786–1925); Tulsa 1921 stays in the mix as a second trained dialect
and, with Minneapolis, doubles as a held-out cross-city transfer test. Train on synthetic
(license-clean, ours), evaluate on real gold (NYU, Lain, FTD, Tulsa, Minneapolis). Modeled on
**Mattingly "3.6M names"** and van Strien's `small-models-for-glam`. Output = **YAML** (see decisions).

## Scripts (all PEP-723, self-contained, each has `--self-test` or `--preview`)

```
data_prep/
  synth_persons.py        # (line->record) generator; --profile {tulsa,nyc,mix} --target --n --seed
                          #   names now from census+harvested pools (was 54 inline); --packing-safe
  fetch_names.py          # build names/surnames.tsv (40k era-skewed US-Census surnames); --self-test
  harvest_names.py        # pipeline entries CSVs -> names/surnames_harvested.tsv (real names); merged
  names/surnames.tsv      # committed census surname pool (surnames_harvested.tsv is generated, gitignored)
  master_directories.csv  # multi-source (nypl|ia|loc|iiif) catalog for sampling; see its README
  ingest_collection.py    # BUILT: turn a collection link -> master rows (review-then-append).
                          #   nypl|ia|iiif source detect; --enrich (NYPL API+archive); see big section below
  nypl_api_archive/       # 155 item MODS JSONs + collection JSON (NYPL API dies 2026-08-01) — committed
  nyu_to_eval.py          # NYU NDJSON -> eval gold
  ftd_to_eval.py          # French Trade Directories -> cross-lingual transfer eval
  harvest_own.py          # Tulsa/Lain pipeline output -> eval gold (--dialect flag; Lain=nyc, not tulsa)
  harvest_minneapolis.py  # Minneapolis 1900 (MIT) transcription -> union-schema SILVER eval
  # sibling repo: directory-pipeline/sources/sample_directories.py  -> sample K pages/volume, download
  #   ONLY those (never whole volumes), ready for `pipeline ocr/extract` -> feeds harvest_names.py
train/sft_qwen.py         # TRL SFT; --target pipe|yaml, LoRA/--qlora/--full, --max-train-samples,
                          #   --batch-size, --epochs; runs locally OR via `hf jobs uv run`
eval/evaluate.py          # field-level P/R/F1/EM; --save <jsonl> --label <name> --target
eval/gliner_baseline.py   # urchade/GLiNER zero-shot extractive baseline -> preds
eval/gemini_baseline.py   # Gemini baseline (the "bar"); defaults --target yaml
eval/qwen_predict.py      # run fine-tuned Qwen -> preds; remote --gold (hf://) + --push-out (for Jobs)
eval/results_table.py     # pivot results/scores.jsonl -> model x eval-set Markdown table
notebooks/colab_finetune.ipynb   # free-Colab T4 training path (no paid plan)
cards/                    # MODEL_CARD.md + DATASET_CARD.md templates
results/                  # eval_table.md (tracked); scores.jsonl (gitignored log)
data/                     # gitignored: all eval sets, synth data, preds
```

## Key decisions & findings (the hard-won ones)

1. **Output format = YAML, not pipe.** Pipe is positional, so a model that drops an *empty* field
   column-shifts everything after it. Measured: pipe broke **~54%** of Gemini's NYU rows and our
   qwen-2b's too (is_business→True, fields dropped, `False` leaking into text fields). YAML names
   each key → immune. Mattingly reached the same conclusion. Train AND eval with `--target yaml`.
2. **Base model = Qwen3.5 (stay on it).** Mattingly used Qwen3.5 (0.8B/2B/4B), **500k** synthetic
   examples, **3 epochs**, YAML, H200 batch 128 → **94–96%**. So the base model is right; our weak
   results are from training at **20k×1 (≈25× too little data)**. Don't switch base models.
3. **External gold sources reviewed:** Minneapolis 1900 (`adamrangwala/DirCity`, MIT, US — added as
   `harvest_minneapolis.py` silver eval, needs review); SODUCO/FTD already used; geographie-cites
   23M = silver French geocoding (skip). See plan.md "External sources evaluated".
4. **GLiNER vs GLiNER2:** use original `urchade/GLiNER` (v0.2.27) — added as the extractive baseline.
5. **Stay on LoRA — MiCA (arXiv 2604.01694) considered & rejected.** "MiCA Learns More Knowledge
   Than LoRA" (Rüdiger & Raschka) freezes the adapter's `B` to the *minor* singular vectors of `W`
   and trains only `A`; claims up to 5.9× / +9.8pp on knowledge recall at 6–60% of LoRA's params.
   **Doesn't apply to us:** it optimizes *knowledge integration* (baking facts into weights), not
   our axis. Our task is structural instruction-following + verbatim span-copying, and our actual
   bottleneck is data coverage (surname pool), not adapter capacity. The authors explicitly scope
   it out: "MiCA in the current setup is **not designed for instruction fine-tuning** … tasks that
   primarily require structural instruction-following rather than knowledge integration may not
   benefit." Also untested in our regime — only 7B models (no sub-3B), only factual MC-QA (no
   extraction/IE/format tasks), and neutral-to-slightly-worse on general benchmarks (TruthfulQA
   35.29 vs LoRA 35.47). Don't A/B it; revisit only if the roadmap ever pivots to weight-baked
   domain facts. (Reviewed 2026-06-29.)

## Qwen3.5 GOTCHAS (critical — these cost us several failed runs)

`Qwen/Qwen3.5-*` is a **hybrid (linear-attention/conv) architecture that also carries a vision
processor**. Fixes already applied in `sft_qwen.py` / `qwen_predict.py`:
- **TRL renamed `max_seq_length`→`max_length`** — sft_qwen now builds SFTConfig kwargs and keeps
  only fields the installed TRL accepts (robust to drift).
- **Pass an explicit `AutoTokenizer`** to SFTTrainer — else new TRL calls `AutoProcessor`, which
  pulls a Qwen vision image-processor needing PIL/torchvision we don't ship → crash.
- **LoRA `target_modules="all-linear"`** — naming q/k/v/o_proj left ~¼ of layers un-adapted on this
  hybrid (the "missing adapter keys" warning). BUT all-linear also adapts the **vision tower**
  (`visual.*` — ~half the saved tensors); harmless to quality but wasteful. Use
  `exclude_modules=["visual"]` to skip it, OR load `AutoModelForCausalLM` at train time so no vision
  modules exist to match.
- **Train and eval MUST load the same model class** (the 2026-06-18 bug). `SFTTrainer(model="id")`
  auto-loads the FULL multimodal model; if eval uses `AutoModelForCausalLM` (text-only), the
  multimodal-nested adapter keys won't graft → PEFT warns "missing adapter keys" and **silently
  applies nothing** → eval scores at the base-model floor. `qwen_predict.py` now loads
  `AutoModelForImageTextToText` first (prints the class it used; verify the warning is absent).
  Symptom to recognize: a *trained* model scoring like an *untrained* one.
- **Missing fast kernels** (`flash-linear-attention`, `causal-conv1d`) → slow torch fallback →
  **~3 s/it** even on a100-large (should be ~0.3). **Measured: 0.8B / 100k×3 = ~4 h ≈ $10 on
  a100-large** (4689 steps; 100k×3 was ~13 h on L4). This is the dominant cost driver. See
  "Training speed — what we tried" below before attempting to fix it.
- **YAML targets are longer than pipe → OOM** on L4 at batch 16 (in `entropy_from_logits`). Fix:
  smaller `--batch-size` or a bigger GPU (a100-large 80 GB handles 0.8B at batch 64 fine).
- Precision auto-selects bf16 (Ampere+) / fp16 (T4). `--qlora` = 4-bit for fitting 4B on a T4.
- Harmless noise to ignore: `[ERROR] loss/logits ... not documented` (transformers docstring lint);
  `fast path not available` (the kernel fallback above).

## Training speed — what we tried (2026-06-18, don't re-run these)

Investigated whether the slow kernel fallback could be cheaply fixed. Smoke probes: 200 synth
examples, l4x1, batch 8, 1 epoch — compare `train_runtime` (baseline = stock TRL torch fallback).

| approach | train_runtime | verdict |
|---|---|---|
| baseline (stock TRL, torch fallback) | 33.2 s | reference (~1.32 s/it) |
| **`packing=True`** (`sft_qwen.py --packing`) | **26.6 s** | **~20% faster, free — the only win** |
| `--with flash-linear-attention` only | 84.0 s | slower; transformers still says "fast path not available" (needs BOTH kernels) |
| `--with flash-linear-attention causal-conv1d` | ERROR | `causal-conv1d` won't build in the uv image (no numpy build-dep, no `nvcc` → `bare_metal_version` error) |
| Unsloth (`train/sft_unsloth_smoke.py`) | 58–62 s | slower at this scale, even with gradient-checkpointing off; its kernels don't cover the hybrid layers (still "fast path not available") |

**Conclusions:**
- **Adopt `--packing`** (HF's default for SFT). ~20% on the smoke likely *understates* it — short
  examples + real length variance pack better on the full 100k. Caveat: packing changed the loss
  curve, so eyeball quality on the first real packed run before trusting it.
- **Kernels / Unsloth are NOT worth it at 0.8B / modest batch.** Manual kernels = build hell +
  no engagement; Unsloth's wins need large batch / VRAM-bound regimes (2B/4B) to amortize.
- **The real cost lever is the GPU** — and we measured it. Same 0.8B / batch 64 / YAML smoke
  (3200 samples) across flavors, extrapolated to a full 100k×3 run (300k samples):

  | GPU / config | throughput | est. full-run | est. cost | note |
  |---|---|---|---|---|
  | `a100-large` batch 64 (what we used) | 21.1 samp/s | ~3.9 h | **~$9.86** | $2.50/hr |
  | **`rtx-pro-6000` batch 64** | **31.4 samp/s** | ~2.65 h | **~$7.30** | **$2.75/hr — best value** |
  | `rtx-pro-6000` batch 128 (+env vars) | 25.6 samp/s | ~3.25 h | ~$8.94 | slower than b64 (see below) |
  | `h200` | — | — | est. ~$7.9–9.9 | **$5/hr; couldn't measure — backend 500, no capacity** |

  **Use `rtx-pro-6000` at batch 64**: ~26% cheaper *and* ~1.5× faster than the a100 we used, and a
  better deal than the h200 for a 0.8B (h200 at 2× the hourly rate is only break-even at best).
- **Batch 128 does NOT help us** (25.6 < 31.4 samp/s). Mattingly's batch-128 win needs the fast
  kernels he had; in our torch-fallback regime a bigger batch just adds memory churn.
- **Batch 128 OOMs by default** (YAML logits/entropy at full vocab), but two env vars make it fit
  — keep as an **OOM escape hatch** for bigger batch/model later:
  `-e HF_DEACTIVATE_ASYNC_LOAD=1 -e PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`.
- `--packing` (~20%) stacks on the GPU win → a packed rtx-pro-6000 run is ~$6.
- Reproduce/inspect: `sft_qwen.py --dry-run` (CPU, free) prints which modules get LoRA adapters —
  use it to confirm `exclude_modules` keeps the vision tower out (verified: 0 visual adapters).

## HF Jobs workflow & gotchas

Jobs work on account **`hadro`** (user has ~$5 PAYG credits; it ran despite docs implying Pro-only).
- Launch: `hf jobs uv run --flavor <f> --timeout <t> --secrets HF_TOKEN <local_script.py> <args>`
  — uploads the LOCAL script and installs its PEP-723 deps via uv. (So local edits take effect on re-run.)
- **Jobs are ASYNC** — the command returns immediately. You MUST wait for training to finish
  (`done -> <repo>`) before evaluating, or the eval 404s on `adapter_config.json`. Use
  `hf jobs logs <id>` (streams until done); `hf jobs ps` / `ps -a` to list running/all.
- **`--timeout` is mandatory** (default **30 min** silently kills training). Set generously; you pay
  for actual runtime, not the cap.
- Flavors: `l4x1` $0.80/hr (24 GB), `a10g-large` $1.50, `a100-large` $2.50 (80 GB),
  `rtx-pro-6000` $2.75 (96 GB — **best value, see speed section**), `h200` $5.00 (141 GB, often no
  capacity → 500). Full list + prices: `hf jobs hardware`.
- **Eval without a 5 GB local download** (slow wifi): upload gold to a private dataset, run
  `qwen_predict.py` as a Job with `--gold hf://datasets/...` + `--push-out hf://datasets/...`, then
  `hf download` the tiny preds and score locally (`evaluate.py`). The model stays in the datacenter.

## Hub & local resources (namespace `hadro`)

**Datasets:**
- `hadro/city-directory-synth` — `synth_train.jsonl` (100k), `synth_smoke.jsonl` (3k). PUBLIC.
- `hadro/cde-evals` — `nyu_eval.jsonl` (3000 rows!), `synth_dev.jsonl` (1k, seed 99), + `preds_*.txt`. PRIVATE (respects NYU CC-BY-SA-NC).

**Models trained so far:**
- `hadro/city-directory-extractor-2b` — 2B, **pipe**, 20k×1 → 0.246 NYU (bad; pipe+undertrained).
- `hadro/city-dir-yaml-test` — 2B, **yaml**, 20k×1, batch 8 → 0.447 synth-dev (the format test).
- `hadro/city-dir-smoke-0.8b` — throwaway pipeline smoke.
- `hadro/city-dir-08b-yaml` — **the good run**: 0.8B, 100k, yaml, 3 epochs, a100, batch 64.
  NYU macro **0.760** / micro 0.755 / EM 26%; synth_dev ~1.0 (fixed eval loader). Full eval panel
  in `results/eval_table.md`. Adapter wastes ~half its tensors on the vision tower (`all-linear`);
  a clean retrain with `exclude_modules=["visual"]` would shrink it.

**Local `data/` (gitignored):** `synth_train.jsonl` (100k), `synth_smoke.jsonl` (3k),
`synth_dev.jsonl` (1k), `nyu_eval.jsonl` (3000), `ftd_eval.jsonl`, `tulsa_eval.jsonl`,
`lain_eval.jsonl`, `minneapolis_eval.jsonl`, plus `preds_*.txt`.

**LoRA note:** `sft_qwen.py` defaults to LoRA → pushes an *adapter*. So `qwen_predict.py` needs
`--base-model Qwen/Qwen3.5-<size>` (drop it only for a merged/full checkpoint).

## Master-directory ingestion — `ingest_collection.py` (status 2026-06-18)

**Goal:** grow `master_directories.csv` by throwing collection **links** at a tool that extracts the
volumes and stages them for review. **Built and working this session** (was the "WIP" the rest of
this doc refers to). This is the workstream the IA follow-up lives in.

**Run it** (needs `requests` → use the pipeline venv):
```bash
PY=/Users/joshhadro/github/directory-pipeline/.venv/bin/python
cd /Users/joshhadro/github/city-directory-extraction
export $(grep -E '^NYPL_API_TOKEN=' ../directory-pipeline/.env | xargs)   # for --enrich; omit → IIIF fallback
$PY data_prep/ingest_collection.py "<collection-url>" [--enrich]   # → master_directories.pending.csv
#   ...review the pending file (fix publisher/borough, drop junk)...
$PY data_prep/ingest_collection.py --merge                          # append to master, dedup, clear pending
```

**Source detection** (`detect_source`): NYPL collection page / bare UUID → IIIF v3 collection
`api-collections.nypl.org/manifests/collection/{uuid}`; `archive.org/details/<id>` / bare slug → IA
`advancedsearch.php?q=collection:<id>` (paginated, `fl[]=` array form) **with a single-item
fallback** (`q=identifier:<id>`); any other URL → generic IIIF Collection/Manifest walk. Rows carry
`source` ∈ {nypl, ia, iiif}; the sibling `sample_directories.py` already resolves all of them.

**Review-then-append + dedup:** stages to `master_directories.pending.csv`, deduped on `(source,id)`
vs both master and pending. `--merge` is the only thing that touches the master. `--print` = stdout
only; `--limit N` caps; idempotent (re-ingesting a done collection reports "0 new").

**`--enrich` (NYPL only) — uses the dying API, archives everything:**
- Token from `NYPL_API_TOKEN` (lives in `../directory-pipeline/.env`; `.strip()`ed for CRLF). Header
  `Authorization: Token token="…"`. **API `api.repo.nypl.org/api/v2` is deprecated 2026-08-01** — no
  token → falls back to scraping the IIIF item manifests (`{uuid}.iiif.json`).
- Fetches `items/item_details/{uuid}` → MODS; fills `publisher` (known-list short name via
  `parse_publisher`, else raw imprint), `year`, `title` (primary titleInfo + partNumber), `borough`.
- **Borough is title-only** (`boroughs_in_title`): single borough named → fill; multiple → blank +
  `covers X, Y` note. MODS `subject.geographic` is deliberately NOT used (noisy — it cross-references
  e.g. a Brooklyn subject onto a Manhattan volume). No city-default guessing in the tool.
- **Archives every response** to `nypl_api_archive/{uuid}.json` (+ `_collection_{uuid}.json`),
  idempotent (skips existing). `--delay` (default 1.0s) paces it; `--no-archive-known` limits the
  sweep to new rows (default archives **all** items — deprecation insurance).
- `EVAL_HELDOUT` flags Trow-1850 / Lain-1897 with a `REVIEW:` note so eval volumes don't leak in.

**What's been ingested:** the NYPL **"New York City directories"** collection
`f7533140-3179-0134-f53a-00505686a51c` (155 items) → **+75 new rows, master 81 → 156 rows**. Then
backfilled `title` + `borough` + `city` for all rows from the archive; hand-curated 14 early imprints
to short names (Duncan, Longworth, Elliot, Mercein, Groot & Elston, …), and tagged 5 **telephone
directories** `PHONEBOOK` (separate-model candidate per the user). **Schema gained a `title` column**
(before `notes`); README updated.

**IA follow-up (status 2026-06-18 — IA path now run end-to-end):**
- The IA path is **built AND now exercised end-to-end** (was "unit-verified only"). Ran
  `ingest_collection.py` on real IA items via the single-item `identifier:<id>` fallback → staged to
  pending → curated → `--merge`. Works. IA enrich is title-regex only (no MODS): publisher/year parse
  fine, but IA `year` metadata is **unreliable** (the whole `trowsgeneraldir*` run is mis-tagged
  "1853" in IA's `year` field — use the `date` field / the year baked into the identifier instead),
  and titles need light curation (city, multi-borough `covers` note, part-volume labels).
- **Trow 1898/99 gap: NOT closeable via IA.** Searched IA exhaustively (title, keyword, date-range
  1898–1900, Google `bub_gb_*` scans) — the **residential** "Trow's New York city directory" for the
  year ending ~May 1899 is **absent from IA too** (IA's `Trow's New York city directory` scans stop
  at 1857/59/63/65/76; the only ~1900 Trow item is `ldpd_6943151_000`, the Columbia *copartnership &
  corporation* directory — a business directory, wrong shape). So 1898/99 is absent from BOTH NYPL and
  IA. The blank-`id` placeholder row stays. Next place to look would be HathiTrust / Google Books /
  LoC (outside the IA path).
- **Done this session — IA Trow gap-fills (master 156 → 160):** added 4 `source=ia` rows for later
  Trow volumes NYPL lacks (NYPL Trow general coverage ends 1913/14, then jumps to Polk/Trow 1920/21):
  `trowsgeneraldire1915trow` (1915), `trowsgeneraldire1917trow` (1917), and the two-part 1922/23
  (`trowsgenerald192223p1trow` / `p2trow`). All Manhattan+Bronx (borough blank + `covers` note per the
  README rule). None hit the eval-heldout signatures.
- **Done this session — BPL "Brooklyn city directories on microfiche" (master 160 → 346):** ingested
  the whole IA collection `brooklyncitydirectoriesonmicrofiche` (186 items) → curated → merged. Split:
  **79 residential** Brooklyn/Williamsburgh directories (1822–1908: Spooner, Hearnes, Smith, Reynolds,
  Hope & Henderson, Boyd, Lain, Upington; `borough=Brooklyn`, `city` = Brooklyn / Williamsburgh /
  New York post-1898) and **107 NYC telephone directories** (1909–1967) tagged `PHONEBOOK` (the
  separate-model track; `borough` blank, `city=New York`). PHONEBOOK total across the master is now
  **112** (107 here + the 5 NYPL phone dirs). **`1897BPL` = the held-out Lain Brooklyn 1897 eval
  volume — kept but `REVIEW:`-flagged** (don't sample/harvest it). Caveats for whoever samples:
  (a) many phone-book years have **2–3 duplicate IA scans** (`*newy`, `*newy_0`, `*newy_1`) — distinct
  ids, all kept; dedupe at sample time; (b) post-1928 phone books are likely **in copyright**;
  (c) phone books are out of the 1786–1925 training era — they're catalogued for the phonebook track,
  not the persons model.
- **Done this session — Durst Old York Library, scoped query (master 346 → 373):** added a
  **within-collection search** to `ingest_collection.py` — it now parses `?query=` / `?q=` from an IA
  URL (or a `--query` flag) and narrows to `collection:<id> AND (<query>)`. Ran it on
  `durstoldyorklibrary?query=directory` (69 hits — a *noisy* full-text match). Curated to **KEEP-only,
  NYC-only = 27** residential/general city directories (Longworth, Doggett, Trow, Mercein, Duncan
  1794, Rode, Franks 1786, Hearnes/Brooklyn). **Dropped:** 25 non-directories (guidebooks, street-
  number guides, almanacs, govt/institutional dirs, Tammany, Stock Exchange…), 11 business/trade/élite
  dirs (the BIZ shape — *not* ingested this time, candidate for a separate track like PHONEBOOK), and
  non-NYC (Newark 1835, Chicago). The 7 Longworth vols have **blank year** (IA date is a uniform
  placeholder "1797"; titles redact the year) + a `year not in IA metadata` note. **Lesson: IA
  full-text collection queries need heavy keep/drop curation** — "directory" matches guides, almanacs,
  and institutional lists, not just person directories.
- **Done this session — LoC source support (master 373 → 375):** added a `loc` extractor to
  `ingest_collection.py` — accepts a `loc.gov/item/<lccn>/` URL or a faceted search/browse URL
  (`loc.gov/books/?fa=...&q=...`), fetches with `fo=json`, paginates (stop on a short page — LoC's
  `pagination.of` is the hit *count*, not page count), books/texts only, row `id` = bare LCCN (the
  sibling sampler builds the manifest from it). Ran the LoC search
  `fa=location:new york|brooklyn & q=city directory` (22 hits — **very noisy**: 7 "Miller's NY as it
  is" guides + govt/misc). Only 2 genuine directories, both ingested per user: `loc/01015253` (Brooklyn
  city directory, Spooner serial 18--c1912, year blank) and `loc/96203733` (1876 Disturnell reprint of
  the 1786 NY directory — knowingly a dup of IA `newyorkdirectory00fran`, kept for institution
  variety). **Lesson (again): LoC/IA full-text "directory" queries need heavy curation.**
- **Done this session — Allen County PL `?query=directory` (master 375 → 449):** ingested the NYC
  residential set from the IA `allen_county` genealogy collection (1803 hits, nationwide+noisy →
  filtered to NYC-title directories → 74 net-new, 4 deduped). Includes **Longworth Manhattan** 1798/
  1813/1816/1826/1839 (net-new, *with* years — fills the early-Manhattan gap the blank-year Durst
  Longworths left), **Flushing/Queens** (Boyd 1885/90/91 — rare Queens coverage), **Brooklyn city
  directory** (Geor/Broo 1903–1912, publisher blank), Brooklyn 1839 (Ogden), and the **Trow's general
  Manhattan&Bronx** run 1903–1922 as accessible IA alternates to the NYPL/dying-API Trow scans (per
  user; mostly dup *years* we already hold, distinct scans). Excluded ~33 business/copartnership,
  ~18 county/farm/society, and Utica (upstate). Caveats: lots of duplicate scans + p1/p2/p3 parts
  (dedupe at sample time); `trowsgeneraldire1853trow` REVIEW-flagged (IA year 1853 contradicts its
  Manhattan&Bronx title). **`allen_county` still has ~1700 unreviewed non-NYC directories** — a strong
  lead for the future "other cities" goal.
- Broader goal still open: Columbia (via `iiif`), other cities (allen_county is the lead), more
  gap-fills, the BIZ-directory track.
- Possible cleanup: `ingest_collection.py` depends on `requests` (pipeline venv only) — could be made
  stdlib-`urllib` to run standalone from this repo.

## Next steps

Following the approved plan (`~/.claude/plans/i-want-to-slightly-golden-frog.md`). Wave 0 (name
realism) is **half done — tooling built & committed; awaiting data + retrain**:

- **DONE:** diagnosed the `name` failure (model regularises unseen surnames → see watch items);
  built `fetch_names.py`+`surnames.tsv` (40k census), `harvest_names.py`, the census+harvested pool
  merge in `synth_persons.py`, `master_directories.csv` (now **156** vols + `title`/`borough`)+README,
  `ingest_collection.py` (built; NYPL collection ingested + archived), and
  `directory-pipeline/sources/sample_directories.py` (multi-source page sampler). Generator now
  emits ~4.6k distinct surnames/5k (was 54).
- **NEXT (in order):**
  1. **Expand the master list** — `ingest_collection.py` is **built + IA path now run end-to-end**
     (see its section above). NYPL "New York City directories" fully ingested (81→156); IA Trow
     1915/1917/1922-23 gap-fills (156→160); BPL Brooklyn microfiche collection (160→346, incl. 107
     `PHONEBOOK` NYC telephone dirs); Durst Old York `?query=directory` (346→373, KEEP-NYC-only); LoC
     `loc` source + 2 NYC dirs (373→375); Allen County PL NYC set (375→449). Tool now supports IA
     within-collection queries (`?query=`/`--query`) and a `loc` source (item or faceted search; use
     `fa=subject:directories`, never `q=city directory`). Trow 1898/99 confirmed absent from IA (and
     NYPL) — try HathiTrust/Google Books/LoC if you want it. Remaining: Columbia (via `iiif`), other
     cities (allen_county ~1700 non-NYC dirs is the lead). Keep eval volumes OUT (NYU Trow-1850,
     Lain-1897) — tool flags `REVIEW:`.
  2. **Pull a real sample (PAID, pennies):** `sample_directories.py` (free download of K pages) →
     `pipeline ocr/extract` (Gemini) → `harvest_names.py` to fold authentic names into the pool.
     Validate the chain on ONE non-eval volume at K=3 first.
  3. **Add a publisher/era context tag** to `synth_persons.py` `_finish()` (today only `dialect`+
     `year`) so the model conditions on style and eval gold is tagged correctly (cf. the lain
     mislabel) — Wave 1 then parameterizes per-publisher styles.
  4. **Regenerate + retrain + re-eval:** `synth_persons.py --n 100000`, train on `rtx-pro-6000`
     b64 + `--packing` + `exclude_modules=["visual"]` (~$6), re-run the eval panel; confirm `name`
     micro-F1 / whole-row EM rise (esp. on Lain). This also lands the vision-adapter cleanup.
- **Later:** Wave 1 (parameterize publisher/era styles), Wave 2 (broaden real eval panel + boroughs),
  then scale the family (500k) and publish.

> **Wave-2 underway (2026-06-22):** the real eval panel is being built from sampled OCR pages via a
> new gold toolchain — see [VISUAL_SAMPLING_HANDOFF.md](VISUAL_SAMPLING_HANDOFF.md)
> (`data_prep/{sample_volumes,make_gold_tool,run_surya_on_samples,validate_gold}.py`,
> 42-volume `gold_sample/worklist.csv`). **Surya OCR complete for all 42** (labeling is now
> browser-only). **14 volumes labeled = 893 lines** (era coverage 1786–1925, all 8 fields exercised,
> **layout col 1→6 complete**): lain1876 (103), boyd1890 (75), doggett1846 (37), duncan1794 (58),
> franks1786 (56), rode1851 (53), mercein1820 (60), ogden1839 (66 — `*`=colored → `race_designation`),
> hearne1852 (52), hopehenderson1856 (60 — `*`=Eastern-District counter-case), trow1907 (68),
> trow1913 (93), polk1917 (72), polk1925 (40 — col-6), all validator-clean (Polk 1933 Staten Island,
> first outer-borough, in progress). Next priority = breadth (boroughs/std tail), not depth. GLiNER
> floor scored on lain1876 (macro-F1 0.33, `address` weakest). Conventions
> are a fixed gold/synth/model contract (key one: `raw_line` = verbatim *page* — OCR misreads fixed —
> vs the 8 record fields canonical). Next: more volumes, then Qwen + Gemini predictions on the panel.

To re-run an eval (note: `qwen_predict.py` now auto-loads the multimodal class — verify the log
prints `AutoModelForImageTextToText` and has NO "missing adapter keys" warning):

```bash
hf jobs uv run --flavor l4x1 --timeout 30m --secrets HF_TOKEN \
  eval/qwen_predict.py --base-model Qwen/Qwen3.5-0.8B --model hadro/city-dir-08b-yaml \
  --gold hf://datasets/hadro/cde-evals/nyu_eval.jsonl --target yaml --limit 500 \
  --push-out hf://datasets/hadro/cde-evals/preds_08b_nyu_fix.txt
hf download hadro/cde-evals preds_08b_nyu_fix.txt --repo-type dataset --local-dir data/
python3 eval/evaluate.py --gold data/nyu_eval.jsonl --pred data/preds_08b_nyu_fix.txt --target yaml \
  --save results/scores.jsonl --label qwen-0.8b-yaml-fixed
python3 eval/results_table.py --out results/eval_table.md && cat results/eval_table.md
```

**Blog post:** the debugging story is captured in [BLOG_NOTES.md](BLOG_NOTES.md) — draft from there.

## Watch items / open questions

- ~~**`is_business` weak (~0.55)**~~ **RESOLVED** — the 0.8B run scores **0.98** on NYU / 1.00
  in-dist once the adapter actually loads. It was never a data problem; it was the eval-loader bug
  making everything look weak.
- ~~**`N/A` for empty + name truncation**~~ **RESOLVED** by the scaled run (20k×1 artifacts).
- **`name` is the #1 remaining gap — DIAGNOSED, fix built, not yet retrained.** On real data the
  model *regularises* unfamiliar surnames to common ones (Alling→Allen, Bemmert→Becker,
  Huelsberg→Holloway); given names + initials are usually right. Worst on out-of-style volumes
  (Lain Brooklyn name-F1 0.33 vs Tulsa 0.72). Root cause: the generator's old ~54-surname pool, so
  the model never learned to *copy* arbitrary surnames. Fix (built, committed `605d82f`): census
  (40k) + harvested real-name pools. Punctuation (`Thos.`→`Thos`) is only ~3–5pts; the bulk is real.
  Verify the lift after the retrain (step 4 in Next steps).
- **Row-count consistency:** `nyu_eval.jsonl` has **3000** rows but the baselines were scored on
  **500** — always `--limit 500` on the NYU eval (and consider re-running baselines on a fixed set).
- **Synthetic-real gap:** synth converges trivially (train token-acc 0.999); the real signal is NYU.
- **Cost (measured, not estimated):** the slow kernels make this ~3× pricier than first assumed.
  **0.8B / 100k×3 = ~4 h ≈ $10** on a100-large (confirmed twice). Scaling to **500k×3 ≈ 5× ≈ ~$50
  for the 0.8B alone**; the full 0.8B/2B/4B family is realistically **~$150–250**, not the ~$10–25
  once guessed. Levers (see "Training speed — what we tried" for measured numbers): switch to
  **`rtx-pro-6000` batch 64** (~$7.30/run — 26% cheaper + 1.5× faster than the a100 we used) +
  **`--packing`** (~20% more → ~$6), and stay on 0.8B (Mattingly got 94–96% on it; ours is already
  competitive on macro-F1). Bigger batch, h200, fast kernels, and Unsloth did NOT pay off at this
  scale; don't chase them.

## Git / housekeeping

Work is on branch **`eval-loader-fix`** (off `main`), committed in order: `144be93` (eval-loader
fix + vision exclude + hf:// scoring), `90e025a` (--packing/--dry-run flags + Unsloth probe),
`0fc63e0` (lain dialect fix + eval panel), `db0725e` (fairer macro/micro scoring), `605d82f`
(name-realism pipeline: census+harvested pools, master list). Not yet merged to `main` or pushed.
Sibling repo: `directory-pipeline` has `e51377e` (`sources/sample_directories.py`) on its
`claude/local-ocr-*` branch.

**Master-list ingestion files (staged this session, not yet committed):**
`data_prep/ingest_collection.py`, `data_prep/master_directories.csv` (now 156 rows + `title` col),
`data_prep/master_directories.README.md`, and `data_prep/nypl_api_archive/` (156 JSONs — the NYPL-API
deprecation snapshot; commit, don't gitignore). **Still intentionally uncommitted:** `docs/HANDOFF.md`
+ `docs/BLOG_NOTES.md` (this doc and the blog draft).
`data/`, `models/`, `*.jsonl` are gitignored; `data_prep/names/surnames_harvested.tsv` is generated
(gitignored) — `surnames.tsv` (census seed) IS committed. `results/eval_table.md` tracked,
`results/scores.jsonl` not.
