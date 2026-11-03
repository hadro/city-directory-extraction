# Round 13: a small 4B delta job over the damaged tier, and the round 12 clean-up

city-directory-extraction, for NYU Torch, 2026-11-03. Code at commit f92f7b7. The same steps are
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
  more than 500 tasks ourselves. This round has only 5 tasks.

## What round 13 is

| Step | Where | Size |
|---|---|---|
| 1. Clean up the damaged tier (round 12's step 10) | login node | frees its tiles and 21 GB of zips |
| 2. Ship and unpack the delta package | laptop, then login node | 3.4 MB |
| 3. The 4B over the delta | GPU, any card, 5 tasks | ~2.2 GPU-hours |
| 4. Send the predictions back | login node | ~15 MB |

**Why a delta.** The re-read changed about 2% of the damaged tier's lines. We have predictions
for the rest from your 4B job over this tier (21014769). This job reads only the 99,968 lines that are
new, and we merge the results on our side. It runs from its own directory, `data/volumes_delta/`,
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

The package is 3.4 MB, sha256 `fb90b429c96b3788734d8200d37c13be78e590b36a818beecf641ad9f580d0c6`.
It holds two things:

- `data/volumes_delta/`: 5 chunks under `delta/`, plus `tasks.txt`, `manifest.json` and
  `staging.json`. These are 99,968 lines in all.
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
cat data/volumes_delta/tasks.txt                          # 5 lines, delta/chunk_000 .. 004
grep -E '"(code_at|lines|tasks)"' data/volumes_delta/staging.json   # f92f7b7-dirty, 99968, 5
```

### 3. Run the 5 tasks (GPU, any card, ~26 minutes each)

This is round 12's line with `VOL` added and the array size changed:

```bash
export GPU_TYPE=l40s
source hpc/env.sh
sbatch $(slurm_gpu_args) \
    --export=ALL,VOL=$DATA/volumes_delta,TASK_OFFSET=0,VENV=$PROJECT/venv-kernels,BATCH=64,MODEL_SIZE=4B,MODEL_ID=Qwen/Qwen3.5-4B \
    --array=0-4 hpc/35_volumes.sbatch
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

Expect 5 prediction files, their 5 `.sha1` sidecars and 5 logs.

## If something goes wrong

| Where | Message | What to do |
|---|---|---|
| Clean-up | `reading` or `not cut` for a volume | Stop and send us the output. All 35 should be `packed before`. |
| 4B | `no data/volumes_delta/tasks.txt` | `VOL` did not reach the job. Check `$DATA` is set (`source hpc/env.sh`) and that `diff` showed the new `VOL` line. |
| 4B | `no task N in tasks.txt` | The array went past 4. |
| 4B | `stale or partial predictions ... redoing` | Expected only after a preemption. Re-submit that index. |
