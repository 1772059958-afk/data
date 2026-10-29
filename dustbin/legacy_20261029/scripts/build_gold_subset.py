"""Derive the gold-solvable subset from a gold-patch evaluation run.

    python scripts/build_gold_subset.py --run-id gold_dev_full --split dev

Why this exists
---------------
The gold patch is the reference answer. If it fails, the failure is a property
of the image, not of any method, and no technique can score above that ceiling.
Leaving such instances in the denominator does two bad things at once: it caps
every arm's resolved rate, and because the broken images cluster by repository
it distorts the per-repository numbers in a direction nobody can correct for
after the fact.

So: run gold first, keep only instances the gold patch actually resolves, and
report on that subset. Every exclusion is written down with the error that
caused it, so the subset can be audited rather than trusted.

The output is frozen in the same way as the dataset itself: a sorted instance
list plus a digest, and a manifest recording where the verdicts came from.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import io
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FROZEN = os.path.join(ROOT, "data", "frozen")
REPORTS = os.path.join(ROOT, "reports")
LOGS = os.path.join(ROOT, "logs", "run_evaluation")

# Ordered: the first rule that matches wins. Under a gold patch every failure
# is environmental, so these classify *which* environmental problem it is
# rather than deciding whether it is one.
CATEGORIES: tuple[tuple[str, str, str], ...] = (
    (
        "numpy_2_removed_alias",
        "was removed in the NumPy 2.0 release",
        "The image ships NumPy 2.x, but the repository at this commit still uses "
        "aliases that 2.0 deleted (np.Inf, np.NaN, ...). The code cannot even be "
        "imported, so no patch can pass.",
    ),
    (
        "build_dependency_fetch_failed",
        "Installing build dependencies",
        "The test run builds the package in place and has to fetch build "
        "dependencies at test time. That fetch failed, so the tests never ran.",
    ),
    (
        "test_fixture_missing_attribute",
        "has no attribute",
        "A test fixture did not set up a value the test then reads -- test-tooling "
        "drift inside the image, unrelated to the patch.",
    ),
    (
        "collection_or_import_error",
        "ImportError while loading conftest",
        "The test session could not even start: the package fails to import "
        "inside this image.",
    ),
)

FALLBACK = (
    "other_environment_failure",
    "Failures under a gold patch are environmental by construction. This one did "
    "not match a known signature; the recorded error line is the evidence.",
)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_lines(path: str) -> list[str]:
    with open(path, encoding="utf-8") as fh:
        return [line.strip() for line in fh if line.strip()]


def first_error_line(path: str) -> str:
    """The most useful error line from a test output file."""

    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    for pattern in (r"^E\s+\S.*$", r"^ERROR:.*$", r"^.*Error:.*$"):
        match = re.search(pattern, text, re.MULTILINE)
        if match:
            return match.group(0).strip()[:300]
    return ""


def classify(instance: str, run_id: str) -> dict[str, str]:
    """Say why this instance failed under the gold patch."""

    out = os.path.join(LOGS, run_id, "gold", instance, "test_output.txt")
    if not os.path.exists(out):
        return {
            "category": "no_test_output",
            "detail": "The run produced no test output for this instance.",
            "evidence": "",
        }

    with open(out, encoding="utf-8", errors="replace") as fh:
        text = fh.read()

    for name, needle, detail in CATEGORIES:
        if needle in text:
            return {"category": name, "detail": detail,
                    "evidence": first_error_line(out) or needle}

    name, detail = FALLBACK
    return {"category": name, "detail": detail,
            "evidence": first_error_line(out) or "(no error line found)"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--split", default="dev", choices=["dev", "test"])
    ap.add_argument("--report", default=None,
                    help="override the report path (default reports/gold.<run-id>.json)")
    ap.add_argument("--extra-run-id", action="append", default=[],
                    help="also treat these runs' resolved ids as passing "
                         "(e.g. a retry run that re-ran the failures)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    report_path = args.report or os.path.join(REPORTS, f"gold.{args.run_id}.json")
    if not os.path.exists(report_path):
        print(f"no report at {report_path}", file=sys.stderr)
        return 1
    with open(report_path, encoding="utf-8") as fh:
        report = json.load(fh)

    resolved = set(report.get("resolved_ids", []))
    # A retry run may rescue instances that failed the first time. Anything it
    # newly resolves counts as passing, and the merge is recorded below.
    merged_from: list[str] = []
    for extra in args.extra_run_id:
        extra_path = os.path.join(REPORTS, f"gold.{extra}.json")
        if not os.path.exists(extra_path):
            print(f"  skipping missing retry report {extra_path}")
            continue
        with open(extra_path, encoding="utf-8") as fh:
            extra_report = json.load(fh)
        newly = set(extra_report.get("resolved_ids", [])) - resolved
        resolved |= newly
        merged_from.append({"run_id": extra, "newly_resolved": sorted(newly)})

    listing = os.path.join(FROZEN, f"instances_{args.split}.txt")
    all_ids = read_lines(listing)

    subset = sorted(i for i in all_ids if i in resolved)
    excluded = sorted(i for i in all_ids if i not in resolved)
    unknown = sorted(resolved - set(all_ids))

    print(f"report     {os.path.relpath(report_path, ROOT)}")
    print(f"split      {args.split}: {len(all_ids)} instances")
    print(f"resolved   {len(subset)}")
    print(f"excluded   {len(excluded)}")
    if unknown:
        print(f"warning: {len(unknown)} resolved id(s) are not in the split list: {unknown}")
    print()

    reasons = {i: classify(i, args.run_id) for i in excluded}

    # If a retry rescued something it is not excluded, so its classification is
    # discarded; only exclusions that survived every run are recorded.
    for i in sorted(reasons):
        print(f"  {i}")
        print(f"      {reasons[i]['category']}: {reasons[i]['evidence'][:110]}")

    by_category = collections.Counter(r["category"] for r in reasons.values())
    print()
    print("exclusion categories:")
    for name, count in by_category.most_common():
        print(f"  {count:>3}  {name}")

    def repo_of(instance_id: str) -> str:
        return instance_id.split("__", 1)[0]

    full_repos = collections.Counter(repo_of(i) for i in all_ids)
    kept_repos = collections.Counter(repo_of(i) for i in subset)
    print()
    print("repositories:")
    print(f"  {'repo':<18}{'kept':>6}{'of':>6}")
    lost = []
    for repo, total in sorted(full_repos.items(), key=lambda kv: -kv[1]):
        kept = kept_repos.get(repo, 0)
        print(f"  {repo:<18}{kept:>6}{total:>6}")
        if kept == 0:
            lost.append(repo)
    if lost:
        print()
        print(f"WARNING: these repositories lose every instance: {', '.join(lost)}")
        print("         anything about them cannot be claimed from this subset.")

    subset_digest = sha256_text("\n".join(subset) + "\n")
    manifest = {
        "split": args.split,
        "source_run_id": args.run_id,
        "source_report": os.path.relpath(report_path, ROOT).replace("\\", "/"),
        "merged_from": merged_from,
        "built_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rule": "an instance is kept only if the reference (gold) patch resolves it",
        "why": (
            "A gold-patch failure is an image defect, not a method result. Keeping "
            "such instances would cap every arm's resolved rate and skew the "
            "per-repository averages, because the broken images cluster by repository."
        ),
        "counts": {
            "full": len(all_ids),
            "kept": len(subset),
            "excluded": len(excluded),
        },
        "exclusion_categories": dict(by_category),
        "excluded": {
            i: {"repo": repo_of(i), **reasons[i]} for i in excluded
        },
        "repositories_lost_entirely": lost,
        "instance_list": f"data/frozen/instances_{args.split}_gold_ok.txt",
        "instance_list_sha256": subset_digest,
    }

    if args.dry_run:
        print()
        print("dry run: nothing written")
        return 0

    out_list = os.path.join(FROZEN, f"instances_{args.split}_gold_ok.txt")
    with open(out_list, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(subset) + "\n")
    out_manifest = os.path.join(FROZEN, f"gold_subset_{args.split}.json")
    with open(out_manifest, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)

    print()
    print(f"wrote {os.path.relpath(out_list, ROOT).replace(chr(92), '/')}  "
          f"({len(subset)} instances, digest {subset_digest[:16]}...)")
    print(f"wrote {os.path.relpath(out_manifest, ROOT).replace(chr(92), '/')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
