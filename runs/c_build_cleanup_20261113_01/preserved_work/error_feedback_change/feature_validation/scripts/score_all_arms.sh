#!/usr/bin/env bash
# Offline scoring only; never calls a model. Explicit new run directory required.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$HERE")"
V="${VENV_DIR:-/opt/swe-env}/bin/python"
RUN_DIR="${1:?usage: score_all_arms.sh runs/TAG}"
cd "$REPO"
mapfile -t META < <("$V" - "$RUN_DIR/matrix.json" <<'PY'
import json,sys
m=json.load(open(sys.argv[1],encoding='utf-8'))
print(m['split'])
print(m['tag'])
print(' '.join(m['designated_instances']))
PY
)
SPLIT="${META[0]}"
TAG="${META[1]}"
read -r -a IDS <<< "${META[2]}"
mkdir -p "$RUN_DIR/scoring"
found=0
for preds in "$RUN_DIR"/predictions_*.jsonl; do
  [ -f "$preds" ] || continue
  found=1
  "$V" -m swebench.harness.run_evaluation \
    --dataset_name data/harness --split "$SPLIT" \
    --predictions_path "$preds" --instance_ids "${IDS[@]}" \
    --run_id "$TAG" --max_workers 3 --report_dir "$RUN_DIR/scoring"
done
[ "$found" = 1 ] || { echo 'No predictions files in run directory' >&2; exit 2; }
