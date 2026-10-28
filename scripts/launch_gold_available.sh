#!/usr/bin/env bash
# Start the "evaluate whatever images we have" pass detached.
#
#   wsl -d Ubuntu -- bash /mnt/c/.../swe-repair/scripts/launch_gold_available.sh [workers]
#
# Safe to run repeatedly: each pass picks up newly downloaded images and skips
# instances that already have a result.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$HERE")"
cd "$REPO" || exit 1
mkdir -p logs

WORKERS="${1:-8}"
OUT="logs/gold_available.log"

pkill -f "run_gold_available.sh" 2>/dev/null || true
sleep 1
docker ps -aq --filter "name=sweb.eval" | xargs -r docker rm -f >/dev/null 2>&1 || true

nohup bash scripts/run_gold_available.sh gold_test_full "$WORKERS" \
  > "$OUT" 2>&1 < /dev/null &
pid=$!
disown || true

sleep 6
echo "launched pid $pid"
echo "log: $REPO/$OUT"
echo
head -8 "$OUT" 2>/dev/null
