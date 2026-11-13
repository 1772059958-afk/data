#!/usr/bin/env bash
# Check whether the Windows-side proxy is usable from inside WSL, and how fast.
#
#   bash scripts/test_host_proxy.sh [proxy_url] [speedtest_url]
#
# Default proxy is the WSL gateway, which is the Windows host. If the proxy
# software has "allow LAN" on, this works and gives WSL a route to hosts that
# are otherwise blocked.
set -u

PROXY="${1:-http://172.30.240.1:7890}"
SPEED_URL="${2:-https://speed.cloudflare.com/__down?bytes=50000000}"

echo "proxy: $PROXY"
echo

echo "== reachability through the proxy =="
for h in github.com registry-1.docker.io huggingface.co auth.docker.io production.cloudflare.docker.com; do
  printf '%-38s ' "$h"
  curl -s -o /dev/null -x "$PROXY" -w '%{http_code}  %{time_total}s\n' \
       --max-time 15 "https://$h" || echo FAIL
done

echo
echo "== throughput through the proxy (50 MB) =="
curl -s -o /dev/null -x "$PROXY" --max-time 40 \
     -w 'downloaded %{size_download} bytes, %{speed_download} B/s\n' \
     "$SPEED_URL" || echo "speed test failed"

echo
echo "== throughput direct, for comparison (same URL) =="
curl -s -o /dev/null --max-time 40 \
     -w 'downloaded %{size_download} bytes, %{speed_download} B/s\n' \
     "$SPEED_URL" || echo "direct fetch failed"
