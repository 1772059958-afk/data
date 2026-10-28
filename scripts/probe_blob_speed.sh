#!/usr/bin/env bash
# Measure real blob throughput for one instance image across candidate mirrors.
#   bash scripts/probe_blob_speed.sh [mirror ...]
set -u
REPO="swebench/sweb.eval.x86_64.marshmallow-code_1776_marshmallow-1343"
MIRRORS="${*:-docker.m.daocloud.io docker.1panel.live dockerproxy.net docker.1ms.run docker.xuanyuan.me}"

for m in $MIRRORS; do
  echo "== $m =="
  tok=$(curl -s --max-time 12 "https://$m/token?service=registry.docker.io&scope=repository:$REPO:pull" \
        | tr ',' '\n' | sed -n 's/.*"token":"\([^"]*\)".*/\1/p' | head -1)
  if [[ -z "${tok:-}" ]]; then
    echo "   token endpoint gave nothing; trying anonymous manifest fetch"
    hdr=""
  else
    hdr="Authorization: Bearer $tok"
    echo "   token ok (${#tok} chars)"
  fi

  man=$(curl -s --max-time 20 ${hdr:+-H "$hdr"} \
        -H 'Accept: application/vnd.docker.distribution.manifest.v2+json' \
        "https://$m/v2/$REPO/manifests/latest")
  if ! grep -q '"layers"' <<<"$man"; then
    echo "   manifest fetch failed: $(head -c 120 <<<"$man")"
    continue
  fi

  # biggest layer digest + size
  big=$(tr '}' '\n' <<<"$man" | grep '"size"' | sed -n 's/.*"size":\([0-9]*\).*"digest":"\(sha256:[0-9a-f]*\)".*/\1 \2/p' | sort -rn | head -1)
  if [[ -z "$big" ]]; then
    big=$(tr '}' '\n' <<<"$man" | grep '"digest"' | sed -n 's/.*"size":\([0-9]*\).*/\1/p' | sort -rn | head -1)
    digest=$(tr '}' '\n' <<<"$man" | grep '"sha256:' | sed -n 's/.*"digest":"\(sha256:[0-9a-f]*\)".*/\1/p' | head -1)
    size=$big
  else
    size=${big%% *}; digest=${big##* }
  fi
  echo "   largest layer: ${size} bytes  $digest"

  out=$(curl -s -o /dev/null --max-time 15 ${hdr:+-H "$hdr"} \
        -w '%{size_download} %{speed_download}' \
        "https://$m/v2/$REPO/blobs/$digest" || true)
  bytes=${out%% *}; speed=${out##* }
  printf '   downloaded %s bytes in 15s cap -> %.2f MB/s\n' "$bytes" \
         "$(awk -v s="${speed:-0}" 'BEGIN{print s/1048576}')"
done
