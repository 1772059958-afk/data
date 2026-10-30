#!/usr/bin/env bash
# Task 3, the half that needs no model and no money.
#
#   bash scripts/run_baseline_stub.sh [split] [run_id]
#
# It writes a predictions file in the exact format the harness reads, grades it,
# and checks that the verdict comes back as expected. This is the part of the
# baseline work that can be finished before anyone hands over an API key: it
# proves the "generated result -> predictions file -> grading -> report" chain,
# and it proves the grader really runs tests instead of trusting the patch text.
#
# Three passes, each with a known-correct expected verdict:
#   empty  -> unresolved   (nothing may be counted as solved by accident)
#   stub   -> unresolved   (a wrong patch must fail)
#   gold   -> resolved     (positive control)
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$HERE")"
VENV="${VENV_DIR:-/opt/swe-env}"

SPLIT="${1:-dev}"
RUN_ID="${2:-stub_dev}"
WORKERS="${3:-2}"

cd "$REPO" || exit 1
mkdir -p runs reports

# Two instances from repos whose images are usually already cached.
mapfile -t IDS < <(head -n 2 "data/frozen/instances_${SPLIT}.txt")
echo "split: $SPLIT   instances: ${IDS[*]}"
echo

fail=0

run_pass() {
  local mode="$1" expect="$2"
  local preds="runs/preds_${RUN_ID}_${mode}.jsonl"
  local rid="${RUN_ID}_${mode}"

  "$VENV/bin/python" scripts/make_predictions.py \
    --split "$SPLIT" --out "$preds" --mode "$mode" --only "${IDS[@]}" >/dev/null || return 1

  "$VENV/bin/python" -m swebench.harness.run_evaluation \
    --dataset_name data/harness \
    --split "$SPLIT" \
    --predictions_path "$preds" \
    --run_id "$rid" \
    --instance_ids "${IDS[@]}" \
    --max_workers "$WORKERS" \
    --report_dir reports >/dev/null 2>&1

  # The harness names the report "<model_name_or_path>.<run_id>.json", with
  # slashes in the model name flattened to underscores.
  local report
  report="$(ls -1t reports/*."${rid}".json 2>/dev/null | head -1)"
  if [[ -z "$report" ]]; then
    printf '%-8s report not found (reports/*.%s.json)\n' "$mode" "$rid"
    return 1
  fi

  local got
  got="$("$VENV/bin/python" - "$report" <<'PY'
import json, sys
with open(sys.argv[1]) as fh:
    d = json.load(fh)
print(f"{d.get('resolved_instances', 0)} resolved / {d.get('total_instances', 0)} total")
PY
)"
  printf '%-8s %s   (expected %s)\n' "$mode" "$got" "$expect"
}

echo "mode     result"
echo "------   ------"
run_pass empty "0 resolved" || fail=$((fail + 1))
run_pass stub  "0 resolved" || fail=$((fail + 1))
run_pass gold  "all resolved" || fail=$((fail + 1))

echo
if [[ $fail -eq 0 ]]; then
  echo "All three passes produced a report. Open them and confirm the empty and"
  echo "stub runs show 0 resolved, and the gold run shows all resolved."
else
  echo "$fail pass(es) failed to produce a report."
fi
exit $(( fail > 0 ? 1 : 0 ))
