#!/bin/bash
#SBATCH --job-name=cde-smoke
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48GB
#SBATCH --time=01:00:00
#SBATCH --gres=gpu:1
#SBATCH --output=logs/smoke-%j.out
#SBATCH --error=logs/smoke-%j.out
#
# STEP 10 — SMOKE TEST: 3k examples, 1 epoch, ~10 minutes. ALWAYS run this first.
#
#     source hpc/env.sh && sbatch $(slurm_gpu_args) \
#         hpc/10_smoke.sbatch
#
# It proves the five things that actually break on a new cluster, in the order they break:
#   1. the GPU is visible inside the container
#   2. the base model loads from the offline cache
#   3. LoRA attaches to the hybrid Qwen3.5 layers and SKIPS the vision tower
#   4. a real training step runs and the loss moves
#   5. an adapter gets written to disk
# Costs ten minutes. The full run costs hours of queue + hours of GPU. Do not skip it.
set -euo pipefail

cd "${SLURM_SUBMIT_DIR:-$PWD}"
source hpc/env.sh

export HF_HUB_OFFLINE=1          # fail loudly on a cache miss instead of hanging on a dead network
export TOKENIZERS_PARALLELISM=false

echo "=== node $(hostname) | job $SLURM_JOB_ID | $(date) ==="
nvidia-smi || { echo "no GPU visible — check --gres and that you used 'apptainer exec --nv'" >&2; exit 1; }

echo
echo "=== dry-run: which modules get LoRA adapters? ==="
# CPU-only check. MUST print 0 visual adapters: 'all-linear' would otherwise adapt Qwen3.5's
# vision tower (half the saved tensors, wasted on a text task) AND create the train/eval
# load-class mismatch that silently zeroed out every early eval in this project.
run_in_env "python train/sft_qwen.py \
    --train-file '$DATA/synth_smoke.jsonl' --target yaml --dry-run"

echo
echo "=== smoke train: 3k x 1 epoch on $GPU_TYPE (batch $BATCH_SIZE) ==="
run_in_env "python train/sft_qwen.py \
    --train-file '$DATA/synth_smoke.jsonl' \
    --target yaml \
    --model '$MODEL_ID' \
    --output-dir '$OUT/smoke' \
    --epochs 1 \
    --batch-size $BATCH_SIZE \
    --grad-accum $GRAD_ACCUM \
    --packing"

echo
echo "=== adapter written? ==="
ls -la "$OUT/smoke" | head -20
test -f "$OUT/smoke/adapter_config.json" \
  && echo "SMOKE PASSED — adapter_config.json present. Next: sbatch hpc/20_train.sbatch" \
  || { echo "SMOKE FAILED — no adapter_config.json" >&2; exit 1; }
