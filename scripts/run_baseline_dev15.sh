#!/usr/bin/env bash
# Baseline over the whole dev gold-solvable subset (15 instances), end to end.
#
#   bash scripts/run_baseline_dev15.sh
#
# Step 1 generate patches (capped, no network beyond the model API),
# step 2 score them with the official harness. Both write to reports/.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$HERE")"
VENV="${VENV_DIR:-/opt/swe-env}"
TAG="baseline_dev15"

cd "$REPO" || exit 1
mkdir -p reports

echo "== 1. generate patches (15 instances, ceiling 2.00 CNY each / 6.00 total) =="
rm -f "reports/${TAG}.jsonl" "reports/${TAG}_run.json"
"$VENV/bin/python" scripts/run_baseline.py \
  --max-tokens 16384 \
  --per-instance-cny 2.0 --total-cny 6.0 \
  --tag "$TAG" \
  --out "reports/${TAG}.jsonl" \
  --report "reports/${TAG}_run.json"
gen_rc=$?
echo "generation exit $gen_rc"

echo
echo "== 2. score with the official harness =="
start=$(date +%s)
"$VENV/bin/python" -m swebench.harness.run_evaluation \
  --dataset_name data/harness \
  --split dev \
  --predictions_path "reports/${TAG}.jsonl" \
  --run_id "$TAG" \
  --max_workers 3 \
  --report_dir reports
rc=$?
end=$(date +%s)

echo
echo "harness exit $rc, wall clock $(( end - start ))s"
echo "report: reports/${TAG}.json"
