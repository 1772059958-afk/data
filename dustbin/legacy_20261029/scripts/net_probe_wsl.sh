#!/usr/bin/env bash
# Quick reachability probe from inside WSL (run via: bash scripts/net_probe_wsl.sh)
set -u
HOSTS="github.com registry-1.docker.io pypi.tuna.tsinghua.edu.cn hf-mirror.com mirror.gcr.io"
echo "--- direct ---"
for h in $HOSTS; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "https://$h" || echo FAIL)
  printf '%-34s %s\n' "$h" "$code"
done
echo "--- proxy env ---"
env | grep -i proxy || echo "(none)"
echo "--- windows host candidates ---"
for ip in 172.30.240.1 172.30.240.2 10.255.255.254; do
  timeout 2 bash -c "echo > /dev/tcp/$ip/7890" 2>/dev/null && echo "$ip:7890 OPEN" || echo "$ip:7890 closed"
done
