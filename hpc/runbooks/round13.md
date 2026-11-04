# Round 13: a 4B delta job over all three re-OCR'd tiers, and the round 12 clean-up

city-directory-extraction, for NYU Torch, 2026-11-03. Code at commit dec98af. The same steps are
on the runbook page (https://claude.ai/artifact/L5hhRFvo22384GUDwNkQZa, "Round 13"); this file is
the copy to work from.

## Reply to round 12

Thank you for both bundles and for the careful notes. All three sha256s matched.

- **The 4B over the 75 volumes is in.** All 557 predictions match their chunks, by SHA-1 and by
  line count (10,405,567 lines), and every log says `loaded Qwen/Qwen3.5-4B`. The 12.3 rows/s you
  measured is what we planned on. Those 10.4 million lines gave 9.13 million usable records.
- **The re-read is imported.** The answers were exactly the shard lists' 6,318 tiles. Your re-cut
  check came back clean, and the import moved what we expected and nothing else.
- **A correction to our runbook.** We wrote that all 35 volumes had table-mode tiles. The shard
  lists actually named 34: Longworth 1798 had none. Nothing to do on your side.
- **The 500-job limit.** Thank you for splitting the array. From now on we will split any job with
  more than 500 tasks ourselves. This round has 15 tasks.

## What round 13 is

| Step | Where | Size |
|---|---|---|
| 1. Clean up the damaged tier (round 12's step 10) | login node | frees its tiles and 21 GB of zips |
| 2. Ship and unpack the delta package | laptop, then login node | 11.6 MB |
| 3. The 4B over the delta | GPU, any card, 15 tasks | ~6.3 GPU-hours |
| 4. Send the predictions back | login node | ~45 MB |

**Why a delta.** Since round 12 we changed how the re-OCR'd pages are turned into lines. The
round 12 re-read changed about 2% of the damaged tier's lines. Two fixes to our import then
brought back text that had been lost. One restores the start of a line that a tile edge cut off.
The other keeps full-width entries that we had been dropping as page banners. Together they touch
all three re-OCR'd tiers: the damaged tier, the 75 volumes of round 12, and the 39 microfilm
volumes. We already have 4B predictions for 15.47 million of their 15.78 million lines, from your
earlier jobs. This job reads only the 287,920 lines that are new, all three tiers in one
directory, and we merge the results on our side. It runs from its own directory, `data/volumes_delta/`,
so `data/volumes/` and its ledger stay as round 12 left them.

## Steps

### 1. Clean up the damaged tier (login node; do this now)

Round 12 is imported, so the damaged tier is done. Delete its tiles and its 35 zips. Please keep
every `answers_*` tar and the re-read's answer files: `--prune` deletes only the tile JPEGs.

```bash
cd /scratch/$USER/city-directory-extraction
python3 hpc/books_pack.py data/reocr_books_records/volumes_abbyy8-damaged.tsv --prune
tail -n +2 data/reocr_books_records/volumes_abbyy8-damaged.tsv | cut -f3 \
    | sed 's|^|data/reocr_zips/|' | xargs rm -fv
```

The first command should report `packed before: 35`.

You may also delete these. We have copies of both.

- The ledger stash `data/volumes/{tasks.txt,manifest.json,staging.json}.damaged4b`.
- The four `data/volumes/*.run2` folders: `1857BPL`, `1906BPL`, `hearnesbrooklync1852unse` and
  `merceinscitydire00merc`.

### 2. Ship and unpack (laptop, then login node)

```bash
scp cde-round13.tar.gz <netid>@<torch-login-host>:/scratch/<netid>/
```

The package is 11.6 MB, sha256 `16243949ae0aa4ba17a4cda52509b49f4a3e54c91117c3bf1cd6e9acdc8bbd8e`.
If you downloaded an earlier `cde-round13.tar.gz` (3.4 MB, sha256 starting `fb90b429`), please
delete it: this one replaces it.
It holds two things:

- `data/volumes_delta/`: 15 chunks under `delta/`, plus `tasks.txt`, `manifest.json` and
  `staging.json`. These are 287,920 lines in all.
- `hpc/35_volumes.sbatch`: one line differs from your copy. `VOL="$DATA/volumes"` becomes
  `VOL="${VOL:-$DATA/volumes}"`, so a job can read a directory other than `data/volumes/`. Without
  `VOL` it behaves exactly as before. The file's sha256 is
  `f20faa9adb2de7a14fa634c6fa7fdc950bce624f025406ae104448c611260356`.

The tar overwrites `hpc/35_volumes.sbatch`, so the commands below save your copy first. The `diff`
should show only that one line. If it shows anything else, those are local changes of yours: put
them back into the new file.

```bash
cd /scratch/$USER/city-directory-extraction
cp hpc/35_volumes.sbatch hpc/35_volumes.sbatch.r12
tar xzf ../cde-round13.tar.gz
diff hpc/35_volumes.sbatch.r12 hpc/35_volumes.sbatch     # the VOL line only
cat data/volumes_delta/tasks.txt                          # 15 lines, delta/chunk_000 .. 014
grep -E '"(code_at|lines|tasks)"' data/volumes_delta/staging.json   # dec98af-dirty, 287920, 15
```

### 3. Run the 15 tasks (GPU, any card, ~26 minutes each)

This is round 12's line with `VOL` added and the array size changed:

```bash
export GPU_TYPE=l40s
source hpc/env.sh
sbatch $(slurm_gpu_args) \
    --export=ALL,VOL=$DATA/volumes_delta,TASK_OFFSET=0,VENV=$PROJECT/venv-kernels,BATCH=64,MODEL_SIZE=4B,MODEL_ID=Qwen/Qwen3.5-4B \
    --array=0-14 hpc/35_volumes.sbatch
```

As before, each log should say `loaded Qwen/Qwen3.5-4B` and end at about 12 rows a second. The
`fast path is not available` warning still prints, as expected. The predictions land beside their
chunks, as `data/volumes_delta/delta/chunk_NNN.preds_4b-100k.txt`.

### 4. Send the predictions back (login node)

```bash
python3 - <<'EOF' > delta-4b.list
import json
for v in json.load(open('data/volumes_delta/manifest.json')).values():
    for c in v['chunks']:
        p = 'data/volumes_delta/' + c['path'][:-len('.jsonl')] + '.preds_4b-100k.txt'
        print(p); print(p + '.sha1')
EOF
ls logs/vol-<jobid>_*.out >> delta-4b.list
tar cf delta-4b-preds.tar -T delta-4b.list
```

Expect 15 prediction files, their 15 `.sha1` sidecars and 15 logs.

## If something goes wrong

| Where | Message | What to do |
|---|---|---|
| Clean-up | `reading` or `not cut` for a volume | Stop and send us the output. All 35 should be `packed before`. |
| 4B | `no data/volumes_delta/tasks.txt` | `VOL` did not reach the job. Check `$DATA` is set (`source hpc/env.sh`) and that `diff` showed the new `VOL` line. |
| 4B | `no task N in tasks.txt` | The array went past 14. |
| 4B | `stale or partial predictions ... redoing` | Expected only after a preemption. Re-submit that index. |
