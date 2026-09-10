# Taking this over — read this first

**Written 2026-09-01.** Three-minute orientation for an agent or person picking this up cold.
Deeper context: [HANDOFF.md](HANDOFF.md) (long, start at "RESUME HERE"),
[GROUND_TRUTH_HANDOFF.md](GROUND_TRUTH_HANDOFF.md) (labelling conventions),
[NAME_HARVEST_PLAN.md](NAME_HARVEST_PLAN.md) (one specific future task).

---

## Where the project actually is

**The stated goal is met.** A 0.8B fine-tune beats the primed Gemini baseline. On the corrected
18-volume board, `qwen-v5` leads primed-pub Gemini by **+0.053 macro / +11.1 whole-row EM**. That
was true since v4; nobody knew because three scoring bugs were suppressing it.

## ⚠️ If you are about to cite a 1906BPL quality number, read this first (2026-09-10)

**`entry_rate.py`'s 10.4% not-real-entry figure for 1906 is STALE**, along with
`data/1906BPL_sample500_eval.jsonl` and its predictions. All three were built before ditto
normalization landed. The volume has been re-ingested; those three were not regenerated.

The cause is worth knowing even if you never touch that volume: **`44` is ABBYY's reading of the
ditto mark `"`, it leads 42% of the lines in this book, and the generator never emitted it.** Fed
the raw form the model runs the `name` field too far and swallows the occupation
(`name='44 Wm elk'`, occupation empty); fed `"` it splits correctly and *also* applies the
contract's OCR fix (`elk`→`clk`). n=500 paired, McNemar exact **p=0.0010**. Ingest now normalizes
it, gated by per-volume frequency so a real house number is never rewritten.

Re-deriving the stale artifacts is ~15 min on the 2B. **Do not compare the new figure to 10.4%** —
different input, not a better model. Full record: HANDOFF, "DITTO RESOLUTION" and "1906BPL
RE-INGESTED".

## ⚡ CAPACITY WAS THE CONSTRAINT. The release candidate is `4b-100k`, not v6.

**Scale runs completed 2026-09-09, and they overturned the previous conclusion.** Every figure
below was reproduced from NYU's shipped predictions before landing.

| run | EM verb | **EM norm** | name-F1 norm | externals norm agg |
|---|---|---|---|---|
| v6 (was the release bar) | 75.2 | 78.6 | 0.943 | 59.5 |
| v7 | 74.5 | 77.6 | 0.939 | 58.7 |
| **2b-100k** | 77.8 | **81.1** | 0.942 | 61.0 |
| **4b-100k** | **78.4** | **82.0** | **0.952** | **62.8** |
| v8-250k (0.8B, 250k) | 71.8 | **74.8** | 0.937 | 54.4 |

**Volume: NEGATIVE, and decisively.** 2.5× the data made the 0.8B *worse* — v8-250k trails v7 by
2.8 normalized points on the panel and loses on all four externals (minneapolis 31.3 → 21.3). The
`synth_dev`-at-98% reading was right about volume. **This is now measured, not inferred.**

**Capacity: POSITIVE, and monotone.** 0.8B → 2B → 4B climbs **78.6 → 81.1 → 82.0** normalized, and
externals 59.5 → 61.0 → 62.8. Critically, the 4B moves **`name` (0.943 → 0.952)** — the field that
stayed flat through three 0.8B generator cycles and was the basis of the whole stop rule.

**Release rule fires.** It was stated in advance: displace v6 only on a normalized win across the
panel *and* every external. 4b-100k wins all five — panel 82.0 vs 78.6, nyu 56.2 vs 56.0, tulsa
67.5 vs 62.8, lain 65.9 vs 65.2, minneapolis 35.2 vs 26.1. **`4b-100k` is the release candidate.**
`2b-100k` captures most of the gain at half the parameters (81.1 vs 82.0 normalized) and is the
sensible choice if inference cost matters — that is a product decision, not a scoring one.

### What was wrong before, and what survives

**I recommended against running these** ("my recommendation: don't"), reasoning that `synth_dev` at
0.997/98.1 proved the model had saturated and the remaining gap was distributional. Half right: it
was distributional *with respect to volume*, and simply wrong about capacity. NYU wanted the runs
partly to characterise their own hardware and pushed for them; that judgement was better than mine.
**The generalisable error: `synth_dev` measures how well the model fits the generator's
distribution, which says nothing about whether a bigger model would fit the REAL one better.**

What survives unchanged:
- Generator/composition iteration is still finished — v7 settled that, and v8-250k reconfirms that
  more of the same distribution does not help.
- The copying-vs-sampling mechanism below still holds and still explains why field-rate tuning is
  pointless.
- The metric discipline still holds: judge on normalized. It is what makes this result credible —
  the 4B's gain is +3.4 normalized, not a verbatim/typography artifact.

### 🛑 The old stop rule (superseded for capacity; still binding for the generator)

**v7 was run 2026-09-08 and the pre-registered stop condition was met.** The rule set before the
run was: *"judge it on the normalized metric — if `name` does not move normalized, the model is
done, say so and stop."* It did not move.

| 21-vol panel, n=1583 | EM verbatim | **EM normalized** | punct gap | name-F1 |
|---|---|---|---|---|
| v5-torch | 67.5 | **79.0** | +11.5 | 0.943 |
| **v6 — best checkpoint** | **75.2** | **78.6** | +3.3 | 0.943 |
| v7 | 74.5 | **77.6** | +3.0 | 0.938 |

Three data compositions, and normalized extraction is flat-to-declining: **79.0 → 78.6 → 77.6**.
Every verbatim gain since v5-torch is convention closure (the punctuation gap falling 11.5 → 3.0),
not extraction ability. I reproduced all six figures from NYU's raw score files; they are exact.

**`v6` remains the best single checkpoint** (verbatim 75.2 / normalized 78.6) and is what should
ship. v7 is not a regression worth reverting — it is simply not an improvement.

**v7 did produce the one bankable win, and traded it away.** franks1786 went **12.5 → 71.4% EM**
(+58.9), beating the ~50% target, confirming the `num_comma` diagnosis outright — and with a
normalized gap of +0.000, exactly as predicted for a convention fix. But the panel netted
**−0.7 EM**, because it gave back trowwilson1865 (−8.4), polk1925 (−7.5), mb1931 (−6.4) and
lain1876 (−5.8). *Convention fixes now reshuffle EM between volumes instead of adding to it.*
That is the signature of a saturated model, and it is why the stop rule exists.

Two fields moved enough to note: `home_address` −0.052 and `employer` −0.069 support-weighted F1.

Run artifacts: `results/runs/v7-21vol/` (includes normalized reports for all three runs) and
`results/runs/v6-21vol/`.

### The stop was replicated on 717 rows NEITHER model was scored on

NYU froze the panel, so the three new volumes were never scored. Run locally 2026-09-08 (v7 and
v6, MPS, all 717 rows):

| held-out group, n=717 | EM verbatim | EM normalized | punct gap |
|---|---|---|---|
| v6 | 55.5 | **79.2** | +23.7 |
| v7 | **65.7** | **78.7** | +13.0 |
| v7 − v6 | **+10.1** | **−0.6** | |

Same signature as the panel (verbatim −0.7, normalized −1.0): **big verbatim movement, no
normalized movement.** The stop rule holds on data neither model was tuned against.

Two things here are worth more than the stop itself:

1. **Extraction generalizes; only convention does not.** Normalized EM on three unseen volumes —
   including `smith`, a publisher that is 0.97% of training — is **79**, statistically the same as
   the 21-volume panel's 78. The model reads directories it has effectively never seen as well as
   ones it was tuned on. The entire deficit on new material is untaught typography, which the
   punct gap shows directly: +23.7 for v6 against +3.3 on the panel.
2. **v7 initially looked like the better RELEASE checkpoint. It is not — release `v6`.** The
   +10.1 on this group is *targeted calibration, not generalization*, and the externals prove it.

### ~~Release decision: `v6`~~ — SUPERSEDED 2026-09-09 by `4b-100k` (see the top of this file).
### The v6-vs-v7 reasoning below is retained because its METHOD is what the 4B decision reused.

Three independent measurements, ordered by how uncontaminated they are:

| evidence | n | winner | margin |
|---|---|---|---|
| **externals** (nyu, tulsa, lain, minneapolis — other cities/publishers, zero influence on any generator tuning) | **3030** | **v6** | **+0.8 EM** |
| 21-volume panel (both models tuned around it) | 1583 | v6 | +0.7 EM |
| 3 new gold volumes | 717 | v7 | +10.1 EM |

**v6 wins on 4,613 rows; v7 wins on 717 — and those 717 are the ones v7's generator was tuned
against.** `doggetts1850` set the `&` two-premises rate, `smith1856` set the race-marker forms, and
`smith1855` is the same publisher and era as `smith1856`. v7 was taught those volumes' conventions,
so scoring well there is the training objective working, not evidence of transfer.

The externals are the honest test — Tulsa, Minneapolis and Brooklyn-Lain had no input to any
generator change in this cycle — and there v6 wins 3 of 4 (nyu −0.8, tulsa −1.3, lain −1.4,
minneapolis +5.2).

**The normalized gap in that evidence is now closed** (2026-09-08; NYU's reports cover the panel
only, so v6 and v7 predictions were regenerated locally for all four externals, 6,060 rows on MPS):

| externals, n=3030 | verbatim | normalized | punct gap |
|---|---|---|---|
| v6 | **59.3** | **59.4** | +0.2 |
| v7 | 58.6 | 58.7 | +0.1 |
| v7 − v6 | **−0.7** | **−0.7** | |

**Verbatim and normalized agree exactly.** v6's lead is extraction, not typography — the one thing
that could have overturned the release decision, and it does not. Control: the local run reproduces
NYU's cluster figures within 0.4 EM on every set. Full report:
`results/runs/v7-21vol/report_normalized_EXTERNALS_v6_v7.txt`.

Note *why* the externals behave differently from the panel: their punctuation gap is ~+0.2 against
the panel's +3.3 (and v5-torch's +11.5). Tulsa, Minneapolis and Lain were built to the same
labelling contract the generator teaches, so normalization has nothing to forgive. The gap is a
property of how far a gold set's printed conventions sit from the contract — mid-century NYC is
where they diverge, which is exactly where the panel's remaining gap lives.

**So: ship `v6`** — *superseded; `4b-100k` now holds the release rule on all five measurements.*
v7 stays archived; it is the cycle that proved the generator stop rule, and franks1786's
12.5 → 71.4 is its result worth citing.

### ⚠️ v6 is NOT semantically better than v5-torch either. The whole gain is punctuation.

Measured 2026-09-02 by regenerating v6 predictions locally and scoring both models
`--report-normalized` on the 693 panel rows where both prediction sets exist:

| v6 − v5-torch | verbatim | normalized |
|---|---|---|
| whole-row EM | **+17.8** | **+0.9** |
| macro-F1 | +0.057 | +0.010 |

`trow1884` is the clearest case: v5-torch scored **37.6 verbatim but 86.5 normalized** — it already
had the content right and merely printed the directional period differently. v6 prints it the gold
way (82.3) and is **1.4 points WORSE semantically** (85.1). The +44 EM on that volume is pure
typography. The panel arithmetic closes exactly: v5-torch's punctuation gap was +11.7, v6's is
+3.3, so 8.0 points of gap were converted — and the verbatim gain was +7.9.

**Consequences, before you plan anything:**
- **Do not use verbatim whole-row EM as the headline for MODEL COMPARISONS.** Use
  `evaluate.py --report-normalized`. Publish the verbatim number (it is what a consumer of the
  gold convention actually gets); judge model *changes* on the normalized one.
- **The punctuation lever is spent.** Total headroom left on the panel is **+3.3 EM**, and 2.5 of
  that sits in four mid-century volumes (doggett1846 +21.6, hopehenderson1856 +18.4, rode1851
  +17.0, longworth1818 +10.4). Three convention cycles bought +0.003 normalized macro combined.
- v6 vs primed Gemini on the 18 volumes Gemini has been scored on is **+0.047 macro / +11.1 EM** —
  versus v5-torch's +0.045 / +10.9. The competitive claim did not move.

See "⛔ STOP CHASING PUNCTUATION" in HANDOFF.md before proposing any convention work.

---

## The single most important fact

**The training data published on `hadro/city-directory-synth` PREDATES the last two generator
fixes.** Verified 2026-09-01:

| fix | commit | in the shipped `synth_train.jsonl`? |
|---|---|---|
| surname-repeat ditto rate | `8d5c438` | ❌ shipped data has 14.0%, generator now gives ~78% |
| franks `num_comma` | `7f456d2` | ❌ shipped data has 0%, generator now gives ~67% |

**So the next retrain must regenerate first.** Do not train on what is currently on the Hub — you
would reproduce v6 and learn nothing.

```bash
python3 data_prep/synth_persons.py --self-test
python3 data_prep/synth_persons.py --profile mix --n 100000 --seed 13 --target yaml --out data/synth_train.jsonl
python3 data_prep/synth_persons.py --profile mix --n 3000  --seed 7  --target yaml --out data/synth_smoke.jsonl
python3 data_prep/synth_persons.py --profile mix --n 1000  --seed 99 --target yaml --out data/synth_dev.jsonl
```
Then upload train/smoke to `hadro/city-directory-synth` (archive a versioned `synth_train_v7.jsonl`
alongside, per convention) and `synth_dev.jsonl` to the gated `hadro/cde-evals`.

---

## Open items, in priority order

1. ~~Get v6 onto the board.~~ **DONE 2026-09-02** (`b90c8fa`). NYU re-scored on CPU; entries are in
   `results/scores.jsonl` and `results/eval_table.md`.
2. **Push the adapters.** `v5-torch` and `v6` are only on `/scratch` (purged after ~60 days) and in
   `~/Downloads`. **The v6 adapter (60 MB) is now on Josh's Mac** in the delivered results folder,
   so this no longer needs NYU's write token — Josh can push v6 himself.
   **v5-torch is NOT NYU-side only** (corrected 2026-09-08): a full backup sits at
   `~/Downloads/Hadro/torch-runs/v5-torch/` — the 60 MB adapter, `RESULTS.md`, a
   `patches/torch-local-changes.diff`, and **24 stored prediction files** covering the whole panel
   plus every external (nyu 500, tulsa 1500, lain 800, minneapolis 230, synth_dev, synth_smoke).
   Those predictions are worth more than they look: they let you re-score v5-torch against any new
   metric on CPU in seconds, with no GPU and no regeneration. That is how the external
   punctuation-gap question was answered (see the release-decision section).
   **No v6 or v7 predictions exist anywhere locally** — only their adapters — so any new metric on
   those two costs a ~3.5 h MPS regeneration for the externals. If NYU still has v6/v7 preds on
   `/scratch`, getting copies is far cheaper than recomputing them, and `/scratch` purges ~60 days
   after each run.
3. ~~One retrain (v7), then stop.~~ **DONE 2026-09-08 — and the stop rule fired.** All four
   accumulated generator changes shipped (ditto `8d5c438`, franks `7f456d2`, harvested surnames,
   `&` two-premises `d2eb264`, plus the `(co'd)` and self-crossing fixes). franks1786 recovered
   12.5 → 71.4% EM exactly as predicted, but the panel netted −0.7 EM and normalized extraction
   fell 78.6 → 77.6. **Do not start cycle eight.** See the stop section at the top.

   **Both are now teed up: see [SCALE_RUNS.md](SCALE_RUNS.md)** — data generated, designs fixed,
   commands written, pre-flight steps and expected outcomes recorded. NYU wants to run them partly
   to characterise their own hardware, which is a good reason independent of the score.

   The two pre-registered variables that remain UNTESTED, in NYU's preferred order:
     * **DATA VOLUME** — the 250k A/B (~10h, free on an L40S). The cheapest remaining question,
       and the only one that isolates volume from composition. It is a genuine test: every cycle
       so far changed *what* the 100k contained, never *how much*.
     * **CAPACITY** — the 2B/4B family, which was the original case for having cluster access.
   Neither is a generator change. If both come back flat, the 0.8B result stands as the finding
   and the project is about writing it up, not training again.
4. **Gold labelling** — tools are generated and gitignored in the repo root.
   ✅ `gold_doggetts1850.html` **DONE 2026-09-07** → `data/doggetts1850_eval.jsonl`, 303 rows,
   2 pages, validator clean. Doggett is the publisher NYU is drawn from, so its hand-labelled
   spouse/race/is_business is what would retire the `--exclude-fields` workaround on the external
   benchmark — but note this volume is 1850/51 and thin on those fields (is_business 7%,
   spouse 10%, race 1%), so it weakens the case for excluding rather than settling it.
   ✅ `gold_smith1855.html` **DONE 2026-09-07** → `data/smith1855_eval.jsonl`, 185 rows, 2 pages,
   validator clean. Brooklyn 1855, a NEW publisher (`smith`), chosen to thicken the 1846-1856
   band where primed Gemini still beats the fine-tune.
   ✅ `gold_smith1856.html` **DONE 2026-09-07** → `data/smith1856_eval.jsonl`, 229 rows, 2 pages,
   validator clean, and the cleanest export yet — 0 errors on arrival, address markers 2/2, both
   firms correctly flagged, and 6 verbatim race designations (`colored`, `col'd`, `cold.`), the
   first Brooklyn volume in the set to carry any.
   Remaining: `gold_upington1906.html`, `gold_smith1854.html`.

   **Both exports so far got convention #8 wrong in OPPOSITE directions**, so state it explicitly
   when generating the next tool: `address` KEEPS its `h`/`r`/`bds` prefix (a lone h-address lives
   there, marker and all, verbatim as printed); `home_address` stores the BARE address with the
   marker stripped. doggetts1850 kept the marker in `home_address` (74 rows); smith1855 dropped it
   from `address` (87 rows). Existing volumes keep it on lone-h rows 97.5-100% of the time.
   **Hold new volumes OUT of `PANEL` in `hpc/30_eval.sbatch`** until the next model is scored on the
   current 21, or you lose the clean A/B again.
5. **Release.** `cards/MODEL_CARD.md` and `cards/DATASET_CARD.md` still carry pre-fix numbers.

**The Brooklyn h/r/bds question is CLOSED.** NYU ran it on both cycles 2026-09-08, recovering the
v6 comparison that was lost to a cleared scratchpad: v6 matched gold marker rates almost exactly
(trowwilson1865 65.9% predicted vs 65.9% gold; worst case boyd1890 −5.3). It is **not** a
franks-comma-class fix, and the flat ~20% training rate does not matter — the model copies the
marker from the raw line rather than sampling a learned prior, as hypothesised. v7 drifted slightly
worse (trowwilson 59.3 vs 65.9), consistent with its general give-back on Trow-era volumes.

## Why further generator tuning does not work — the mechanism, measured four ways

Asked 2026-09-08: "are there further adjustments we should make to the synth data?" The answer is
**no**, and the reason is more useful than the answer. **The model conditions on the input line, not
on a learned prior over field rates.** Every attempt to find a distribution mismatch that matters
has failed, in the same way:

| mismatch in training data | what happened at eval |
|---|---|
| `race_designation` at 6.3% (v5 era) | **0** false positives on all five NYC Polk volumes |
| residence marker in `address` ~20% vs gold 65–88% (Brooklyn) | v6 matched gold almost exactly — trowwilson1865 **65.9% predicted vs 65.9% gold** |
| `employer` at 12.7% vs gold 4.2% (3× over) | model **under**-predicts: pred_ne/gold_ne = 0.89 (v6), 0.82 (v7) |
| `same` as an address value: **0 occurrences** in 100k | model emits `home_address: 'same'` correctly anyway |

That last one is the cleanest: the generator produces `do`/`do.` 2,237 times and `same` zero times,
yet the model handles `same` fine on tulsa and minneapolis. It is copying, not sampling.

**So marginal rates are not a lever, and never were.** Do not spend a cycle re-weighting how often
the generator emits a field or a form.

**The one thing that IS a lever — and it is nearly exhausted:** cases where the gold performs a
TRANSFORMATION on the printed line that the generator never demonstrates. Copying cannot teach
those, because the answer is not in the input. franks1786 is the proof: the page prints
`95, Water-street`, gold stores `95 Water-street`, and the model had to learn to *strip* a comma —
which it could not infer, and could not do, until the generator showed it (12.5 → 71.4% EM). The
`(co'd)` fix and the `h`/`r`/`bds` marker rules are the same shape.

Diagnostic that distinguishes them: **if the correct output is a substring of the raw line, the
model will get it from copying and the generator rate is irrelevant. If the correct output requires
deleting, re-casing, or re-ordering what the page prints, the generator must demonstrate it.**

v7 showed even that lever now reshuffles rather than adds (franks +58.9, but −0.7 net on the panel).

---

**Explicitly NOT worth doing** (each measured, not assumed):
- **cycle eight, or any further generator/composition work** — v7 settled this empirically, not by
  argument: three compositions, normalized 79.0 → 78.6 → 77.6
- ~~scaling synthetic data or training 2B/4B~~ — **RESOLVED 2026-09-09, and the entry was half
  wrong.** Volume: confirmed useless (250k is worse). Capacity: **wrong — 2B and 4B both beat every
  0.8B, monotonically.** The flag below was right that this entry was inferred rather than measured;
  running it changed the release candidate. Kept as a worked example of the failure mode.
  Original text: The inference: `synth_dev`
  is now macro 0.997 / EM 98.1% (v7), so the model reproduces its own training distribution almost
  perfectly, and the ~20-point gap to real gold (normalized ~78) is a DISTRIBUTION gap, which
  neither more rows of the same distribution nor more parameters can close. That is a strong
  argument and I believe it. It is still an argument. Nobody has run a 250k A/B or a 2B fine-tune.
  NYU's v7 SUMMARY recommends exactly these two as the "pre-registered next variables", so the
  project currently holds both positions at once — resolve it explicitly rather than by whichever
  document someone reads first.
- re-probing GLiNER2 — done and documented in `eval/gliner2_baseline.py`
- harvesting more surnames — run 2026-09-02, moved the miss rate 49.2% → 48.8%. 99.3% of directory
  surnames appear on exactly one page, so that metric mostly detects whether you sampled the gold
  page itself. See HANDOFF.md.
- more punctuation/convention cycles — **+3.3 EM of headroom left on the whole panel**, and it does
  not register on the normalized metric at all.

**A metric caveat that changes which volumes look weak.** Macro-F1 averages over *present* fields,
so a field with one gold instance weighs as much as `name` with 103. `employer` scores F1 0.000 on
doggett1846, rode1851 and trow1913 — from 1, 1 and 2 instances. Excluding fields with fewer than 10
gold instances: polk1917 macro **0.691 → 0.859**, trow1913 **0.786 → 0.929**, panel
**0.854 → 0.917**. The much-discussed "Polk floor" is substantially this artifact; polk1917's EM of
56.9 is genuinely low, but its macro was never the story. Consider reporting macro with a minimum
support threshold, or leaning on micro-F1, before diagnosing another volume as broken.

**The one real capability gap is mid-century.** Primed Gemini still beats v6 on rode1851 (−32.1),
doggett1846 (−29.7) and hopehenderson1856 (−20.0) whole-row EM. Part is punctuation, but not all:
rode1851 at FULL punctuation credit is 83.0 against Gemini's 98.1 verbatim. Gemini gets it from a
prompt description, so the convention is learnable and describable — this is the most promising
remaining lever if anyone wants one, and it is not the same thing as the spent punctuation lever.

---

## Loose ends with no owner

- **`results/runs/`** is untracked. It holds NYU's run artifacts (`SUMMARY.md`, job logs,
  `report_normalized_*`). Decide whether run artifacts belong in git or should be gitignored like
  `scores.jsonl`.
- **42 `nyu` gold rows contain a literal `|`**, which the pipe serializer truncates
  (`'9 Carmine |'` → `'9 Carmine'`). `evaluate.py --self-test` now fails on this for `--target pipe`
  and warns for yaml. Probably junk in NYU's regex-derived silver — likely fix is to scrub the gold,
  not escape the delimiter. Affects the pipe-target board entries (GLiNER, qwen-2b).
- **`train/sft_qwen.py`'s `--check-termination` probe and `eval/qwen_predict.py` must stay in sync**
  on stop tokens. Both were fixed together in `d476deb`; a change to one needs the other.

---

## Hard-won things that will cost you a cycle if you forget

**Four silent scoring artifacts, all of which looked exactly like model failures:**

| when | what | cost |
|---|---|---|
| 2026-06-18 | eval loaded `AutoModelForCausalLM` vs training's multimodal class; adapter silently not applied | NYU macro read 0.358, was 0.760 |
| 2026-08-04 | `parse_yaml` was last-key-wins; a runaway completion's truncated copy overwrote good values | ~12 points EM |
| 2026-09-01 | `parse_yaml` stripped quotes but never UNESCAPED; Polk's printed ditto marker could not match | 60–90% of rows in five volumes; read as a "Polk floor" |
| 2026-09-01 | pipe target truncates a gold value containing `\|` | 42 nyu rows |

**`evaluate.py --self-test` now round-trips the gold through the real serializer and both parsers.**
It catches two of the four. Run it on a Polk volume after any change to serialization or scoring.
Before this, `--self-test` compared gold against gold *as Python dicts* — which is why three of the
four survived it.

**When a volume or field scores absurdly low, verify the round trip before blaming the model.**
Four for four.

**Local eval works and reproduces CUDA to within one row per volume.** You do not need the cluster
to score — this is how the v6 normalized numbers above were obtained. Regenerating all 21 panel
volumes with the v6 adapter on an M2 (MPS) gave panel EM **75.3 vs NYU's official 75.2**: 18 of 21
volumes matched exactly, and trow1884 / boyd1890 / mb1931 each differed by exactly one row
(generation nondeterminism between MPS and the L40S). Close enough for diagnosis; **do not use a
local run to update the board** — score there, publish from the cluster.

```bash
uv venv evalenv --python 3.12
VIRTUAL_ENV=./evalenv uv pip install "transformers==5.14.1" "peft==0.20.0" "accelerate>=1.0" torch sentencepiece protobuf
./evalenv/bin/python eval/qwen_predict.py --base-model Qwen/Qwen3.5-0.8B --model <adapter-dir> \
    --gold data/<vol>_eval.jsonl --out /tmp/p.txt --target yaml --batch-size 16
```
~50 min for the 21-volume panel on an M2. Verified byte-identical to the L40S output on three
control volumes, all three metrics. `qwen_predict.py` handles MPS as of 2026-09-01 — before that
`device_map="auto"` SIGSEGVed with **no traceback**, which looks like the script doing nothing.

**`--base-model` is required** — `sft_qwen.py` trains LoRA, so a run directory is an adapter.
**Watch for `missing adapter keys`** — it means the adapter silently did not apply and you scored
the bare base model.

---

## Who does what

Josh labels gold (browser, on his Mac) and owns the generator and repo. **NYU Torch** (collaborator)
owns training and scoring — they have the pinned environment, a GPU allocation, and have caught two
significant bugs the local side missed. They work from `hpc/README.md` and pull code from GitHub and
data from Hugging Face; nothing is `scp`'d.

The two shareable status pages written for them:
- v5-torch verification — <https://claude.ai/code/artifact/f795b373-e6ec-4787-b7fb-71aacccd13f3>
- 21-volume re-score instructions — <https://claude.ai/code/artifact/db8febe1-6c91-491a-929c-a68f78ff5a22>

Both predate the `parse_yaml` fix and the punctuation decision, so **treat their numbers as stale**
even though the procedures still hold.
