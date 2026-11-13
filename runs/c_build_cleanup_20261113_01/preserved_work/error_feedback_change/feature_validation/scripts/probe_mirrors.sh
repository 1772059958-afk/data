#!/usr/bin/env bash
# Compare docker registry mirrors from inside WSL: reachability and throughput.
#   bash scripts/probe_mirrors.sh
set -u
MIRRORS="docker.m.daocloud.io docker.1panel.live dockerproxy.net docker.1ms.run docker.xuanyuan.me"

echo "== registry endpoint reachability =="
for m in $MIRRORS; do
  printf '%-26s ' "$m"
  curl -s -o /dev/null -w '%{http_code}  %{time_total}s\n' --max-time 10 "https://$m/v2/" || echo FAIL
done

echo
echo "== blob throughput (100 MB from the SWE-bench base layer) =="
REPO="swebench/sweb.eval.x86_64.marshmallow-code_1776_marshmallow-1343"
for m in $MIRRORS; do
  tok=$(curl -s --max-time 12 "https://$m/token?service=registry.docker.io&scope=repository:$REPO:pull" \
        | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')
  if [[ -z "$tok" ]]; then
    printf '%-26s no token\n' "$m"
    continue
  fi
  printf '%-26s ' "$m"
  curl -s -o /dev/null --max-time 20 -H "Authorization: Bearer $tok" \
       -w 'manifest %{http_code} %{time_total}s\n' \
       "https://$m/v2/$REPO/manifests/latest" || echo FAIL
done
