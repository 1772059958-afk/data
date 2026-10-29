"""Minimal fixed-flow baseline: one prompt in, one patch out.

    /opt/swe-env/bin/python scripts/run_baseline.py --instances a b c
    /opt/swe-env/bin/python scripts/run_baseline.py --dry-run

What this is
------------
A single-shot baseline, deliberately the simplest thing that can produce a
patch: gather repository context, ask the model once, take the diff it writes,
write a predictions file. It is *not* Agentless and must not be reported as
Agentless. Its job is to make the generation half of the loop real, so that
"generate a patch -> score it -> book what it cost" stops being a diagram and
starts producing numbers.

Context comes out of the instance's own container image, which already has the
repository checked out at the base commit. That means the run needs no network
beyond the model API.

The patch file format is the harness's: one JSON object per line with
instance_id, model_name_or_path and model_patch.

Cost is capped per instance. The cap is enforced before the request leaves the
machine, so an over-budget instance fails rather than quietly overrunning.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):  # pragma: no cover
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

import pyarrow.parquet as pq  # noqa: E402

from swe_repair.llm import DeepSeekClient, ModelConfig  # noqa: E402
from swe_repair.spend import SpendGuard, SpendPolicy  # noqa: E402

MAX_CONTEXT_CHARS = 120_000
MAX_FILES = 6


# --------------------------------------------------------------- containers
def docker(args: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True,
                          timeout=timeout, errors="replace")


def image_for(instance_id: str) -> str:
    return f"swebench/sweb.eval.x86_64.{instance_id.replace('__', '_1776_')}:latest"


def run_in_container(image: str, script: str, timeout: int = 300) -> str:
    proc = docker(["run", "--rm", "--entrypoint", "/bin/bash", image, "-lc", script],
                  timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"container command failed: {proc.stderr.strip()[:400]}")
    return proc.stdout


def mention_candidates(problem: str) -> list[str]:
    """Repo-relative file paths the problem statement points at.

    Bug reports quote paths from the reporter's own machine, so the useful part
    is the tail after the package directory. Keep those tails and match them
    against the checkout later.
    """

    raw = re.findall(r"[/\w.\-]+\.py", problem)
    tails: list[str] = []
    for path in raw:
        parts = path.lstrip("/").split("/")
        # Drop absolute prefixes such as /home/x/proj/ or /_/env/lib/python3.7/
        for marker in ("site-packages", "src", "lib"):
            if marker in parts:
                parts = parts[parts.index(marker) + 1:]
                break
        tail = "/".join(parts[-3:])
        if tail.endswith(".py") and tail not in tails and not tail.startswith("python"):
            tails.append(tail)
    return tails[:MAX_FILES]


def collect_context(image: str, instance: dict) -> tuple[str, list[str]]:
    """Read the files that matter out of the container's checkout."""

    tails = mention_candidates(instance.get("problem_statement", ""))

    test_files: list[str] = []
    for name in instance.get("FAIL_TO_PASS") or []:
        path = name.split("::", 1)[0]
        if path.endswith(".py") and path not in test_files:
            test_files.append(path)
    tails += [t for t in test_files[:2] if t not in tails]

    wanted = "\n".join(tails)
    script = f"""
cd /testbed
git rev-parse HEAD
printf '%s\\n' '---FILES---'
ls
printf '%s\\n' '---MATCHES---'
while IFS= read -r tail; do
  [ -z "$tail" ] && continue
  # No `set -e` here on purpose: a pattern that finds nothing is normal, and
  # a failing command substitution would otherwise abort the whole run.
  found=$(find . -path ./.git -prune -o -type f -name "$(basename "$tail")" -print 2>/dev/null \\
          | grep -E "/${{tail}}$|^{{tail}}$" | head -1) || found=""
  if [ -z "$found" ]; then
    found=$(find . -path ./.git -prune -o -type f -name "$(basename "$tail")" -print 2>/dev/null | head -1) || found=""
  fi
  [ -n "$found" ] && echo "$tail|$found"
done <<'TAILS'
{wanted}
TAILS
exit 0
"""
    out = run_in_container(image, script)
    head, _, rest = out.partition("---FILES---")
    listing, _, matches = rest.partition("---MATCHES---")

    resolved: list[tuple[str, str]] = []
    for line in matches.strip().splitlines():
        if "|" not in line:
            continue
        tail, path = line.split("|", 1)
        path = path.strip().lstrip("./")
        if path and (tail, path) not in resolved:
            resolved.append((tail, path))

    chunks: list[str] = []
    used: list[str] = []
    budget = MAX_CONTEXT_CHARS
    for tail, path in resolved[:MAX_FILES]:
        body = run_in_container(image, f"cd /testbed && cat -- '{path}'")
        if len(body) > budget:
            body = body[:budget] + "\n... [truncated]\n"
        budget -= len(body)
        chunks.append(f"### {path}\n```python\n{body}\n```")
        used.append(path)
        if budget <= 0:
            break

    repo_listing = "\n".join(sorted(
        line for line in listing.strip().splitlines() if line.strip()
    )[:60])

    context = (
        f"Repository root listing (partial):\n{repo_listing}\n\n"
        + ("\n\n".join(chunks) if chunks else
           "(no file from the report could be located in the checkout)")
    )
    return context, used


# ----------------------------------------------------------------- prompting
SYSTEM = """You are fixing a bug in a real Python repository.

You will be given a bug report and the contents of the files the report points
at. Reply with a single unified diff that fixes the bug.

Rules:
- Output the diff inside one ```diff fenced block, and nothing else outside it.
- Paths must be relative to the repository root, with a/ and b/ prefixes.
- Change as little as possible. Do not reformat code you are not fixing.
- Do not add tests. The repository's own tests decide whether you are right.
- If you are unsure, make your best single attempt rather than asking.
"""


def build_messages(instance: dict, context: str) -> list[dict]:
    problem = instance.get("problem_statement", "").strip()
    hint = (instance.get("hints_text") or "").strip()
    body = f"# Bug report\n\n{problem}\n"
    if hint:
        body += f"\n# Additional notes\n\n{hint}\n"
    body += f"\n# Repository files\n\n{context}\n"
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": body},
    ]


DIFF_BLOCK = re.compile(r"```(?:diff|patch)?\s*\n(.*?)```", re.DOTALL)


def extract_patch(text: str) -> str:
    match = DIFF_BLOCK.search(text or "")
    candidate = match.group(1) if match else (text or "")
    lines = candidate.splitlines()
    start = next((i for i, l in enumerate(lines)
                  if l.startswith("--- ") or l.startswith("diff --git")), None)
    if start is None:
        return ""
    return "\n".join(lines[start:]).rstrip() + "\n"


HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")


def repair_hunk_headers(patch: str) -> tuple[str, int]:
    """Recompute the line counts in every @@ header from the hunk body.

    Language models routinely write a hunk header whose counts do not match
    the body that follows. `patch` and `git apply` reject those outright
    ("malformed patch"), even when the edit itself is correct, so a wrong exit
    looks like a bad fix when it is only a bad header. Counting the body is
    mechanical, so we do it here. Returns (patch, number_of_headers_rewritten).
    """

    lines = patch.splitlines()
    out: list[str] = []
    repaired = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        m = HUNK_HEADER.match(line)
        if not m:
            out.append(line)
            i += 1
            continue

        old_start, _, new_start, _, tail = m.groups()
        body: list[str] = []
        j = i + 1
        while j < len(lines):
            nxt = lines[j]
            if nxt.startswith("@@ ") or nxt.startswith("diff --git"):
                break
            # A new file section starts with "--- a/..." immediately followed
            # by "+++ b/..."; a hunk body line can also begin with "---", so
            # only the pair counts as a boundary.
            if (nxt.startswith("--- ") and j + 1 < len(lines)
                    and lines[j + 1].startswith("+++ ")):
                break
            body.append(nxt)
            j += 1

        old_n = new_n = 0
        for b in body:
            if b.startswith("\\"):          # "\ No newline at end of file"
                continue
            if b.startswith("+"):
                new_n += 1
            elif b.startswith("-"):
                old_n += 1
            else:                            # context line (possibly empty)
                old_n += 1
                new_n += 1

        was = f"{m.group(2) or 1},{m.group(4) or 1}"
        now = f"{old_n},{new_n}"
        if was != now:
            repaired += 1
        out.append(f"@@ -{old_start},{old_n} +{new_start},{new_n} @@{tail}")
        out.extend(body)
        i = j

    return "\n".join(out).rstrip() + "\n", repaired


# ---------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--instances", nargs="*", default=None,
                    help="defaults to the whole dev gold-solvable subset")
    ap.add_argument("--limit", type=int, default=None,
                    help="only take the first N of the default subset")
    ap.add_argument("--per-instance-cny", type=float, default=2.0,
                    help="hard ceiling for one instance (default 2.00)")
    ap.add_argument("--total-cny", type=float, default=6.0)
    ap.add_argument("--effort", default="low",
                    choices=["low", "high", "max"])
    ap.add_argument("--max-tokens", type=int, default=4096)
    ap.add_argument("--out", default="reports/baseline_dev.jsonl")
    ap.add_argument("--report", default="reports/baseline_dev_run.json")
    ap.add_argument("--tag", default="baseline_dev")
    ap.add_argument("--dry-run", action="store_true",
                    help="build prompts and show sizes, spend nothing")
    ap.add_argument("--repair-hunks", action="store_true",
                    help="recompute @@ line counts from the hunk body before "
                         "writing the patch (fixes 'malformed patch' rejections)")
    args = ap.parse_args()

    if args.instances:
        ids = args.instances
    else:
        with open(os.path.join(REPO, "data/frozen/instances_dev_gold_ok.txt"),
                  encoding="utf-8") as fh:
            ids = [line.strip() for line in fh if line.strip()]
        if args.limit:
            ids = ids[:args.limit]

    rows = pq.read_table(os.path.join(REPO, "data/harness/dev.parquet")).to_pylist()
    by_id = {r["instance_id"]: r for r in rows}
    todo = [by_id[i] for i in ids if i in by_id]
    missing = [i for i in ids if i not in by_id]
    if missing:
        print(f"warning: not in the dev split: {missing}", file=sys.stderr)

    print(f"instances      : {len(todo)}")
    print(f"model          : deepseek-flash  thinking=on effort={args.effort}")
    print(f"per-instance   : ceiling {args.per_instance_cny:.2f} CNY")
    print(f"total ceiling  : {args.total_cny:.2f} CNY")
    print()

    config = ModelConfig(thinking=True, effort=args.effort,
                         max_tokens=args.max_tokens)

    prompts: dict[str, list[dict]] = {}
    contexts: dict[str, list[str]] = {}
    context_failures: list[dict] = []
    ready: list[dict] = []
    for inst in todo:
        iid = inst["instance_id"]
        print(f"  {iid}")
        try:
            image = image_for(iid)
            context, used = collect_context(image, inst)
        except Exception as exc:  # one bad instance must not kill the batch
            print(f"      context failed: {exc}")
            context_failures.append({"instance_id": iid, "stage": "collect_context",
                                     "error": f"{type(exc).__name__}: {exc}"})
            continue
        prompts[iid] = build_messages(inst, context)
        contexts[iid] = used
        ready.append(inst)
        chars = sum(len(m["content"]) for m in prompts[iid])
        print(f"      context files: {', '.join(used) or '(none located)'}")
        print(f"      prompt chars : {chars}  (~{chars // 4} tokens)")
    print()

    if context_failures:
        print(f"skipped before the model: {len(context_failures)} instance(s)")
        print()
    todo = ready

    if args.dry_run:
        print("dry run: no model calls, nothing written")
        return 0

    guard = SpendGuard(SpendPolicy(
        ceiling_cny=args.total_cny,
        approval_threshold_cny=args.total_cny,
        note=f"{args.tag}: {len(todo)} instances at {args.per_instance_cny:.2f} CNY each",
    ))
    client = DeepSeekClient(config, guard=guard)

    out_path = os.path.join(REPO, args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    results = []
    total_spent = 0.0
    call_failures: list[dict] = []
    for inst in todo:
        iid = inst["instance_id"]
        before = guard.spent_cny
        worst = guard.worst_case_cny(config.model,
                                    max_output_tokens=config.max_tokens)
        if before + worst > args.per_instance_cny + 1e-9:
            print(f"  {iid}: skipped, next call could exceed the per-instance "
                  f"ceiling ({before + worst:.2f} > {args.per_instance_cny:.2f})")
            continue

        print(f"  calling the model for {iid} ...")
        try:
            result = client.chat(prompts[iid])
        except Exception as exc:  # keep going; one API error is not fatal
            print(f"      call failed: {type(exc).__name__}: {exc}")
            call_failures.append({"instance_id": iid, "stage": "chat",
                                  "error": f"{type(exc).__name__}: {exc}"})
            continue
        patch = extract_patch(result.text)
        hunk_fixes = 0
        if args.repair_hunks and patch.strip():
            patch, hunk_fixes = repair_hunk_headers(patch)
        spent = guard.spent_cny - before
        total_spent += spent

        print(f"      served {result.record.served_model}, "
              f"{result.record.prompt_tokens} in / {result.record.output_tokens} out, "
              f"{result.record.latency_seconds:.1f}s, {spent:.4f} CNY")
        print(f"      patch: {len(patch.splitlines())} lines, "
              f"{'empty (no diff found)' if not patch.strip() else 'extracted'}")
        if hunk_fixes:
            print(f"      hunks repaired: {hunk_fixes} header(s) had wrong counts")

        with open(out_path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps({
                "instance_id": iid,
                "model_name_or_path": result.record.served_model,
                "model_patch": patch,
            }, ensure_ascii=False) + "\n")

        results.append({
            "instance_id": iid,
            "context_files": contexts[iid],
            "patch_lines": len(patch.splitlines()),
            "patch_empty": not patch.strip(),
            "hunk_headers_repaired": hunk_fixes,
            "cost_cny": round(spent, 6),
            "prompt_tokens": result.record.prompt_tokens,
            "output_tokens": result.record.output_tokens,
            "reasoning_tokens": result.record.reasoning_tokens,
            "latency_seconds": round(result.record.latency_seconds, 2),
            "served_model": result.record.served_model,
            "finish_reason": result.record.finish_reason,
        })

    report = {
        "tag": args.tag,
        "built_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "what": ("single-shot fixed-flow baseline: one prompt per instance, "
                 "patch taken from the model's reply. Not Agentless."),
        "model_config": {"model": config.model, "thinking": config.thinking,
                         "effort": config.effort, "max_tokens": config.max_tokens},
        "ceiling_cny_per_instance": args.per_instance_cny,
        "ceiling_cny_total": args.total_cny,
        "spent_cny_total": round(total_spent, 6),
        "guard": guard.summary(),
        "predictions_file": os.path.relpath(out_path, REPO).replace("\\", "/"),
        "instances": results,
        "skipped": {
            "context_failures": context_failures,
            "call_failures": call_failures,
        },
    }
    rep_path = os.path.join(REPO, args.report)
    os.makedirs(os.path.dirname(rep_path), exist_ok=True)
    with open(rep_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)

    print()
    print(f"spent total    : {total_spent:.4f} CNY")
    print(f"predictions    : {os.path.relpath(out_path, REPO)}")
    print(f"run report     : {os.path.relpath(rep_path, REPO)}")
    print()
    print("next: score them with the harness, e.g.")
    print(f"  python -m swebench.harness.run_evaluation --dataset_name data/harness \\")
    print(f"      --split dev --predictions_path {os.path.relpath(out_path, REPO)} \\")
    print(f"      --run_id {args.tag} --instance_ids {' '.join(i['instance_id'] for i in todo)} \\")
    print("      --max_workers 3 --report_dir reports")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
