#!/usr/bin/env bash
# For every instance that failed under the gold patch, show the first real
# error the test run reported. Gold patches are supposed to pass, so a failure
# here is an environment problem, not a model problem, and it has to be
# understood before any result is reported.
#
#   bash scripts/summarise_gold_failures.sh [run_id]
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$HERE")"
RUN_ID="${1:-gold_dev_full}"
ROOT="$REPO/logs/run_evaluation/$RUN_ID/gold"

REPORT="$REPO/reports/gold.$RUN_ID.json"
python3 - "$REPORT" <<'PY' > /tmp/_unresolved.txt
import json, sys
with open(sys.argv[1]) as fh:
    data = json.load(fh)
print("\n".join(sorted(data.get("unresolved_ids", []))))
PY

count=0
while read -r inst; do
  [[ -z "$inst" ]] && continue
  count=$((count + 1))
  echo "==== $inst ===="
  out="$ROOT/$inst/test_output.txt"
  if [[ ! -f "$out" ]]; then
    echo "   (no test output)"
    continue
  fi

  # The first line that looks like a real error, plus a little context.
  line=$(grep -n -m1 -E "^E +[A-Za-z]|Error:|error: " "$out" || true)
  if [[ -z "$line" ]]; then
    echo "   (no error line found; last 6 lines)"
    tail -n 6 "$out" | sed 's/^/   /'
    continue
  fi
  lineno=${line%%:*}
  start=$(( lineno > 3 ? lineno - 3 : 1 ))
  sed -n "${start},$(( lineno + 1 ))p" "$out" | sed 's/^/   /'
done < /tmp/_unresolved.txt

echo
echo "gold-patch failures: $count"
