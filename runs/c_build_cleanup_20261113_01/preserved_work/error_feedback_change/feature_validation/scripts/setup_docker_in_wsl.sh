#!/usr/bin/env bash
# Step 3: prepare the Linux side of the evaluation stack.
#
#   sudo bash setup_docker_in_wsl.sh [--proxy http://127.0.0.1:7890] [--no-proxy]
#
# Three things happen here:
#   1. the Docker engine is installed and pointed at registry mirrors, because
#      the official registry is not always reachable from this network;
#   2. a Python virtual environment with the SWE-bench harness is created inside
#      the Linux filesystem (not on /mnt/c, which is slow and breaks venvs);
#   3. if a proxy is reachable from here, apt, pip and the Docker daemon are all
#      pointed at it, so downloads that need it work the same way they do on
#      Windows.
#
# Why the harness runs inside Ubuntu: the official harness drives containers and
# copies files into them. With the daemon inside WSL, host paths and daemon paths
# are the same filesystem, so there is no path translation to get wrong. The
# dataset stays on /mnt/c and is readable from here.
set -euo pipefail

VENV_DIR="${VENV_DIR:-/opt/swe-env}"
PROXY=""
AUTO_PROXY=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --proxy) PROXY="$2"; AUTO_PROXY=0; shift 2 ;;
    --no-proxy) AUTO_PROXY=0; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  echo "run this with sudo" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

say() { printf '\n\033[36m==> %s\033[0m\n' "$*"; }
ok()  { printf '    \033[32m%s\033[0m\n' "$*"; }
warn() { printf '    \033[33m%s\033[0m\n' "$*"; }

# ---------------------------------------------------------------- proxy
probe_proxy() {
  local candidate="$1"
  curl -s -o /dev/null --max-time 8 -x "$candidate" https://github.com && return 0
  return 1
}

if [[ $AUTO_PROXY -eq 1 ]]; then
  gateway="$(ip route show default 2>/dev/null | awk '{print $3}' | head -n1 || true)"
  for candidate in "http://127.0.0.1:7890" "http://${gateway}:7890"; do
    [[ -n "$candidate" ]] || continue
    if probe_proxy "$candidate"; then
      PROXY="$candidate"
      ok "found a working proxy at $candidate"
      break
    fi
  done
fi

if [[ -n "$PROXY" ]]; then
  say "recording the proxy for apt, pip, git and the Docker daemon: $PROXY"
  printf 'Acquire::http::Proxy "%s";\nAcquire::https::Proxy "%s";\n' "$PROXY" "$PROXY" \
    > /etc/apt/apt.conf.d/95swe-proxy
  mkdir -p /etc/systemd/system/docker.service.d
  cat >/etc/systemd/system/docker.service.d/http-proxy.conf <<PROXYCONF
[Service]
Environment="HTTP_PROXY=$PROXY"
Environment="HTTPS_PROXY=$PROXY"
Environment="NO_PROXY=localhost,127.0.0.1,::1"
PROXYCONF
  mkdir -p /etc/pip.conf.d
  cat >/etc/pip.conf <<PIPCONF
[global]
proxy = $PROXY
PIPCONF
  cat >/etc/profile.d/swe-proxy.sh <<PROFILECONF
export HTTP_PROXY=$PROXY
export HTTPS_PROXY=$PROXY
export NO_PROXY=localhost,127.0.0.1,::1
PROFILECONF
  ok "written; re-run with --no-proxy if you want to remove this, or delete /etc/apt/apt.conf.d/95swe-proxy"
else
  warn "no proxy detected: downloads go out directly (some hosts are blocked on this network)"
fi

# ---------------------------------------------------------------- docker
say "installing the Docker engine and the Python toolchain"
if ! apt-get update; then
  warn "apt-get update failed"
  if [[ -z "$PROXY" ]]; then
    warn "no proxy in use; switching the Ubuntu sources to a domestic mirror and retrying"
    for f in /etc/apt/sources.list.d/ubuntu.sources /etc/apt/sources.list; do
      [[ -f "$f" ]] || continue
      sed -i 's|https\?://archive.ubuntu.com|https://mirrors.tuna.tsinghua.edu.cn|g;
              s|https\?://security.ubuntu.com|https://mirrors.tuna.tsinghua.edu.cn|g' "$f"
    done
    apt-get update || { warn "still failing: fix networking, then re-run this script"; exit 1; }
  else
    warn "the proxy is already configured for apt; check that $PROXY still answers"
    exit 1
  fi
fi
apt-get install -y --no-install-recommends \
  docker.io ca-certificates curl git python3 python3-venv python3-pip jq

say "configuring registry mirrors (the official registry is not always reachable)"
mkdir -p /etc/docker
cat >/etc/docker/daemon.json <<'JSON'
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://docker.1panel.live"
  ]
}
JSON

if pidof systemd >/dev/null 2>&1; then
  systemctl daemon-reload
  systemctl enable docker
  systemctl restart docker
else
  service docker restart
fi

say "verifying the daemon"
for _ in $(seq 1 30); do
  if docker info >/dev/null 2>&1; then break; fi
  sleep 1
done
docker info --format '    server: {{.ServerVersion}}   driver: {{.Driver}}   mirrors: {{.RegistryConfig.Mirrors}}'

say "pulling hello-world to prove that pulls work"
if docker run --rm hello-world >/dev/null 2>&1; then
  ok "pull test passed"
else
  warn "pull test failed. Try: docker pull docker.m.daocloud.io/library/hello-world"
  warn "If everything needs the proxy, check /etc/systemd/system/docker.service.d/http-proxy.conf"
fi

# ---------------------------------------------------------------- python
say "creating the harness environment in $VENV_DIR (inside the Linux filesystem)"
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  python3 -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/pip" install --quiet --upgrade pip

say "installing the SWE-bench harness (this needs a few minutes)"
if ! "$VENV_DIR/bin/pip" install --quiet 'swebench==5.0.2' 'pyarrow>=21'; then
  warn "pip install failed; retry with a mirror:"
  warn "  $VENV_DIR/bin/pip install -i https://pypi.tuna.tsinghua.edu.cn/simple swebench==5.0.2 pyarrow"
  exit 1
fi
ok "harness installed: $("$VENV_DIR/bin/python" -c 'import swebench,sys;print("swebench",swebench.__version__,"on",sys.version.split()[0])')"

if [[ -n "${SUDO_USER:-}" ]]; then
  usermod -aG docker "$SUDO_USER"
  ok "added $SUDO_USER to the docker group (log out of WSL and back in)"
fi

say "done"
cat <<EOF
    Next, still inside Ubuntu:

        bash $(cd "$(dirname "$0")" && pwd)/check_env_wsl.sh

    That script checks the container runtime, the harness environment and the
    frozen dataset in one pass, and then prints the single command that runs the
    gold-patch smoke test on one development instance.

    Note: WSL has no systemd at boot on some setups. If 'docker info' fails after
    a restart, run:  sudo service docker start
EOF
