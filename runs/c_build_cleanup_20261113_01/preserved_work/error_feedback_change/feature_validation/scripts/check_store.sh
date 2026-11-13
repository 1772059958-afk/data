#!/usr/bin/env bash
# Where are the images actually kept, and is the store growing?
#
#   bash scripts/check_store.sh [seconds]
set -uo pipefail

# 从脚本位置推导仓库根，不要写死机器路径
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$HERE")"

SECS="${1:-60}"

echo "docker root : $(docker info --format '{{.DockerRootDir}}')"
echo "distro      : $(. /etc/os-release 2>/dev/null; echo "$PRETTY_NAME")"
echo "uptime      :$(uptime -p 2>/dev/null)"
echo

for candidate in /var/lib/containerd /var/lib/docker /data/containerd; do
  if [ -d "$candidate" ]; then
    printf 'present %-22s %s\n' "$candidate" "$(du -sh "$candidate" 2>/dev/null | cut -f1)"
  else
    printf 'absent  %-22s\n' "$candidate"
  fi
done

echo
echo "image count : $(docker images -q | wc -l)"

# With the containerd snapshotter enabled, image layers land in
# /var/lib/containerd, not under DockerRootDir (which stays at a few hundred KB).
# Measure both, so a stalled download is not confused with "nothing to do".
for root in /var/lib/containerd /var/lib/docker; do
  [ -d "$root" ] || continue
  before=$(du -sb "$root" 2>/dev/null | cut -f1)
  sleep "$SECS"
  after=$(du -sb "$root" 2>/dev/null | cut -f1)
  delta=$(( after - before ))
  echo "growth of $root over ${SECS}s: $(( delta / 1024 / 1024 )) MB  ($(( delta / 1024 / 1024 / SECS )) MB/s)"
  SECS=0
done

echo
echo "prepull running: $(ps -eo cmd | grep -c '[p]repull_images')"
echo "last prepull lines:"
tail -3 "$REPO/logs/prepull_test.log" 2>/dev/null | sed 's/^/  /'
