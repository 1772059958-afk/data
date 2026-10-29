"""Merge generation runs and their harness verdicts into one summary.

    /opt/swe-env/bin/python scripts/summarise_baseline.py \
        --run reports/baseline_dev_run.json \
        --run reports/baseline_dev_retry_run.json \
        --tag baseline_dev \
        --out reports/baseline_dev_summary.json

A baseline gets re-run for reasons that are not the method (a ceiling that was
too low, a truncated reply). The summary keeps the first attempt *and* the
retry, because "it passed after we raised the limit" is a result worth
reporting, while quietly overwriting the first attempt is not.
"""

from __future__ import annotations

import argparse
import glob
import io
import json
import os
import sys
from datetime import datetime, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(path: str):
    full = path if os.path.isabs(path) else os.path.join(ROOT, path)
    if not os.path.exists(full):
        return None
    with open(full, encoding="utf-8") as fh:
        return json.load(fh)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", action="append", required=True,
                    help="a run report from run_baseline.py; repeatable")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    attempts = []
    per_instance: dict[str, dict] = {}
    total_cost = 0.0
    total_tokens = 0

    for path in args.run:
        blob = load(path)
        if blob is None:
            print(f"  skipping missing {path}")
            continue
        attempts.append({
            "report": path,
            "model_config": blob.get("model_config"),
            "spent_cny": blob.get("spent_cny_total"),
            "instances": [
                {"instance_id": i["instance_id"],
                 "finish_reason": i["finish_reason"],
                 "output_tokens": i["output_tokens"],
                 "reasoning_tokens": i.get("reasoning_tokens"),
                 "patch_lines": i["patch_lines"],
                 "patch_empty": i["patch_empty"],
                 "cost_cny": i["cost_cny"]}
                for i in blob.get("instances", [])
            ],
        })
        total_cost += float(blob.get("spent_cny_total") or 0.0)
        for i in blob.get("instances", []):
            total_tokens += int(i["prompt_tokens"]) + int(i["output_tokens"])
            per_instance[i["instance_id"]] = {
                "instance_id": i["instance_id"],
                "cost_cny": i["cost_cny"],
                "patch_empty": i["patch_empty"],
                "patch_lines": i["patch_lines"],
                "finish_reason": i["finish_reason"],
                "output_tokens": i["output_tokens"],
                "reasoning_tokens": i.get("reasoning_tokens"),
            }

    # Harness verdicts: the newest file per instance wins, since a re-run is
    # meant to replace the earlier verdict.
    verdicts: dict[str, dict] = {}
    for path in sorted(glob.glob(os.path.join(ROOT, "reports",
                                              f"*{args.tag}*.json"))):
        if path.endswith("_run.json") or path.endswith("_summary.json"):
            continue
        blob = load(path)
        if not isinstance(blob, dict) or "resolved_ids" not in blob:
            continue
        for key, verdict in (("resolved_ids", "resolved"),
                             ("unresolved_ids", "unresolved"),
                             ("empty_patch_ids", "empty_patch")):
            for iid in blob.get(key) or []:
                verdicts[iid] = {"verdict": verdict,
                                 "source": os.path.relpath(path, ROOT)}

    for iid, row in per_instance.items():
        found = verdicts.get(iid)
        row["verdict"] = found["verdict"] if found else "not_scored"
        row["verdict_source"] = found["source"] if found else None

    resolved = [i for i, r in per_instance.items() if r["verdict"] == "resolved"]
    n = len(per_instance)

    import statistics

    costs = sorted(r["cost_cny"] for r in per_instance.values())
    median_cost = statistics.median(costs) if costs else None
    # Cost per *solved* instance is the number that matters for a budget: it is
    # total spend divided by the fixes that actually landed.
    cost_per_resolved = (total_cost / len(resolved)) if resolved else None

    by_verdict: dict[str, list[str]] = {}
    for iid, row in sorted(per_instance.items()):
        by_verdict.setdefault(row["verdict"], []).append(iid)

    summary = {
        "tag": args.tag,
        "built_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model_config": attempts[-1]["model_config"] if attempts else None,
        "what": ("single-shot fixed-flow baseline (one prompt per instance, "
                 "patch taken from the reply). Not Agentless."),
        "failure_modes": by_verdict,
        "attempts": attempts,
        "instances": sorted(per_instance.values(), key=lambda r: r["instance_id"]),
        "totals": {
            "instances": n,
            "resolved": len(resolved),
            "resolved_rate": round(len(resolved) / n, 4) if n else None,
            "spent_cny": round(total_cost, 6),
            "tokens": total_tokens,
            "cost_per_instance_cny": round(total_cost / n, 6) if n else None,
            "median_cost_cny": round(median_cost, 6) if median_cost is not None else None,
            "cost_per_resolved_cny": (round(cost_per_resolved, 6)
                                     if cost_per_resolved is not None else None),
        },
    }

    out = os.path.join(ROOT, args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)

    print(f"instances     : {n}")
    print(f"resolved      : {len(resolved)}  ({summary['totals']['resolved_rate']})")
    print(f"spent         : CNY {summary['totals']['spent_cny']}")
    print(f"per instance  : CNY {summary['totals']['cost_per_instance_cny']}")
    print(f"median cost   : CNY {summary['totals']['median_cost_cny']}")
    print(f"per resolved  : CNY {summary['totals']['cost_per_resolved_cny']}")
    print()
    for row in summary["instances"]:
        print(f"  {row['instance_id']:<42}{row['verdict']:<12}"
              f"{row['patch_lines']:>3} lines  CNY {row['cost_cny']:.4f}")
    print()
    print(f"wrote {os.path.relpath(out, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
