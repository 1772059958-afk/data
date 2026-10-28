#!/usr/bin/env bash
# Re-run, one at a time, every instance whose gold patch failed in a previous
# run.
#
#   bash scripts/rerun_gold_failures.sh gold_dev_full [max_workers]
#
# Gold patches are the reference answers, so a failure means the environment,
# not the patch. Re-running serially separates the two kinds of failure:
#
#   passes on retry   -> the environment is flaky (slow network, timeouts)
#   fails again       -> the image is genuinely broken for that instance
#
# Failures of the second kind have to be excluded from the experiment or the
# resolved rate is capped by something that has nothing to do with the method.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$HERE")"
VENV="${VENV_DIR:-/opt/swe-env}"

SOURCE="${1:-gold_dev_full}"
WORKERS="${2:-1}"
RUN_ID="${SOURCE}_retry"

cd "$REPO" || exit 1

REPORT="reports/gold.$SOURCE.json"
if [[ ! -f "$REPORT" ]]; then
  echo "no report at $REPORT"
  exit 1
fi

mapfile -t IDS < <("$VENV/bin/python" - "$REPORT" <<'PY'
import json, sys
with open(sys.argv[1]) as fh:
    print("\n".join(sorted(json.load(fh).get("unresolved_ids", []))))
PY
)

if [[ ${#IDS[@]} -eq 0 ]]; then
  echo "nothing to re-run: $SOURCE had no unresolved instances"
  exit 0
fi

echo "re-running ${#IDS[@]} instance(s) from $SOURCE, ${WORKERS} worker(s)"
printf '  %s\n' "${IDS[@]}"
echo

"$VENV/bin/python" -m swebench.harness.run_evaluation \
  --dataset_name data/harness \
  --split dev \
  --predictions_path gold \
  --run_id "$RUN_ID" \
  --instance_ids "${IDS[@]}" \
  --max_workers "$WORKERS" \
  --report_dir reports
rc=$?

echo
echo "retry report: reports/gold.$RUN_ID.json"
exit $rc
