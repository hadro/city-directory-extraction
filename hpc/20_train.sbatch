#!/bin/bash
#SBATCH --job-name=cde-train
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=12
#SBATCH --mem=64GB
#SBATCH --gres=gpu:1
#SBATCH --requeue
#SBATCH --output=logs/train-%j.out
#SBATCH --error=logs/train-%j.out
#
# STEP 20 — THE FULL FINE-TUNE. 100k synthetic examples x 3 epochs, LoRA, YAML target.
#
#     source hpc/env.sh
#     sbatch $(slurm_gpu_args) --time=$TRAIN_TIME \
#            --export=ALL,RUN_NAME=v6 hpc/20_train.sbatch
#
# RESUMPTION: --save-steps checkpoints every 500 steps and --resume-from-checkpoint auto picks
# up the latest one. Combined with #SBATCH --requeue that means a wall-clock kill or a preemption
# costs you minutes, not the whole run — resubmit the identical command and it continues.
# (Without this the trainer only checkpoints per epoch, i.e. every ~1-4 h. On a shared cluster
# with a hard --time limit that is the difference between a hiccup and a lost day.)
set -euo pipefail

cd "${SLURM_SUBMIT_DIR:-$PWD}"
source hpc/env.sh

RUN_NAME="${RUN_NAME:-hpc1}"
RUN_OUT="$OUT/$RUN_NAME"
TRAIN_FILE="${TRAIN_FILE:-$DATA/synth_train.jsonl}"

export HF_HUB_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
# OOM escape hatch, measured on this workload: YAML targets produce longer sequences than pipe
# and the full-vocab logits/entropy computation spikes memory. If you still OOM, drop BATCH_SIZE
# (and raise GRAD_ACCUM to keep the effective batch constant) rather than fiddling further.
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export HF_DEACTIVATE_ASYNC_LOAD=1

echo "=== node $(hostname) | job $SLURM_JOB_ID | $(date) ==="
echo "  run          $RUN_NAME"
echo "  train file   $TRAIN_FILE  ($(wc -l < "$TRAIN_FILE") lines)"
echo "  gpu          $GPU_TYPE (${GPU_MEM}GB)  batch $BATCH_SIZE x grad-accum $GRAD_ACCUM"
echo "  output       $RUN_OUT"
nvidia-smi

# Precision is auto-selected inside sft_qwen.py via torch.cuda.is_bf16_supported(). Every GPU on
# Torch (H200/H100/A100/L40S/RTX-Pro-6000) is Ampere-or-newer, so this is always bf16 — the
# fp16 fallback only mattered on Greene-era Turing/Volta cards. Nothing to set here.

# Called directly, NOT via srun: run_in_env is a shell function, and srun execs a binary in a
# fresh process, so `srun run_in_env ...` fails with "command not found". This is a single-node,
# single-task, single-GPU job — sbatch already runs the script on the allocated node, and
# `apptainer exec --nv` sees the GPU fine without a step launcher.
run_in_env "python train/sft_qwen.py \
    --train-file '$TRAIN_FILE' \
    --target yaml \
    --model '$MODEL_ID' \
    --output-dir '$RUN_OUT' \
    --epochs 3 \
    --batch-size $BATCH_SIZE \
    --grad-accum $GRAD_ACCUM \
    --lr 2e-4 \
    --packing \
    --save-steps 500 \
    --save-total-limit 2 \
    --resume-from-checkpoint auto"

echo
echo "=== done $(date) ==="
ls -la "$RUN_OUT"
echo
echo "Next:"
echo "  sbatch \$(slurm_gpu_args) --export=ALL,RUN_NAME=$RUN_NAME hpc/30_eval.sbatch"
echo "  # then, from the LOGIN node:  bash hpc/40_push_adapter.sh $RUN_NAME <hf-repo-id>"
