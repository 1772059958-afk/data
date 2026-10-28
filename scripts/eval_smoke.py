"""End-to-end smoke test of the evaluation chain, using gold patches.

This is the cheapest way to prove the pipeline works: it hands the harness a
patch that is known to be correct, so the expected outcome is "resolved" for
every instance. No model is called, so it costs nothing.

The harness is pointed at the frozen local parquet directory, which keeps the
run offline and pinned to the revision recorded in data/frozen/manifest.json.

    python scripts/eval_smoke.py --split dev --limit 1
    python scripts/eval_smoke.py --dry-run --split dev --limit 3
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):  # pragma: no cover
    pass

from swe_repair import runlog  # noqa: E402


def frozen_ids(split: str) -> list[str]:
    path = os.path.join(ROOT, "data", "frozen", f"instances_{split}.txt")
    if not os.path.exists(path):
        raise SystemExit(f"missing {path}; run scripts/freeze_dataset.py first")
    with open(path, encoding="utf-8") as fh:
        return [line.strip() for line in fh if line.strip()]


def docker_ok() -> tuple[bool, str]:
    exe = shutil.which("docker")
    if not exe:
        return False, "docker not found on PATH"
    try:
        out = subprocess.run([exe, "info", "--format", "{{.ServerVersion}}"],
                             capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return False, "docker info timed out (is the engine running?)"
    if out.returncode != 0:
        return False, (out.stderr or out.stdout).strip()[:200]
    return True, out.stdout.strip()


def build_command(args, instance_ids: list[str]) -> list[str]:
    cmd = [
        sys.executable, "-m", "swebench.harness.run_evaluation",
        "-d", os.path.join(ROOT, "data", "raw"),
        "-s", args.split,
        "-i", *instance_ids,
        "-p", args.predictions,
        "-id", args.run_id,
        "--max_workers", str(args.max_workers),
        "-t", str(args.timeout),
        "--report_dir", os.path.join(ROOT, "reports"),
    ]
    return cmd


def find_report(run_id: str) -> str | None:
    pattern = os.path.join(ROOT, "reports", f"*.{run_id}.json")
    hits = sorted(glob.glob(pattern))
    return hits[-1] if hits else None


def write_records(run_id: str, instance_ids: list[str], report: dict | None,
                  log_path: str, config_hash: str) -> dict[str, str]:
    resolved = set(report.get("resolved_ids", [])) if report else set()
    unresolved = set(report.get("unresolved_ids", [])) if report else set()
    errored = set(report.get("error_ids", [])) if report else set()
    empty = set(report.get("empty_patch_ids", [])) if report else set()

    outcomes: dict[str, str] = {}
    with runlog.RunLogger(log_path) as log:
        for iid in instance_ids:
            if iid in resolved:
                status = "resolved"
            elif iid in empty:
                status = "empty_patch"
            elif iid in errored:
                status = "error"
            elif iid in unresolved:
                status = "unresolved"
            else:
                status = "not_run"
            outcomes[iid] = status
            log.write({
                "instance_id": iid,
                "run_id": run_id,
                "seed": 0,
                "model_version": "gold-patch-smoke-test",
                "config_hash": config_hash,
                "base_commit": report.get("base_commits", {}).get(iid, "") if report else "",
                "container_id": None,
                "prefix_budget": {
                    "token": 0, "model_call": 0, "tool_call": 0,
                    "wallclock_seconds": 0, "prefix_fraction": 0.0,
                },
                "route": "fixed",
                "route_reason": "smoke_test_gold_patch",
                "patch_hash": runlog.patch_hash(report.get("gold_patches", {}).get(iid, "")
                                                if report else "") if report else None,
                "public_validation": {
                    "status": "pass" if status == "resolved" else "not_run",
                    "detail": "gold patch smoke test",
                },
                "input_tokens": 0,
                "output_tokens": 0,
                "model_calls": 0,
                "tool_calls": 0,
                "elapsed_seconds": 0.0,
                "termination_reason": "agent_finish" if status == "resolved" else "error",
                "evaluation_status": status,
                "split": report.get("split", "") if report else "",
            })
    return outcomes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", default="dev", choices=["dev", "test"])
    ap.add_argument("--instances", nargs="*", help="explicit instance ids")
    ap.add_argument("--limit", type=int, default=1, help="take the first N frozen ids")
    ap.add_argument("--predictions", default="gold",
                    help="'gold' or a path to a predictions jsonl file")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--max-workers", type=int, default=1)
    ap.add_argument("--timeout", type=int, default=1800, help="per-instance timeout seconds")
    ap.add_argument("--logs", default=os.path.join(ROOT, "runs", "eval_records.jsonl"))
    ap.add_argument("--config", default=os.path.join(ROOT, "configs", "frozen_v1.json"))
    ap.add_argument("--dry-run", action="store_true", help="print the command and exit")
    args = ap.parse_args()

    with open(args.config, encoding="utf-8") as fh:
        config = json.load(fh)
    chash = runlog.config_hash(config)
    if args.run_id is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        args.run_id = f"smoke_gold_{args.split}_{stamp}"

    ids = args.instances or frozen_ids(args.split)[: args.limit]
    cmd = build_command(args, ids)

    print("instances:", ", ".join(ids))
    print("command:  ", " ".join(f'"{c}"' if " " in c else c for c in cmd))
    if args.dry_run:
        return 0

    ok, detail = docker_ok()
    if not ok:
        print(f"\ndocker is not usable: {detail}", file=sys.stderr)
        print("run scripts/setup_docker.ps1 (elevated) then scripts/setup_docker_in_wsl.sh",
              file=sys.stderr)
        return 2
    print("docker:", detail)

    started = datetime.now(timezone.utc)
    proc = subprocess.run(cmd, cwd=ROOT)
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()

    report_path = find_report(args.run_id)
    report = None
    if report_path:
        with open(report_path, encoding="utf-8") as fh:
            report = json.load(fh)
    outcomes = write_records(args.run_id, ids, report, args.logs, chash)

    print(f"\nharness exit code: {proc.returncode}   wall clock: {elapsed:.0f}s")
    print(f"report:  {report_path or 'not found'}")
    print(f"log:     {args.logs}")
    for iid, status in outcomes.items():
        print(f"  {status:10s} {iid}")
    return 0 if proc.returncode == 0 else proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
