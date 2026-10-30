#!/usr/bin/env bash
# Evaluate only the instances whose image is already on disk.
#
#   bash scripts/run_gold_available.sh [run_id] [workers]
#
# Why: the harness treats a failed pull as a finished instance, so handing it an
# instance with no local image both wastes minutes waiting for a pull to time
# out and can silently produce no result. Filtering first means the evaluation
# never touches the network at all.
#
# The run is resumable, so this can be called repeatedly as downloads land:
# instances that already produced a result are skipped.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$HERE")"
VENV="${VENV_DIR:-/opt/swe-env}"

RUN_ID="${1:-gold_test_full}"
WORKERS="${2:-8}"
SPLIT="${SPLIT:-test}"

cd "$REPO" || exit 1
mkdir -p reports logs

mapfile -t ALL < "data/frozen/instances_${SPLIT}.txt"
AVAIL=()
MISSING=0
for inst in "${ALL[@]}"; do
  img="swebench/sweb.eval.x86_64.${inst//__/_1776_}:latest"
  if docker image inspect "$img" >/dev/null 2>&1; then
    AVAIL+=("$inst")
  else
    MISSING=$(( MISSING + 1 ))
  fi
done

echo "run_id:      $RUN_ID"
echo "split:       $SPLIT"
echo "images here: ${#AVAIL[@]} / ${#ALL[@]}   (still missing: $MISSING)"
echo "workers:     $WORKERS"
echo "started:     $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo

if [ "${#AVAIL[@]}" -eq 0 ]; then
  echo "no local images for this split yet" >&2
  exit 1
fi

start=$(date +%s)
"$VENV/bin/python" -m swebench.harness.run_evaluation \
  --dataset_name data/harness \
  --split "$SPLIT" \
  --predictions_path gold \
  --run_id "$RUN_ID" \
  --instance_ids "${AVAIL[@]}" \
  --max_workers "$WORKERS" \
  --report_dir reports
rc=$?
end=$(date +%s)

echo
echo "exit code: $rc   wall clock: $(( end - start ))s"
echo "finished:  $(date -u +%Y-%m-%dT%H:%M:%SZ)"
