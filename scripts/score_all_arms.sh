#!/usr/bin/env bash
# Explicit container scoring; never calls a model. New provenance-bound reports.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$HERE")"
V="${VENV_DIR:-/opt/swe-env}/bin/python"
RUN_DIR="${1:?usage: score_all_arms.sh runs/TAG}"
cd "$REPO"
exec "$V" scripts/score_run.py "$RUN_DIR" --execute
