#!/bin/bash
#SBATCH --job-name=cde-churro
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48GB
#SBATCH --time=04:00:00
#SBATCH --gres=gpu:1
#SBATCH --output=logs/churro-%A_%a.out
#SBATCH --error=logs/churro-%A_%a.out
#
# STEP 38 -- Churro-3B over column crops of the re-OCR'd microfilm pages (docs/PIPELINE.md #27).
# One array task per shard of data/reocr_columns/tasks.txt (data_prep/reocr_columns.py stage).
#
# Once, on a LOGIN node (compute nodes have no network), in $PROJECT:
#     tar xf cde-churro-columns.tar                            # -> data/reocr_columns/
#     bash hpc/38_churro_setup.sh                              # uv, the environment, the model
# Then, after `source hpc/env.sh`, one shard to time it, and the rest:
#     sbatch $(slurm_gpu_args) --array=0 hpc/38_churro.sbatch
#     sbatch $(slurm_gpu_args) --array=1-<N-1> hpc/38_churro.sbatch     # N = lines of tasks.txt
#
# Back home, the answers and logs only (about 100 MB):
#     { find data/reocr_columns -name '*_churro-3b.*'; ls logs/churro-*.out; } | tar cf churro-answers.tar -T -
# then, here: tar xf churro-answers.tar && python3 data_prep/reocr_columns.py import
#
# Resumable: a crop with its _churro-3b.raw.txt is skipped, so re-submitting the same --array
# after a preemption or a wall-clock kill redoes only what is missing. TASK_OFFSET is added to
# the array index, as in 35_volumes.sbatch, for arrays larger than the cluster's limit.
set -euo pipefail

cd "${SLURM_SUBMIT_DIR:-$PWD}"
source hpc/env.sh
export HF_HUB_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export UV_CACHE_DIR="$PROJECT/uv_cache"              # as hpc/38_churro_setup.sh built it
export UV_PYTHON_INSTALL_DIR="$PROJECT/uv_python"
export UV_OFFLINE=1                                  # no network here: use what setup cached
UV="${UV:-$(command -v uv || echo "$PROJECT/bin/uv")}"

TASKS=data/reocr_columns/tasks.txt
[ -f "$TASKS" ] || { echo "no $TASKS -- unpack cde-churro-columns.tar" >&2; exit 1; }
i=$(( ${SLURM_ARRAY_TASK_ID:?run as an array job} + ${TASK_OFFSET:-0} ))
SHARD=$(sed -n "$((i + 1))p" "$TASKS")
[ -n "$SHARD" ] || { echo "no task $i in $TASKS" >&2; exit 1; }

echo "=== task $i | $SHARD | node $(hostname) | $(date) ==="
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
"$UV" run hpc/churro_columns.py "$SHARD" --device cuda
echo "=== done $(date) ==="
