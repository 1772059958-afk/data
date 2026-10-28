#!/usr/bin/env bash
# Self-check for the Linux side, the counterpart of scripts/check_env.py.
#
#   bash scripts/check_env_wsl.sh
#
# It reports, in the order that they block progress: the container runtime, the
# harness environment, the frozen dataset, and the image pull path. It ends by
# printing the exact command for the gold-patch smoke test. Needs no root.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$HERE")"
VENV_DIR="${VENV_DIR:-/opt/swe-env}"
DATA="$REPO/data"

failures=0
line()  { printf '%-34s %s\n' "$1" "$2"; }
good()  { printf '%-34s \033[32m%s\033[0m\n' "$1" "$2"; }
bad()   { printf '%-34s \033[31m%s\033[0m\n' "$1" "$2"; failures=$((failures + 1)); }

echo "repo: $REPO"
echo

if command -v docker >/dev/null 2>&1; then
  server="$(docker info --format '{{.ServerVersion}}' 2>/dev/null || true)"
  if [[ -n "$server" ]]; then
    good "container runtime" "docker $server"
    mirrors="$(docker info --format '{{.RegistryConfig.Mirrors}}' 2>/dev/null || true)"
    line "registry mirrors" "${mirrors:-none configured}"
  else
    bad "container runtime" "docker CLI present but the daemon is not answering (try: sudo service docker start)"
  fi
else
  bad "container runtime" "docker not found"
fi

if [[ -x "$VENV_DIR/bin/python" ]]; then
  if "$VENV_DIR/bin/python" - <<'PY' >/dev/null 2>&1
import swebench, pyarrow, docker  # noqa: F401
PY
  then
    good "harness environment" "$VENV_DIR ($("$VENV_DIR/bin/python" -c 'import swebench;print("swebench",swebench.__version__)'))"
  else
    bad "harness environment" "$VENV_DIR exists but swebench/pyarrow/docker do not all import"
  fi
else
  bad "harness environment" "$VENV_DIR missing (run scripts/setup_docker_in_wsl.sh)"
fi

for split in dev test; do
  parquet="$DATA/raw/$split.parquet"
  listing="$DATA/frozen/instances_$split.txt"
  if [[ -f "$parquet" && -f "$listing" ]]; then
    good "frozen $split split" "$(wc -l < "$listing") instances, $(du -h "$parquet" | cut -f1) parquet"
  else
    bad "frozen $split split" "missing $parquet or $listing"
  fi
done

PYBIN="$VENV_DIR/bin/python"
[[ -x "$PYBIN" ]] || PYBIN="$(command -v python3 || echo python3)"

for split in dev test; do
  parquet="$DATA/harness/$split.parquet"
  if [[ -f "$parquet" ]]; then
    cols="$("$PYBIN" -c "import pyarrow.parquet as pq,sys; print(len(pq.ParquetFile(sys.argv[1]).schema_arrow.names))" "$parquet" 2>/dev/null || echo 0)"
    if [[ "$cols" == "17" ]]; then
      good "harness $split split" "$(du -h "$parquet" | cut -f1) parquet, schema v2 ($cols cols, has image)"
    else
      bad "harness $split split" "$parquet has $cols columns; the harness needs the v2 schema with 'image'"
    fi
  else
    bad "harness $split split" "missing $parquet (fetched from hf-mirror, see data/harness/manifest.json)"
  fi
done

if [[ -f "$REPO/configs/frozen_v1.json" ]]; then
  good "frozen config" "$(jq -r '.config_version + " (" + .status + ")"' "$REPO/configs/frozen_v1.json" 2>/dev/null || echo present)"
else
  bad "frozen config" "configs/frozen_v1.json missing"
fi

echo
if [[ $failures -eq 0 ]]; then
  echo -e "\033[32mAll checks passed.\033[0m"
  echo
  echo "Gold-patch smoke test, one instance from the dev split (no model calls, no cost):"
  echo
  echo "    cd $REPO"
  echo "    $VENV_DIR/bin/python -m swebench.harness.run_evaluation \\"
  echo "        --dataset_name data/harness \\"
  echo "        --split dev \\"
  echo "        --predictions_path gold \\"
  echo "        --run_id smoke_dev_1 \\"
  echo "        --instance_ids \$(head -n1 data/frozen/instances_dev.txt) \\"
  echo "        --max_workers 1"
  echo
  echo "Expect: every instance resolved, and a report written under the repo."
else
  echo -e "\033[31m$failures check(s) failed; fix those before running the harness.\033[0m"
fi

exit $(( failures > 0 ? 1 : 0 ))
