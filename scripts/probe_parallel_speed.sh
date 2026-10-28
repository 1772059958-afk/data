#!/usr/bin/env bash
# Is the proxy the bottleneck, or is Docker serialising layer downloads?
#
#   bash scripts/probe_parallel_speed.sh [streams] [megabytes]
#
# Pulls the same file over N parallel connections and reports the aggregate
# rate. If aggregate grows with N, the network has headroom and a slow
# concurrent `docker pull` is Docker's layer locking, not the link.
set -uo pipefail

N="${1:-8}"
MB="${2:-30}"
URL="https://production.cloudflare.docker.com/registry-v2/docker/registry/v2/blobs/sha256/e0/e0f8b9d70e0e0e2ff7a0e4f6d1d1f0b1c1a1d1e1f1a1b1c1d1e1f1a1b1c1d1e1/data"
# Fall back to a plain, always-available file if the CDN path 404s.
URL="https://speed.cloudflare.com/__down?bytes=$(( MB * 1000000 ))"
PROXY="http://172.30.240.1:7890"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

echo "streams: $N   size each: ${MB} MB   proxy: $PROXY"
echo

start=$(date +%s.%N)
for i in $(seq 1 "$N"); do
  curl -s -x "$PROXY" -o "$tmp/out.$i" "$URL" &
done
wait
end=$(date +%s.%N)

total=$(du -sb "$tmp" | cut -f1)
secs=$(echo "$end - $start" | bc)
echo "total downloaded: $(( total / 1000000 )) MB in ${secs}s"
echo "aggregate: $(echo "scale=1; $total / 1048576 / $secs" | bc) MB/s"
