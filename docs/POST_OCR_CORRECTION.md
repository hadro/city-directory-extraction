# Post-OCR correction: is it a step this pipeline wants?

**Written 2026-09-15.** Asked: would post-OCR correction — find/replace, or a trained corrector —
help the city-directory extraction pipeline? Short answer: **yes, but almost certainly not as a
correction stage.** The highest-value version of this work is re-aiming the generator's noise
model, and the second-highest is a nine-line normalisation at hOCR ingest. A trained corrector
sitting between OCR and the extractor is third, and the repo cannot yet justify it.

One caveat up front, because it bounds everything below: **`huggingface.co` and `arxiv.org` are
blocked by this environment's egress proxy.** Every model and paper cited here was identified
through web search result snippets, not by reading the model card or the PDF. Treat the model
list as leads to verify, not as verified facts. Parameter counts and training corpora are quoted
from those snippets and should be checked against the card before anyone depends on them.

---

## 1. The finding that reframes the question

**This pipeline already has a post-OCR corrector. It is the extractor.**

`synth_persons.py` corrupts the input line and leaves the target clean
(`synth_persons.py:85`, *"OCR noise is applied to the INPUT line only; target stays clean"*;
the implementation is `add_noise` at `synth_persons.py:1350`).
Every training example is therefore a post-OCR correction pair with an extraction step stapled to
it. The model is trained to read `Brewsler` and write `Brewster` — it just also writes the other
seven fields while it does so.

That matters because of the mechanism this project already established
([TAKEOVER.md](TAKEOVER.md), "copying vs sampling"):

> *If the correct output is a substring of the raw line, copying handles it and the rate is
> irrelevant; if it requires deleting, re-casing or re-ordering, the generator must demonstrate
> it.*

OCR correction is the second kind — a substitution, never a substring copy. So the model's ability
to correct OCR is **entirely determined by what `add_noise` demonstrates**, and by nothing else.
That makes `add_noise` the lever, and it has never been aimed at anything.

## 2. What `add_noise` actually produces (measured 2026-09-15)

Measured over 20,000 generated `--profile mix` lines, comparing each line before and after
`add_noise` (`python3 data_prep/measure_synth_noise.py`, which reproduces every figure in this
section):

| `--noise` | lines touched | edits/line | **input CER** |
|---|---|---|---|
| **0.35 (the shipped default)** | 25.8% | 0.434 | **0.0101** |
| 0.6 | 44.9% | 0.749 | 0.0174 |
| 1.0 | 75.0% | 1.250 | 0.0291 |

Mean generated line length is 43 characters.

Against that, the number the project already measured for its **production** input:

> IA hOCR, **CER-all 0.067** ([HANDOFF.md](HANDOFF.md) L1183, from `historical-ocr-eval`)

**The model is trained on input roughly 6.6× cleaner than the input `ia_volume_to_jsonl.py`
feeds it.** Even at `--noise 1.0` — every line corrupted — the generator only reaches 0.029, less
than half of production. The default cannot be turned up far enough to close the gap; the *shape*
of the corruption has to change, not just the rate.

Three smaller diagnostics from the same run, each a straightforward fix:

- **`--noise 0.35` does not mean 35% of lines.** It means 25.8%. Of the lines that pass the
  probability gate, only 74.0% actually change — `add_noise` picks a confusion pair, calls
  `out.find(frm)`, and silently no-ops when the pattern is absent.
- **One of the eleven confusion pairs never fires.** `("ii", "n")` requires `ii` in the line,
  which essentially only happens if `("u", "ii")` already fired on the same line. Applicability of
  the rest ranges from `l`→`1` at 73.6% of lines down to `cl`→`d` at 9.3%.
- **Edits skew slightly toward the front of the line** — 27.0% land in the first quarter against
  17.2% in the last — because `find()` always takes the first occurrence. Mild, and it happens to
  favour the surname, but it is an artifact of the implementation rather than a property of any
  scanner.

None of the eleven pairs was derived from this corpus. They are the generic OCR-confusion list
(`m`/`rn`, `l`/`1`, `O`/`0`), which is a reasonable prior and is not the same thing as a
measurement.

## 3. The blind spot: the gold panel cannot see any of this

Labelling convention #2 ([GROUND_TRUTH_HANDOFF.md](GROUND_TRUTH_HANDOFF.md) L118):

> **raw_line = corrected page** — fix OCR misreads in raw_line too (long-s `f`→`s`:
> `fexton`→`sexton`; `Brewsler`→`Brewster`), so raw_line and fields tell the same story.

So the 21-volume panel scores the model on **hand-cleaned input**. Production hands it raw hOCR.
Whatever OCR robustness the model does or does not have, **the regression harness is blind to it
by construction** — and the blindness runs in the flattering direction. The 82.0 normalized EM is
a ceiling measured on input quality the pipeline never actually sees.

This is worth stating carefully, because there is an adjacent claim that is *not* supported.
`nyu_eval` is the one eval set built on uncorrected OCR, and the 4B scores 56.2 EM on it against
82.0 on the panel. It is tempting to read that 26-point gap as the cost of OCR noise. **Don't.**
NYU is a third-party CRF parse with three synthesized fields and a different labelling basis
([GROUND_TRUTH_HANDOFF.md](GROUND_TRUTH_HANDOFF.md) §"Derived vs transcribed gold"); the gap is
confounded beyond use. The honest position is that **the cost of OCR noise to extraction is
currently unmeasured**, and §5 is how to measure it.

## 4. What bounds the upside — the repo's own negative result

Before anyone budgets for a correction stage, two findings already in `HANDOFF.md` cap what it can
buy:

**Fabrication does not follow OCR quality.** ([HANDOFF.md](HANDOFF.md) §"Fabrication is driven by
PAGE TYPE") The 1906 ABBYY tier is **13× cleaner** than the 1836 microfilm tier on non-ASCII
garbage (1.0% vs 13.3%), and fabricated-record rates are 5.1% vs 6.1% with overlapping CIs. All
eight 1906 failures were advertising copy, not OCR damage.

> *Better scanning does not reduce fabrication; it produces cleanly-rendered fiction.*

**Post-OCR correction is a better-scanning intervention.** It will not touch the fabrication
problem, which is the pipeline's largest known correctness defect. Anyone proposing correction as
a fabrication fix is proposing something this project has already measured and falsified.

**What correction *can* buy** is the other failure mode, which the same section names: micro13's
leaf 76, *"real entries wrecked by microfilm OCR (`Clure John, Jaborerrear 107.Gold)) |. .`),
degraded but not invented."* Those are real people whose records come out damaged. That is a
recall-and-accuracy problem on genuine entries, it is exactly what post-correction addresses, and
it is disjoint from fabrication.

## 5. The parallel corpus you already have — `data_prep/ocr_delta.py`

Here is the thing this repo did not know it had.

The gold tool pre-fills `raw_line` from `{stem}_surya.json` and the labeller edits it in place to
fix misreads. **The pre-correction text is still on disk.** Every one of the 2,300 hand-labelled
lines is one half of a post-OCR correction pair, and the other half is sitting in the Surya JSON
in the sibling repo, unexamined.

The post-OCR literature's recurring complaint is that domain-matched parallel corpora are scarce.
This project has 2,300 lines of 1786–1933 NYC directory text, hand-corrected by people who were
looking at the line crop, under a written contract, validator-clean, and ours to license.

`data_prep/ocr_delta.py` recovers it:

```bash
python3 data_prep/ocr_delta.py --self-test
python3 data_prep/ocr_delta.py --gold 'data/*_eval.jsonl' \
    --surya-root ../directory-pipeline/output --noise-table --out data/ocr_pairs.jsonl
```

It aligns gold rows to Surya lines within a page by character similarity (handling wrapped
entries, which are one gold row across two OCR lines), then reports:

- **per-volume and overall CER** — how much OCR error the panel silently removes, i.e. the true
  size of the §3 blind spot, per publisher and per era;
- **where the damage lands**, by gold field — the question that decides whether this matters, since
  damage to `name` is expensive and damage to a trailing `address` token is not;
- **the measured confusion table**, and with `--noise-table`, a paste-ready `_NOISE_SUBS`
  replacement emitted in the generator's direction (clean → OCR, the reverse of the tally — the
  easiest thing to get backwards here);
- **the corpus itself** (`--out`), for training or evaluating any corrector.

Report-only by default, `--self-test` covers the alignment edge cases, in the house style. It has
not been run on real data — `data/` is gitignored and absent from this checkout, and the sibling
repo is not here. **Every number it would produce is currently unknown. Run it first.**

One honest limitation: it cannot distinguish a labeller's OCR fix from a labeller's slip. Both are
edits. `validate_gold.py`'s token-drift warnings are the cross-check, and volume matters — a
confusion pair seen once is noise, one seen eighty times is the scanner.

## 6. The three options, ranked

### Tier 1 — normalise at ingest. Do this regardless. (hours)

`ia_volume_to_jsonl.py` performs **no character normalisation at all** — no long-s folding, no
quote normalisation. Meanwhile the gold contract mandates conv #5, *"Long-s → `s` everywhere"*,
and the labellers applied it by hand.

So the model is trained and evaluated on long-s-folded input and runs in production on input that
is not folded. That is a free, deterministic, zero-risk mismatch, and it is worst precisely on the
early volumes (Franks 1786, Longworth 1818/19) where the panel is already weakest.

The defensible find/replace tier is small and typographic — long-s `ſ`→`s`, curly quotes to
straight (the `first_letter` work measured apostrophe surnames in this corpus at 4:1 curly), `½`→`1/2` per
conv #4, unicode dash folding. **Each rule must be one the contract already mandates.** Anything
lexical — "`Broadwav` is probably `Broadway`" — belongs in tier 3 with an evaluation attached, not
in a dictionary someone hand-edits.

### Tier 2 — re-aim the generator's noise model. This is the recommendation. (~$6 + a day)

Run `ocr_delta.py --noise-table`, replace `_NOISE_SUBS` with what it measures, raise the rate until
generated input CER matches the tier the model will actually run on, fix the three implementation
bugs in §2, regenerate, retrain, re-score.

Why this over a correction stage:

- It uses this project's **established lever**. Generator fixes closed every coverage gap in the
  v1→v5 table; the stop rule fired on *convention* work specifically, and this is not convention
  work — it is a distribution the generator has never demonstrated correctly.
- It costs one training run (~$6 measured, [TRAINING_OPTIONS.md](TRAINING_OPTIONS.md)) and adds
  **zero inference cost and zero new dependency** to the production path.
- It cannot hallucinate. A corrector that rewrites `Brewsler`→`Brewster` in a separate stage has
  destroyed the evidence if it was wrong. A model trained on realistic noise makes the same
  decision with the whole line in view and the extraction objective constraining it.
- §1 says it is the only thing that can work: the model corrects exactly what the generator
  demonstrates.

The stop rule is pre-registered in §7, because this is a generator change and the generator's
history in this repo is a history of confident changes that netted zero.

### Tier 3 — a trained corrector stage. Not yet justified. (weeks)

A seq2seq or small-LM corrector between hOCR and the extractor. The literature is real and the
models exist (§8). Three reasons it ranks third here:

1. **A directory line is the adversarial case for LM-based correction.** Post-OCR correction works
   by using context to constrain a language model. A 43-character directory line is a surname, a
   trade abbreviation and a street number — almost pure named entity, with essentially no
   linguistic context. Worse, the correct output is frequently *not* the likely one: this corpus
   contains `Dusenbery`, `Dusenbury` and `Duryea` as three printed spellings of one surname on one
   page ([GROUND_TRUTH_HANDOFF.md](GROUND_TRUTH_HANDOFF.md), trow1884), and conv #2a says a
   printer's error must be **preserved**, not corrected. A corrector with a good prior over English
   will normalise all three and be wrong every time — which is the same failure the project
   already diagnosed when the original 54-surname pool made the model regularise unseen surnames.
2. **It has a failure mode the current design does not.** The extractor cannot silently rewrite the
   page, because `raw_line` passes through. A corrector can, and the literature's consistent
   finding is that hallucination rises with input CER — i.e. it is worst exactly on the microfilm
   tier where it is most needed.
3. **The measurement to justify it does not exist yet.** §5 produces it.

If tier 3 does get run, the design that fits this corpus is **constrained, not generative**: use
correction as a *candidate generator* and let something else adjudicate. Two adjudicators are
already in the repo —

- **The alphabetical walk.** `alpha_run_filter.py` establishes that the body of a volume is a
  monotonic A→Z sequence and that this *"needs no threshold, which is the whole point."* A surname
  that breaks the walk is either a non-entry or a name whose leading characters are damaged. That
  is a free, high-precision detector on the field that matters most, and it constrains the fix: the
  corrected surname must sort between its neighbours.
- **The harvested name pools.** `names/surnames.tsv` (40k era-skewed census surnames) plus the
  harvested pools give a gazetteer to score candidates against — the classical lexicon approach,
  which is well-suited to entity-dense text precisely where a general LM is not.

Accept a correction only when the walk and the gazetteer agree, abstain otherwise, and keep the
original. HIPE-OCRepair-2026 found that **abstaining is a competitive strategy in low-noise
settings** and documented over-correction risk on clean input; on this corpus, where roughly half
the volumes are the clean ABBYY tier, abstention should be the default behaviour rather than a
fallback.

## 7. The pre-registered experiment, and the stop rule

**Step 0 (blocked on data, hours).** Run `ocr_delta.py` over all 24 labelled volumes. This is the
gate: if overall CER is **below ~0.02** and damage rarely lands on `name`, then the panel's blind
spot is small, tier 2's premise is wrong, and the right answer is tier 1 and stop. Hamdi et al.
(2020) found post-correction consistently improves NER when CER is in the **2–10%** band; the
production hOCR figure of 0.067 sits inside it, but that figure is whole-page CER over 291 IA
volumes, and *listing lines specifically, on the volumes that were hand-labelled* may be cleaner.
**These are different numbers and the decision should be made on the second one.**

**Step 1 (tier 1, hours).** Ingest normalisation. No retrain needed; score the panel before and
after to confirm it is inert on clean input.

**Step 2 (tier 2, ~$6 + a day).** Measured `_NOISE_SUBS`, rate matched to the target tier, the
three §2 bugs fixed. Retrain `4b-100k`. The comparison is against `4b-100k` on identical data
composition, changing only the noise model.

**Step 3 — the honest evaluation, and the part that must not be skipped.** The panel **cannot**
score this, because its input is clean; a noise-model change should be roughly inert there, and
"inert on the panel" is the expected result, not a null. The real test is a **degraded-input
panel**: take the `ocr_delta.py` pairs, feed the model the *OCR* side, score against the same gold
records. That set does not exist today and Step 0 creates it. Report both, always paired.

**Pre-registered stop rule.** Judge on normalized EM, per house discipline:

> **Tier 2 ships only if it gains on the degraded-input panel without losing on the clean panel.**
> A gain on degraded input paid for by a loss on clean input means the model has traded reading
> accuracy for noise tolerance — that is the wrong trade for a corpus that is roughly half clean
> ABBYY scans. **If degraded-input EM does not move, the noise model was not the constraint: say
> so and stop.** Do not proceed to tier 3 on the theory that a bigger intervention would have
> worked — that is the reasoning the v7 cycle already falsified.

And one prediction worth writing down in advance so it can be wrong: **tier 2 will move
degraded-input EM and will not move the clean panel by more than noise.** If the clean panel moves
materially in either direction, something other than the noise model changed, and the run should
be diagnosed rather than shipped.

## 8. The landscape — models and research

Identified by web search; **not verified against the model cards** (see the caveat at the top).

### Models on Hugging Face

| model | shape | trained on | fit here |
|---|---|---|---|
| [`PleIAs/OCRonos-Vintage`](https://huggingface.co/PleIAs/OCRonos-Vintage) | 124M, GPT-2-style, from scratch | 18B tokens of Library of Congress / Internet Archive / HathiTrust, **majority 1880–1920** | **Best era and cost fit.** CPU-runnable, reported >10k tok/s on GPU. Same archives this catalog draws from. Try first. |
| [`pykale/bart-large-ocr`](https://huggingface.co/pykale/bart-large-ocr) | BART-large seq2seq | BLN600, 19c British newspapers | English, right century, wrong genre (prose, not entity-dense listings) |
| [`pykale/llama-2-7b-ocr`](https://huggingface.co/pykale/llama-2-7b-ocr) | Llama-2-7B, instruction-tuned | BLN600 | Same corpus; reported much stronger (§ below), much costlier |
| [`yelpfeast/byt5-base-english-ocr-correction`](https://huggingface.co/yelpfeast/byt5-base-english-ocr-correction) | ByT5-base, byte-level | English OCR | Byte-level is the right architecture for character confusions and long-s |
| [`viklofg/swedish-ocr-correction`](https://huggingface.co/viklofg/swedish-ocr-correction), [`KBLab/swedish-ocr-correction`](https://huggingface.co/KBLab/swedish-ocr-correction) | ByT5-small | Swedish newspapers 1818–2018 + fraktur 1626–1816 | Wrong language — but the **closest methodological template**: byte-level, historical, and explicitly handles long-s (`ſ`), which is this corpus's single most common fix |
| [`ml6team/byt5-base-dutch-ocr-correction`](https://huggingface.co/ml6team/byt5-base-dutch-ocr-correction) | ByT5-base | Dutch | Same template |
| [`jvdzwaan/ocrpostcorrection-task-1`](https://huggingface.co/jvdzwaan/ocrpostcorrection-task-1) | mBERT | ICDAR 2019 post-OCR competition | **Error *detection*, not correction** — arguably the more useful half here, since detection plus abstention is the low-risk design |

Datasets and benchmarks: [`PleIAs/Post-OCR-Correction`](https://huggingface.co/datasets/PleIAs/Post-OCR-Correction)
(~1B words, Gallica + Chronicling America, en/fr/de/it — machine-generated corrections, so silver
not gold) and the [HIPE-OCRepair-2026](https://github.com/hipe-eval/HIPE-OCRepair-2026-data) data
and leaderboard.

### Research worth reading, in the order that matters here

1. **Hamdi et al., *When to Use OCR Post-correction for Named Entity Recognition?* (2020).** The
   single most decision-relevant paper: NER improves consistently from post-correction when OCR
   sits at **2–10% CER / 10–25% WER**. Our 0.067 is inside that band, which is the strongest
   external argument for doing this at all.
2. **HIPE-OCRepair-2026 (ICDAR).** The current benchmark — English/French/German, 17th–20th c.,
   metric is character-level Match Error Rate. Best adapted system (BnF-Mistral) ≈0.005 cMER with
   preference ≈0.9, **with documented over-correction risk on low-noise inputs**, and the finding
   that abstaining is competitive when noise is low. Note the unit of correction is a paragraph,
   article or page — **not a line**. Nothing in this benchmark tells you how these systems behave
   on 43 characters of entity-dense text with no context, which is our entire input.
3. **Kanerva et al., *OCR Error Post-Correction with LLMs in Historical Documents: No Free
   Lunches* (RESOURCEFUL 2025).** Llama-3.1-70B cut 18th-century English CER by 38.7% relative;
   every open-weight model tested made historical Finnish **worse**. The title is the finding.
4. **Thomas et al., *Leveraging LLMs for Post-OCR Correction of Historical Newspapers* (LT4HALA
   2024)** — the BLN600 work behind the `pykale` models. Instruction-tuned Llama-2 cut CER 54.51%
   against fine-tuned BART's 23.30%, on limited training data.
5. **Multimodal LLMs for OCR, Post-Correction and NER in Historical Documents (2025).** 6 of 7
   models improved English CER zero-shot (7.3–58.1% relative); models that see **the image as well
   as the text** do substantially better. Relevant because this project throws the image away at
   ingest — `ia_volume_to_jsonl.py` reads hOCR and never downloads a page. If correction ever
   becomes important enough, re-introducing the line crop is a bigger lever than a better text-only
   corrector, and the gold toolchain already crops lines.

The recurring caution across all five: hallucination, script-switching and instruction-following
breakdown, all worsening as input CER rises. For a corpus whose output is people's names and
addresses, a corrector that invents a plausible surname is worse than one that leaves `Jaborerrear`
alone.

## 9. What I would do first

1. `python3 data_prep/ocr_delta.py --self-test` and
   `python3 data_prep/measure_synth_noise.py --self-test` — both pass today.
2. Run `ocr_delta.py` for real over all 24 labelled volumes with `--noise-table --out data/ocr_pairs.jsonl`.
   That is a few minutes of compute and it decides everything else in this document.
3. Ship tier 1 (ingest normalisation) regardless of what step 2 says.
4. Take the tier 2 decision on the measured listing-line CER, against the §7 gate.

Nothing above tier 1 should be built before step 2 exists. The recurring lesson in
[TAKEOVER.md](TAKEOVER.md) is that this project's expensive mistakes were all confident reasoning
about its own corpus that a measurement later reversed — the `synth_dev` saturation argument, the
unprimed Gemini bar, the 14.4% fabrication rate. **This document is confident reasoning about its
own corpus.** Treat it accordingly.
