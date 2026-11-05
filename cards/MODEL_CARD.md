---
license: apache-2.0
base_model: Qwen/Qwen3.5-4B
library_name: peft
pipeline_tag: text-generation
language:
  - en
tags:
  - glam
  - city-directory
  - historical-documents
  - structured-extraction
  - named-entity-recognition
  - genealogy
  - lora
datasets:
  - hadro/city-directory-synth
---

<!-- DRAFT 2026-10-31, for the v1 release. Pending hadro's decisions before upload: the repo
namespace (<namespace> below), the licence (apache-2.0 above is the recommendation: the base
model is Apache-2.0 and the training data is synthetic and ours), and the records dataset's
name. Fill <FILL> marks from the release audit. The GitHub links assume the repo is public by
then. One card serves all three repos: for the 2B and the 0.8B, change `base_model`, the title,
"(this repo)" in the sizes table, and BASE / ADAPTER in the snippet. Run names in this repo and
private backups: 4b-100k (hadro/cde-4b-100k), 2b-100k (hadro/cde-2b-100k), v7 (hadro/cde-0.8b-v7). -->

# City Directory Extractor 4B

A LoRA adapter for [Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B) that turns **one line of
a historical US city directory** into a structured record of eight fields, copying each value as
printed. It was trained only on synthetic lines, and evaluated on hand-labeled lines from 21 New
York and Brooklyn directories printed between 1786 and 1933, plus four other collections. It
produced the records in [`<namespace>/<records dataset>`](https://huggingface.co/datasets/<namespace>/<records dataset>).

## Three sizes

The same training on the same data, at three sizes of Qwen3.5. Accuracy is close (see
Evaluation); what differs is the hardware each needs.

| Size | Adapter | Seconds per line on a 16 GB Apple laptop | Use it for |
|---|---|---|---|
| **4B** (this repo) | 143 MB | ~11 | Whole volumes on a GPU. It built the records dataset, and it is the only size scored end to end on real scans |
| [2B](https://huggingface.co/<namespace>/city-directory-extractor-2b) | 83 MB | ~5 | A laptop or a smaller GPU: within a point of the 4B on the gold panel |
| [0.8B](https://huggingface.co/<namespace>/city-directory-extractor-0.8b) | 60 MB | ~3 | The smallest machines and quick trials; about four points behind the 4B |

The laptop times are one line at a time on an M2 with 16 GB (transformers 5.14.1, PyTorch on
Apple's GPU, measured 2026-11-02); batching helps (the 2B has reached about half a line a second).
Even so, a laptop is for trying lines, not for corpora: a 100,000-line volume would take days
even on the 0.8B. On a GPU, see Throughput below.

## What it does

Input: one directory line, with a short tag naming the publisher and year. Output: YAML with
eight keys, each a string copied from the line, or empty when the line does not have it.

```
[publisher=trow; year=1906] Breeze Geo paper 62 Duane h 430 W 57th
```
```yaml
name: "Breeze Geo"
is_business: "False"
spouse_name: ""
race_designation: ""
occupation_role: "paper"
employer: ""
address: "62 Duane"
home_address: "430 W 57th"
```

| Field | What it holds |
|---|---|
| `name` | The name as printed, surname first, including a leading ditto mark (`"`, `—`) where the directory repeats the surname above. The ditto is resolved downstream, not by the model. |
| `is_business` | `True` for a firm or institution, else `False` |
| `spouse_name` | A spouse or widow marker as printed (`wid Jeremy`, `widow`) |
| `race_designation` | A racial marker as printed (`col'd`, `(c)`): see Ethical considerations |
| `occupation_role` | The occupation, abbreviations kept (`clk`, `carp`) |
| `employer` | The employer where the directory prints one (Polk style) |
| `address` | The business or only address, residence markers kept (`rear 142 Laurens`, `r 303 N Boston av`) |
| `home_address` | The home address where a second one follows `h` / `h.` |

Values are verbatim. The model does not expand abbreviations, normalize streets or geocode.

## How to use

```python
import torch
from peft import PeftModel
from transformers import AutoModelForImageTextToText, AutoTokenizer

BASE, ADAPTER = "Qwen/Qwen3.5-4B", "<namespace>/city-directory-extractor-4b"
FIELDS = ["name", "is_business", "spouse_name", "race_designation",
          "occupation_role", "employer", "address", "home_address"]
SYSTEM = ("You convert ONE line from a historical US city directory into structured fields. "
          "Output YAML with exactly these keys: " + ", ".join(FIELDS) + ". "
          "Copy values verbatim; use True/False for is_business; use an empty string for absent "
          "fields. Output only the YAML.")

tok = AutoTokenizer.from_pretrained(BASE)
tok.pad_token = tok.pad_token or tok.eos_token
tok.padding_side = "left"
# Load the base with the multimodal class it was trained with: under AutoModelForCausalLM the
# adapter's keys do not match, and it is silently not applied.
model = PeftModel.from_pretrained(
    AutoModelForImageTextToText.from_pretrained(BASE, torch_dtype="auto", device_map="auto"),
    ADAPTER).eval()

line = "Breeze Geo paper 62 Duane h 430 W 57th"
prompt = tok.apply_chat_template(
    [{"role": "system", "content": SYSTEM},
     {"role": "user", "content": f"[publisher=trow; year=1906] {line}"}],
    tokenize=False, add_generation_prompt=True, enable_thinking=False)
enc = tok(prompt, return_tensors="pt").to(model.device)
out = model.generate(**enc, max_new_tokens=128, do_sample=False,
                     eos_token_id=[tok.eos_token_id, tok.pad_token_id],
                     pad_token_id=tok.pad_token_id)
print(tok.decode(out[0, enc["input_ids"].shape[1]:], skip_special_tokens=True))
```

Three settings matter:

- **`enable_thinking=False`.** Qwen3.5-4B's chat template otherwise opens a reasoning block, and
  the completion fills with prose instead of the record.
- **Greedy decoding** (`do_sample=False`), with both stop tokens as above.
- **Keep the first record only.** Parse key by key and stop at the first repeated key; the
  repo's `eval/qwen_predict.py` (`parse_completion`) does this.

All three sizes were checked to stop cleanly after one record even without the stop tokens (24
gold lines from 12 volumes each, `results/stop_test.py`); the settings above are still the safe
default.

The tag carries the publisher and year when you know them (`[publisher=?; year=?]` otherwise). The
publisher names seen in training are `trow`, `polk-tulsa`, `lain`, `polk`, `longworth`, `doggett`,
`duncan`, `upington`, `hopehenderson`, `smith`, `boyd`, `hearne`, `mb`, `mercein`, `rode`, `franks`
and `ogden`. An ablation found the publisher tag made no measurable difference on the 2B and 4B.

**Throughput (4B).** 12.6 lines a second on one L40S at batch 64 with
[flash-linear-attention](https://github.com/fla-org/flash-linear-attention) installed, 7.2
without it. No GPU speed was recorded for the 2B and 0.8B.

## Training

- **Data:** synthetic only, [`hadro/city-directory-synth`](https://huggingface.co/datasets/hadro/city-directory-synth)
  `synth_train_v7.jsonl`: 100,000 lines (sha256 `509d8f4ce1a99a53…`), written by
  `data_prep/synth_persons.py --profile mix --n 100000 --seed 13 --target yaml`. The generator's
  vocabularies, abbreviations and layouts are grounded in real directories, but no real line is
  in the training set, so no non-commercial source data reaches the weights.
- **Method:** TRL `SFTTrainer`, LoRA r=16, α=32, dropout 0.05, on every linear layer of the
  language model (the vision tower excluded); loss on the completion only; 3 epochs, learning
  rate 2e-4, effective batch 64, sequences up to 512 tokens. One GPU on NYU's Torch cluster.
  All three sizes were trained this way, on the same file.

## Evaluation

All scores are whole-row exact match: every one of the eight fields must equal the gold value.

**Hand-labeled gold, 21 New York and Brooklyn volumes, 1786–1933/34 (1,583 lines).** The labelers
corrected OCR misreads in the input lines, so this measures extraction on clean text.

| Model | Row EM, verbatim | Row EM, abbreviation periods ignored | `name` F1 | Four other collections, periods ignored |
|---|---|---|---|---|
| **4B** | **78.4** | **82.0** | **0.952** | **62.8** |
| 2B | 77.8 | 81.1 | 0.942 | 61.0 |
| 0.8B | 74.5 | 77.6 | 0.939 | 58.7 |
| Gemini 3.1 Flash-Lite, prompted with the labeling conventions | 61.7 | — | — | — |

More synthetic data did not help: 250,000 lines made the 0.8B worse (74.8 with periods ignored).
Size did.

**Other collections, 4B (row EM, verbatim).**

| Set | Lines | Row EM | Note |
|---|---|---|---|
| Tulsa 1921 (Polk) | 1,500 | 67.5 | labels from a Gemini extraction (silver) |
| Lain's Brooklyn 1897 | 800 | 65.8 | |
| Minneapolis 1900 | 230 | 64.8 | after a gold correction (2026-10-17) |
| NYU NYC directories 1850–1890 | 500 | 56.0 | three of its fields are derived by regex, not transcribed |

**End to end, on real scans (4B only).** Through the whole pipeline (LightOnOCR-3 re-OCR of the page, line
assembly, this model, and the copy guard below) on 17 book-scan gold sets: **67.0** row EM over
2,062 gold lines, from 50.0 to 88.0 by set. The same panel through the Internet Archive's own
OCR scored 55.2. Here the OCR, not the model, sets most of the ceiling.

**Whole volumes (4B only).** Where a directory prints its own count of names, usable records per printed
name: Doggett 1845 0.982, Brooklyn (Lain) 1876 0.982, Longworth 1826 0.897.

<FILL: the release audit: N records sampled across the corpus, checked against the page image,
X% correct (95% interval), by tier.>

## Limitations

- **It never refuses.** Every line becomes a record, including a running head, an
  advertisement, or the second line of a wrapped entry. Filter the input to listing lines, and
  filter the output. The records dataset carries the flags for this (`usable`, `role`,
  `non_entry_page`).
- **It sometimes rewrites a printed word** into a more familiar one: `Mhtn` to `Mthn`, `Degraw` to
  `Delaware`, `Bancker` to `Banker`. The repo's `postprocess/copy_guard.py` puts the printed word
  back from the line; the end-to-end score above includes it.
- **It sometimes changes a number.** On the hand-labeled panel, about 2% of the 4B's lines came
  back with a house number's digits swapped or changed (`731` to `371`, `r8512` to `r2851`).
  Check numbers against the line, or the page, before relying on an address.
- **It can invent a given name** where the directory prints a widow under her husband's name
  without one of her own.
- **It cannot tell what a leading `*` means.** Some directories star colored residents, others
  star firms, advertisers or Eastern District addresses, and the model sees one line, not the
  volume's key. Over the released records it set `race_designation` on 6,698 lines that carry no
  race mark and left it empty on 2,628 that do. The records dataset resolves this per volume
  (`race_designation_resolved`); on other directories, read the volume's key before trusting `*`.
- **Two copies of the same line can come out differently** depending on the batch they were
  decoded in (bf16): 8 of 20,000 records in one test chunk.
- **Coverage.** Trained on New York, Brooklyn and Tulsa conventions, English only. Other cities'
  directories work where they share those conventions; the Minneapolis and Tulsa scores show
  roughly how far that goes.
- **One line at a time.** Page segmentation, wrapped-entry joining and ditto resolution happen
  before and after the model.

## Ethical considerations

The directories record the social categories of their time. The model copies them as printed:
`race_designation` holds the markers directories used to set Black residents apart (`col'd`,
`(c)`, `colored`, a leading `*` in some directories), and `spouse_name` holds widowhood. Faithful copies serve historical and
genealogical research, including research on segregation itself. Treat these fields as
historical evidence, not as descriptions of people, and give them that context wherever they are
shown.

## Citation

<FILL: citation, once the release name is decided.> Built in
[city-directory-extraction](https://github.com/hadro/city-directory-extraction). Evaluation
uses the NYU "NYC Directories Extracted Persons Entries, 1850–1890" (Wolf, Chioh, Balogh, Spaan,
2020; CC BY-NC-SA 4.0, evaluation only), the Tulsa 1921 Polk-Hoffhine City Directory, and the
DirCity Minneapolis 1900 set. Method after W.J.B. Mattingly's small-model name parsing and Daniel
van Strien's small-models-for-glam work.
