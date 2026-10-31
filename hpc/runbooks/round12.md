# Round 12: clean up three tiers, re-read the damaged tier's table-mode tiles, and run the 4B over 75 volumes

city-directory-extraction, for NYU Torch, 2026-10-30, with the 4B job added 2026-10-31. Code at
commit d5cce25 for the re-read (no `hpc/` script has changed since round 11's 0c31a09); the 4B
package's lines were staged at 0e384e7. The same steps are on the runbook page
(https://claude.ai/artifact/L5hhRFvo22384GUDwNkQZa, "Round 12"); this file is the copy to work from.

## Reply to round 11

Thank you, and for the careful notes again. Both sha256s matched, the re-read covered exactly the
41,904 tiles in the lists, and all 14 BPL volumes imported cleanly. Nothing moved that should not
have: no volume's listing bounds changed.

- **The re-read worked.** On Trow 1915, 1917 and 1922/23, entries glued two to a line (two names
  in one table cell) fell by about 40%: on 1915 from 3,987 to 2,326. Lines that open with a
  ditto mark rose by about 100,000, and the commas that the table form added are gone.
- **The loops you flagged cost nothing.** On the 514 tiles where the re-read looped, it still
  gives more lines than the table reading did: 32,523 against 30,157. We kept them.
- **One thing we found, for your information only.** With tables banned, about 0.4% of tiles
  were answered as a figure description (`<figure> ### Figure – ...`) instead of being read. The
  first reading does this too, on 0.27% of tiles. Our import now treats such an answer as no
  reading. Nothing to change on your side.

Because the gain is clear, we would like the abbyy8-damaged tier's 6,318 table-mode tiles re-read
the same way (steps 2 to 5). Its tiles and zips were pruned, so this needs the 35 zips again.

**New in this round: the 4B over the 75 volumes you read in rounds 10 and 11** (the first tier's
58, the 14 BPL among them, and abbyy8-clean's 17), steps 6 to 9. It is the big job, about 229
GPU-hours, and it shares nothing with the re-read. **Please submit it first** (step 8): the
re-read is about an hour and can run beside it.

## What round 12 is

| Step | Where | Size |
|---|---|---|
| 1. Clean up first, abbyy8-clean and the 14 BPL | login node | frees their tiles and ~50 GB of zips |
| 2–3. Download and re-cut the 35 abbyy8-damaged volumes | DTN, then a CPU array | 21 GB of zips |
| 4. Re-read 6,318 tiles with tables banned | GPU, L40S, 4 tasks | ~1 GPU-hour |
| 5. Pack and send back | login node | ~19,000 small files |
| 6–7. Ship the 4B package, set the last job aside, unpack | laptop, then login node | 318 MB |
| 8. The 4B over 75 volumes | GPU, any card, 557 tasks | ~229 GPU-hours, ~14 hours at 16 GPUs |
| 9. Send the predictions back | login node | ~1.7 GB |

## Steps

### 1. Clean up the first, abbyy8-clean and BPL tiers (login node; do this now)

Round 11 is imported, so these three tiers are done. Delete their tiles and zips; please keep
every `answers_*` tar.

```bash
cd /scratch/$USER/city-directory-extraction
python3 hpc/books_pack.py data/reocr_books_records/volumes_first.tsv --prune
python3 hpc/books_pack.py data/reocr_books_records/volumes_abbyy8-clean.tsv --prune
python3 hpc/books_pack.py data/reocr_books_records/volumes_first-bpl14.tsv --prune
for t in volumes_first.tsv volumes_abbyy8-clean.tsv; do
    tail -n +2 data/reocr_books_records/$t | cut -f3 | sed 's|^|data/reocr_zips/|'
done | xargs rm -fv
```

The first command reports the 14 BPL volumes as `reading`. That is expected: their tars are
under `answers_first-bpl14/`, and the third command prunes them. `--prune` deletes only the tile
JPEGs; answers, `boxes.json` and `STAGED` stay.

### 2. Ship, unpack, and download the damaged tier again (laptop, then the DTN)

```bash
scp cde-round12.tar <netid>@<torch-login-host>:/scratch/<netid>/
# then, on Torch:
cd /scratch/$USER/city-directory-extraction
tar xf ../cde-round12.tar
```

The tar is 0.7 MB, sha256 `5dd1c5696b148e73c48ebddfb65836eecdcb70d3cb8950e8ba9752f032b9eac7`. It holds only the re-read's shard lists:
`data/reocr_tiers/tasks_abbyy8-damaged_notables_tables.txt` (4 tasks) and
`data/reocr_tiers/shards_abbyy8-damaged_notables_tables/shard_000.txt` … `shard_003.txt`, built on
the laptop from the tier's answers.

Then, on the DTN, the same download as when the tier was first read (2026-10-22):

```bash
ssh dtn012.hpc.nyu.edu
cd /scratch/$USER/city-directory-extraction
nohup bash hpc/41_books_download.sh data/reocr_books_records/volumes_abbyy8-damaged.tsv \
    > logs/download-abbyy8-damaged-r12.log 2>&1 &
```

All 35 volumes have some table-mode tiles (8 to 722 each), so all 35 zips are needed, 21 GB as before.

### 3. Re-cut the 35 volumes (login node, then a CPU array of 35 tasks)

The tiling script skips a volume that has `STAGED`, so move that aside first. Save copies of
`boxes.json` and `columns.json` too: the re-cut rewrites them, and they must come out the same,
or the tiles would not be the ones the shard lists name.

```bash
source hpc/env.sh
for id in $(tail -n +2 data/reocr_books_records/volumes_abbyy8-damaged.tsv | cut -f1); do
    d=data/reocr_tiers/$id
    cp $d/boxes.json $d/boxes.json.prev
    [ -f $d/columns.json ] && cp $d/columns.json $d/columns.json.prev
    mv $d/STAGED $d/STAGED.prev
done
# login node, with network, if the pinned environment is no longer cached; ends "self-test ok"
UV_CACHE_DIR=$PROJECT/uv_cache UV_PYTHON_INSTALL_DIR=$PROJECT/uv_python \
    $PROJECT/bin/uv run hpc/books_tiles.py --self-test
sbatch --account=$SLURM_ACCOUNT \
    --export=ALL,VOLS=data/reocr_books_records/volumes_abbyy8-damaged.tsv \
    --array=0-34 hpc/42_books_tiles.sbatch
```

No `PILLOW=` this time: these volumes were first cut under the pinned Pillow 10.4.0. Once
all 35 tasks are done, check both things before reading:

```bash
python3 - <<'EOF'
import json
from pathlib import Path
bad = 0
for line in Path('data/reocr_books_records/volumes_abbyy8-damaged.tsv').read_text().splitlines()[1:]:
    d = Path('data/reocr_tiers') / line.split('\t')[0]
    for f in ('boxes.json', 'columns.json'):
        if (d / (f + '.prev')).exists() and \
                json.loads((d / f).read_text()) != json.loads((d / (f + '.prev')).read_text()):
            bad += 1
            print('DIFFERS', d / f)
missing = [t for s in sorted(Path('data/reocr_tiers/shards_abbyy8-damaged_notables_tables').glob('shard_*.txt'))
           for t in s.read_text().split() if not Path(t).exists()]
print(f'{bad} files differ, {len(missing)} of the listed tiles missing')
EOF
```

It should print `0 files differ, 0 of the listed tiles missing`. **If either number is not 0,
please stop and send us the output.** Do not read the tiles in that case.

The re-cut leaves the tier's first answers (`*_lightonocr-3-1b-greedy-vllm.*`) where they are.

### 4. Re-read the table-mode tiles (GPU, L40S, 4 tasks, ~1 GPU-hour)

```bash
export GPU_TYPE=l40s
source hpc/env.sh
sbatch $(slurm_gpu_args) --export=ALL,TASKS=data/reocr_tiers/tasks_abbyy8-damaged_notables_tables.txt,TAG=vllm-notables \
    --array=0-3 hpc/43_lightonocr_notables.sbatch
```

As in round 11, each log should print `table output banned: bad_words=['|', '<table']` and the slug
`lightonocr-3-1b-greedy-vllm-notables`. After a partial run, this rewrites the list with only the
tiles not yet re-read, and prints the `sbatch` line to use:

```bash
python3 hpc/books_shards.py data/reocr_books_records/volumes_abbyy8-damaged.tsv \
    --slug lightonocr-3-1b-greedy-vllm-notables --tables
```

### 5. Pack and send back (login node)

The same recipe as round 11, for this round's shards:

```bash
python3 - <<'EOF' > table-reread-r12.list
import collections, glob, os
SLUG = 'lightonocr-3-1b-greedy-vllm-notables'
want = collections.defaultdict(set)
for s in glob.glob('data/reocr_tiers/shards_abbyy8-damaged_notables_tables/shard_*.txt'):
    for t in open(s).read().split():
        d, b = os.path.split(t)
        want[d].add(b[:-len('.jpg')])
for d, stems in sorted(want.items()):
    for f in sorted(os.listdir(d)):
        stem, sep, _ = f.partition('_' + SLUG + '.')
        if sep and stem in stems:
            print(os.path.join(d, f))
EOF
wc -l < table-reread-r12.list                     # about 19,000: three per tile, plus loops

tar cf answers-round12.tar -T table-reread-r12.list
tar cf logs-round12.tar logs/notables-<jobid>_*.out logs/tiles-<jobid>_*.out logs/download-abbyy8-damaged-r12.log
```

Please send `answers-round12.tar`, `logs-round12.tar`, and the output of step 3's check.

### 6. Ship the 4B package (laptop)

```bash
scp cde-volumes-books-first-clean.tar.gz <netid>@<torch-login-host>:/scratch/<netid>/
```

318 MB, sha256 `c1680577d004dab9dd53546bf2e60af3cf145f828d0a769ec9e67ac354228ea9`. It unpacks to
`data/volumes/`: one directory per volume with its chunks (75 volumes, 557 chunks of at most
20,000 lines, 10,405,567 lines in all), plus `tasks.txt`, `manifest.json` and `staging.json`.

### 7. Set the last 4B job aside, then unpack (login node)

```bash
cd /scratch/$USER/city-directory-extraction
for f in tasks.txt manifest.json staging.json; do
    cp data/volumes/$f data/volumes/$f.damaged4b       # the damaged tier's 4B job's ledger
done
for v in $(tar tzf ../cde-volumes-books-first-clean.tar.gz | cut -d/ -f3 | sort -u \
           | grep -v -e '^$' -e '\.txt$' -e '\.json$'); do
    [ -d data/volumes/$v ] && mv -v data/volumes/$v data/volumes/$v.run2
done
tar xzf ../cde-volumes-books-first-clean.tar.gz       # -> data/volumes/...
grep -E '"(code_at|volumes|tasks)"' data/volumes/staging.json
wc -l < data/volumes/tasks.txt                       # 557
```

The second loop moves aside any older directory of these 75 volumes, as you did for the canary's
four before the last job. We expect four from runs 1 and 2 (`1857BPL`, `1906BPL`,
`hearnesbrooklync1852unse`, `merceinscitydire00merc`); their chunks are cut differently now, and
a stale chunk left beside the new ones would only confuse the send-back. `staging.json` should
read `"code_at": "0e384e7-dirty"`, 75 volumes and 557 tasks. The "dirty" is only untracked files
in Josh's checkout.

### 8. Run the 557 tasks (GPU, any card, ~14 hours at your 16-GPU limit)

```bash
export GPU_TYPE=l40s
source hpc/env.sh
sbatch $(slurm_gpu_args) \
    --export=ALL,TASK_OFFSET=0,VENV=$PROJECT/venv-kernels,BATCH=64,MODEL_SIZE=4B,MODEL_ID=Qwen/Qwen3.5-4B \
    --array=0-556 hpc/35_volumes.sbatch
```

The same line as the damaged tier's job, with the array size changed. Each log should say
`loaded Qwen/Qwen3.5-4B` and end at about 12 rows a second, and the `fast path is not available`
warning still prints, as expected. A task is about 26 minutes. A preempted task is simply
re-submitted with its index.

### 9. Send the predictions back (login node)

```bash
python3 - <<'EOF' > first-clean-4b.list
import json
for v in json.load(open('data/volumes/manifest.json')).values():
    for c in v['chunks']:
        p = 'data/volumes/' + c['path'][:-len('.jsonl')] + '.preds_4b-100k.txt'
        print(p); print(p + '.sha1')
EOF
ls logs/vol-<jobid>_*.out >> first-clean-4b.list
tar cf first-clean-4b-preds.tar -T first-clean-4b.list
```

Built from the manifest, as before, so no older run's predictions come along. Expect 557
prediction files, their 557 `.sha1` sidecars and 557 logs, about 1.7 GB. If the job is still
running when the re-read is done, please send round 12's re-read first: we import it while the 4B
runs.

### 10. Clean up the damaged tier again: please wait for Josh

Once round 12 is imported, we will ask you to prune these tiles again and delete the 35 zips.

## If something goes wrong

| Where | Message | What to do |
|---|---|---|
| Re-cut | `staged already ... skipping` | That volume's `STAGED` was not moved aside (step 3's loop). |
| Re-cut | `no ..._jp2.zip or .tar` | The download has not finished that volume; re-run step 2's command, then re-submit. |
| Re-cut check | `DIFFERS` or tiles missing | Stop, and send us the output. |
| Reading | `EMPTY`, `looped` | Expected now and then, as before. |
| 4B | `no task N in tasks.txt` | `tasks.txt` is not this package's: check step 7's `wc -l` reads 557. |
| 4B | `stale or partial predictions ... redoing` | Expected only after a preemption. On a first run it means an older chunk was left in place: check step 7's second loop. |
