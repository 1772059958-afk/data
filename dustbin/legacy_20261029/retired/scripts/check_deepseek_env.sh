#!/usr/bin/env bash
# Report whether the DeepSeek endpoint is reachable and which HTTP client is
# available, from inside WSL.
set -u

echo "-- endpoint --"
curl -s -o /dev/null --max-time 15 -w 'api.deepseek.com from WSL: %{http_code} (%{time_total}s)\n' \
     https://api.deepseek.com/models || echo "unreachable"

echo
echo "-- python packages --"
for py in /opt/swe-env/bin/python python3; do
  if command -v "$py" >/dev/null 2>&1 || [[ -x "$py" ]]; then
    "$py" - <<'PY' 2>/dev/null || echo "  $py: not usable"
import importlib.util as u, sys
want = ("openai", "requests", "httpx")
have = [m for m in want if u.find_spec(m)]
print("  {}: {}".format(sys.executable, ", ".join(have) if have else "none of openai/requests/httpx"))
PY
  fi
done

echo
echo "-- key present? --"
if [[ -n "${DEEPSEEK_API_KEY:-}" ]]; then
  echo "DEEPSEEK_API_KEY is set in this shell (${#DEEPSEEK_API_KEY} chars)"
else
  echo "DEEPSEEK_API_KEY is not set in this shell"
fi
