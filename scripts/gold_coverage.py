"""How much of a split the gold sweep actually reached, and how it went.

    python scripts/gold_coverage.py --run-id gold_test_full --split test

`build_gold_subset.py` answers "which instances can be repaired at all" and is
only meaningful once a split has been swept end to end. This answers the
smaller question you need while the sweep is still filling in: what did we
actually cover, and did anything fail for environmental reasons in the part we
did cover?

The distinction matters, because a partial sweep is easy to misread as a
complete one.
"""

from __future__ import annotations

import argparse
import collections
import io
import json
import os
import sys
from datetime import datetime, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FROZEN = os.path.join(ROOT, "data", "frozen")
REPORTS = os.path.join(ROOT, "reports")


def repo_of(instance_id: str) -> str:
    return instance_id.split("__", 1)[0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--split", default="test")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    listing = os.path.join(FROZEN, f"instances_{args.split}.txt")
    with open(listing, encoding="utf-8") as fh:
        all_ids = [line.strip() for line in fh if line.strip()]

    report_path = os.path.join(REPORTS, f"gold.{args.run_id}.json")
    if not os.path.exists(report_path):
        print(f"no report at {report_path}", file=sys.stderr)
        return 1
    with open(report_path, encoding="utf-8") as fh:
        report = json.load(fh)

    resolved = set(report.get("resolved_ids", []))
    done = set(report.get("completed_ids", [])) | resolved
    missing = [i for i in all_ids if i not in done]

    per_repo: dict[str, tuple[int, int, int]] = {}
    for repo in sorted({repo_of(i) for i in all_ids}):
        total = sum(1 for i in all_ids if repo_of(i) == repo)
        seen = sum(1 for i in all_ids if repo_of(i) == repo and i in done)
        ok = sum(1 for i in all_ids if repo_of(i) == repo and i in resolved)
        per_repo[repo] = (seen, ok, total)

    print(f"split      {args.split}: {len(all_ids)} instances")
    print(f"report     {os.path.relpath(report_path, ROOT)}")
    print(f"covered    {len(done)}")
    print(f"not yet    {len(missing)}")
    print(f"resolved   {len(resolved)}")
    print(f"unresolved {report.get('unresolved_instances', '?')}")
    print(f"infra/err  {report.get('infra_failure_instances', '?')} / "
          f"{report.get('error_instances', '?')}")
    print()
    print(f"  {'repo':<16}{'covered':>8}{'of':>6}{'gold ok':>9}{'rate':>8}")
    for repo, (seen, ok, total) in sorted(per_repo.items(),
                                          key=lambda kv: -kv[1][2]):
        rate = f"{ok / seen:.0%}" if seen else "-"
        print(f"  {repo:<16}{seen:>8}{total:>6}{ok:>9}{rate:>8}")

    complete = len(done) >= len(all_ids)
    if not complete:
        print()
        print("This is a partial sweep. Do NOT read it as the split's ceiling:")
        print(f"  {len(missing)} instances were never evaluated.")

    manifest = {
        "split": args.split,
        "source_run_id": args.run_id,
        "source_report": os.path.relpath(report_path, ROOT).replace("\\", "/"),
        "built_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "complete": complete,
        "counts": {
            "full": len(all_ids),
            "covered": len(done),
            "not_yet_evaluated": len(missing),
            "resolved": len(resolved),
        },
        "per_repo": {
            repo: {"covered": s, "gold_ok": ok, "total": t}
            for repo, (s, ok, t) in per_repo.items()
        },
        "not_yet_evaluated": missing,
        "note": (
            "A partial sweep measures the instances it reached, not the split. "
            "The ceiling for the full split stays unknown until every instance "
            "has a gold verdict."
        ),
    }

    out = os.path.join(FROZEN, f"gold_coverage_{args.split}.json")
    if args.dry_run:
        print()
        print("dry run: nothing written")
        return 0
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
    print()
    print(f"wrote {os.path.relpath(out, ROOT).replace(chr(92), '/')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
