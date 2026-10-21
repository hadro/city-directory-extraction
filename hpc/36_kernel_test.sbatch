#!/bin/bash
#SBATCH --job-name=cde-kernels
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48GB
#SBATCH --time=03:00:00
#SBATCH --gres=gpu:1
#SBATCH --output=logs/kernels-%j.out
#SBATCH --error=logs/kernels-%j.out
#
# STEP 36 -- does the 4B extractor run faster on Qwen3.5's fast-path kernels, and read the same?
# (docs/PIPELINE.md #28, "THE reocr TIER RAN": NYU's option 3, with option 2's batch A/B folded in.)
#
# Every 4B log so far says "The fast path is not available because one of the required library is
# not installed. Falling back to torch implementation": flash-linear-attention and causal-conv1d are
# not in the overlay, so Qwen3.5's linear-attention layers run in plain PyTorch. The L40S running as
# fast as an H200 (~7 rows/s) fits that. This job reads the same lines in the CURRENT overlay and in
# a COPY with the kernels, back to back on one GPU, so the node cannot confound the comparison:
#   speed   5,000 lines of brooklynnewyorkc19123broo/chunk_000 (the reocr canary chunk, job
#           20304867_0), batch 32 and 64 in each overlay
#   parity  the 17 sets of the LightOn real-OCR panel, 2,062 gold rows (job 20077014 read them),
#           in each overlay at batch 32, scored against gold on the laptop
# Greedy decoding through different kernels need not be byte-identical, so parity is judged on gold.
#
# Inputs: cde-kernel-test.tar.gz -> data/kernel_test/ (and this file). Outputs: data/kernel_test/out/.
# Nothing under data/volumes is read or written, and the production overlay is only mounted :ro.
#
# Once, on a LOGIN node (it needs the network), from $PROJECT -- copy the overlay, add the kernels:
#     source hpc/env.sh
#     cp "$OVERLAY" "$PROJECT/overlay-kernels.ext3"
#     apptainer exec --overlay "$PROJECT/overlay-kernels.ext3:rw" --bind "$PROJECT:$PROJECT" \
#         "$CONTAINER_SIF" /bin/bash -c "source /ext3/env.sh; pip install 'flash-linear-attention>=0.2.2' \
#         && pip install causal-conv1d --no-build-isolation"
# causal-conv1d fetches a prebuilt wheel matching torch/CUDA/Python, else compiles with nvcc. If it
# will not install, carry on with flash-linear-attention alone: transformers falls back one kernel at
# a time (the delta rule and gated norm are fla's, the short convolution is causal-conv1d's), so
# the warning still prints but most of the fast path is in use. The versions block says which.
# Then:
#     sbatch $(slurm_gpu_args) hpc/36_kernel_test.sbatch
#
# Back home: tar cf kernel-test-results.tar data/kernel_test/out logs/kernels-<jobid>.out
set -euo pipefail

cd "${SLURM_SUBMIT_DIR:-$PWD}"
export MODEL_SIZE=4B
source hpc/env.sh
[[ "$MODEL_ID" == *-4B ]] || { echo "MODEL_ID is $MODEL_ID: this test is for the 4B" >&2; exit 1; }

ADAPTER="${ADAPTER:-$OUT/4b-100k}"
CURRENT="$OVERLAY"
KERNELS="${KERNELS:-$PROJECT/overlay-kernels.ext3}"
T=data/kernel_test
export HF_HUB_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export PYTHONUNBUFFERED=1         # each line reaches the timestamps when printed, not at exit

[ -f "$ADAPTER/adapter_config.json" ] || { echo "no adapter at $ADAPTER" >&2; exit 1; }
[ -f "$KERNELS" ] || { echo "no $KERNELS -- copy the overlay and install the kernels first" >&2; exit 1; }
[ -f "$T/inputs.sha1" ] || { echo "no $T/inputs.sha1 -- unpack cde-kernel-test.tar.gz here" >&2; exit 1; }
(cd "$T" && sha1sum -c --quiet inputs.sha1) || { echo "the inputs do not match inputs.sha1" >&2; exit 1; }
mkdir -p "$T/out"

echo "=== kernel test | node $(hostname) | $(date) ==="
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader

cat > "$T/out/versions.py" <<'EOF'
import importlib
import torch
import transformers
print(f"  torch {torch.__version__} (CUDA {torch.version.cuda}, GPU {torch.cuda.is_available()}) "
      f"| transformers {transformers.__version__}")
for m in ("triton", "fla", "causal_conv1d"):
    try:
        print(f"  {m} {getattr(importlib.import_module(m), '__version__', '(no __version__)')}")
    except Exception as e:                                   # noqa: BLE001 - a report, not a check
        print(f"  {m}: not importable ({type(e).__name__}: {str(e)[:150]})")
try:
    from transformers.utils import import_utils as iu
    print(f"  transformers takes fla: {iu.is_flash_linear_attention_available()}, "
          f"causal-conv1d: {iu.is_causal_conv1d_available()}")
except Exception as e:                                       # noqa: BLE001
    print(f"  (could not ask transformers: {e})")
EOF
for ov in "$CURRENT" "$KERNELS"; do
    echo "--- versions in $ov"
    OVERLAY="$ov" run_in_env "python $T/out/versions.py"
done

# Each output line of a run carries the second it was printed, so decoding is timed from the
# "loaded" line, apart from the model load (and fla's first-call Triton compile counts as decoding).
stamp() { while IFS= read -r line; do echo "$(date +%s) $line"; done; }
printf 'run\tlines\tload_s\tdecode_s\trows_per_s\n' > "$T/out/summary.tsv"
run() {   # run <label> <overlay> <batch> <input>
    local label=$1 ov=$2 batch=$3 in=$4
    local out="$T/out/$label.txt" log="$T/out/$label.log" n t0 t1 tl
    n=$(grep -c . "$in")
    echo "--- $label: $n lines, batch $batch, overlay $ov"
    t0=$(date +%s)
    if ! OVERLAY="$ov" run_in_env "python eval/qwen_predict.py --base-model '$MODEL_ID' --model '$ADAPTER' \
        --gold '$in' --out '$out' --target yaml --batch-size $batch" 2>&1 | stamp > "$log"; then
        echo "    FAILED -- the last lines of $log:"
        tail -5 "$log" | cut -c12- | sed 's/^/    /'
        printf '%s\t%s\tFAILED\t\t\n' "$label" "$n" >> "$T/out/summary.tsv"
        return 0                  # the other runs still tell us something
    fi
    t1=$(date +%s)
    tl=$(awk '/ loaded /{print $1; exit}' "$log")
    tl=${tl:-$t0}
    grep -h "fast path\|loaded\|wrote" "$log" | cut -c12- | sed 's/^/    /' || true
    printf '%s\t%s\t%s\t%s\t%s\n' "$label" "$n" "$((tl - t0))" "$((t1 - tl))" \
        "$(python3 -c "print(round($n / max($t1 - $tl, 1), 2))")" >> "$T/out/summary.tsv"
    tail -1 "$T/out/summary.tsv" | sed 's/^/    /'
}

run speed.current.b32 "$CURRENT" 32 "$T/speed.jsonl"
run speed.kernels.b32 "$KERNELS" 32 "$T/speed.jsonl"
run speed.kernels.b64 "$KERNELS" 64 "$T/speed.jsonl"
run speed.current.b64 "$CURRENT" 64 "$T/speed.jsonl"
run panel.current.b32 "$CURRENT" 32 "$T/panel.jsonl"
run panel.kernels.b32 "$KERNELS" 32 "$T/panel.jsonl"

echo "=== summary (decode_s excludes the model load) ==="
column -t "$T/out/summary.tsv"
echo "=== done $(date) ==="
