#!/usr/bin/env bash
# Stop using the domestic registry mirrors and pull from Docker Hub directly,
# through the proxy set up by setup_proxy_in_wsl.sh.
#
#   bash scripts/docker_use_hub_direct.sh          # Hub via proxy
#   bash scripts/docker_use_hub_direct.sh --mirrors # back to mirrors
#
# Measured on this machine: the mirrors delivered roughly 1 MB/s, Docker Hub
# through the proxy about 3.6 MB/s, and only the proxy route can reach the
# images' other hosting domains.
set -eo pipefail

MODE="${1:-}"
DAEMON=/etc/docker/daemon.json
GATEWAY="$(ip route | awk '/^default/{print $3; exit}')"
PROXY="http://${GATEWAY}:7890"

python3 - "$DAEMON" "$GATEWAY" "$PROXY" "$MODE" <<'PY'
import json, os, sys

path, gateway, proxy, mode = sys.argv[1], sys.argv[2], sys.argv[3], (
    sys.argv[4] if len(sys.argv) > 4 else "")

cfg = json.load(open(path)) if os.path.exists(path) else {}
cfg["proxies"] = {
    "http-proxy": proxy,
    "https-proxy": proxy,
    "no-proxy": f"localhost,127.0.0.1,::1,{gateway}",
}

if mode == "--mirrors":
    cfg["registry-mirrors"] = ["https://docker.m.daocloud.io", "https://docker.1panel.live"]
else:
    cfg.pop("registry-mirrors", None)

json.dump(cfg, open(path, "w"), indent=2)
print(json.dumps(cfg, indent=2))
PY

systemctl daemon-reload
systemctl restart docker
sleep 3
echo
docker info --format 'docker {{.ServerVersion}}  mirrors={{.RegistryConfig.Mirrors}}'
