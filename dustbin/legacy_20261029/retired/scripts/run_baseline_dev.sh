#!/usr/bin/env bash
# Baseline end to end on a few dev instances: generate, then score.
#
#   bash scripts/run_baseline_dev.sh [n_instances] [per_instance_cny]
#
# Three steps, in this order on purpose:
#   1. build the prompts and print their size, spending nothing
#   2. call the model, capped at a per-instance ceiling
#   3. hand the patches to the official harness, which is the only thing
#      allowed to decide whether they are any good
#
# Every number that comes out of step 2 and 3 is written to reports/, so the
# cost and the outcome can be quoted separately.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$HERE")"
VENV="${VENV_DIR:-/opt/swe-env}"

N="${1:-3}"
PER_INSTANCE="${2:-2.0}"
TAG="baseline_dev"

cd "$REPO" || exit 1
mkdir -p reports

if [ ! -f .env ]; then
  echo "no .env found." >&2
  echo "create $REPO/.env containing one line:" >&2
  echo "  DEEPSEEK_API_KEY=sk-..." >&2
  exit 2
fi

mapfile -t IDS < <(head -n "$N" data/frozen/instances_dev_gold_ok.txt)
echo "instances: ${IDS[*]}"
echo

echo "== 1. prompt sizes (no spend) =="
"$VENV/bin/python" scripts/run_baseline.py \
  --instances "${IDS[@]}" --dry-run \
  --per-instance-cny "$PER_INSTANCE" || exit 1

echo
echo "== 2. generate patches =="
rm -f reports/baseline_dev.jsonl
"$VENV/bin/python" scripts/run_baseline.py \
  --instances "${IDS[@]}" \
  --per-instance-cny "$PER_INSTANCE" --total-cny 6.0 \
  --tag "$TAG" || exit 1

echo
echo "== 3. score with the official harness =="
start=$(date +%s)
"$VENV/bin/python" -m swebench.harness.run_evaluation \
  --dataset_name data/harness \
  --split dev \
  --predictions_path "reports/baseline_dev.jsonl" \
  --run_id "$TAG" \
  --instance_ids "${IDS[@]}" \
  --max_workers 3 \
  --report_dir reports
rc=$?
end=$(date +%s)

echo
echo "harness exit $rc, wall clock $(( end - start ))s"
echo "report: reports/$TAG.json"
