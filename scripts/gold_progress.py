"""How far along is a gold sweep, and how is it going per repository.

    python scripts/gold_progress.py --run-id gold_test_full --split test

Per-instance results are written as each instance finishes, so this works the
same way while the run is in flight and after it lands. Counts only instances
that actually produced a result -- a log directory on its own just means the
instance was started, which is why the harness's own progress bar is the one
to trust for "how far along".
"""

from __future__ import annotations

import argparse
import collections
import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--split", default="test")
    args = ap.parse_args()

    listing = os.path.join(ROOT, "data", "frozen", f"instances_{args.split}.txt")
    with open(listing, encoding="utf-8") as fh:
        all_ids = [line.strip() for line in fh if line.strip()]

    report_path = os.path.join(ROOT, "reports", f"gold.{args.run_id}.json")
    resolved: set[str] = set()
    done: set[str] = set()
    source = "logs (run still in progress)"
    if os.path.exists(report_path):
        with open(report_path, encoding="utf-8") as fh:
            report = json.load(fh)
        resolved = set(report.get("resolved_ids", []))
        done = set(report.get("completed_ids", [])) | resolved
        source = os.path.relpath(report_path, ROOT)
    else:
        logdir = os.path.join(ROOT, "logs", "run_evaluation", args.run_id, "gold")
        if os.path.isdir(logdir):
            for instance in os.listdir(logdir):
                report_file = os.path.join(logdir, instance, "report.json")
                if not os.path.exists(report_file):
                    continue
                done.add(instance)
                try:
                    with open(report_file, encoding="utf-8") as fh:
                        payload = json.load(fh)
                except (OSError, ValueError):
                    continue
                entry = payload.get(instance, {})
                if entry.get("resolved"):
                    resolved.add(instance)

    def repo_of(instance_id: str) -> str:
        return instance_id.split("__", 1)[0]

    print(f"source     {source}")
    if resolved or done:
        print(f"progress   {len(done)}/{len(all_ids)} finished, {len(resolved)} resolved")
    else:
        print("progress   no per-instance results yet (still pulling images)")
        return 0

    per_repo: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0, 0])
    for i in all_ids:
        if i not in done:
            continue
        row = per_repo[repo_of(i)]
        row[0] += 1
        row[1] += 1 if i in resolved else 0
    for i in all_ids:
        per_repo[repo_of(i)][2] += 1

    print()
    print(f"  {'repo':<16}{'done':>6}{'of':>6}{'gold ok':>9}{'rate':>8}")
    for repo, (d, ok, total) in sorted(per_repo.items(), key=lambda kv: -kv[1][2]):
        rate = f"{ok / d:.0%}" if d else "-"
        print(f"  {repo:<16}{d:>6}{total:>6}{ok:>9}{rate:>8}")

    if args.split == "test":
        print()
        print("note: a repo that finishes at 0% is an image defect, not a method result;")
        print("      those instances get excluded from the subset (see build_gold_subset.py)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
