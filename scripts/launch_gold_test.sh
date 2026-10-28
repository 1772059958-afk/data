#!/usr/bin/env bash
# Start the test-split gold sweep detached, so it keeps going after the
# launching shell (and the PowerShell window) goes away.
#
#   wsl -d Ubuntu -- bash /mnt/c/.../swe-repair/scripts/launch_gold_test.sh [workers]
#
# Progress:  tail -f logs/gold_test_full.log
#            python scripts/gold_progress.py --run-id gold_test_full --split test
#
# Safe to re-run: the harness skips instances it already has results for under
# this run_id, so restarting only costs the in-flight instances.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$HERE")"
cd "$REPO" || exit 1
mkdir -p logs reports

WORKERS="${1:-8}"
LOG="logs/gold_test_full.log"
pkill -f "run_gold_test_split.sh gold_test_full" 2>/dev/null || true
pkill -f "swebench.harness.run_evaluation" 2>/dev/null || true
sleep 2
# Containers left behind by the interrupted run hold RAM and do nothing.
docker ps -aq --filter "name=sweb.eval" | xargs -r docker rm -f >/dev/null 2>&1 || true

nohup bash scripts/run_gold_test_split.sh gold_test_full "$WORKERS" \
  > "$LOG" 2>&1 < /dev/null &
pid=$!
disown || true

sleep 5
echo "launched pid $pid"
echo "log: $REPO/$LOG"
echo
head -20 "$LOG" 2>/dev/null
echo "---"
ps -eo pid,etime,cmd | grep -E "run_evaluation|run_gold_test" | grep -v grep
