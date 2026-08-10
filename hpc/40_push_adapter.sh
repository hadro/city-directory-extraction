#!/bin/bash
# STEP 40 — publish a trained adapter to the Hugging Face Hub. RUN ON THE LOGIN NODE.
#
#     source hpc/env.sh
#     export HF_TOKEN=hf_...            # a WRITE token from huggingface.co/settings/tokens
#     bash hpc/40_push_adapter.sh v6 hadro/city-dir-08b-yaml-v6
#
# Why a separate step instead of --push-to-hub during training: compute nodes have no outbound
# internet, so an in-training push would fail at the very end of a multi-hour job. Train offline,
# push from the login node. (It also avoids the partially-trained-checkpoint hazard that bit this
# project on HF Jobs, where per-epoch auto-push left a half-trained model sitting under the full
# run's name after a job was killed.)
#
# Remember: /scratch is purged after ~60 days without access. Pushing IS your backup.
set -euo pipefail

: "${PROJECT:?source hpc/env.sh first}"
RUN_NAME="${1:?usage: 40_push_adapter.sh <run-name> <hf-repo-id>}"
REPO_ID="${2:?usage: 40_push_adapter.sh <run-name> <hf-repo-id>}"
ADAPTER="$OUT/$RUN_NAME"

[ -f "$ADAPTER/adapter_config.json" ] || { echo "no adapter at $ADAPTER" >&2; exit 1; }
: "${HF_TOKEN:?export HF_TOKEN=<write token> first}"

echo "  adapter  $ADAPTER"
echo "  ->       https://huggingface.co/$REPO_ID"
du -sh "$ADAPTER"
read -r -p "push? [y/N] " ok
[ "$ok" = "y" ] || { echo "aborted"; exit 0; }

run_in_env "python -c '
from huggingface_hub import HfApi
api = HfApi(token=\"$HF_TOKEN\")
api.create_repo(\"$REPO_ID\", exist_ok=True)
api.upload_folder(
    folder_path=\"$ADAPTER\",
    repo_id=\"$REPO_ID\",
    # checkpoint-* are the mid-run resume checkpoints; the final adapter is at the top level.
    ignore_patterns=[\"checkpoint-*\", \"*.pt\", \"optimizer.pt\", \"runs/*\"],
)
print(\"pushed -> https://huggingface.co/$REPO_ID\")
'"
