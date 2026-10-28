"""Run the paired-branch counterfactual on a few instances.

Per instance this does four things, in this order, on one container:

1. the shared prefix (index, localise x2, read, N candidates, validate each);
2. the fixed continuation (one more candidate, no tools) -- arm A's endpoint;
3. the interactive escalation from the prefix state -- what C/D/E would get;
4. a standalone interactive session from nothing -- arm B.

Branches 2 and 3 are both run because this is a *counterfactual* experiment: the
routers are then evaluated offline against the resulting table, so one pass of
paid work supports every policy. Arm D's decision comes from the real router in
``swe_repair.router``, driven by a snapshot of the state taken at the prefix
boundary -- deliberately not re-derived from summary numbers, because
reconstructing the patch history would fake the duplicate rate.

Usage (inside WSL, with the venv at /opt/swe-env):

    /opt/swe-env/bin/python scripts/run_cf.py --dry-run
    /opt/swe-env/bin/python scripts/run_cf.py --total-cny 9.5 --tag cf_dev4
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

import pyarrow.parquet as pq  # noqa: E402

from swe_repair import cf  # noqa: E402
from swe_repair.budget import BudgetState, tier_table  # noqa: E402
from swe_repair.interact import (  # noqa: E402
    SYSTEM as INTERACT_SYSTEM,
    InteractionBudget,
    run_interactive,
)
from swe_repair.llm import DeepSeekClient, ModelConfig  # noqa: E402
from swe_repair.prefix import (  # noqa: E402
    Container,
    Candidate,
    candidate_messages,
    context_block,
    extract_patch,
    image_for,
    lexical_localize,
    read_files,
    resolve_paths,
    run_prefix,
    validate_candidate,
)
from swe_repair.router import (  # noqa: E402
    RouterConfig,
    evaluate_all,
    route_cascade,
    route_fixed_or_stop,
    route_for_arm,
    route_random,
)
from swe_repair.spend import SpendGuard, SpendPolicy  # noqa: E402
from swe_repair.state import RepairState, generation_view  # noqa: E402

DEFAULT_INSTANCES = (
    "marshmallow-code__marshmallow-1343",
    "pylint-dev__astroid-1196",
    "pylint-dev__astroid-1978",
    "sqlfluff__sqlfluff-1625",
)

# Placeholders for the smoke run only. The protocol requires both to be
# calibrated on the dev split and frozen before any main experiment; 0.50 exists
# solely so the machinery can run, and every output file records that.
PLACEHOLDER_THRESHOLD = 0.5
PLACEHOLDER_SWITCH = 0.5

# The frozen config's `small` tier allows 32000 tokens, which a single prefix
# already exceeds: three calls over a 15k-token context measured 47009 tokens,
# so the budget rule fired on every instance and A/C/D/E all stopped at the same
# point. The demo tier below is wide enough for a prefix plus a continuation on
# this context size. It is an amendment, recorded in the protocol, not a knob
# tuned to produce a result.
DEMO_TIER = {
    "token": 200_000,
    "model_call": 12,
    "tool_call": 20,
    "wallclock_seconds": 600.0,
}


def load_config() -> dict:
    with open(os.path.join(REPO, "configs/frozen_v1.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _container_slug(instance_id: str) -> str:
    """Deterministic container name (``hash()`` is salted per process)."""
    return re.sub(r"[^a-zA-Z0-9_.-]", "-", instance_id)[:36]


# --------------------------------------------------------------------------
# prompt pieces
# --------------------------------------------------------------------------


def tried_patches_block(state: RepairState) -> str:
    lines: list[str] = []
    for candidate in state.patches.candidates:
        if not candidate.diff.strip():
            lines.append(f"### attempt {candidate.index}: (no patch was produced)")
            continue
        body = candidate.diff
        if len(body) > 2000:
            body = body[:2000] + "\n... [truncated]"
        lines.append(
            f"### attempt {candidate.index} "
            f"(applies_cleanly={candidate.applies_cleanly}, "
            f"public_test={candidate.validation})\n```diff\n{body}\n```"
        )
    return "\n\n".join(lines) or "(no patches yet)"


def escalation_seed(problem: str, prefix) -> list[dict]:
    """Start the interactive branch from what the prefix already learned.

    The file text is included on purpose. Without it the interactive branch has
    to spend its whole tool budget rediscovering files the fixed branch was
    handed for free, which measures the seed rather than the branch.
    """
    files = "\n".join(f"- {p}" for p in prefix.context_files) or "(none)"
    body = (
        f"# Bug report\n\n{problem.strip()}\n\n"
        f"# Files the fixed prefix looked at\n\n{files}\n\n"
        f"# Contents of those files\n\n{prefix.context_text}\n\n"
        f"# Patches the fixed prefix already tried\n\n"
        f"{tried_patches_block(prefix.state)}\n\n"
        "Continue from here. Do not repeat a patch listed above; work out why it "
        "failed and produce a better one, then call finish with it."
    )
    return [
        {"role": "system", "content": INTERACT_SYSTEM},
        {"role": "user", "content": body},
    ]


# --------------------------------------------------------------------------
# one instance
# --------------------------------------------------------------------------


def run_one(
    row: dict,
    client: DeepSeekClient,
    *,
    cfg: RouterConfig,
    config_version: str,
    config_hash: str,
    n_candidates: int,
    interactive_budget: InteractionBudget,
    skip_standalone: bool,
    verbose: bool = True,
) -> tuple[cf.InstanceOutcome, str]:
    """Run all four steps. Returns the outcome and the prefix snapshot (JSON)."""
    iid = row["instance_id"]
    box = Container(image_for(iid), f"cf-{_container_slug(iid)}")
    box.start()
    try:
        prefix = run_prefix(
            row, client,
            config_version=config_version, config_hash=config_hash,
            n_candidates=n_candidates, container=box,
        )
        prefix_best = prefix.state.patches.best_candidate()
        # Freeze the state exactly at the decision point, before anything else
        # can touch the patch history. The budget travels with it, so the
        # router's budget rule has real consumption to reason about.
        prefix_state = _attach_budget(prefix.state, tokens=prefix.tokens,
                                      calls=prefix.calls)
        snapshot = json.dumps(prefix_state.to_dict(), ensure_ascii=False,
                              sort_keys=True)

        outcome = cf.InstanceOutcome(
            instance_id=iid,
            features=prefix.features(),
            prefix_candidate_index=prefix_best.index if prefix_best else None,
            prefix_cost_cny=prefix.cost_cny,
            prefix_calls=prefix.calls,
            prefix_tokens=prefix.tokens,
            prefix_trace=list(prefix.trace),
        )
        if verbose:
            print(f"    prefix   : {prefix.calls} calls, {prefix.cost_cny:.4f} CNY, "
                  f"files={len(prefix.context_files)}, "
                  f"u_loc={outcome.features['u_loc']}, "
                  f"u_dup={outcome.features['u_dup']}, "
                  f"public_pass={outcome.features['n_public_pass']}, "
                  f"signal={outcome.features['behavioural_signal']}")

        # ---- 2. fixed continuation (arm A's endpoint) --------------------
        problem = str(row.get("problem_statement") or "")
        stop = route_fixed_or_stop(prefix_state, cfg)
        fixed_diff = prefix_best.diff if prefix_best else ""
        if stop.route == "fixed":
            bodies = read_files(box, prefix.context_files)
            reply = client.chat(
                candidate_messages(problem, context_block(bodies), n_candidates)
            )
            raw = extract_patch(reply.text)
            if raw.strip():
                validated = validate_candidate(
                    box, Candidate.build(n_candidates, raw, origin="continuation"),
                    tuple(prefix.state.localization.symbols_union()),
                )
                prefix.state.patches.add(validated.candidate)
            outcome.fixed_cost_cny = reply.record.cost_cny
            outcome.fixed_calls = 1
            best = prefix.state.patches.best_candidate()
            fixed_diff = best.diff if best else fixed_diff
        else:
            outcome.notes.append(f"arm A stopped instead of continuing: {stop.rule}")
        outcome.fixed_diff = fixed_diff
        if verbose:
            print(f"    fixed    : +{outcome.fixed_calls} call(s), "
                  f"{outcome.fixed_cost_cny:.4f} CNY, "
                  f"{len(fixed_diff.splitlines())} lines")

        # ---- 3. interactive escalation from the prefix state ------------
        esc = run_interactive(
            problem,
            client=client,
            budget=interactive_budget,
            container=box,
            instance_id=iid,
            seed_messages=escalation_seed(problem, prefix),
        )
        outcome.interactive_diff = esc.final_diff
        outcome.interactive_cost_cny = esc.cost_cny
        outcome.interactive_calls = esc.calls
        outcome.interactive_ended_by = esc.ended_by
        if verbose:
            print(f"    escalate : {esc.calls} calls / {esc.tool_calls} tools, "
                  f"{esc.cost_cny:.4f} CNY, ended={esc.ended_by}, "
                  f"{len(esc.final_diff.splitlines())} lines")

        # ---- 4. standalone interactive (arm B) --------------------------
        if not skip_standalone:
            solo = run_interactive(
                problem,
                client=client,
                budget=interactive_budget,
                container=box,
                instance_id=iid,
            )
            outcome.standalone_diff = solo.final_diff
            outcome.standalone_cost_cny = solo.cost_cny
            outcome.standalone_calls = solo.calls
            if verbose:
                print(f"    B solo   : {solo.calls} calls / {solo.tool_calls} tools, "
                      f"{solo.cost_cny:.4f} CNY, ended={solo.ended_by}")
        return outcome, snapshot
    finally:
        box.close()


def _attach_budget(state: RepairState, *, tokens: int, calls: int) -> RepairState:
    """Attach the demo budget state so the router's budget rule has real data.

    Uses ``DEMO_TIER`` rather than the config's ``small`` tier, because that tier
    is smaller than one prefix and made every arm stop immediately.
    """
    budget = BudgetState.for_tier(
        "demo", {"demo": DEMO_TIER}
    )
    budget.spend(
        token=max(0, int(tokens)),
        model_call=max(0, int(calls)),
        tool_call=0,
        wallclock_seconds=0.0,
    )
    state.budget = budget
    return state


# --------------------------------------------------------------------------
# arm decisions
# --------------------------------------------------------------------------


def arm_decisions(
    state: RepairState, cfg: RouterConfig, rng: random.Random
) -> dict[str, str]:
    """What each arm decides at the prefix boundary, with the rule that fired."""
    out: dict[str, str] = {}
    a = route_fixed_or_stop(state, cfg)
    out["A"] = a.route
    c = route_cascade(state, cfg)
    out["C"] = c.route
    d = route_for_arm("D", state, cfg, allow_uncalibrated=True)
    out["D"] = d.route
    e = route_random(state, cfg, rng=rng, probability=PLACEHOLDER_SWITCH)
    out["E"] = e.route
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--instances", nargs="*", default=list(DEFAULT_INSTANCES))
    ap.add_argument("--n-candidates", type=int, default=2,
                    help="candidates generated by the prefix (default 2)")
    ap.add_argument("--interactive-calls", type=int, default=8,
                    help="model calls allowed per interactive session")
    ap.add_argument("--interactive-tools", type=int, default=10,
                    help="tool calls allowed per interactive session")
    ap.add_argument("--per-instance-cny", type=float, default=2.2)
    ap.add_argument("--total-cny", type=float, default=9.5,
                    help="hard ceiling for the whole run (protocol: 10.00)")
    ap.add_argument("--max-tokens", type=int, default=16384,
                    help="output ceiling; 8192 truncated patches in thinking mode")
    ap.add_argument("--effort", default="low", choices=["low", "high", "max"])
    ap.add_argument("--skip-standalone", action="store_true",
                    help="skip arm B's session (the single largest cost)")
    ap.add_argument("--seed", type=int, default=20261023)
    ap.add_argument("--tag", default="cf_dev4")
    ap.add_argument("--dry-run", action="store_true",
                    help="containers and prompts only; no model calls, no spend")
    args = ap.parse_args()

    raw_cfg = load_config()
    cfg = RouterConfig.from_config(raw_cfg).with_thresholds(
        localization_disagreement=PLACEHOLDER_THRESHOLD,
        duplicate_rate=PLACEHOLDER_THRESHOLD,
    )

    rows = pq.read_table(os.path.join(REPO, "data/harness/dev.parquet")).to_pylist()
    by_id = {r["instance_id"]: r for r in rows}
    todo = [generation_view(by_id[i]) for i in args.instances if i in by_id]
    missing = [i for i in args.instances if i not in by_id]
    if missing:
        print(f"warning: not in the dev split: {missing}", file=sys.stderr)

    print(f"instances      : {len(todo)}")
    print(f"model          : deepseek-flash  thinking=on effort={args.effort} "
          f"max_tokens={args.max_tokens}")
    print(f"prefix         : {args.n_candidates} candidates")
    print(f"interactive    : {args.interactive_calls} calls / "
          f"{args.interactive_tools} tools per session")
    print(f"ceilings       : {args.per_instance_cny:.2f} CNY per instance, "
          f"{args.total_cny:.2f} CNY total")
    print("thresholds     : 0.50 / 0.50 -- PLACEHOLDER, not calibrated")
    print()

    if args.dry_run:
        for row in todo:
            iid = row["instance_id"]
            box = Container(image_for(iid), f"cf-dry-{abs(hash(iid)) % 100000}")
            box.start()
            try:
                code, listing = box.bash("cd /testbed && ls")
                entries = [x for x in listing.splitlines() if x.strip()]
                lexical = lexical_localize(row.get("problem_statement", ""))
                paths = resolve_paths(box, sorted(lexical))
                bodies = read_files(box, paths)
                chars = len(context_block(bodies))
                print(f"  {iid}")
                print(f"      listing   : {len(entries)} entries")
                print(f"      lexical   : {sorted(lexical) or '(none)'}")
                print(f"      resolved  : {paths or '(none)'}")
                print(f"      context   : {chars} chars (~{chars // 4} tokens)")
            finally:
                box.close()
        print("\ndry run: no model calls, nothing spent")
        return 0

    guard = SpendGuard(SpendPolicy(
        ceiling_cny=args.total_cny,
        approval_threshold_cny=args.total_cny,
        assumed_prompt_tokens=60_000,
        note=f"{args.tag}: paired-branch smoke run",
    ))
    client = DeepSeekClient(
        ModelConfig(thinking=True, effort=args.effort, max_tokens=args.max_tokens),
        guard=guard,
    )
    interactive_budget = InteractionBudget(
        model_calls=args.interactive_calls,
        tool_calls=args.interactive_tools,
    )
    rng = random.Random(args.seed)

    outcomes: list[cf.InstanceOutcome] = []
    decisions: dict[str, dict[str, str]] = {}
    failures: list[dict] = []
    snapshots: dict[str, str] = {}

    for row in todo:
        iid = row["instance_id"]
        print(f"  {iid}")
        if guard.spent_cny >= args.total_cny:
            failures.append({"instance_id": iid, "stage": "precheck",
                             "error": "total ceiling already reached"})
            print("      skipped: total ceiling reached")
            continue
        try:
            outcome, snapshot = run_one(
                row, client,
                cfg=cfg,
                config_version=cfg.config_version,
                config_hash=cfg.digest,
                n_candidates=args.n_candidates,
                interactive_budget=interactive_budget,
                skip_standalone=args.skip_standalone,
            )
            outcomes.append(outcome)
            snapshots[iid] = snapshot
        except Exception as exc:
            failures.append({"instance_id": iid, "stage": "run_one",
                             "error": f"{type(exc).__name__}: {exc}"})
            print(f"      FAILED: {type(exc).__name__}: {exc}")
        print(f"      spent so far: {guard.spent_cny:.4f} CNY")
        print()

    # Decisions are computed after the fact from the frozen prefix snapshots, so
    # an API failure later in an instance cannot change how its arm decided.
    for outcome in outcomes:
        state = RepairState.from_dict(json.loads(snapshots[outcome.instance_id]))
        decisions[outcome.instance_id] = arm_decisions(state, cfg, random.Random(
            f"{args.seed}:{outcome.instance_id}"
        ))
        # Record the whole rule table, not just the winner: if D never differs
        # from C, the next question is which rule is doing the escalating, and
        # that cannot be answered from the decision alone.
        outcome.router_rules = evaluate_all(state, cfg, allow_uncalibrated=True)

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    os.makedirs(os.path.join(REPO, "reports"), exist_ok=True)

    preds_path = os.path.join(REPO, "reports", f"{args.tag}.jsonl")
    counts = {arm: 0 for arm in ("A", "B", "C", "D", "E", "ESC")}
    with open(preds_path, "w", encoding="utf-8", newline="\n") as fh:
        for outcome in outcomes:
            routes = decisions.get(outcome.instance_id, {})
            patches = {
                "A": outcome.fixed_diff,
                # ESC is not an arm: it is the escalation branch scored on its
                # own so the counterfactual cell is filled even for instances
                # where every arm happened to freeze early.
                "ESC": outcome.interactive_diff,
                "C": (outcome.interactive_diff if routes.get("C") == "interactive"
                      else outcome.fixed_diff),
                "D": (outcome.interactive_diff if routes.get("D") == "interactive"
                      else outcome.fixed_diff),
                "E": (outcome.interactive_diff if routes.get("E") == "interactive"
                      else outcome.fixed_diff),
            }
            # Arm B is only written when its session actually ran: submitting an
            # empty patch would be scored as a failure and read as "B is bad"
            # when in truth B was never run.
            if not args.skip_standalone:
                patches["B"] = outcome.standalone_diff
            for arm, patch in patches.items():
                fh.write(json.dumps({
                    "instance_id": outcome.instance_id,
                    "model_name_or_path": f"{args.tag}-{arm}",
                    "model_patch": patch,
                }, ensure_ascii=False) + "\n")
                counts[arm] += 1

    matrix = {
        "tag": args.tag,
        "built_utc": stamp,
        "what": (
            "paired-branch counterfactual smoke run: shared prefix, fixed "
            "continuation, interactive escalation, standalone interactive. "
            "A connectivity check for the five-arm machinery, NOT an effect result."
        ),
        "caveats": [
            "n is tiny: no ordering, no significance, no 'one arm is better' claim",
            f"routing thresholds are placeholders at {PLACEHOLDER_THRESHOLD}",
            f"arm E switch probability is a placeholder at {PLACEHOLDER_SWITCH}",
            "repeats = 1",
        ],
        "model_config": {
            "model": "deepseek-flash", "thinking": True,
            "effort": args.effort, "max_tokens": args.max_tokens,
        },
        "budget": {
            "tier": "demo",
            "tier_ceiling": dict(DEMO_TIER),
            "amendment": (
                "config small tier is 32000 tokens, but one prefix measured "
                "47009 tokens, so the budget rule fired on every instance and "
                "A/C/D/E all stopped. The demo tier is the amendment."
            ),
            "prefix_candidates": args.n_candidates,
            "interactive_model_calls": args.interactive_calls,
            "interactive_tool_calls": args.interactive_tools,
            "per_instance_cny": args.per_instance_cny,
            "total_cny": args.total_cny,
        },
        "config": {"version": cfg.config_version, "hash": cfg.digest},
        "spent_cny": guard.spent_cny,
        "guard": guard.summary(),
        "predictions_file": os.path.relpath(preds_path, REPO).replace("\\", "/"),
        "prediction_rows_per_arm": counts,
        "decisions": decisions,
        "instances": [o.to_dict() for o in outcomes],
        "quadrants_before_scoring": cf.quadrant_table(outcomes),
        "failures": failures,
    }
    matrix_path = os.path.join(REPO, "reports", f"{args.tag}_matrix.json")
    with open(matrix_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(matrix, fh, indent=2, ensure_ascii=False)

    print(f"spent total    : {guard.spent_cny:.4f} CNY")
    print(f"predictions    : {os.path.relpath(preds_path, REPO)}")
    print(f"matrix         : {os.path.relpath(matrix_path, REPO)}")
    print()
    print("next: score all five arms in one harness pass")
    print("  /opt/swe-env/bin/python -m swebench.harness.run_evaluation \\")
    print("      --dataset_name data/harness --split dev \\")
    print(f"      --predictions_path {os.path.relpath(preds_path, REPO)} \\")
    print(f"      --run_id {args.tag} --max_workers 3 --report_dir reports")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
