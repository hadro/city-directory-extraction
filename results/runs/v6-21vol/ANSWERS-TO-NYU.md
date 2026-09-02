# Answers to the four asks in SUMMARY.md

Written 2026-09-02 against the official parser-fixed scores, using v6 predictions regenerated
locally from the delivered adapter (MPS, all 21 panel volumes). That local run reproduces the
cluster to within one row per volume — panel EM 75.3 vs your official 75.2, 18/21 volumes exact,
`trow1884` / `boyd1890` / `mb1931` off by exactly one row each (MPS-vs-L40S generation
nondeterminism).

---

## First, the headline your re-score establishes — and a caveat on how to read it

**v6 official: 0.854 macro / 0.921 micro / 75.2% EM.** It is on the board (`b90c8fa`).

**But v6 is not semantically better than v5-torch.** Scoring both models `--report-normalized` on
the 693 panel rows where both prediction sets exist:

| v6 − v5-torch | verbatim | normalized |
|---|---|---|
| whole-row EM | **+17.8** | **+0.9** |
| macro-F1 | +0.057 | +0.010 |

`trow1884` is the cleanest case: v5-torch scored **37.6 verbatim but 86.5 normalized** — it already
had the content right and simply printed the directional period its own way. v6 prints it the gold
way (82.3) and is **1.4 points worse semantically** (85.1).

The panel arithmetic closes exactly: v5-torch's punctuation gap was +11.7, v6's is +3.3, so **8.0
points of gap were converted — and the verbatim gain was +7.9.** On the 18 volumes primed Gemini
has been scored on, v6 is 0.845/72.9 against v5-torch's 0.843/72.6; the competitive claim did not
move (+11.1 EM vs +10.9).

None of this makes the number wrong — verbatim is what a consumer of the gold convention actually
gets, so publish it. But judge *model changes* on the normalized metric.

---

## Ask 1 — which surface form introduced the number-comma, and which convention wins?

**Your diagnosis was right, and the fix is already upstream in `7f456d2` (post-v6).**

The form is the Longworth neighbourhood comma (`nbhd_comma`, "Grand, Corl.-hook"), which v6 added
and the model generalised to franks's house-number comma.

**The gold convention wins, and it is not arbitrary.** The franks page *does* print the comma —
`raw_line` is `Brower N. merchant, 95, Water-street` — and the record strips it to
`95 Water-street`. That is convention #3, and it is unanimous: 96.4% of franks raw lines carry the
comma, 0 of 56 records keep it.

Confirmed on the local preds: **48 of 56 franks addresses fail on exactly this one character**,
which is the whole −37.5 EM (address F1 0.143). The fix teaches it as a raw-side-only hint gated to
`publisher=franks`; verified on a fresh 20k generation, the record keeps the comma 0% of the time
and non-franks leakage is 0.17%.

⚠️ **One gap worth closing before you retrain:** the generator emits the comma on **66.4% of franks
raw lines vs gold's 96.4%**, because the hint only fires on digit-leading addresses and only 66% of
generated franks addresses start with a house number. Worth making franks addresses more
house-number-first.

## Ask 2 — the surviving mid-century gap is a different convention. It is the single-letter marker period.

Diagnosed on the local preds for doggett1846 / rode1851 / hopehenderson1856 / longworth1818.
It is not the directional rule; it is **whether a one-letter address marker keeps its period**, and
the model applies one rule uniformly where gold varies by publisher:

```
doggett1846   gold 'r. 6 Stanton'          pred 'r 6 Stanton'      <- gold KEEPS it
doggett1846   gold 'h E. 18th n. Av. 2'    pred 'h. E. 18th n Av. 2'  <- gold DROPS it on h
hopehenderson gold 'h 8 Raymond'           pred 'h. 8 Raymond'
rode1851      gold 'r. 213 W. 40th'        pred 'r 213 W. 40th'
```

Gold forms in the failing rows: `n.` ×24, `h.` ×22, `r.` ×12, `c.` ×6, bare `h` ×4, `b.` ×3 — so
the period is usually kept, and bare `h` is the publisher-specific exception. Same shape as the
directional fix: era/publisher-keyed, not global.

**Size it before you spend a cycle on it.** Rows whose *only* error is this marker period:

| volume | rows | share |
|---|---|---|
| doggett1846 | 6 / 37 | 16.2% |
| rode1851 | 8 / 53 | 15.1% |
| longworth1818 | 11 / 106 | 10.4% |
| hopehenderson1856 | 6 / 60 | 10.0% |
| **total** | **31 / 256** | **+2.0 EM panel-weighted** |

That is real but small, it is punctuation, and it will not register on the normalized metric.
**Recommendation: do not spend cycle seven on it.** Total punctuation headroom left on the whole
panel is +3.3 EM.

## Ask 3 — the Polk floor: not race markers, and not one convention either

You were right that race markers were vacuous. The macro story is largely a **metric artifact**:
macro-F1 averages over *present* fields, so a field with one gold instance weighs as much as `name`
with 103. Excluding fields with fewer than 10 gold instances:

- polk1917 macro **0.691 → 0.859**
- trow1913 **0.786 → 0.929**
- panel **0.854 → 0.917**

`employer` scores F1 0.000 on doggett1846, rode1851 and trow1913 from **1, 1 and 2** instances.

**polk1917's EM of 56.9 is still genuinely low** (31 of 72 rows wrong), but it is diffuse — no
single fixable cluster:

- **occupation/address boundary** on multi-word trade abbreviations — `cotton gds 66 Leonard`: gold
  splits `cotton gds` / `66 Leonard R406`, model puts `gds` in the address (12 address + 11
  occupation errors)
- **parentheses**, which gold keeps and the model drops — `(wid Nathan)` → `wid Nathan`,
  `(Francis R & Jas M Emmons)` → bare. Note the normalizer does **not** forgive this (it strips only
  `.` before whitespace), so it is a genuine error, not typography. But rows whose *only* fault is
  parentheses are **8 across all six Polk-family volumes = +0.5 EM**. Smaller than it looks.
- **honorific placement** in queens1933 — gold `Trogel Josephine Mrs`, model drops `Mrs` from the
  name and prepends it to the occupation (`Mrs sec`)
- **abbreviation "correction"** — gold `fctywkr`, model emits `factwkr`. It is normalising where it
  should be copying verbatim.

That last one is the interesting one: the model **mis-copies** unfamiliar strings (`886 B.way` →
`386 Bowy`, `Bancker` → `Banncker`, `Delancy` → `Delancey`, `Av. 6` → `Av B`). That is the copying-
robustness hypothesis behind the harvested surname pool, which is now generated but untested.

## Ask 4 — the silent `hf download` on gated `cde-evals`

Real and worth guarding against, since it nearly scored v6 against the v5 synth_dev. The dataset is
private *and* NC-licensed, so it must stay gated. Suggested check after any gold sync, before
scoring:

```bash
ls data/*_eval.jsonl | wc -l          # expect 21 panel + externals
python3 eval/evaluate.py --gold data/polk1925_eval.jsonl --self-test   # round-trips the gold
```

The round-trip guard is the one that would have caught it — it fails loudly if the gold is missing
or unparseable, rather than scoring an empty set.

---

## What we think v7 should carry

Three generator changes have accumulated, none scored. Ship them together, then stop:

1. `7f456d2` franks `num_comma` — **the one bankable item**, ≈ +1.3 EM panel-weighted (see the
   66% / 96% caveat above)
2. `8d5c438` surname-repeat ditto rate — untested, targets `name`
3. the harvested surname pool — 3,276 era-authentic surnames the census pool lacks; the coverage
   metric it was built for came out negative (49.2% → 48.8%), but the copying-robustness hypothesis
   is untested and the mis-copying above is direct evidence for it

**Judge it on the normalized metric.** The franks recovery is a convention fix, so it will show up
verbatim and not normalized — that one is expected and fine. If `name` does not move normalized,
the model is done.
