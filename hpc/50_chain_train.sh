#!/bin/bash
# STEP 50 — submit a multi-day run as a CHAIN of dependent jobs. RUN ON THE LOGIN NODE.
#
#     source hpc/env.sh
#     bash hpc/50_chain_train.sh 4 v6-4b
#
# WHY: clusters cap wall-clock per job (Torch documents a 24-GPU-per-user quota for jobs under
# 48 h, so treat 48 h as the planning boundary — CONFIRM YOUR ACTUAL LIMIT with
# `sinfo -o "%P %l"` or your admins). The 500k family runs exceed that:
#
#     python3 hpc/estimate_run.py --n 500000        # hours + required job count per config
#
# e.g. 4B/500k on an L40S is ~181 GPU-hours = 4 chained jobs (on an H200 it is ~42 h = ONE job,
# so check the estimator before assuming you need a chain at all). This script submits N jobs
# where each waits on the previous one with --dependency=afterany, so job k+1 starts whether
# job k finished, timed out, or was preempted. Because 20_train.sbatch passes
# --resume-from-checkpoint auto, each link picks up from the last 500-step checkpoint. The
# chain self-terminates: once training completes, the remaining links resume a finished run
# and exit in minutes.
#
# afterany (not afterok) is deliberate — a wall-clock kill is a NON-ZERO exit, and that is
# exactly the case we need the next link to handle.
set -euo pipefail

: "${PROJECT:?source hpc/env.sh first}"
N_JOBS="${1:?usage: 50_chain_train.sh <n-jobs> <run-name>}"
RUN_NAME="${2:?usage: 50_chain_train.sh <n-jobs> <run-name>}"

cd "$PROJECT"
mkdir -p logs

echo "chaining $N_JOBS x $TRAIN_TIME jobs for run '$RUN_NAME'"
echo "  model    $MODEL_ID   (size $MODEL_SIZE)"
echo "  gpu      $GPU_TYPE (${GPU_MEM}GB), batch $BATCH_SIZE x accum $GRAD_ACCUM"
echo "  output   $OUT/$RUN_NAME"
echo

prev=""
for i in $(seq 1 "$N_JOBS"); do
  dep=""
  [ -n "$prev" ] && dep="--dependency=afterany:$prev"
  # shellcheck disable=SC2046
  id=$(sbatch --parsable $(slurm_gpu_args) $dep \
        --time="$TRAIN_TIME" \
        --job-name="cde-${RUN_NAME}-${i}" \
        --export=ALL,RUN_NAME="$RUN_NAME" \
        hpc/20_train.sbatch)
  echo "  link $i/$N_JOBS: job $id${prev:+  (after $prev)}"
  prev="$id"
done

echo
echo "watch:   squeue -u \$USER"
echo "cancel:  scancel --name=cde-$RUN_NAME-1 ... or  scancel -u \$USER"
echo "logs:    tail -f $PROJECT/logs/train-*.out"
echo
echo "When the chain finishes, any leftover links exit immediately (nothing left to train)."
echo "Then:  sbatch \$(slurm_gpu_args) --export=ALL,RUN_NAME=$RUN_NAME hpc/30_eval.sbatch"
