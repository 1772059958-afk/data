#!/usr/bin/env bash
# Download every instance image before the evaluation run, with retries.
#
#   bash scripts/prepull_images.sh test [jobs] [attempts]
#
# Why this exists
# ---------------
# The first test-split run died on flaky pulls: 47 instances failed with
# "connection aborted" and 11 with "500 Server Error" from the registry, all
# *during* the run. The harness treats a failed pull as a finished instance, so
# those runs produce no result and you have to notice the hole yourself.
#
# Pulling is also the only part of the pipeline that touches the network, and
# the only part that can fail transiently. So do it separately: pull everything
# here with retries, and let the evaluation run afterwards find every image
# already on disk. A network hiccup then costs one retry instead of a silent
# missing result.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$HERE")"
cd "$REPO" || exit 1

SPLIT="${1:-test}"
JOBS="${2:-4}"
ATTEMPTS="${3:-4}"
LOG="logs/prepull_${SPLIT}.log"

mkdir -p logs

mapfile -t INSTANCES < "data/frozen/instances_${SPLIT}.txt"
if [ "${#INSTANCES[@]}" -eq 0 ]; then
  echo "no instances in data/frozen/instances_${SPLIT}.txt" >&2
  exit 1
fi

IMAGES=()
for inst in "${INSTANCES[@]}"; do
  IMAGES+=("swebench/sweb.eval.x86_64.${inst//__/_1776_}:latest")
done

echo "split:    $SPLIT (${#IMAGES[@]} images)"
echo "jobs:     $JOBS    attempts: $ATTEMPTS"
echo "log:      $LOG"
echo "started:  $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo

pull_one() {
  local img="$1" attempt
  local name="${img##*/}"
  local tag="${name%:latest}"

  if docker image inspect "$img" >/dev/null 2>&1; then
    echo "have    $tag"
    return 0
  fi

  for attempt in $(seq 1 "$ATTEMPTS"); do
    # -q keeps the output to one line per layer set; failures still surface.
    if docker pull -q "$img" >/dev/null 2>&1; then
      echo "pulled  $tag"
      return 0
    fi
    echo "retry   $tag (attempt $attempt of $ATTEMPTS failed)"
    sleep $(( attempt * 15 ))
  done

  echo "FAILED  $tag"
  return 1
}

export -f pull_one
export ATTEMPTS

start=$(date +%s)
printf '%s\n' "${IMAGES[@]}" \
  | xargs -P "$JOBS" -I{} bash -c 'pull_one "$@"' _ {} \
  | tee "$LOG"
rc=${PIPESTATUS[0]}
end=$(date +%s)

echo
echo "=== summary ==="
echo "have:   $(grep -c '^have' "$LOG" 2>/dev/null || echo 0)"
echo "pulled: $(grep -c '^pulled' "$LOG" 2>/dev/null || echo 0)"
echo "failed: $(grep -c '^FAILED' "$LOG" 2>/dev/null || echo 0)"
echo "wall clock: $(( end - start ))s"

if grep -q '^FAILED' "$LOG" 2>/dev/null; then
  echo
  echo "still missing:"
  grep '^FAILED' "$LOG" | sed 's/^FAILED  /  /'
  echo
  echo "re-run this script to retry just those."
  exit 1
fi

echo "all images present"
