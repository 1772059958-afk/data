#!/usr/bin/env bash
# Rough download-rate sample: how fast is the image store growing?
#
#   bash scripts/pull_rate.sh [seconds]
set -uo pipefail

SECS="${1:-60}"
store=/var/lib/containerd

before=$(du -sb "$store" 2>/dev/null | cut -f1)
sleep "$SECS"
after=$(du -sb "$store" 2>/dev/null | cut -f1)

delta=$(( after - before ))
echo "store        $store"
echo "before       $before bytes"
echo "after        $after bytes"
echo "growth       $delta bytes in ${SECS}s  =  $(( delta / 1024 / 1024 )) MB/min"
echo
echo "images finished so far: $(docker images -q | wc -l)"
echo "repos:"
docker images --format '  {{.Repository}}' | sed 's/swebench\/sweb.eval.x86_64.//' | cut -d_ -f1 | sort | uniq -c
echo
echo "active pulls (dockerd connections):"
ss -tnp 2>/dev/null | grep -c dockerd || echo 0
