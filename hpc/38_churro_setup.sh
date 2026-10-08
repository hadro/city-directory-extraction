#!/bin/bash
# STEP 38, once, on a Torch LOGIN node (compute nodes have no network), from $PROJECT:
#
#     bash hpc/38_churro_setup.sh
#
# Readies Churro-3B over the column crops (hpc/38_churro.sbatch): checks the crops are unpacked,
# finds or installs uv, builds the job's Python environment, downloads the model, and prints the
# sbatch lines. Safe to re-run; each step skips what is already done.
#
# Everything goes under $PROJECT on /scratch. uv's default cache and Python installs live in
# ~/.cache and ~/.local/share, and /home on Torch allows only 30K files: torch alone exceeds it.
# hpc/38_churro.sbatch sets the same UV_* paths, and runs uv offline against what this builds.
set -euo pipefail

cd "$(dirname "$0")/.."
source hpc/env.sh

export UV_CACHE_DIR="$PROJECT/uv_cache"              # same three lines in hpc/38_churro.sbatch
export UV_PYTHON_INSTALL_DIR="$PROJECT/uv_python"
UV="${UV:-$(command -v uv || echo "$PROJECT/bin/uv")}"

TASKS=data/reocr_columns/tasks.txt
if [ ! -f "$TASKS" ]; then
  echo "no $TASKS: unpack the crops first, here in $PWD:  tar xf cde-churro-columns.tar" >&2
  exit 1
fi
N=$(wc -l < "$TASKS")
echo "=== crops: $(find data/reocr_columns -name '*_c*.jpg' | wc -l) in $N shards"

if [ ! -x "$UV" ]; then
  echo "=== uv not found: installing it into $PROJECT/bin (Astral's installer)"
  mkdir -p "$PROJECT/bin"
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$PROJECT/bin" UV_NO_MODIFY_PATH=1 sh
  UV="$PROJECT/bin/uv"
fi
echo "=== uv: $UV ($("$UV" --version))"

echo "=== building the job environment (churro-ocr, torch; several GB, once)"
"$UV" run hpc/churro_columns.py --help > /dev/null
echo "    ok"

echo "=== downloading stanford-oval/churro-3B into $HF_HOME (~7.5 GB, once)"
"$UV" tool run --from huggingface_hub hf download stanford-oval/churro-3B > /dev/null
echo "    ok"

echo "=== checking the job can start with no network, as on a compute node"
UV_OFFLINE=1 HF_HUB_OFFLINE=1 "$UV" run hpc/churro_columns.py --help > /dev/null
echo "    ok"

cat <<EOF

Ready. GPU type for this run: $GPU_TYPE (export GPU_TYPE=l40s before 'source hpc/env.sh' to change).
First one shard, to measure seconds per crop (the log prints each):
    sbatch \$(slurm_gpu_args) --array=0 hpc/38_churro.sbatch
Then the rest:
    sbatch \$(slurm_gpu_args) --array=1-$((N - 1)) hpc/38_churro.sbatch
EOF
