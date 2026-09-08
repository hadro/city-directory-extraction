# Plan — harvest real NYC names into the synthetic generator

**For:** an agent working across two repos.
**Status:** not started. Written 2026-09-01.
**Prerequisite:** do NOT start this until the ditto-rate retrain (`8d5c438`) has been scored. See
"When to start" below — this may turn out to be unnecessary.

---

## Why

`name` is the weakest field with full support on the 21-volume gold panel: **F1 0.821 over 1583
rows** (v6). The generator draws surnames from `data_prep/names/surnames.tsv` — 40,000 names from
the **2010 US census**. Measured against the panel:

> **227 of 461 distinct real gold surnames (49.2%) are not in that pool.**

They are not exotic; they are systematically the wrong *distribution*:

| missing surname | volume | why the census misses it |
|---|---|---|
| `Bancker`, `Brouer`, `Broseus` | franks1786, mercein1820 | Dutch colonial New York |
| `Corroll`, `Costan` | boyd1890 | period OCR/spelling variants |
| `DeNoia`, `Denole`, `Denora` | polk1933si | 1930s Staten Island Italian-American cluster |
| `Blagge`, `Burras`, `Craik` | franks1786, boyd1890 | common-then, rare-now |

`data_prep/harvest_names.py` already exists and works, and `synth_persons.py` already boosts
`surnames_harvested.tsv` over the census pool when it is present. **That file has never existed.**
The harvest was planned in cycle five and never run. The blocker is source data, not code.

**Scale of the prize, for calibration:** when the generator had only 54 surnames, `lain1876` name-F1
was **0.33**. At 40k census names it is **0.821**. This is the same lever, further along.

---

## The one hard rule: leakage

**Harvest only from pages that are NOT in the eval panel.** This is existing project policy, not a
new invention — `README.md` line 288 and `harvest_names.py`'s own docstring both state it, and the
catalog carries `REVIEW:` flags (`"matches held-out eval signature — keep OUT of harvest set"`).

Two ways to satisfy it. **Prefer the second:**

1. Different volumes entirely — dilutes the era/place authenticity that is the whole point.
2. **Different PAGES of the same volumes.** The gold uses ~2 sampled pages out of hundreds. Other
   pages of Trow 1884 or Polk 1917 give the same city, publisher and year with no row overlap.

**Never harvest from:** NYU Trow Manhattan 1850/51, Lain & Healy Brooklyn 1897 (both `REVIEW:`-flagged
as EVAL HELDOUT), or the exact page images already used for gold. The gold page filenames are in each
`data/<slug>_eval.jsonl` under `context.image` — read them and exclude those images by name.

Note the *record* being harvested is a name pool, not rows: the generator recombines name + occupation
+ address randomly, so a surname appearing in both places is not memorisation. The rule exists so the
held-out sets stay honest, and it is cheap to follow.

---

## Steps

Two repos are involved:
- `~/github/directory-pipeline` — produces `entries_*.csv` (has its own `.venv`)
- `~/github/city-directory-extraction` — consumes them

```bash
PIPE=~/github/directory-pipeline
CDE=~/github/city-directory-extraction
PY=$PIPE/.venv/bin/python           # pipeline venv; Surya needs `uv sync --extra gpu`
```

### 1. Pick target volumes

Choose 2–3 NYC volumes whose publisher/era matches where names fail. Good candidates, all already in
`data_prep/master_directories.csv`:

- a **late Trow** (1907/1913 family) — the dense-volume surname distribution
- a **Polk NYC** (1917/1925/1933) — the 1930s immigrant-cluster names the census pool misses worst
- an **early Manhattan** (Longworth/Mercein 1810s–20s) — Dutch colonial names

**Use `data_prep/sample_volumes.py` rather than hand-picking.** It reads
`master_directories.csv`, stratifies by publisher × era × column_count, and — importantly here —
**already excludes eval holdouts automatically** (`EXCLUDE_NOTE` matches
`phonebook|biz|eval|holdout|held-out|keep out` in the notes column). That is the leakage rule
implemented, so you inherit it instead of re-deriving it.

```bash
cd $CDE
python3 data_prep/sample_volumes.py --by publisher,decade --per 1 --max 12 \
    --out-dir data_prep/harvest_sample
```

Writes `worklist.csv` (master-format subset of just those volumes) and `WORKLIST.md`. A run on
2026-09-01 gave 332 in-scope volumes → 12 selected, spanning Longworth 1804/05–1835, Doggett
1846/47 and Trow 1885/86–1912 — exactly the era spread the missing surnames come from.

**One thing its exclusion does NOT do:** it drops the two `REVIEW:`-flagged holdouts, not the 21
panel volumes. That is correct for this task — harvesting *different pages* of a panel volume is
allowed and preferred — but if you decide to harvest whole non-panel volumes instead, filter the
21 out yourself.

Then cross-check anything you pick against the `REVIEW:` column before using it.

### 2. Run the pipeline

> `sources/sample_directories.py` no longer exists. Both `gold_sample/WORKLIST.md` and the
> `sample_volumes.py` generator that emits it were fixed on 2026-09-01 (`56c2f97`) to point at
> `main.py` instead — but check `main.py --help` anyway, the stage flags have changed before.

```bash
cd $PIPE
$PY main.py --help                  # read this first; stage flags have changed before
```

The chain you need is `--download --select-pages --surya-ocr --gemini-ocr`, which has a shorthand:

```bash
$PY main.py <source-args> --guided
```

`--select-pages` opens an interactive browser UI to choose sample pages and writes `selection.txt`
per volume. **This is where you exclude the gold pages** — pick a different part of the book. Later
stages refuse to run without `selection.txt`.

Then extract structured entries:

```bash
$PY main.py <source-args> --align-ocr --extract-entries
```

This writes `output/<slug>/entries_<model>.csv`. Confirm before continuing:

```bash
ls $PIPE/output/<slug>/entries_*.csv
```

**Sanity check:** as of 2026-09-01 the only city-directory `entries_*.csv` in `output/` are
**Tulsa 1921/1922** — wrong city for this purpose. If you see only those, the pipeline run did not
produce what you need.

If a stage misbehaves, the `debug-pipeline` skill in this project diagnoses pipeline symptoms.

### 3. Harvest

```bash
cd $CDE
python3 data_prep/harvest_names.py $PIPE/output/<slug>/entries_*.csv
```

- Handles both name schemas (single `name` column, or separate `surname`/`given_name`)
- Skips `is_business` rows
- **Merges across runs**, so harvest volume-by-volume and re-run freely
- Writes `data_prep/names/surnames_harvested.tsv` and `given_harvested.tsv`
  (`Name<TAB>count`), both gitignored

Verify it did something and that Gemini noise did not dominate:

```bash
wc -l data_prep/names/*_harvested.tsv
sort -t$'\t' -k2 -rn data_prep/names/surnames_harvested.tsv | head -30
```

Eyeball that list. Expect real surnames. If you see OCR fragments (`apts`, `arcade`, `bros`) or
given names in the surname file, the extraction schema was misread — fix before regenerating.

### 4. Regenerate and measure

```bash
cd $CDE
python3 data_prep/synth_persons.py --self-test
python3 data_prep/synth_persons.py --profile mix --n 100000 --seed 13 --target yaml \
    --out data/synth_train.jsonl
python3 data_prep/synth_persons.py --profile mix --n 3000 --seed 7  --target yaml \
    --out data/synth_smoke.jsonl
python3 data_prep/synth_persons.py --profile mix --n 1000 --seed 99 --target yaml \
    --out data/synth_dev.jsonl
```

The generator picks the harvested pools up automatically — no code change.

**Confirm the coverage gap actually closed** (this is the point of the exercise):

```python
# re-run the measurement that motivated this: how many gold surnames are now in the pool?
# expect the 49.2% miss rate to drop substantially.
```

Then ship: upload `synth_train.jsonl` / `synth_smoke.jsonl` to `hadro/city-directory-synth`
(archive a versioned `synth_train_v8.jsonl` alongside, per convention), and `synth_dev.jsonl` to the
gated `hadro/cde-evals`.

---

## When to start — and when NOT to

**Do not start until the ditto-rate retrain is scored.** `8d5c438` fixed the surname-repeat ditto
rate (generator ~15% vs gold 81% for trow-late), which is **337 panel rows, 21% of the panel**, and
is the *dominant* cluster in observed name failures (`-Bernhard`, `-Adolph A` → `Adolph A`). It ships
with the untested franks `num_comma` fix from `7f456d2`.

If that retrain moves `name` materially, this harvest may be unnecessary. If `name` stays near 0.821,
this is the next thing to try and you will have a clean baseline to measure against.

**Judge the result on the punctuation-normalized metric** (`evaluate.py --report-normalized`), not
the verbatim one. See `docs/HANDOFF.md` → "⛔ STOP CHASING PUNCTUATION": cycle six's headline +7.8 EM
was **−0.3** normalized. Verbatim gains that vanish under normalization are typography, not learning.

**Honest uncertainty:** the model *copies* names from the input line rather than generating them from
a pool, so a richer pool teaches robust copying of unfamiliar strings — it does not add memorised
vocabulary. That mechanism is plausible and matches the 54→40k history, but it is **not directly
measured**. Treat this as the best remaining hypothesis, not a certainty, and be willing to report
that it did not work.

---

## Definition of done

- [ ] `surnames_harvested.tsv` / `given_harvested.tsv` exist, from **non-eval** pages only
- [ ] Top-30 surnames eyeballed and plausible for the era/place
- [ ] Gold-surname miss rate measurably below 49.2%
- [ ] 100k/3k/1k regenerated; `--self-test` green; dev has 0% overlap with train
- [ ] Data uploaded, versioned copy archived
- [ ] `docs/HANDOFF.md` updated with the measured before/after, **including if it did not help**
