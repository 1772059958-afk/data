#!/usr/bin/env bash
# Gold-patch sweep over the whole test split (300 instances, 12 repos).
#
#   bash scripts/run_gold_test_split.sh [run_id] [max_workers]
#
# Still no model calls: "gold" reuses the reference patch, so this costs no
# money -- only machine time. Two things come out of it:
#
#   1. the solvable ceiling. Every instance the reference patch cannot fix is
#      an image defect, and no method can score on it. Those have to be known
#      before any paid run, or the paid numbers are unreadable.
#   2. every repository image ends up on disk, so the later paid run does not
#      spend its first hour pulling.
#
# Resumable: the harness skips instances it already has results for under the
# same run_id, so re-running this command after an interruption continues
# instead of starting over.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$HERE")"
VENV="${VENV_DIR:-/opt/swe-env}"

RUN_ID="${1:-gold_test_full}"
# 16 GB RAM / 20 vCPU. Test containers install and run full package test
# suites, so this is kept below the core count to keep the box out of swap.
WORKERS="${2:-5}"

cd "$REPO" || exit 1
mkdir -p reports logs

mapfile -t IDS < data/frozen/instances_test.txt
echo "run_id: $RUN_ID   instances: ${#IDS[@]}   workers: $WORKERS"
echo "started: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo

start=$(date +%s)
"$VENV/bin/python" -m swebench.harness.run_evaluation \
  --dataset_name data/harness \
  --split test \
  --predictions_path gold \
  --run_id "$RUN_ID" \
  --instance_ids "${IDS[@]}" \
  --max_workers "$WORKERS" \
  --report_dir reports
rc=$?
end=$(date +%s)

echo
echo "exit code: $rc   wall clock: $(( end - start ))s"
echo "finished: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "report  : reports/gold.$RUN_ID.json"
docker system df
