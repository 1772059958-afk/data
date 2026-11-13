#!/usr/bin/env bash
# Start the image pre-pull detached, so it keeps going after this shell exits.
#
#   wsl -d Ubuntu -- bash /mnt/c/.../swe-repair/scripts/launch_prepull.sh [split] [jobs]
#
# Progress:  tail -f logs/prepull_console.log
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$HERE")"
cd "$REPO" || exit 1
mkdir -p logs

SPLIT="${1:-test}"
JOBS="${2:-4}"
OUT="logs/prepull_console.log"

pkill -f "prepull_images.sh $SPLIT" 2>/dev/null || true
sleep 1

nohup bash scripts/prepull_images.sh "$SPLIT" "$JOBS" 4 \
  > "$OUT" 2>&1 < /dev/null &
pid=$!
disown || true

sleep 5
echo "launched pid $pid"
echo "log: $REPO/$OUT"
echo
head -12 "$OUT" 2>/dev/null
echo "---"
tail -3 "$OUT" 2>/dev/null
ps -eo pid,etime,cmd | grep -E "[p]repull_images" | head -3
