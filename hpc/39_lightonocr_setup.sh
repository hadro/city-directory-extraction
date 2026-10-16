#!/bin/bash
# STEP 39, once, on a Torch LOGIN node (compute nodes have no network), from $PROJECT:
#
#     bash hpc/39_lightonocr_setup.sh
#
# Readies LightOnOCR-3 over the half tiles (hpc/39_lightonocr.sbatch): checks the tiles are
# unpacked, finds or installs uv, builds the job's Python environment (the bench's versions,
# pinned in hpc/lightonocr_tiles.py), downloads the model, checks an offline start, and prints
# the sbatch lines. Safe to re-run; each step skips what is already done.
#
# Everything goes under $PROJECT on /scratch: /home on Torch allows only 30K files, and torch
# alone exceeds it. hpc/39_lightonocr.sbatch sets the same UV_* paths and runs uv offline.
# MODEL=lightonai/LightOnOCR-3-4B bash hpc/39_lightonocr_setup.sh also fetches the 4B.
# ENGINE=vllm bash hpc/39_lightonocr_setup.sh also builds the batched runner's environment.
set -euo pipefail

cd "$(dirname "$0")/.."
source hpc/env.sh

export UV_CACHE_DIR="$PROJECT/uv_cache"              # same three lines in hpc/39_lightonocr.sbatch
export UV_PYTHON_INSTALL_DIR="$PROJECT/uv_python"
UV="${UV:-$(command -v uv || echo "$PROJECT/bin/uv")}"
MODEL="${MODEL:-lightonai/LightOnOCR-3-1B}"

for TASKS in data/reocr_halves/tasks.txt data/reocr_halves/bench_tasks.txt; do
  if [ ! -f "$TASKS" ]; then
    echo "no $TASKS: unpack the tiles first, here in $PWD:  tar xf cde-lightonocr-halves.tar" >&2
    exit 1
  fi
done
N=$(wc -l < data/reocr_halves/tasks.txt)
echo "=== tiles: $(find data/reocr_halves -name '*_c*_h*.jpg' | wc -l) in $N shards," \
     "plus $(cat $(cat data/reocr_halves/bench_tasks.txt) | wc -l) bench tiles"

if [ ! -x "$UV" ]; then
  echo "=== uv not found: installing it into $PROJECT/bin (Astral's installer)"
  mkdir -p "$PROJECT/bin"
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$PROJECT/bin" UV_NO_MODIFY_PATH=1 sh
  UV="$PROJECT/bin/uv"
fi
# The job looks for uv at $PROJECT/bin/uv when Slurm does not carry PATH into it, so a uv found
# elsewhere on PATH is linked there (NYU, 2026-10-15: theirs lives in /scratch/$USER/bin).
if [ ! -e "$PROJECT/bin/uv" ]; then
  mkdir -p "$PROJECT/bin"
  ln -s "$UV" "$PROJECT/bin/uv"
  echo "=== linked $PROJECT/bin/uv -> $UV, where the job looks when its PATH has no uv"
fi
echo "=== uv: $UV ($("$UV" --version))"

echo "=== building the job environment (transformers 5.19, torch 2.14; several GB, once)"
"$UV" run hpc/lightonocr_tiles.py --help > /dev/null
echo "    ok"

echo "=== downloading $MODEL into $HF_HOME (once)"
"$UV" tool run --from huggingface_hub hf download "$MODEL" > /dev/null
echo "    ok"

echo "=== checking the job can start with no network, as on a compute node"
UV_OFFLINE=1 HF_HUB_OFFLINE=1 "$UV" run hpc/lightonocr_tiles.py --help > /dev/null
echo "    ok"

if [ "${ENGINE:-hf}" = vllm ]; then
  # the batched runner's own environment (vLLM pins its own torch); built here, where there is
  # network, and checked offline as the compute node will run it
  echo "=== building the vLLM environment (hpc/lightonocr_vllm.py; several GB, once)"
  "$UV" run hpc/lightonocr_vllm.py --help > /dev/null
  UV_OFFLINE=1 HF_HUB_OFFLINE=1 "$UV" run hpc/lightonocr_vllm.py --help > /dev/null
  echo "    ok"
fi

if [ "${ENGINE:-hf}" = vllm ]; then
cat <<EOF

Ready (vLLM). GPU type for this run: $GPU_TYPE (export GPU_TYPE=l40s before 'source hpc/env.sh' to change).
First the parity run: task 0's tiles read by vLLM, to be scored beside the per-tile run's answers:
    sbatch \$(slurm_gpu_args) --export=ALL,ENGINE=vllm,TASKS=data/reocr_halves/bench_tasks.txt --array=0 hpc/39_lightonocr.sbatch
Then, once Josh has the parity scores back, a batch with ENGINE=vllm in its --export.
EOF
else
cat <<EOF

Ready. GPU type for this run: $GPU_TYPE (export GPU_TYPE=l40s before 'source hpc/env.sh' to change).
First the bench tiles, to measure seconds per tile and re-score the bench under this setup:
    sbatch \$(slurm_gpu_args) --export=ALL,TASKS=data/reocr_halves/bench_tasks.txt --array=0 hpc/39_lightonocr.sbatch
Then, once Josh has the bench scores back, the whole run:
    sbatch \$(slurm_gpu_args) --array=0-$((N - 1)) hpc/39_lightonocr.sbatch
EOF
fi
