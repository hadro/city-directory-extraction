---
license: cc-by-4.0
language:
  - en
tags:
  - glam
  - city-directory
  - historical-documents
  - synthetic
  - structured-extraction
  - named-entity-recognition
pretty_name: City Directory Lines, Synthetic Extraction Pairs
task_categories:
  - text-generation
size_categories:
  - 100K<n<1M
---

<!-- DRAFT 2026-10-31. For hadro/city-directory-synth, which is public but has no README yet.
The licence (cc-by-4.0) is the earlier draft's choice; confirm it with the release licence
decision. The GitHub links assume the repo is public by release. -->

# City Directory Lines, Synthetic Extraction Pairs

Synthetic directory lines, each paired with the eight-field record a reader would extract from
it. This is the training set of the
[City Directory Extractor 4B](https://huggingface.co/<namespace>/city-directory-extractor-4b). No
line is copied from a real directory, so the set and models trained on it can be released
openly; real hand-labeled lines are kept for evaluation only.

## Files

| File | Rows | What it is |
|---|---|---|
| `synth_train_v7.jsonl` | 100,000 | **The 4B's training set** (sha256 `509d8f4ce1a99a53…`). `synth_train.jsonl` is the same file |
| `synth_train_250k.jsonl` | 250,000 | The same generator and seed run longer; its first 100,000 rows are v7's. Trained the volume experiment, which made the 0.8B worse |
| `synth_train_v3.jsonl` … `_v6.jsonl` | 100,000 each | Earlier generator versions, for reproducing the 0.8B's cycles |
| `synth_smoke.jsonl` | 3,000 | A smoke-test set (seed 7) |

The 1,000-row dev set (seed 99) is with the evaluation sets in the gated
[`hadro/cde-evals`](https://huggingface.co/datasets/hadro/cde-evals). Train, dev and smoke share
no line, and every `raw_line` in the 250k set is distinct.

## A row

```json
{"raw_line": "Schofield Faye, dressmaker rear 510 Catharine.",
 "context": {"publisher": "doggett", "alphabetical_range": "SCH", "directory_year": "1842"},
 "record": {"name": "Schofield Faye", "is_business": false, "spouse_name": "",
            "race_designation": "", "occupation_role": "dressmaker", "employer": "",
            "address": "rear 510 Catharine", "home_address": ""}}
```

- `raw_line`: the line as a directory would print it, sometimes with OCR-style noise added. This
  is the model's input.
- `context`: the publisher's style, the page's alphabetical range and the year. Publisher and year
  go into the prompt.
- `record`: the target. Values are copied from the line, so most of extraction is choosing what
  to copy. Where the labeling conventions change the printed form (a trailing period dropped, as
  above), the record shows the change.

The 4B was trained on the records serialized as YAML (`--target yaml`).

## What it imitates

Three quarters New York and Brooklyn, one quarter Tulsa. The New York and Brooklyn lines come in
sixteen publisher styles, 1786–1933; the Tulsa lines imitate the 1921 Polk directory, the best
grounded style (48,000 real published rows) and the one that teaches the `employer` field. The
share is the generator's `--mix-weight` (0.75 New York since the third cycle; it was half before).
In v7:

| Publisher style | Rows |
|---|---|
| `trow` | 34,397 |
| `polk-tulsa` | 25,051 |
| `lain` | 9,812 |
| `polk` | 9,097 |
| `longworth` | 8,584 |
| `doggett` | 3,020 |
| `duncan`, `upington`, `hopehenderson`, `smith`, `boyd`, `hearne`, `mb`, `mercein`, `rode`, `franks`, `ogden` | 10,039 together |

Each style's layout, abbreviations, address forms and ditto marks come from reading its pages
(the profiles in `data_prep/style_profiles/`). Surnames mix census frequencies with names
harvested from the directories themselves; occupations come from directory volumes that are not
used for evaluation. Field rates in v7: home address 14.6% of rows, spouse or widow marker
15.7%, employer 12.7%, ditto-led name 12.6%, business 3.7%, race marker 2.9%.

The rates matter less than the forms. The trained models copied what each line contained, not
how often the generator emitted a field. What a model could not learn without examples was a
transformation the gold makes to the printed line, such as dropping the comma in Franks'
`95, Water-street`.

## How to regenerate

```bash
python3 data_prep/synth_persons.py --profile mix --n 100000 --seed 13 --target yaml --out synth_train.jsonl
python3 data_prep/synth_persons.py --profile mix --n 3000   --seed 7  --target yaml --out synth_smoke.jsonl
python3 data_prep/synth_persons.py --profile mix --n 1000   --seed 99 --target yaml --out synth_dev.jsonl
```

From [city-directory-extraction](https://github.com/hadro/city-directory-extraction); the
generator has no dependencies beyond Python. Byte-identical output needs the generator's commit
of the v7 build.

## Evaluation sets (not training data)

| Set | Lines | Licence | Where |
|---|---|---|---|
| Gold panel: 21 New York and Brooklyn volumes, 1786–1933/34, hand-labeled | 1,583 | ours | `hadro/cde-evals` (gated) |
| NYU NYC directories 1850–1890 | 500 | CC BY-NC-SA 4.0: evaluation only | `hadro/cde-evals` (gated); source [archive.nyu.edu](https://archive.nyu.edu/handle/2451/61521) |
| Tulsa 1921 (Polk), Gemini-extracted (silver) | 1,500 | ours | `hadro/cde-evals` (gated) |
| Lain's Brooklyn 1897 | 800 | ours | `hadro/cde-evals` (gated) |
| Minneapolis 1900 | 230 | MIT | `hadro/cde-evals` (gated); source [DirCity](https://github.com/adamrangwala/DirCity_Directory_Crop-out-with-Key-Lines) |

`hadro/cde-evals` is gated rather than open because it includes the NYU set, whose licence is
non-commercial. None of these sets is in the training data.

## Limitations

- Synthetic lines miss some of what real OCR does. The 4B scores 82.0 row EM on hand-corrected
  gold lines and 67.0 end to end on real scans (see the model card).
- The styles cover New York, Brooklyn and Tulsa. Other cities' directories are out of
  distribution where their conventions differ.
- Race markers are generated only in forms the directories print (none unattested in the 250k
  set). Some NYC forms were first taken from NYU's parsed records rather than read off the page,
  so the 250k set was checked against the directories for that reason.

## Citation and sources

<FILL: citation.> Grounding sources: the Tulsa 1921 Polk-Hoffhine City Directory (Tulsa
City-County Library); the NYU "NYC Directories Extracted Persons Entries, 1850–1890" (Wolf,
Chioh, Balogh, Spaan, 2020), for vocabulary only; and page reads of the directories themselves.
Method after W.J.B. Mattingly's "Parsing 3.6M Historical Names with Small Models" and Daniel van
Strien's small-models-for-glam work.
