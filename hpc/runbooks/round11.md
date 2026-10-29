# Round 11: re-read the table-mode tiles, and read the 14 BPL volumes

city-directory-extraction, for NYU Torch, 2026-10-29. Code at commit 0c31a09.
The same steps are on the runbook page (https://claude.ai/artifact/L5hhRFvo22384GUDwNkQZa,
"Round 11"); this file is the copy to work from.

## Reply to round 10

Thank you for both bundles and the careful notes. Every sha256 matched. All 258 predictions of the
4B job match their chunks, and the 61 volumes of the last two tiers imported cleanly. The canary
volumes held: Doggett 1845 gives 0.982 usable records per printed name, and Longworth 1826 rose
from 0.859 to 0.897.

- **The 14 BPL volumes: your option 1, tile them with Pillow 12.3.0.** We checked it on the laptop
  with 1866BPL pages. Our pinned 10.4.0 fails on the same pages, and 12.3.0 reads them as clean
  listing pages. Where both versions decode a page, the pixels and the JPEG bytes the cutter writes
  are identical, so no parity check is needed. `hpc/42_books_tiles.sbatch` now takes
  `PILLOW=12.3.0` for this (step 3).
- **The table test was useful.** Banning tables costs nothing measurable on the hand-checked text:
  93.6% of gold entries exact before, 93.4% after, one line. But across the two tiers you just
  read, LightOn answered 21% of tiles as tables, and half the tiles on Trow 1915 and 1922/23. So we
  would like those tiles re-read (step 2). Your `SamplingParams` subclass is in our copy now,
  unchanged.
- **Please do not prune the first and abbyy8-clean tiers yet, and do not delete their zips.** The
  re-read needs their tiles. We will confirm cleanup for everything once round 11 is back.
- **Ogden's 50 EMPTY tiles are fine.** Those pages are blank versos showing the next page through
  the paper. We now leave them out by leaf.

## What round 11 is

Two GPU jobs. Both use `hpc/43_lightonocr_notables.sbatch`, the table test's wrapper, which bans
table output.

| Job | Tiles | Tasks | L40S GPU-hours |
|---|---|---|---|
| Re-read the first and abbyy8-clean tiles that came back as tables | 41,904 | 22 | ~9.5 |
| Read the 14 BPL volumes, cut under Pillow 12.3.0 | ~50,700 (12,908 pages) | ~26 | ~9 |

Banning tables leaves an ordinary tile's reading as it was. On the test's 311 non-table tiles, the
banned reader matched the first run as often as two runs of the plain reader match each other. So
the 14 BPL volumes need no second pass later.

## Steps

### 1. Ship and unpack (laptop, then login node)

```bash
scp cde-table-reread.tar <netid>@<torch-login-host>:/scratch/<netid>/
# then, on Torch:
cd /scratch/$USER/city-directory-extraction
tar xf ../cde-table-reread.tar
```

The tar is 3.9 MB, sha256 `6cb340589e4ac4e6635ed76931e4916699b8d91c8cc2412446133e3c0b192673`.
It holds:

- `hpc/lightonocr_vllm_notables.py`, with your subclass fix;
- `hpc/43_lightonocr_notables.sbatch`, with the time limit raised to 2 hours, because a task is now
  2,000 tiles;
- `hpc/42_books_tiles.sbatch`, which takes `PILLOW=12.3.0`;
- `hpc/books_shards.py` and `hpc/books_pack.py`, which now take `--slug` (and `--tables` for the
  shards). Without those options they behave as before;
- the re-read's shard lists, built on the laptop from the answers' metadata:
  `data/reocr_tiers/tasks_first_notables_tables.txt` (8 tasks) and
  `data/reocr_tiers/tasks_abbyy8-clean_notables_tables.txt` (14 tasks), with their `shards_*`
  directories;
- `data/reocr_books_records/volumes_first-bpl14.tsv`, the 14 BPL volumes' rows of
  `volumes_first.tsv`.

It does not touch `hpc/lightonocr_vllm.py` (your copy with the `transformers==5.14.1` pin) or
`hpc/env.sh`.

### 2. Re-read the table-mode tiles (GPU, L40S, 22 tasks, ~9.5 GPU-hours)

```bash
export GPU_TYPE=l40s
source hpc/env.sh
sbatch $(slurm_gpu_args) --export=ALL,TASKS=data/reocr_tiers/tasks_first_notables_tables.txt,TAG=vllm-notables \
    --array=0-7 hpc/43_lightonocr_notables.sbatch
sbatch $(slurm_gpu_args) --export=ALL,TASKS=data/reocr_tiers/tasks_abbyy8-clean_notables_tables.txt,TAG=vllm-notables \
    --array=0-13 hpc/43_lightonocr_notables.sbatch
```

Each log should print `table output banned: bad_words=['|', '<table']` and the slug
`lightonocr-3-1b-greedy-vllm-notables`. The answers land beside each tile under that slug. The
first answers stay where they are.

After a partial run, this rewrites the lists with only the tiles not yet re-read, and prints the
`sbatch` line to use:

```bash
python3 hpc/books_shards.py data/reocr_books_records/volumes_first.tsv \
    --slug lightonocr-3-1b-greedy-vllm-notables --tables
python3 hpc/books_shards.py data/reocr_books_records/volumes_abbyy8-clean.tsv \
    --slug lightonocr-3-1b-greedy-vllm-notables --tables
```

### 3. Cut the 14 BPL volumes under Pillow 12.3.0 (login node once, then a CPU array of 14 tasks)

```bash
source hpc/env.sh
# login node, with network: caches the environment for the compute nodes; ends "self-test ok"
UV_CACHE_DIR=$PROJECT/uv_cache UV_PYTHON_INSTALL_DIR=$PROJECT/uv_python \
    $PROJECT/bin/uv run --python 3.12 --no-project --with pillow==12.3.0 --with numpy==2.0.2 \
    python hpc/books_tiles.py --self-test
sbatch --account=$SLURM_ACCOUNT \
    --export=ALL,VOLS=data/reocr_books_records/volumes_first-bpl14.tsv,PILLOW=12.3.0 \
    --array=0-13 hpc/42_books_tiles.sbatch
```

The zips are the ones already on /scratch. Python 3.12 matters: numpy 2.0.2 has no wheel for newer
Pythons, and it fails to build from source. Each log should end with the volume's tile count, as
before.

### 4. Read the 14 volumes (login node, then GPU, ~26 tasks, ~9 GPU-hours)

```bash
python3 hpc/books_shards.py data/reocr_books_records/volumes_first-bpl14.tsv \
    --slug lightonocr-3-1b-greedy-vllm-notables
```

This writes `data/reocr_tiers/tasks_first-bpl14_notables.txt` and prints the full `sbatch` line for
`43_lightonocr_notables.sbatch`, array size included. Run that line. Expect about 50,700 tiles. If
it lists a volume as `not cut yet`, check that volume's tile log first.

### 5. Pack and send back (login node)

```bash
python3 hpc/books_pack.py data/reocr_books_records/volumes_first-bpl14.tsv \
    --slug lightonocr-3-1b-greedy-vllm-notables      # -> data/reocr_tiers/answers_first-bpl14/<id>.tar

python3 - <<'EOF' > table-reread.list
import collections, glob, os
SLUG = 'lightonocr-3-1b-greedy-vllm-notables'
want = collections.defaultdict(set)              # each volume's directory is listed once
for s in glob.glob('data/reocr_tiers/shards_*_notables_tables/shard_*.txt'):
    for t in open(s).read().split():
        d, b = os.path.split(t)
        want[d].add(b[:-len('.jpg')])
for d, stems in sorted(want.items()):
    for f in sorted(os.listdir(d)):
        stem, sep, _ = f.partition('_' + SLUG + '.')
        if sep and stem in stems:
            print(os.path.join(d, f))
EOF
wc -l < table-reread.list                         # about 126,000

tar cf answers-round11.tar data/reocr_tiers/answers_first-bpl14 -T table-reread.list
tar cf logs-round11.tar logs/notables-<jobid>_*.out logs/tiles-<jobid>_*.out
```

The list holds only the re-read's answer files: about 126,000 small files, three per tile. Each BPL
volume comes as one tar, as before. Please send:

- `answers-round11.tar`;
- `logs-round11.tar`;
- the summary lines from `books_pack.py` and `books_shards.py`.

### 6. Clean up: please wait for Josh

Once we have confirmed round 11's import, we will ask you to prune the first, abbyy8-clean and
BPL tiers and delete their zips, all in one go. Please keep every `answers_*` tar.

## If something goes wrong

| Where | Message | What to do |
|---|---|---|
| Tiles | `broken data stream when reading image file` | The task ran without `PILLOW=12.3.0`. Re-submit with it; volumes already cut are skipped. |
| Tiles | uv error about being offline, or numpy failing to build | Step 3's login-node command was not run, or ran without `--python 3.12`. |
| Reading | `EMPTY`, `looped` | Expected now and then, as before. |
| Reading | a task hits the 2-hour limit | Re-run step 2's `books_shards.py ... --tables` line; it lists only what is missing. |
