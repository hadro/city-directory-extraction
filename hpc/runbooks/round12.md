# Round 12: clean up three tiers, and re-read the damaged tier's table-mode tiles

city-directory-extraction, for NYU Torch, 2026-10-30. Code at commit d5cce25 (no `hpc/` script
has changed since round 11's 0c31a09). The same steps are on the runbook page
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
the same way (steps 2 to 6). Its tiles and zips were pruned, so this needs the 35 zips again.

## What round 12 is

| Step | Where | Size |
|---|---|---|
| 1. Clean up first, abbyy8-clean and the 14 BPL | login node | frees their tiles and ~50 GB of zips |
| 2–3. Download and re-cut the 35 abbyy8-damaged volumes | DTN, then a CPU array | 21 GB of zips |
| 4. Re-read 6,318 tiles with tables banned | GPU, L40S, 4 tasks | ~1 GPU-hour |
| 5. Pack and send back | login node | ~19,000 small files |

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

### 6. Clean up the damaged tier again: please wait for Josh

Once round 12 is imported, we will ask you to prune these tiles again and delete the 35 zips.

## If something goes wrong

| Where | Message | What to do |
|---|---|---|
| Re-cut | `staged already ... skipping` | That volume's `STAGED` was not moved aside (step 3's loop). |
| Re-cut | `no ..._jp2.zip or .tar` | The download has not finished that volume; re-run step 2's command, then re-submit. |
| Re-cut check | `DIFFERS` or tiles missing | Stop, and send us the output. |
| Reading | `EMPTY`, `looped` | Expected now and then, as before. |
