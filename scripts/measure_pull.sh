#!/usr/bin/env bash
# Time an image pull and report the effective throughput.
#
#   bash scripts/measure_pull.sh <image> [log]
#
# Used to compare the mirror route against Docker Hub through the proxy.
set -uo pipefail

IMAGE="${1:?usage: measure_pull.sh <image> [log]}"
LOG="${2:-/tmp/pull_measure.log}"

echo "image: $IMAGE"
before=$(docker system df --format '{{.Type}} {{.Size}}' | awk '/Images/{print $2}')

start=$(date +%s)
if docker pull "$IMAGE" > "$LOG" 2>&1; then
  rc=0
else
  rc=$?
fi
end=$(date +%s)
elapsed=$(( end - start ))

after=$(docker system df --format '{{.Type}} {{.Size}}' | awk '/Images/{print $2}')

echo "exit code : $rc"
echo "elapsed   : ${elapsed}s"
echo "images    : $before -> $after"
tail -n 3 "$LOG"
