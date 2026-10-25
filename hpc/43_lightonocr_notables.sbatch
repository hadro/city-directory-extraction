#!/bin/bash
#SBATCH --job-name=cde-notables
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32GB
#SBATCH --time=01:00:00
#SBATCH --gres=gpu:1
#SBATCH --output=logs/notables-%A_%a.out
#SBATCH --error=logs/notables-%A_%a.out
#
# STEP 43 -- LightOnOCR-3 with table output banned (hpc/lightonocr_vllm_notables.py), the first
# test of re-reading table-mode tiles that way (docs/PIPELINE.md #32 (b), step 5c). The same
# environment and settings as 39_lightonocr.sbatch with ENGINE=vllm; a file of its own so that
# job and its runner are not touched. After `source hpc/env.sh`, on an L40S:
#     sbatch $(slurm_gpu_args) --array=0 hpc/43_lightonocr_notables.sbatch
#
# Settings, passed with --export=ALL,NAME=value:
#     TASKS        the tasks file (default data/reocr_halves/notables_tasks.txt: task 0's tiles)
#     TAG          the slug's suffix (default vllm-notables -> lightonocr-3-1b-greedy-vllm-notables)
#
# Back home, the answers and the log:
#     { find data/reocr_halves data/reocr_benchcols -name '*_lightonocr-3-1b-greedy-vllm-notables.*'; \
#       ls logs/notables-*.out; } | tar cf notables-answers.tar -T -
set -euo pipefail

cd "${SLURM_SUBMIT_DIR:-$PWD}"
source hpc/env.sh
export HF_HUB_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export UV_CACHE_DIR="$PROJECT/uv_cache"              # as hpc/39_lightonocr_setup.sh built it
export UV_PYTHON_INSTALL_DIR="$PROJECT/uv_python"
export UV_OFFLINE=1                                  # no network here: use what setup cached
UV="${UV:-$(command -v uv || echo "$PROJECT/bin/uv")}"

TASKS="${TASKS:-data/reocr_halves/notables_tasks.txt}"
[ -f "$TASKS" ] || { echo "no $TASKS -- unpack cde-table-test.tar" >&2; exit 1; }
i=$(( ${SLURM_ARRAY_TASK_ID:?run as an array job} + ${TASK_OFFSET:-0} ))
SHARD=$(sed -n "$((i + 1))p" "$TASKS")
[ -n "$SHARD" ] || { echo "no task $i in $TASKS" >&2; exit 1; }

echo "=== task $i | $SHARD | node $(hostname) | $(date) ==="
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
"$UV" run hpc/lightonocr_vllm_notables.py "$SHARD" --model "${MODEL:-lightonai/LightOnOCR-3-1B}" \
    --temperature 0 --tag "${TAG:-vllm-notables}"
echo "=== done $(date) ==="
