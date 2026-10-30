#!/usr/bin/env bash
# Task 2: single-instance evaluation chain, gold-patch smoke test.
#
#   bash scripts/run_gold_smoke.sh [instance_id] [run_id]
#
# "gold" tells the harness to use the reference patch from the dataset, so this
# exercises build -> apply -> run tests -> grade with no model calls and no cost.
# Success means every instance is graded "resolved", which is what proves the
# chain works end to end. Runtime is dominated by the first image pull; later
# instances in the same repo reuse the cached base layers.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$HERE")"
VENV="${VENV_DIR:-/opt/swe-env}"

INSTANCE="${1:-marshmallow-code__marshmallow-1343}"
RUN_ID="${2:-smoke_dev_1}"

cd "$REPO" || exit 1

echo "instance : $INSTANCE"
echo "run_id   : $RUN_ID"
echo "dataset  : data/harness (schema v2, carries the image field)"
echo

start=$(date +%s)
"$VENV/bin/python" -m swebench.harness.run_evaluation \
  --dataset_name data/harness \
  --split dev \
  --predictions_path gold \
  --run_id "$RUN_ID" \
  --instance_ids "$INSTANCE" \
  --max_workers 1 \
  --report_dir reports
rc=$?
end=$(date +%s)

echo
echo "exit code: $rc   elapsed: $(( end - start ))s"
echo "report    : reports/$RUN_ID.json"
