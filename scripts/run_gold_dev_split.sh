#!/usr/bin/env bash
# Gold-patch sweep over the whole dev split (23 instances, 6 repos).
#
#   bash scripts/run_gold_dev_split.sh [run_id] [max_workers]
#
# Still no model calls: "gold" reuses the reference patch. The point is to show
# the chain works across every repository in the dev split and to measure the
# real per-instance wall clock and the on-disk image footprint, which is what
# the cost estimate needs.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$HERE")"
VENV="${VENV_DIR:-/opt/swe-env}"

RUN_ID="${1:-gold_dev_full}"
WORKERS="${2:-4}"

cd "$REPO" || exit 1
mkdir -p reports

mapfile -t IDS < data/frozen/instances_dev.txt
echo "instances: ${#IDS[@]}  workers: $WORKERS  run_id: $RUN_ID"
echo

start=$(date +%s)
"$VENV/bin/python" -m swebench.harness.run_evaluation \
  --dataset_name data/harness \
  --split dev \
  --predictions_path gold \
  --run_id "$RUN_ID" \
  --instance_ids "${IDS[@]}" \
  --max_workers "$WORKERS" \
  --report_dir reports
rc=$?
end=$(date +%s)

echo
echo "exit code: $rc   wall clock: $(( end - start ))s"
echo "report    : reports/gold.$RUN_ID.json"
docker system df
