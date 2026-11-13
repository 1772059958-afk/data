#!/usr/bin/env bash
# Rewrite /etc/docker/daemon.json as valid JSON.
#
# The file written by setup_proxy_in_wsl.sh had a trailing comma after the last
# key, which is not valid JSON. Docker tolerated it on the version that was
# running, but a stricter reader would refuse to parse it, and a daemon that
# cannot read its own config is a bad thing to discover after a reboot.
#
# The proxy that is actually in use comes from the systemd drop-in
# (/etc/systemd/system/docker.service.d/proxy.conf), so this file is a
# belt-and-braces copy. No restart is needed for this edit; it applies the next
# time the daemon starts.
set -euo pipefail

target=/etc/docker/daemon.json
echo "before:"
cat "$target" 2>/dev/null || echo "  (missing)"

sudo tee "$target" >/dev/null <<'JSON'
{
  "proxies": {
    "http-proxy": "http://172.30.240.1:7890",
    "https-proxy": "http://172.30.240.1:7890"
  }
}
JSON

echo
echo "after:"
cat "$target"

python3 - "$target" <<'PY'
import json, sys
with open(sys.argv[1]) as fh:
    cfg = json.load(fh)
print("parses OK ->", cfg)
PY

echo
echo "active proxy (from the systemd drop-in, unchanged):"
docker info --format '  HTTPProxy={{.HTTPProxy}}  HTTPSProxy={{.HTTPSProxy}}'
