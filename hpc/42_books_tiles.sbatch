#!/bin/bash
#SBATCH --job-name=cde-tiles
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=24GB
#SBATCH --time=02:00:00
#SBATCH --output=logs/tiles-%A_%a.out
#SBATCH --error=logs/tiles-%A_%a.out
#
# STEP 42 -- cut the book-scan volumes' half tiles on Torch, one CPU array task per volume
# (docs/PIPELINE.md #27). No GPU. Task i cuts the volume on line i+1 of the TSV's body.
#
# Needs, from earlier steps:
#   data/reocr_books_records/<id>.records.jsonl.gz and the TSV   (from the Mac, in the package)
#   data/reocr_zips/<archive>, complete                           (hpc/41_books_download.sh, DTN)
# Once, on a LOGIN node (network), the Python environment hpc/books_tiles.py pins:
#     UV_CACHE_DIR=$PROJECT/uv_cache UV_PYTHON_INSTALL_DIR=$PROJECT/uv_python \
#         $PROJECT/bin/uv run hpc/books_tiles.py --self-test
# Then, with N = the TSV's volumes:
#     source hpc/env.sh
#     sbatch --account=$SLURM_ACCOUNT --export=ALL,VOLS=data/reocr_books_records/volumes_abbyy8-damaged.tsv \
#         --array=0-<N-1> hpc/42_books_tiles.sbatch
#
# Writes data/reocr_tiers/<id>/ (tiles, boxes.json, columns.json, STAGED). Resumable: a volume
# with STAGED is skipped, so re-submitting the same --array redoes only what is missing. A task
# whose archive is not yet complete stops at once and says so; re-submit it after the download.
set -euo pipefail

cd "${SLURM_SUBMIT_DIR:-$PWD}"
source hpc/env.sh
export UV_CACHE_DIR="$PROJECT/uv_cache"
export UV_PYTHON_INSTALL_DIR="$PROJECT/uv_python"
export UV_OFFLINE=1                                  # no network here: use what setup cached
UV="${UV:-$(command -v uv || echo "$PROJECT/bin/uv")}"

VOLS="${VOLS:?pass VOLS=<volumes TSV> with --export}"
i=$(( ${SLURM_ARRAY_TASK_ID:?run as an array job} + ${TASK_OFFSET:-0} ))
IFS=$'\t' read -r IDENT TIER ARCHIVE BYTES PAGES < <(tail -n +2 "$VOLS" | sed -n "$((i + 1))p")
[ -n "${IDENT:-}" ] || { echo "no volume $i in $VOLS" >&2; exit 1; }

echo "=== task $i | $IDENT ($TIER) | $PAGES pages | $ARCHIVE | node $(hostname) | $(date) ==="
if [ -f "data/reocr_tiers/$IDENT/STAGED" ]; then
    echo "staged already -- skipping"; exit 0
fi
A="data/reocr_zips/$ARCHIVE"
got=$( [ -f "$A" ] && wc -c < "$A" | tr -d ' ' || echo 0 )
[ "$got" = "$BYTES" ] || { echo "$A: $got of $BYTES bytes -- not downloaded yet (hpc/41_books_download.sh)" >&2; exit 1; }

"$UV" run hpc/books_tiles.py "$IDENT" --workers "${SLURM_CPUS_PER_TASK:-8}"
echo "=== done $(date) ==="
