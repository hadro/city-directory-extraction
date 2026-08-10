#!/bin/bash
# STEP 0 — build the Python environment. RUN ON THE LOGIN NODE (it needs internet).
#
#     cd $PROJECT && source hpc/env.sh && bash hpc/00_setup_env.sh
#
# Two modes, chosen by USE_CONTAINER in env.sh:
#
#   USE_CONTAINER=1 (default, the NYU-recommended pattern)
#       Copies a public ext3 overlay image from /share/apps/overlay-fs-ext3/, installs miniconda
#       + all deps INSIDE it, and writes /ext3/env.sh as the activation hook. The whole ~150k-file
#       dependency tree then lives in ONE file on /scratch — which is the point: /home allows only
#       30K inodes and a naive `pip install torch` exceeds that by itself. NYU documents this
#       exact pattern ("Singularity with Conda" in the Torch container docs).
#
#   USE_CONTAINER=0
#       Plain `python -m venv`. Simpler, portable to clusters without the inode pressure.
#
# ALTERNATIVE worth knowing: NYU also documents "Apptainer with uv", installing uv into the same
# overlay (UV_INSTALL_DIR=/ext3/.uv, UV_PROJECT_ENVIRONMENT=/ext3/.venv). Because every script in
# this repo carries PEP-723 inline dependency metadata, `uv run train/sft_qwen.py ...` would
# resolve deps with no requirements.txt at all. Not used here only because the conda path is what
# this bundle was tested against — switch if you prefer uv.
#
# Idempotent: re-running upgrades packages in place rather than rebuilding from scratch.
set -euo pipefail

: "${PROJECT:?source hpc/env.sh first}"
cd "$PROJECT"
REQ="$PROJECT/hpc/requirements.txt"
[ -f "$REQ" ] || { echo "missing $REQ — did you unpack the bundle into \$PROJECT?" >&2; exit 1; }

# CUDA 12 wheels. If your cluster's driver is older, change this to cu118 and re-run.
TORCH_INDEX="${TORCH_INDEX:-https://download.pytorch.org/whl/cu121}"

if [ "$USE_CONTAINER" = "1" ]; then
  echo "=== container mode: apptainer + ext3 overlay ==="
  [ -f "$CONTAINER_SIF" ] || { echo "no image at $CONTAINER_SIF — check 'ls /share/apps/images/'" >&2; exit 1; }

  if [ ! -f "$OVERLAY" ]; then
    echo "--- copying overlay from $OVERLAY_SRC (a few minutes) ---"
    [ -f "$OVERLAY_SRC" ] || { echo "no overlay at $OVERLAY_SRC — check 'ls /share/apps/overlay-fs-ext3/'" >&2; exit 1; }
    cp "$OVERLAY_SRC" "$PROJECT/"
    gunzip "$PROJECT/$(basename "$OVERLAY_SRC")"
    mv "$PROJECT/$(basename "${OVERLAY_SRC%.gz}")" "$OVERLAY"
  else
    echo "--- overlay already at $OVERLAY (reusing) ---"
  fi

  # NOTE: :rw here. Every LATER use mounts it :ro (see run_in_env in env.sh) so that concurrent
  # jobs can share one overlay — an ext3 overlay may be writable by only one process at a time.
  echo "--- installing into the overlay (writable mount) ---"
  "$APPTAINER_BIN" exec --overlay "$OVERLAY:rw" --bind "$PROJECT:$PROJECT" "$CONTAINER_SIF" /bin/bash <<INNER
set -euo pipefail
if [ ! -d /ext3/miniconda3 ]; then
  echo "  installing miniconda into the overlay..."
  curl -sSL https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -o /tmp/mc.sh
  bash /tmp/mc.sh -b -p /ext3/miniconda3
  rm /tmp/mc.sh
fi

# The activation hook run_in_env sources on every later invocation.
cat > /ext3/env.sh <<'HOOK'
#!/bin/bash
export PATH=/ext3/miniconda3/bin:\$PATH
source /ext3/miniconda3/etc/profile.d/conda.sh
conda activate
HOOK
chmod +x /ext3/env.sh
source /ext3/env.sh

python -m pip install --upgrade pip
echo "  installing torch from $TORCH_INDEX ..."
python -m pip install --index-url "$TORCH_INDEX" torch
echo "  installing the rest ..."
python -m pip install -r "$REQ"
INNER

else
  echo "=== venv mode ==="
  module load python/intel/3.8.6 2>/dev/null || module load anaconda3/2024.02 2>/dev/null || true
  [ -d "$VENV" ] || python3 -m venv "$VENV"
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
  python -m pip install --upgrade pip
  python -m pip install --index-url "$TORCH_INDEX" torch
  python -m pip install -r "$REQ"
fi

echo
echo "--- verifying ---"
run_in_env "python -c '
import torch, transformers, trl, peft
print(f\"  torch        {torch.__version__}\")
print(f\"  transformers {transformers.__version__}\")
print(f\"  trl          {trl.__version__}\")
print(f\"  peft         {peft.__version__}\")
print(f\"  cuda compiled for: {torch.version.cuda}\")
print(\"  NOTE: torch.cuda.is_available() is False on a login node — that is expected.\")
print(f\"  cuda visible here: {torch.cuda.is_available()}\")
'"

echo
echo "OK. Next: bash hpc/01_prefetch.sh"
