#!/bin/bash
# STEP 1 — stage everything a compute node will need. RUN ON THE LOGIN NODE.
#
#     source hpc/env.sh && bash hpc/01_prefetch.sh
#
# WHY THIS STEP EXISTS: HPC compute nodes commonly have no general outbound internet (NYU has
# not documented Torch's policy either way — CONFIRM, but this design is safe regardless). A job that
# calls AutoModel.from_pretrained("Qwen/Qwen3.5-0.8B") will hang or fail there. So we download
# the base model into $HF_HOME (on /scratch) now, and every job script then runs with
# HF_HUB_OFFLINE=1 so a cache miss becomes a loud, immediate error instead of a silent stall.
#
# If your cluster's compute nodes DO have outbound access (or a proxy), this step is still
# worth running once — it keeps 400 concurrent jobs from re-downloading the same 2 GB.
set -euo pipefail

: "${PROJECT:?source hpc/env.sh first}"
cd "$PROJECT"

echo "=== 1/3  base model -> \$HF_HOME ==="
echo "  model:   $MODEL_ID"
echo "  cache:   $HF_HOME"
# snapshot_download grabs the whole repo, so it does not matter which auto-class loads it later.
# That matters here: Qwen3.5 is multimodal and training/eval MUST load the same class
# (AutoModelForImageTextToText) — see the eval-loader bug in docs/HANDOFF.md.
run_in_env "python -c '
from huggingface_hub import snapshot_download
p = snapshot_download(\"$MODEL_ID\")
print(f\"  cached at {p}\")
'"

echo
echo "=== 2/3  training + eval data ==="
missing=0
check() {
  if [ -f "$DATA/$1" ]; then
    printf "  ok    %-32s %s lines\n" "$1" "$(wc -l < "$DATA/$1")"
  else
    printf "  MISS  %s\n" "$1"; missing=1
  fi
}
check synth_train.jsonl
check synth_smoke.jsonl
check synth_dev.jsonl
for f in "$DATA"/*_eval.jsonl; do [ -e "$f" ] && printf "  ok    %-32s %s lines\n" "$(basename "$f")" "$(wc -l < "$f")"; done

if [ "$missing" = "1" ]; then
  echo
  echo "  Some training files are missing. Either they were left out of the bundle, or you"
  echo "  want to regenerate them here (the generator is self-contained and needs no network):"
  echo "      run_in_env \"python data_prep/synth_persons.py --profile mix --n 100000 --seed 13 \\"
  echo "                    --target yaml --out $DATA/synth_train.jsonl\""
  echo "      run_in_env \"python data_prep/synth_persons.py --profile mix --n 3000 --seed 7 \\"
  echo "                    --target yaml --out $DATA/synth_smoke.jsonl\""
fi

echo
echo "=== 3/3  prompt sanity check (no GPU, no model) ==="
# Cheapest possible confirmation that the data and the prompt builder agree — this prints the
# exact strings the model will be trained on, including the [publisher=…; year=…] context tag.
run_in_env "python train/sft_qwen.py --train-file $DATA/synth_train.jsonl --target yaml --preview-prompts 2" || true

echo
echo "OK. Next: sbatch hpc/10_smoke.sbatch   (always smoke before the full run)"
