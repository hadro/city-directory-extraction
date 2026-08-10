#!/bin/bash
#SBATCH --job-name=cde-eval
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48GB
#SBATCH --time=03:00:00
#SBATCH --gres=gpu:1
#SBATCH --output=logs/eval-%j.out
#SBATCH --error=logs/eval-%j.out
#
# STEP 30 — score a trained adapter against the full gold panel.
#
#     source hpc/env.sh
#     sbatch $(slurm_gpu_args) \
#            --export=ALL,RUN_NAME=v6 hpc/30_eval.sbatch
#
# Runs the 18-volume NYC panel (1786-1933) plus the external sets, then the scorer, then the
# pivot table. Predictions land in $DATA/preds_<run>_<set>.txt and metrics append to
# results/scores.jsonl — same layout as every previous cycle, so the numbers drop straight
# into the comparison board in docs/HANDOFF.md.
set -euo pipefail

cd "${SLURM_SUBMIT_DIR:-$PWD}"
source hpc/env.sh

RUN_NAME="${RUN_NAME:-hpc1}"
ADAPTER="${ADAPTER:-$OUT/$RUN_NAME}"

export HF_HUB_OFFLINE=1
export TOKENIZERS_PARALLELISM=false

[ -f "$ADAPTER/adapter_config.json" ] || { echo "no adapter at $ADAPTER" >&2; exit 1; }
mkdir -p results

# The 18-volume gold panel — this is the regression harness, not a sample.
PANEL="franks1786 duncan1794 mercein1820 ogden1839 doggett1846 rode1851 hearne1852
       hopehenderson1856 lain1876 boyd1890 trow1907 trow1913 polk1917 polk1925 mb1931
       polk1933bk polk1933si queens1933"
# Externals + in-distribution control. NYU is scored at --limit 500 for comparability with
# every earlier baseline (the file has 3000 rows; the published numbers are all on the first 500).
EXTERNALS="synth_dev lain tulsa minneapolis"

echo "=== node $(hostname) | job $SLURM_JOB_ID | $(date) ==="
echo "  adapter $ADAPTER"
nvidia-smi

score_one() {
  local set_name="$1" gold="$2" limit_arg="$3"
  [ -f "$gold" ] || { echo "  skip $set_name (no $gold)"; return 0; }
  local pred="$DATA/preds_${RUN_NAME}_${set_name}.txt"
  echo
  echo "--- $set_name ---"
  # --base-model is required because sft_qwen.py trains LoRA, so $ADAPTER is an adapter, not a
  # full checkpoint. qwen_predict.py loads the base as AutoModelForImageTextToText to match how
  # SFTTrainer loaded it — watch the log for that line and for the ABSENCE of any
  # "missing adapter keys" warning. That warning means the adapter silently did not apply and
  # you are scoring the bare base model.
  run_in_env "python eval/qwen_predict.py \
      --base-model '$MODEL_ID' --model '$ADAPTER' \
      --gold '$gold' --out '$pred' --target yaml \
      --batch-size 32 $limit_arg"
  run_in_env "python eval/evaluate.py \
      --gold '$gold' --pred '$pred' --target yaml \
      --save results/scores.jsonl --label 'qwen-0.8b-yaml-$RUN_NAME' " \
    || echo "  (scoring failed for $set_name)"
}

for v in $PANEL;     do score_one "$v" "$DATA/${v}_eval.jsonl" ""; done
# lain/tulsa/minneapolis are ALSO *_eval.jsonl; synth_dev is the only set without the suffix.
for v in $EXTERNALS; do
  [ "$v" = "synth_dev" ] && g="$DATA/synth_dev.jsonl" || g="$DATA/${v}_eval.jsonl"
  score_one "$v" "$g" ""
done
score_one nyu "$DATA/nyu_eval.jsonl" "--limit 500"

echo
echo "=== pivot table ==="
run_in_env "python eval/results_table.py --out results/eval_table.md"
cat results/eval_table.md

echo
echo "=== done $(date) ==="
echo "Copy results/eval_table.md + results/scores.jsonl back to your laptop:"
echo "  scp -r <netid>@<torch-login-host>:$PROJECT/results ."
