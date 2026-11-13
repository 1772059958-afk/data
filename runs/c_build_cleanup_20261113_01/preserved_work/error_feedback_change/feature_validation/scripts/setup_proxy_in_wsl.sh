#!/usr/bin/env bash
# Point WSL at the Windows-side proxy, when the proxy allows LAN connections.
#
#   sudo bash scripts/setup_proxy_in_wsl.sh
#
# The Windows host is the WSL default gateway. Docker Hub, GitHub and
# huggingface.co are unreachable from WSL otherwise; with the proxy they are
# reachable, and downloads were several times faster than the mirror route.
#
# Safe to re-run. Removes nothing; use --revert to undo.
set -uo pipefail

REVERT=0
[[ "${1:-}" == "--revert" ]] && REVERT=1

GATEWAY="$(ip route | awk '/^default/{print $3; exit}')"
PORT="${PROXY_PORT:-7890}"
PROXY="http://${GATEWAY}:${PORT}"

if [[ $REVERT -eq 1 ]]; then
  rm -f /etc/profile.d/proxy.sh
  rm -f /etc/systemd/system/docker.service.d/proxy.conf
  python3 - <<'PY'
import json, os
p = "/etc/docker/daemon.json"
if os.path.exists(p):
    cfg = json.load(open(p))
    cfg.pop("proxies", None)
    json.dump(cfg, open(p, "w"), indent=2)
PY
  systemctl daemon-reload
  systemctl restart docker
  echo "reverted"
  exit 0
fi

echo "gateway: $GATEWAY   proxy: $PROXY"

if ! timeout 3 bash -c "echo > /dev/tcp/${GATEWAY}/${PORT}" 2>/dev/null; then
  echo
  echo "The proxy is not reachable on ${PROXY}."
  echo "In the proxy client, turn on the setting that accepts LAN connections"
  echo "(Clash: 允许局域网连接 / Allow LAN), then run this again."
  exit 1
fi

check=$(curl -s -o /dev/null -x "$PROXY" -w '%{http_code}' --max-time 12 https://github.com || echo 000)
echo "github.com through the proxy: $check"
if [[ "$check" != "200" && "$check" != "301" && "$check" != "302" ]]; then
  echo "The port is open but the proxy is not forwarding; check the client."
  exit 1
fi

# 1. shell-wide, with the mirror hosts kept direct so they stay fast.
cat > /etc/profile.d/proxy.sh <<EOF
export http_proxy="$PROXY"
export https_proxy="$PROXY"
export HTTP_PROXY="$PROXY"
export HTTPS_PROXY="$PROXY"
export no_proxy="localhost,127.0.0.1,::1,hf-mirror.com,pypi.tuna.tsinghua.edu.cn,mirrors.tuna.tsinghua.edu.cn,docker.m.daocloud.io,docker.1panel.live,${GATEWAY}"
export NO_PROXY="\$no_proxy"
EOF
chmod 644 /etc/profile.d/proxy.sh
echo "wrote /etc/profile.d/proxy.sh"

# 2. dockerd, so image pulls from Docker Hub go through the proxy.
mkdir -p /etc/systemd/system/docker.service.d
cat > /etc/systemd/system/docker.service.d/proxy.conf <<EOF
[Service]
Environment="HTTP_PROXY=$PROXY"
Environment="HTTPS_PROXY=$PROXY"
Environment="NO_PROXY=localhost,127.0.0.1,::1,${GATEWAY}"
EOF
echo "wrote /etc/systemd/system/docker.service.d/proxy.conf"

# 3. the daemon.json form, which newer Docker versions read for pulls.
python3 - "$PROXY" "$GATEWAY" <<'PY'
import json, os, sys
proxy, gw = sys.argv[1], sys.argv[2]
p = "/etc/docker/daemon.json"
cfg = json.load(open(p)) if os.path.exists(p) else {}
cfg["proxies"] = {
    "http-proxy": proxy,
    "https-proxy": proxy,
    "no-proxy": f"localhost,127.0.0.1,::1,{gw}",
}
json.dump(cfg, open(p, "w"), indent=2)
print("updated /etc/docker/daemon.json")
PY

systemctl daemon-reload
systemctl restart docker
sleep 3
docker info --format 'docker {{.ServerVersion}}  mirrors={{.RegistryConfig.Mirrors}}'

echo
echo "Open a new WSL shell (or: source /etc/profile.d/proxy.sh) for the env vars."
