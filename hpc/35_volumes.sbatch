#!/bin/bash
#SBATCH --job-name=cde-vol
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48GB
#SBATCH --time=04:00:00
#SBATCH --gres=gpu:1
#SBATCH --output=logs/vol-%A_%a.out
#SBATCH --error=logs/vol-%A_%a.out
#
# STEP 35 -- run the release candidate over WHOLE VOLUMES, one chunk per array task.
#
#     source hpc/env.sh                     # with MODEL_SIZE=4B
#     sbatch $(slurm_gpu_args) --array=0-<N-1> hpc/35_volumes.sbatch
#
# Chunks and tasks.txt come from hpc/prep_volumes.py (run on the laptop, shipped as
# cde-volumes.tar.gz and unpacked into $DATA/volumes). Task i reads line i+1 of tasks.txt.
#
# Resumable by construction: a chunk whose prediction file already holds as many records as the
# chunk has lines is skipped, so re-submitting the same --array after a preemption or a
# wall-clock kill redoes only what is missing. Records are YAML separated by a blank line.
set -euo pipefail

cd "${SLURM_SUBMIT_DIR:-$PWD}"
source hpc/env.sh

RUN_NAME="${RUN_NAME:-4b-100k}"
ADAPTER="${ADAPTER:-$OUT/$RUN_NAME}"
BATCH="${BATCH:-32}"                      # 32 on L40S (as measured); 64 is safe on H200
VOL="$DATA/volumes"
export HF_HUB_OFFLINE=1
export TOKENIZERS_PARALLELISM=false

[ -f "$ADAPTER/adapter_config.json" ] || { echo "no adapter at $ADAPTER" >&2; exit 1; }
[ -f "$VOL/tasks.txt" ] || { echo "no $VOL/tasks.txt -- unpack cde-volumes.tar.gz" >&2; exit 1; }

i="${SLURM_ARRAY_TASK_ID:?run as an array job}"
read -r IDENT CHUNK NLINES < <(sed -n "$((i + 1))p" "$VOL/tasks.txt")
[ -n "${IDENT:-}" ] || { echo "no task $i in tasks.txt" >&2; exit 1; }
IN="$VOL/$CHUNK"
PRED="${IN%.jsonl}.preds_${RUN_NAME}.txt"

echo "=== task $i | $IDENT | $CHUNK ($NLINES lines) | node $(hostname) | $(date) ==="
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader

have=0
[ -f "$PRED" ] && have=$(python3 -c "import sys; t=open(sys.argv[1]).read().strip(); print(len(t.split('\n\n')) if t else 0)" "$PRED")
if [ "$have" -ge "$NLINES" ]; then
    echo "already complete ($have records) -- skipping"
    exit 0
fi

start=$(date +%s)
run_in_env "python eval/qwen_predict.py \
    --base-model '$MODEL_ID' --model '$ADAPTER' \
    --gold '$IN' --out '$PRED.partial' --target yaml --batch-size $BATCH"
mv "$PRED.partial" "$PRED"
secs=$(( $(date +%s) - start ))
echo "=== done: $NLINES lines in ${secs}s = $(python3 -c "print(round($NLINES/max($secs,1),2))") rows/s ==="
