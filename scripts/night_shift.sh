#!/usr/bin/env bash
# Run the test-split gold sweep unattended, making progress with whatever is
# available at any moment.
#
#   bash scripts/night_shift.sh [hours] [run_id]
#
# The download link is slow and unpredictable, and pulling inside the harness
# turns a slow link into silently missing results. So the two are decoupled:
# this loop keeps the pre-pull alive, periodically evaluates every instance
# whose image has landed, and stops when the split is covered or time runs out.
# Both halves are idempotent, so being interrupted costs nothing but the pass
# that was in flight.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$HERE")"
cd "$REPO" || exit 1
mkdir -p logs reports

HOURS="${1:-7}"
RUN_ID="${2:-gold_test_full}"
SPLIT="${SPLIT:-test}"
PASS_GAP="${PASS_GAP:-1200}"     # seconds between evaluation passes
LOG="logs/night_shift.log"
DEADLINE=$(( $(date +%s) + HOURS * 3600 ))

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }

count_results() {
  local dir="logs/run_evaluation/${RUN_ID}/gold"
  [ -d "$dir" ] || { echo 0; return; }
  find "$dir" -name report.json 2>/dev/null | wc -l
}

total=$(wc -l < "data/frozen/instances_${SPLIT}.txt")
log "night shift start: $SPLIT, $total instances, run_id $RUN_ID, budget ${HOURS}h"
log "results so far: $(count_results)"

while [ "$(date +%s)" -lt "$DEADLINE" ]; do
  if ! pgrep -f "prepull_images.sh $SPLIT" >/dev/null 2>&1; then
    log "pre-pull not running; restarting it"
    nohup bash scripts/prepull_images.sh "$SPLIT" 6 4 \
      >> "logs/prepull_console.log" 2>&1 < /dev/null &
    disown || true
    sleep 10
  fi

  have=$(count_results)
  if [ "$have" -ge "$total" ]; then
    log "all $total instances have a result; stopping"
    break
  fi

  log "evaluation pass (results so far: $have / $total)"
  bash scripts/run_gold_available.sh "$RUN_ID" 8 >> "$LOG" 2>&1
  log "pass done (exit $?), results now: $(count_results)"

  # Downloading continues in parallel; give it time to land more images.
  slept=0
  while [ "$slept" -lt "$PASS_GAP" ] && [ "$(date +%s)" -lt "$DEADLINE" ]; do
    sleep 60
    slept=$(( slept + 60 ))
  done
done

log "night shift finished: $(count_results) / $total instances have results"
docker images -q | wc -l | xargs -I{} log "images on disk: {}"
