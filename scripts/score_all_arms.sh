#!/usr/bin/env bash
# Score each arm separately. The harness handles one model per invocation in
# practice, so a multi-model file leaves all but the first unscored.
set -u
V=/opt/swe-env/bin/python
REPO=/mnt/c/Users/MECH/Documents/Codex/2026-10-15/z/swe-repair
TAG=${1:-cf_dev4}
cd "$REPO" || exit 1

for arm in A B C D E ESC; do
  preds="reports/${TAG}_${arm}.jsonl"
  [ -f "$preds" ] || { echo "skip $arm (no file)"; continue; }
  echo "== scoring $arm =="
  "$V" -m swebench.harness.run_evaluation \
    --dataset_name data/harness \
    --split dev \
    --predictions_path "$preds" \
    --run_id "$TAG" \
    --max_workers 3 \
    --report_dir reports 2>&1 | grep -E "Instances (submitted|completed|resolved|unresolved|with empty)|Report written" || true
done
echo "== reports =="
ls -1 reports/ | grep -E "^${TAG}-" || true
