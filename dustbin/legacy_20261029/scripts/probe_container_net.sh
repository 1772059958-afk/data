#!/usr/bin/env bash
# What the evaluation containers can actually reach, and how fast.
#
#   bash scripts/probe_container_net.sh [image] [proxy_url]
#
# Some instances run `pip install -e .` while the tests run. When that build
# needs to fetch something, a slow or unreachable index turns a perfectly good
# patch into a failure, so this is worth knowing before trusting any score.
set -uo pipefail

IMAGE="${1:-swebench/sweb.eval.x86_64.pyvista_1776_pyvista-4315:latest}"
# From inside a container the WSL host is docker's bridge gateway, not the
# gateway WSL itself uses.
BRIDGE="$(ip -4 addr show docker0 2>/dev/null | awk '/inet /{print $2}' | cut -d/ -f1)"
PROXY="${2:-http://${BRIDGE:-172.17.0.1}:7890}"

echo "image : $IMAGE"
echo "proxy : $PROXY  (docker bridge gateway)"
echo

echo "== proxy env vars inside the container =="
docker run --rm "$IMAGE" env 2>/dev/null | grep -i proxy || echo "   (none injected)"

echo
echo "== can the container reach the proxy at all? =="
docker run --rm "$IMAGE" bash -c "timeout 3 bash -c 'echo > /dev/tcp/${PROXY#http://}' && echo open || echo closed" 2>/dev/null \
  | sed "s/^/   /"

echo
echo "== pypi direct, no proxy, 60s cap =="
docker run --rm "$IMAGE" bash -c \
  "timeout 60 python -m pip download --no-deps -q setuptools -d /tmp/x && echo OK || echo 'FAILED or timed out'" 2>&1 \
  | tail -3 | sed "s/^/   /"

echo
echo "== pypi through the proxy, 60s cap =="
docker run --rm -e "http_proxy=$PROXY" -e "https_proxy=$PROXY" "$IMAGE" bash -c \
  "timeout 60 python -m pip download --no-deps -q setuptools -d /tmp/x && echo OK || echo 'FAILED or timed out'" 2>&1 \
  | tail -3 | sed "s/^/   /"

echo
echo "== pypi via the Tsinghua mirror, 60s cap =="
docker run --rm -e "PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple" "$IMAGE" bash -c \
  "timeout 60 python -m pip download --no-deps -q setuptools -d /tmp/x && echo OK || echo 'FAILED or timed out'" 2>&1 \
  | tail -3 | sed "s/^/   /"
