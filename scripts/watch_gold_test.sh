#!/usr/bin/env bash
# Block until the test-split gold sweep finishes, printing progress on a timer.
#
#   bash scripts/watch_gold_test.sh [max_minutes]
#
# Exits as soon as reports/gold.gold_test_full.json exists, so it is safe to
# re-run: a finished sweep returns immediately.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$HERE")"
cd "$REPO" || exit 1

MAX_MIN="${1:-180}"
STEPS=$(( MAX_MIN / 3 ))
REPORT="reports/gold.gold_test_full.json"

for _ in $(seq 1 "$STEPS"); do
  if [ -f "$REPORT" ]; then
    echo "DONE: $REPORT exists"
    break
  fi
  sleep 180
  printf '=== %s ===\n' "$(date '+%H:%M:%S')"
  tail -n 1 logs/gold_test_full.log
  python3 scripts/gold_progress.py --run-id gold_test_full 2>&1 | sed -n '1,17p'
done

if [ -f "$REPORT" ]; then
  echo
  echo "final report:"
  tail -n 1 logs/gold_test_full.log
fi
