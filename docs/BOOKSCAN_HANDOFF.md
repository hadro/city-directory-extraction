# Book-scan re-OCR and the 4B: what to do when NYU's results land

**Written 2026-10-22, at commit 9cde1ca.** For a model or person picking this up cold when results
come back from NYU's Torch cluster. It says what is out, how to receive each result, how to judge
it, what to do next, and the traps that have already cost a day. The deep record is
[PIPELINE.md](PIPELINE.md) #27 (the re-OCR) and #28; this file is the operating guide on top of it.
Do not follow HANDOFF.md's "Next steps" (June 2026, three cycles stale).

---

## 0. The project in one paragraph

Turn 19th- and early 20th-century city directories (Internet Archive scans) into one record per
printed entry. The chain: OCR (IA's own, or our LightOnOCR-3 re-OCR) -> the survey
(`data_prep/survey_*.py`: listing bounds, sections, page numbers, scoped listing lines per volume,
in sidecars `data_prep/survey/ia_<id>.json`) -> the 4B extractor (`Qwen3.5-4B` + LoRA `4b-100k`,
one line -> an 8-field YAML record, run on NYU Torch by `hpc/35_volumes.sbatch`) -> the copy guard
(`postprocess/copy_guard.py`) -> records (`postprocess/assemble_records.py` -> `data/records/`).
Training is settled; the frontier is whole-volume extraction at corpus scale. The single most
important operational fact: **the model never refuses**, so every non-entry line that reaches it
comes back as a confident fabricated person. `usable` (entry-shaped, a start line, on a listing
page, not eval-held-out) is the conservative record subset, and **usable records per printed
name** (for volumes that print their own count) is the volume-scale accuracy check we have.

## 1. Where things stand

| what | result | commit |
|---|---|---|
| LightOn vs IA OCR, book-scan panel (2,062 gold rows) | line exact 59.1% -> 82.8% (tesseract layer) / **83.6% (IA's words as the layer)**; 4B row EM guarded 55.2 -> 67.2 | 0186733, ea080a9, aa5e016 |
| fast-path kernels (flash-linear-attention only) | 4B **12.59 rows/s at batch 64 vs 7.58**; gold panel 67.21 vs 67.03, 4 flips all toward | 57612f7 |
| canary re-OCR (4 volumes, 8,908 tiles, 1.6 GPU-h) | imported. Scoped lines per printed name: Doggett 1845 1.005 -> **1.000**, Longworth 1826 0.944 -> **0.980**, 1876BPL 1.029 -> 1.054 (margin ads); **Trow 1907 p3 33,522 -> 104,621** scoped lines (IA's OCR had failed page by page; needed the tesseract layer) | f68b067 |
| IA-OCR coverage over the 3 remaining tiers | 3,028 of 73,826 pages under 0.5; mostly six Trow parts 1907-1914 | f68b067 |
| Torch-side staging for the full re-OCR | built and tested end to end (tiles and import byte-identical to the canary's) | 6002d70 |
| import tooling | `reocr_books.py import / coverage / facts`, `survey_adleaves.py features --merge` | 9cde1ca |

**Costs to plan with:** LightOn (vLLM, L40S) **0.53 s a tile**, ~80 s engine start a task. The 4B
**12.6 rows/s** in `venv-kernels` at batch 64 on any card (7.2 without the kernels; an H200 was
no faster than an L40S without them, unmeasured with them).

## 2. What is out at NYU (sent by hadro on or after 2026-10-22)

| | package | runbook (private artifacts; hadro shares them) | comes back as |
|---|---|---|---|
| **A. job 3: the canary's 4B pass** | `cde-volumes-books-canary.tar.gz` (9.6 MB, sha256 cd23bf11...6923): `data/volumes_books_canary` at f68b067, 19 tasks, 312,660 lines | https://claude.ai/artifact/9jx1ZeAycJR572kHrWdYv5 (job 3) | `canary-4b-preds.tar`: `data/volumes/<id>/chunk_NNN.preds_4b-100k.txt` + `.sha1`, `logs/vol-<job>_*.out` |
| **B. abbyy8-damaged re-OCR** | `cde-books-damaged.tar` (358 MB, sha256 1f8d8fa7...7291): code at 6002d70 + 35 volumes' word records | https://claude.ai/artifact/L5hhRFvo22384GUDwNkQZa | `data/reocr_tiers/answers_abbyy8-damaged/<id>.tar` (one per volume, possibly in batches) + `lighton-abbyy8-damaged-logs.tar` + a summary line |

**Update 2026-10-23: A and B are back and done** (canary scored, tier imported: PIPELINE #27). Out
now: **C. the 4B over the damaged tier** (all 35 volumes + the canary's 4 again), RESTAGED
2026-10-26 before sending with every line-assembly fix below and PIPELINE #32 (g)'s ditto dashes
(re-import 657e9c4): `cde-volumes-books-damaged-v4.tar.gz` (152 MB, sha256 f7d04180...ededf4, 258
tasks, 4,678,164 lines, ~103 GPU-h; v2 and v3 were never sent and are deleted). Comes back as
`books-damaged-4b-preds.tar`; install into `data/volumes_books_damaged_v4/`, verify the 258
`.sha1`s as in section 3 step 1, guard, and
assemble with `--out data/records_books_damaged`. Judge the canary four against job 3
(`results/records_books_canary.json`: Longworth 0.859 should rise), and the two "generaldire" Trow
volumes by the glued-entry proxy in PIPELINE #32 (a). 1876BPL and Doggett 1845 keep their earlier
wrap indent (`survey_harvest.WRAP_PINS`: a knife-edge calibration flip, measured harmful).
Also with D, optional: **the table test**, `cde-table-test.tar` (194 MB, sha256 ef27dde3...8c9a):
`hpc/lightonocr_vllm_notables.py` + `hpc/43_lightonocr_notables.sbatch` re-read task 0 (the bench's
138 gold tiles and 188 screen tiles) with table output banned, a separate job that touches nothing
D uses. Back as `notables-answers.tar`; score the slug `lightonocr-3-1b-greedy-vllm-notables` as the
vLLM parity run was (`reocr_pair.py bench <slug> --kind halves`, `post`, `score`) beside
`-vllm`, the 11 table tiles above all: the first step of PIPELINE #32 (b) 5c. NYU's copy of
`hpc/lightonocr_vllm.py` carries their `transformers==5.14.1` pin (now in ours too): never send a
copy without it.
Line-assembly work in progress elsewhere (PIPELINE #30, #32 (b)-(e)): [LINE_ASSEMBLY_HANDOFF.md](LINE_ASSEMBLY_HANDOFF.md);
fixes committed before D returns reach D's import for free. **In the code D's import will use, so
far:** the joiner's margin guard measured from the text for name-shaped lines (PIPELINE #32 (f),
survey; ~100-180 two-person composites a Trow part fewer); unread words placed where the print has
room, and leading runs kept on their tile (#32 (c), import); a side banner's glyph no longer
splits an entry from its run-over (#32 (d), import); LightOn's invented table headings ("Name,
Address") are left out (#32 (b), import); a model-read start no longer joins on the indent past the
volume's own run-overs' reach (#30, survey: banners and the next column's entries). When D lands, run `line_assembly.py tables --damage` on its
volumes: its table rate decides the Torch re-read of table tiles (#32 (b), 5c). #30's panel veto is eval-only. All of
it is in C too, restaged before sending.
Also out: **D. the LightOn re-read of the last two tiers**, `cde-books-first-clean.tar` (875 MB,
sha256 25754bd7...7ae4: word positions for 58 `first` + 17 `abbyy8-clean` volumes, written at 32ebc26;
Torch code unchanged since 6002d70), same runbook page, "Also next". ~165k + ~70k tiles, ~39 GPU-h.
Comes back as `answers_first/` and `answers_abbyy8-clean/` volume tars: receive and import as in
section 4, after PIPELINE #31 (the import on one core would take ~9 h). Watch Trow 1915/1917 (the
`_jp2.tar` frame check has seen one page) and the coverage flags (Bronx 1871, Trow 1863/1876, Trow
1914 p2).

**Update 2026-10-29: C and D are back** (C assembled to `data/records_books_damaged`, D's 61 volumes
imported, 6f5ca31; the record is in PIPELINE #27 after "Staged for the 4B 2026-10-24"). Out now:
**round 11**, `cde-table-reread.tar` (3.9 MB, sha256 6cb34058...2673, code at 0c31a09), runbook
section "Round 11" on the damaged-tier page (v7): (a) the 41,904 tiles of D that LightOn read as
tables, re-read with tables banned (slug `lightonocr-3-1b-greedy-vllm-notables`; PIPELINE #32 (b)
5c); (b) the 14 BPL volumes Pillow 10.4.0 cannot decode, tiled under 12.3.0 (hadro, 2026-10-29: same
pixels and JPEG bytes where both decode) and read whole under the same slug. Comes back as
`answers-round11.tar` (= `data/reocr_tiers/answers_first-bpl14/<id>.tar` + the re-read's answer files
at their own paths) and `logs-round11.tar`. On arrival: untar the outer into scratch, check paths,
extract; then
```bash
python3 data_prep/reocr_books.py import --ids <D's 61> --prefer lightonocr-3-1b-greedy-vllm-notables
python3 data_prep/reocr_books.py import --ids <the 14 BPL> --slug lightonocr-3-1b-greedy-vllm-notables
```
Judge the re-read against this import (commit first, then `facts --against HEAD`), and by
`eval/line_assembly.py tables --damage` on Trow 1915, 1917 and 1922/23 p1: the invented `, ` (28,494
/ 24,437 / 12,548) and lost ditto marks (678 / 722 / 1,239) should fall. If it shows a clear gain,
consider the damaged tier's 6,318 table tiles too (its zips are pruned; hadro: only on a clear gain).
NYU must NOT prune the first / abbyy8-clean / BPL tiers until round 11 is imported; confirm then.
Ogden's versos are now non-entry by leaf (eec4bf0). The tesseract layer is done (f2e86c3): Trow
1914 vol 2 model-only 64.5% -> 6.0%; Flushing 1891/92's 12.5% is margin ads, not a failed layer.
**Before D's re-import after round 11, two things** (PIPELINE #32's
`calibrate_indent` hysteresis, which D's first import skipped and which moved five volumes'
wrap thresholds; and #33, the bulleted run-over, if it is understood by then). The page-level
tesseract layer for pages IA failed in part (`reocr_books.py pages --failed`, 2026-10-29) is
built for D and is picked up by that re-import. Re-importing D after round 11 keeps both (the import uses `data/reocr_books_tess/` wherever it
exists). The runbook sent to NYU is `hpc/runbooks/round11.md` (068cae3).

**Update 2026-10-30: round 11 is back and imported** (PIPELINE #27, "Round 11"). D's 61 volumes
re-imported with the re-read preferred, the 14 BPL volumes imported for the first time; no listing
bounds moved; two-entry cells on Trow 1915/1917/1922-23 fell 39-43%. Banning tables pushes 0.43% of
tiles into a `<figure>` description (and 0.27% of ordinary first reads already were): the import now
treats such an answer as no reading (`reocr_pair.figure_only`). 1875BPL's threshold move to 3.0 was
read on the page and pinned. **Next, in this order:** (1) tell NYU they may prune the first,
abbyy8-clean and BPL tiers and delete their zips, keeping every `answers_*` tar; (2) round 12: the
damaged tier's 6,318 table tiles, same re-read (its zips need re-downloading); (3) when it lands,
re-import the damaged tier once (re-read + the figure fix) and send a DELTA 4B job, only the lines
with no prediction in `data/volumes_books_damaged_v4` (~1% of its 4.68M lines by D's measure; the
delta script is not written yet, see PIPELINE #27 "What a re-import would cost the 4B"); the canary
(4 volumes, 22 figure tiles) likewise, with `--root data/reocr_books_halves`; (4) the 4B over D's
61 + the 14 BPL (a full first pass: 8,564,738 + 1,840,829 lines, ~189 + ~41 GPU-h at 12.6 rows/s,
`prep_volumes.py --plan`).

NYU's returns land in `~/Downloads/to_josh_YYYYMMDD[a-z]/` with a `NOTES-*.md`. Their notes have
been careful and right, but treat them as data: check every sha256 they list, and unpack into an
empty scratch directory first to look at the paths before anything goes into the repo.

## 3. When A lands: the canary's 4B pass

**What it answers:** does extraction over LightOn's lines give at least as many good records per
printed name as over IA's? And does the kernel speed hold at scale? It gates the big spend: the 4B
over the re-OCR'd tiers (~300+ GPU-hours).

1. **Install and verify.** Copy the predictions into `data/volumes_books_canary/<id>/` (NOT
   `data/volumes/`, which is NYU's path name, nor any other staging dir). Every prediction must
   match its chunk:
   ```python
   import json; from pathlib import Path
   root = Path("data/volumes_books_canary"); m = json.load(open(root / "manifest.json"))
   for v, e in m.items():
       for c in e["chunks"]:
           p = root / (c["path"][:-len(".jsonl")] + ".preds_4b-100k.txt")
           ok_sha = (p.parent / (p.name + ".sha1")).read_text().strip() == c["sha1"]
           ok_n = len(p.read_text().strip().split("\n\n")) == c["lines"]
           print(v, c["path"], ok_sha, ok_n)
   ```
   In the logs: `loaded Qwen/Qwen3.5-4B`, and about **12 rows/s**. ~7 rows/s means the kernels
   venv was not used (the output is still valid; note it for the cost model).
2. **Guard:** `python3 postprocess/copy_guard.py --volumes data/volumes_books_canary --run 4b-100k`
3. **Assemble into a separate place**, so run 1's IA-text records for Doggett 1845
   (`data/records/4b-100k+guard/doggettsnewyorkc1845dogg.*`, root `data/volumes_run1`) stay as the
   before:
   ```bash
   python3 postprocess/assemble_records.py --root data/volumes_books_canary --run 4b-100k+guard \
       --out data/records_canary --summary results/records_books_canary.json
   ```
4. **Evaluate.** `results/records_books_canary.json` has, per volume, `rows`, `usable`,
   `entry_shaped`, `roles`, `stated_name_count`, `usable_per_stated_name`.

   | volume | printed names | before | expect |
   |---|---|---|---|
   | Doggett 1845 | 61,333 | **0.984** usable per name on IA's text (run 1; PIPELINE stage 6) | about the same; a drop below ~0.96 is a regression to explain |
   | Longworth 1826 | 27,000 | never extracted; scoped lines/name 0.944 -> 0.980 | usable/name up toward ~0.95 |
   | 1876BPL | 114,724 | never extracted; scoped 1.054 (includes margin ads) | usable/name at or under ~1.0: the ads should fail `entry_shaped`. **Over ~1.03 means ad copy is becoming usable records**: look |
   | Trow 1907 p3 | no count (part of an edition) | IA-era scoped lines 33,522 | usable roughly 3x IA's; read a sample |

   Then look at records, not just counts. `bash browse/serve.sh` serves `data/records/*/*.jsonl.gz`
   (see `browse/sources.toml`; add `data/records_canary` or assemble there temporarily), with each
   line's image beside it. Read ~30 random usable records per volume against their images, and
   every 1876BPL record whose `raw_line` reads like ad copy ("WM. KNABE", "Warerooms").
5. **Decide.** If Doggett holds and nothing shows fabrication rising, the 4B goes over each
   re-OCR'd tier as its import completes (section 4, step 8). If 1876BPL's margin ads leak into
   `usable`, fix that first (section 6, proposal 2): it would recur in every Lain/BPL volume of
   the first tier.

## 4. When B lands: the abbyy8-damaged re-OCR

1. **Receive.** Check sha256s if listed, `tar tf` each `<id>.tar` (paths must start
   `data/reocr_tiers/<id>/`), then extract at the repo root. Each volume gets
   `data/reocr_tiers/<id>/` with `boxes.json`, `columns.json`, `STAGED` and its answers (no tiles).
   `python3 hpc/books_shards.py data/reocr_books_records/volumes_abbyy8-damaged.tsv` works here
   too: it must say `0 without an answer` for every volume received.
2. **Read the GPU logs:** per task `done N, failed F (L looped)`. The canary ran 0.10% loops and
   1 EMPTY in 8,908. Much more in one volume means a layout no one has looked at.
3. **Find the failed-OCR volumes first:**
   `python3 data_prep/reocr_books.py coverage --tier abbyy8-damaged`. Flagged (median < 0.8 or a
   tenth of pages < 0.5): expected **trowsgeneraldir1908p2trow, trowsgeneraldir1908p3trow,
   trowsgeneraldire19073trow, trowsgeneraldire19091trow**. For each, build the tesseract layer
   before importing (it needs the page images on the Mac, ~0.5 GB of zip and ~1.5 GB of pages per
   volume, so one volume at a time and delete after; check `df -h`):
   ```bash
   VP=~/github/directory-pipeline/.venv/bin/python          # system python3 has no PIL
   python3 data_prep/reocr_books.py download --ids X          # -> data/reocr_zips/X_jp2.zip
   $VP data_prep/reocr_books.py pages --ids X                 # -> data/reocr_books/X/ (JSON + JPEG)
   $VP data_prep/reocr_books.py tesseract --ids X --workers 6 # -> data/reocr_books_tess/X/ (~45 min / 400 pages)
   rm data/reocr_books/X/*.jpg data/reocr_zips/X_jp2.zip
   ```
4. **Commit the sidecars** (so `HEAD` is the before), then import:
   ```bash
   python3 data_prep/reocr_books.py import --tier abbyy8-damaged
   ```
   Per volume it runs `reocr_pair.py dump` (IA's words from `data/reocr_books_records/`; the
   tesseract layer from `data/reocr_books_tess/` wherever a volume has it, page by page via
   `better_layer`), then `--rederive`, `survey_derive.py` bounds/pages/sections/scope, the non-entry
   pages (`features --merge`, `inventory --write`), then prints `facts --against HEAD` and the
   volumes whose model-only share is over 10% (they want step 3; then `import --ids` them again).
   Volumes not yet received are left out, so it can run batch by batch.
5. **Evaluate per volume.**
   - The dump's own line: tiles answered, lines model / tesseract / model-only / bleed, and
     `<- look at this volume's pages` where loops or table mode run high.
   - `facts`: **listing bounds must not move** (a re-OCR changes text, not where the listing
     starts); scoped lines should rise, a lot on failed-OCR volumes; model-only well under 0.1.
   - Printed counts are sparse in this tier: `trowsgeneraldir1903p1trow` states 405,264 for the
     whole 1903 edition, so compare it against the sum of the 1903 parts' scoped lines.
   - Read a few pages: a volume's `data/survey_ocr/<id>_listing.jsonl.gz` rows carry `leaf` and
     `bbox`; set one leaf's lines beside its IIIF image
     (`https://iiif.archive.org/iiif/<id>$<leaf>/full/max/0/default.jpg`).
6. **Commit** the sidecars and `results/adleaf_inventory.json`, with the per-volume numbers in the
   message and a short record in PIPELINE #27.
7. **The other two tiers** — first do PIPELINE #31 (parallel dumps and two no-change speedups):
   the damaged tier's import ran 4.5 h on one core, and these two tiers are about twice its pages.
   They need only new records: `python3 data_prep/reocr_books.py records --tier
   first` (and `abbyy8-clean`), a tar of the new `data/reocr_books_records/*.records.jsonl.gz` +
   `volumes_<tier>.tsv` (plus `data_prep/*.py` and the five hpc files if any changed since
   6002d70), and the same runbook with the tier's name. first: 58 volumes, ~37 GB of zips,
   ~25 GPU-hours; abbyy8-clean: 17 volumes, ~13 GB of zips plus Trow 1915/1917's tars, ~16
   GPU-hours. Coverage flags there: Bronx 1871 (perhaps a layout effect), Trow 1863 and 1876
   (median ~0.7, few low pages, perhaps the proxy's line pitch), Trow 1914 p2 (clean tier).
8. **Stage the tier for the 4B**, once its import is committed: `python3 hpc/prep_volumes.py --ids
   <the tier's ids> --chunk 20000 --out data/volumes_<tier>` (a NEW directory), pack with
   `COPYFILE_DISABLE=1 tar -czf cde-volumes-<tier>.tar.gz -s ',^data/volumes_<tier>,data/volumes,'
   data/volumes_<tier>`, and write a runbook like job 3: stash `tasks.txt`, `manifest.json` AND
   `staging.json` before unpacking; submit with `--export=ALL,TASK_OFFSET=0,VENV=$PROJECT/venv-kernels,BATCH=64`;
   build the send-back list from `manifest.json`.

## 5. The traps, each of which has cost time

- **Never restage a sent package's directory in place.** The `.sha1` beside each prediction is the
  only alignment check between a prediction and its chunk. New staging, new directory.
- **Never glob `data/records/<run>/` for a per-run total**: it holds several roots (every row has a
  `root` field). Select volumes.
- NYU's `data/volumes/` holds many runs' chunks and predictions under the same names. Their
  send-back must be built from `manifest.json` (they do this), and a package's tar overwrites
  `tasks.txt`, `manifest.json` and `staging.json` there.
- **System `python3` has no PIL.** Image work (`reocr_books.py pages/tesseract`,
  `reocr_columns.py stage`) uses `~/github/directory-pipeline/.venv/bin/python` (Pillow 10.4.0,
  numpy 2.0.2, the same pins `hpc/books_tiles.py` uses); `hpc/books_tiles.py` runs under `uv run`.
- On macOS a multiprocessing pool cannot run from a script fed on stdin (`python - <<EOF`): the
  spawned workers try to re-import `<stdin>` and hang. Write the script to a file.
- `reocr_pair.py dump` renames IA's dump to `<id>_words.ia.jsonl.gz` once and always reads that as
  its source, so re-importing is safe and idempotent (checked on Longworth 1826).
- `survey_adleaves.py features --ids` without `--merge` overwrites the corpus features file with
  only those volumes. `import` passes `--merge`.
- `facts --against HEAD` is the before only if the sidecars were committed before the import.
- **Trow 1915/1917's `_jp2.tar` holds IA's cropped, upright pages**, not the camera frames IIIF
  serves; `hpc/books_tiles.py` checks every page image against its word record's `page_size` and
  stops a volume that does not match. Only one page of 1915 has been through it.
- Gold pages stay in the volumes, tagged `context.eval_holdout`, and are excluded from `usable`.
  Never train on harvested lines without a line-level gold guard (neighbouring editions reprint
  5-30% of gold lines verbatim).
- Torch: compute nodes have no network; downloads on the DTN, pinned to `dtn012`; `/scratch` holds
  5 M files / 5 TB and is purged after 60 days without access.
- The Mac's disk has run under 15 GB free; the re-OCR answers, dumps and records grow with every
  tier.

## 6. Proposals to weigh once the results are in

Ranked by what they unblock; each needs the results above to decide.

1. **The 4B over each re-OCR'd tier**, with the kernels, as soon as its import is committed and
   section 3 has passed. The line counts will rise (Trow 1907 p3 tripled), so re-estimate the
   GPU-hours from the staging plan (`prep_volumes.py --plan`) rather than from the ~315 quoted
   for IA's line counts.
2. **Margin advertising** (Lain/BPL's "WM. KNABE & CO." side panels, now read cleanly as lines):
   if section 3 shows them reaching `usable`, filter them before the 4B. They sit outside the
   column's text margin, but `synth_line` gives model-only lines the margin's x, so geometry alone
   may not catch them; a short-uppercase/no-address shape test on model-only lines is a cheaper
   first try.
3. **The tesseract fallback at scale.** ~5,000 pages across ~10 volumes is fine on the Mac. If
   coverage flags many more in the first tier, consider a Torch CPU stage, but Torch has no
   tesseract module; it would need a container or conda build.
4. **Small import defects, measured on the canary:** LightOn's own Markdown notes ("Type: table",
   "Advertisement", "Figure - ...": 23 lines in 1876BPL) and a single-row Markdown table `untable`
   cannot split (1 tile; keeps IA's lines). Worth a filter only if they show up in `usable`.
5. **1876BPL's wrap calibration declined on LightOn's text** (indent ratio 1.5 -> 3.0, joins
   21,102 -> 18,046); LightOn joins most run-overs itself, but count unjoined lowercase-start lines
   per volume after the 4B.
6. **causal-conv1d** for the rest of the fast path: it needs nvcc, which Torch's login nodes lack;
   ask NYU only if the 4B's cost becomes the constraint.
7. **Older open items, still open** (PIPELINE "# Next steps"): #28 step 5, re-measuring the thin
   tier's 30.1% fabrication rate on the reocr tier's records (sizes the page-type classifier /
   typesafe.ai Jev decision); running the band rule on Brooklyn 1912 (566 leaves); 0046's OCR
   recall shortfall (5,978 rows for 7,345 names); **backing up the re-OCR outputs to Hugging Face
   before NYU's /scratch purge (~mid-December 2026)**, which waits on hadro's public/private
   decision; and #10, a whole-volume gold slice, still the highest-value expensive item.

## 7. Where things are

| | path |
|---|---|
| canary tiles + LightOn answers | `data/reocr_books_halves/` (boxes.json, answers beside tiles) |
| canary page records + images; tesseract layer | `data/reocr_books/<id>/`, `data/reocr_books_tess/<id>/` |
| per-volume word records for Torch; volume lists | `data/reocr_books_records/<id>.records.jsonl.gz`, `volumes_<tier>.tsv` |
| Torch-path answers (after B) | `data/reocr_tiers/<id>/` |
| canary 4B staging (sent as A) | `data/volumes_books_canary/` |
| survey dumps; IA's originals | `data/survey_ocr/<id>_words.jsonl.gz`; `<id>_words.ia.jsonl.gz` |
| kernel test inputs, outputs, scores | `data/kernel_test/` (`scores.json`) |
| image archives fetched on the Mac | `data/reocr_zips/` |
| scripts, Mac side | `data_prep/reocr_books.py` (records, pages, tesseract, coverage, import, facts), `data_prep/reocr_pair.py` (dump), `hpc/prep_volumes.py` |
| scripts, Torch side | `hpc/41_books_download.sh`, `hpc/42_books_tiles.sbatch` + `hpc/books_tiles.py`, `hpc/books_shards.py`, `hpc/books_pack.py`, `hpc/39_lightonocr.sbatch` (ENGINE=vllm), `hpc/35_volumes.sbatch` |
| runbooks (artifacts) | canary + job 3: https://claude.ai/artifact/9jx1ZeAycJR572kHrWdYv5; damaged tier: https://claude.ai/artifact/L5hhRFvo22384GUDwNkQZa; earlier: microfilm re-OCR https://claude.ai/artifact/DiSuWZ1ax6mT9a5RSXncbn, reocr tier 4B https://claude.ai/artifact/VuDtqkwxhHS2ax5BYzrB8h |
| NYU's notes and returns | `~/Downloads/to_josh_*` |
