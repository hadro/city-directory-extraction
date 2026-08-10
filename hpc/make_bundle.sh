#!/bin/bash
# Build the self-contained HPC bundle. RUN ON YOUR LAPTOP, from the repo root:
#
#     bash hpc/make_bundle.sh
#     scp cde-hpc-bundle-*.tar.gz <netid>@<torch-login-host>:/scratch/<netid>/
#
# Produces ONE tarball (~6 MB) holding the training scripts, the eval harness, the synthetic
# training data, the full gold panel, and the docs. Nothing else is needed on the cluster except
# the base model, which hpc/01_prefetch.sh downloads there.
#
#   --no-data     scripts + docs only (~1 MB) — for when the data goes over separately, or when
#                 you'd rather regenerate it on the cluster with synth_persons.py
#   --no-gold     omit the gold eval sets. USE THIS IF LICENSING REQUIRES IT: the NYU gold is
#                 CC-BY-SA-NC and the panel gold is hand-labeled from library scans. Both are
#                 gitignored in this repo on purpose. Check before handing the tarball to anyone
#                 outside the project.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$PWD"
STAMP="$(git log -1 --format=%h 2>/dev/null || echo nogit)"
NAME="cde-hpc-bundle-$STAMP"
STAGE="$(mktemp -d)/$NAME"

WITH_DATA=1
WITH_GOLD=1
for a in "$@"; do
  case "$a" in
    --no-data) WITH_DATA=0 ;;
    --no-gold) WITH_GOLD=0 ;;
    *) echo "unknown flag: $a" >&2; exit 1 ;;
  esac
done

mkdir -p "$STAGE"/{hpc,train,eval,data_prep/names,data,docs,results}

echo "=== staging scripts ==="
cp hpc/*.sh hpc/*.sbatch hpc/*.py hpc/requirements.txt hpc/README.md "$STAGE/hpc/"
cp train/sft_qwen.py                    "$STAGE/train/"
cp eval/qwen_predict.py eval/evaluate.py eval/results_table.py "$STAGE/eval/"
cp data_prep/synth_persons.py           "$STAGE/data_prep/"
cp data_prep/names/*.tsv                "$STAGE/data_prep/names/"
cp docs/HANDOFF.md docs/TRAINING_OPTIONS.md "$STAGE/docs/" 2>/dev/null || true
cp README.md                            "$STAGE/REPO_README.md"
cp cards/MODEL_CARD.md cards/DATASET_CARD.md "$STAGE/docs/" 2>/dev/null || true

if [ "$WITH_DATA" = "1" ]; then
  echo "=== staging training data ==="
  for f in synth_train.jsonl synth_smoke.jsonl synth_dev.jsonl; do
    [ -f "data/$f" ] && cp "data/$f" "$STAGE/data/" && echo "  $f ($(wc -l < "data/$f") lines)"
  done
fi

if [ "$WITH_GOLD" = "1" ]; then
  echo "=== staging gold eval sets ==="
  n=0
  for f in data/*_eval.jsonl; do
    [ -e "$f" ] || continue
    cp "$f" "$STAGE/data/"; n=$((n+1))
  done
  echo "  $n gold sets"
  cat > "$STAGE/data/LICENSE_NOTE.txt" <<'EOF'
The gold evaluation sets in this directory are NOT under the repository's code license.

  nyu_eval.jsonl        derived from NYU's 1850 directory transcription — CC-BY-SA-NC
  ftd_eval.jsonl        French Trade Directories (SODUCO)
  minneapolis_eval.jsonl  adamrangwala/DirCity, MIT
  *_eval.jsonl (panel)  hand-labeled by this project from library page scans
                        (NYPL / Internet Archive / LoC), one gold set per volume

Use them for evaluation within this project. Check the terms before redistributing.
EOF
else
  echo "=== gold eval sets OMITTED (--no-gold) ==="
fi

echo "=== packing ==="
( cd "$(dirname "$STAGE")" && tar czf "$ROOT/$NAME.tar.gz" "$NAME" )
rm -rf "$(dirname "$STAGE")"

echo
echo "built  $ROOT/$NAME.tar.gz  ($(du -h "$ROOT/$NAME.tar.gz" | cut -f1))"
echo
echo "Ship it:"
echo "  scp $NAME.tar.gz <netid>@<torch-login-host>:/scratch/<netid>/"
echo "  ssh <netid>@<torch-login-host>"
echo "  cd /scratch/\$USER && tar xzf $NAME.tar.gz && mv $NAME city-directory-extraction"
echo "  cd city-directory-extraction && cat hpc/README.md"
