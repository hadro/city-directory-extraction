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

**The best model is `v6`** — trained on NYU Torch 2026-09-01, 21-volume panel. **Officially scored
and on the board as of 2026-09-02** (`b90c8fa`); the earlier "simulation" caveat is retired.

| 21-vol panel, n=1583 | macro | micro | EM |
|---|---|---|---|
| v5-torch (corrected) | 0.826 | 0.897 | 67.3% |
| **v6 (official)** | **0.854** | **0.921** | **75.2%** |

Run artifacts: `results/runs/v6-21vol/`. Authoritative scores are `scores-parserfix.jsonl`;
the `-oldparser` copies are kept ONLY for the parser-fix-vs-gold-edit decomposition.

### ⚠️ v6 is NOT semantically better than v5-torch. The whole gain is punctuation.

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
   so this no longer needs NYU's write token — Josh can push v6 himself. v5-torch is the baseline v6
   is measured against and is still NYU-side only.
3. **One retrain (v7), then stop.** THREE un-shipped generator changes have accumulated; ship them
   together, since none has been scored:
     * `8d5c438` surname-repeat ditto rate — untested, targets `name`
     * `7f456d2` franks `num_comma` — **the one bankable item.** v6 regressed franks1786 by
       −37.5 EM; 48 of its 56 rows fail on a single inserted comma after the house number. Worth
       ≈ +1.3 EM panel-weighted on its own.
     * the harvested surname pool (gitignored, picked up automatically) — untested hypothesis;
       see the name-harvest section in HANDOFF.md, whose headline result was negative.
   **Judge it on the normalized metric**, and remember the franks recovery is a convention fix, so
   it will show up verbatim and not normalized. If `name` does not move normalized, stop.
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

**Explicitly NOT worth doing** (each measured, not assumed):
- cycle-seven punctuation work (ceiling +5.5 EM, all typography)
- scaling synthetic data or training 2B/4B — `synth_dev` is macro 0.992 / EM 96.0%, the model has
  saturated its own distribution; capacity and volume are not the constraint
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
