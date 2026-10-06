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
#     source hpc/env.sh
#     tar xzf cde-churro-columns.tar.gz                        # -> data/reocr_columns/
#     ${UV:-uv} run hpc/churro_columns.py --help               # builds the env into uv's cache
#     ${UV:-uv} run --with huggingface_hub hf download stanford-oval/churro-3B
# Then:
#     sbatch $(slurm_gpu_args) --array=0-<N-1> hpc/38_churro.sbatch     # N = lines of tasks.txt
#
# Resumable: a crop with its _churro-3b.raw.txt is skipped, so re-submitting the same --array
# after a preemption or a wall-clock kill redoes only what is missing. TASK_OFFSET is added to
# the array index, as in 35_volumes.sbatch, for arrays larger than the cluster's limit.
set -euo pipefail

cd "${SLURM_SUBMIT_DIR:-$PWD}"
source hpc/env.sh
export HF_HUB_OFFLINE=1
export TOKENIZERS_PARALLELISM=false

TASKS=data/reocr_columns/tasks.txt
[ -f "$TASKS" ] || { echo "no $TASKS -- unpack cde-churro-columns.tar.gz" >&2; exit 1; }
i=$(( ${SLURM_ARRAY_TASK_ID:?run as an array job} + ${TASK_OFFSET:-0} ))
SHARD=$(sed -n "$((i + 1))p" "$TASKS")
[ -n "$SHARD" ] || { echo "no task $i in $TASKS" >&2; exit 1; }

echo "=== task $i | $SHARD | node $(hostname) | $(date) ==="
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
${UV:-uv} run hpc/churro_columns.py "$SHARD" --device cuda
echo "=== done $(date) ==="
