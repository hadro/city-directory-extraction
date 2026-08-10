#!/bin/bash
# Shared configuration for the NYU-HPC city-directory fine-tune.
# Sourced by every 0*/1*/2*/3*/4*/5* script here. Edit the top block, nothing else.
#
#   source hpc/env.sh
#
# TARGET CLUSTER: **NYU Torch** (services.rt.nyu.edu/docs/hpc/). Torch replaced Greene, which
# was decommissioned 2026-01-30. If you find yourself reading Greene-era docs or blog posts,
# the things that changed and matter here are: Apptainer (not Singularity), images under
# /share/apps (not /scratch/work/public), a MANDATORY --account, and GPU selection via
# --constraint rather than a typed --gres.
#
# Everything lives under $PROJECT on /scratch — NEVER /home. /home is 50 GB but only **30K
# inodes**, and a single pip install of torch blows through that on its own. /scratch is
# 5 TB / 5M files but is PURGED after 60 days without access, so treat it as working space and
# push results to the Hub (step 40). Check with `myquota`.

# ---- edit these ------------------------------------------------------------------------
PROJECT="${PROJECT:-/scratch/$USER/city-directory-extraction}"

# Model size. 0.8B is the workhorse; 2B/4B are the family scale-up (see hpc/README.md
# "Scaling to 2B and 4B" and `python3 hpc/estimate_run.py` for hours/VRAM/jobs at each).
MODEL_SIZE="${MODEL_SIZE:-0.8B}"
MODEL_ID="${MODEL_ID:-Qwen/Qwen3.5-$MODEL_SIZE}"

# REQUIRED on Torch — an active allocation is needed to submit any job. Find yours with:
#     my_slurm_accounts
SLURM_ACCOUNT="${SLURM_ACCOUNT:-}"

# GPU to target, selected via --constraint. Torch inventory (from the spec sheet):
#   h200          141 GB   232 GPUs   fastest AND biggest — 4B/500k fits one 48h job
#   l40s           48 GB   272 GPUs   most numerous; slowest here (bandwidth-bound)
#   a100           80 GB   172 GPUs   the measured baseline (some nodes may be 40 GB — verify)
#   h100           80 GB    60 GPUs
#   rtx-pro-6000   96 GB    16 GPUs   the exact card our $6 reference run was measured on
# Availability vs speed is the real trade — see hpc/README.md.
GPU_TYPE="${GPU_TYPE:-h200}"

# Container mode. 1 = Apptainer + ext3 overlay (the NYU-recommended pattern; keeps the ~150k
# dependency files inside ONE file, so you never hit the inode quota).
# 0 = plain python venv (simpler; fine on clusters without the inode pressure).
USE_CONTAINER="${USE_CONTAINER:-1}"

# Torch public images/overlays. Verify before your first run:
#   ls /share/apps/images/ | grep -i cuda
#   ls /share/apps/overlay-fs-ext3/
CONTAINER_SIF="${CONTAINER_SIF:-/share/apps/images/cuda12.1.1-cudnn8.9.0-devel-ubuntu22.04.2.sif}"
OVERLAY_SRC="${OVERLAY_SRC:-/share/apps/overlay-fs-ext3/overlay-15GB-500K.ext3.gz}"

# Apptainer is the continuation of Singularity; Torch ships only `apptainer`. Older clusters
# may still have `singularity` — this falls back automatically.
APPTAINER_BIN="${APPTAINER_BIN:-$(command -v apptainer || command -v singularity || echo apptainer)}"
# ---- end edit --------------------------------------------------------------------------

export PROJECT MODEL_SIZE MODEL_ID GPU_TYPE USE_CONTAINER CONTAINER_SIF OVERLAY_SRC APPTAINER_BIN

export OVERLAY="$PROJECT/overlay-15GB-500K.ext3"
export VENV="$PROJECT/venv"                 # used when USE_CONTAINER=0
export DATA="$PROJECT/data"
export OUT="$PROJECT/out"
export LOGS="$PROJECT/logs"

# Keep every cache on /scratch. The HF default is ~/.cache/huggingface, which is exactly the
# inode trap described above.
export HF_HOME="$PROJECT/hf_cache"
export HF_DATASETS_CACHE="$HF_HOME/datasets"
export TRANSFORMERS_CACHE="$HF_HOME/hub"
export TORCH_HOME="$PROJECT/torch_cache"
export TRITON_CACHE_DIR="$PROJECT/triton_cache"

# GPU VRAM (GB).
case "$GPU_TYPE" in
  h200)         GPU_MEM=141 ;;
  rtx-pro-6000) GPU_MEM=96 ;;
  a100|h100)    GPU_MEM=80 ;;
  l40s)         GPU_MEM=48 ;;
  *)            GPU_MEM=0; echo "env.sh: unknown GPU_TYPE '$GPU_TYPE' (expected h200|h100|a100|l40s|rtx-pro-6000)" >&2 ;;
esac
export GPU_MEM

# Training shape per (model size x GPU). Effective batch is held at 64 everywhere via grad-accum,
# so a smaller card changes throughput but NOT the optimization trajectory — that keeps the
# family runs comparable to the 0.8B board in docs/HANDOFF.md.
#
# Batch numbers come from hpc/estimate_run.py, whose VRAM model is calibrated against the one
# config we have actually run (0.8B @ batch 64 on an 80 GB A100). The key non-obvious fact: the
# [batch x 512 x 248320] logits tensor dominates memory and does NOT scale with model size, so
# 4B needs barely more VRAM than 2B. Batch, not parameters, sets the wall.
#   python3 hpc/estimate_run.py --size 4B --gpu h200     # hours + VRAM + chained-job count
case "${MODEL_SIZE}-${GPU_TYPE}" in
  0.8B-h200|0.8B-h100|0.8B-a100|0.8B-rtx-pro-6000) _B=64; _T="12:00:00" ;;
  0.8B-l40s)                                       _B=32; _T="36:00:00" ;;
  2B-h200)                                         _B=64; _T="30:00:00" ;;
  2B-h100|2B-a100|2B-rtx-pro-6000)                 _B=32; _T="48:00:00" ;;
  2B-l40s)                                         _B=16; _T="48:00:00" ;;
  4B-h200)                                         _B=64; _T="48:00:00" ;;
  4B-h100|4B-a100|4B-rtx-pro-6000)                 _B=32; _T="48:00:00" ;;
  4B-l40s)                                         _B=16; _T="48:00:00" ;;
  *)                                               _B=16; _T="24:00:00"
                                                   echo "env.sh: no tuned shape for ${MODEL_SIZE}/${GPU_TYPE}; using conservative batch $_B" >&2 ;;
esac
export BATCH_SIZE="${BATCH_SIZE:-$_B}"
export GRAD_ACCUM="${GRAD_ACCUM:-$(( 64 / _B < 1 ? 1 : 64 / _B ))}"
export TRAIN_TIME="${TRAIN_TIME:-$_T}"
unset _B _T

# run_in_env <shell command string> — execute inside the container (or venv), with the
# dependency environment activated. Every job script funnels through this.
run_in_env() {
  if [ "$USE_CONTAINER" = "1" ]; then
    "$APPTAINER_BIN" exec --nv \
      --overlay "$OVERLAY:ro" \
      --bind "$PROJECT:$PROJECT" \
      "$CONTAINER_SIF" \
      /bin/bash -c "source /ext3/env.sh; $*"
  else
    /bin/bash -c "source $VENV/bin/activate; $*"
  fi
}
# `export -f` is a bashism. Guard it so sourcing this from zsh doesn't abort the file under -e.
export -f run_in_env 2>/dev/null || true

# SLURM flags every submission needs. On Torch the account is MANDATORY, and GPU type is chosen
# with --constraint (NOT the Greene-era `--gres=gpu:<type>:1`, which Torch does not accept).
# Partitions are deliberately NOT set: Torch's docs say do not specify them manually — QoS on
# your account controls access, and naming one is how you land in the wrong queue.
slurm_gpu_args() {
  local a=("--gres=gpu:1" "--constraint=$GPU_TYPE")
  [ -n "$SLURM_ACCOUNT" ] && a+=("--account=$SLURM_ACCOUNT")
  echo "${a[@]}"
}

if [ -z "$SLURM_ACCOUNT" ] && command -v my_slurm_accounts >/dev/null 2>&1; then
  echo "env.sh: SLURM_ACCOUNT is unset and Torch requires --account." >&2
  echo "        Your accounts:" >&2
  my_slurm_accounts 2>/dev/null | sed 's/^/          /' >&2
  echo "        Set SLURM_ACCOUNT in hpc/env.sh before submitting." >&2
fi

mkdir -p "$PROJECT" "$DATA" "$OUT" "$LOGS" "$HF_HOME"
