#!/usr/bin/env bash
# Start the unattended overnight sweep detached.
#
#   wsl -d Ubuntu -- bash /mnt/c/.../swe-repair/scripts/launch_night_shift.sh [hours]
#
# Progress:  tail -f logs/night_shift.log
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$HERE")"
cd "$REPO" || exit 1
mkdir -p logs

HOURS="${1:-7}"

# Match the running script's own command line, not this launcher's path, which
# also contains "night_shift.sh" and would always look like a hit.
if pgrep -f "bash scripts/night_shift.sh" >/dev/null 2>&1; then
  echo "night shift already running; leaving it alone"
  exit 0
fi

nohup bash scripts/night_shift.sh "$HOURS" gold_test_full \
  > logs/night_shift_console.log 2>&1 < /dev/null &
pid=$!
disown || true

sleep 5
echo "launched night shift pid $pid for ${HOURS}h"
echo "log: $REPO/logs/night_shift.log"
echo
tail -5 logs/night_shift.log 2>/dev/null
ps -eo pid,etime,cmd | grep -E "[n]ight_shift|[r]un_evaluation" | head -3
