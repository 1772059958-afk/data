"""Join the harness verdicts back onto the counterfactual matrix.

``run_cf.py`` produces patches and a matrix without any verdicts; this script
reads the harness reports, fills in what each branch actually solved, and then
answers the three questions the smoke run is supposed to answer:

1. which quadrant each instance falls in, and how much of the pool genuinely
   needs escalation;
2. whether the prefix features carry any signal about that;
3. how much of the oracle's headroom each policy captures -- and whether the
   five arms actually differ from one another.

The last point is checked explicitly rather than inferred: if arm D's decisions
are identical to arm C's on every instance, that is reported as the finding it
is, not buried in a table.

    /opt/swe-env/bin/python scripts/analyse_cf.py --tag cf_dev4
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

from swe_repair import cf  # noqa: E402

VERDICT_KEYS = ("resolved_ids", "unresolved_ids", "empty_patch_ids", "error_ids")


def load_verdicts(tag: str) -> tuple[dict[str, set[str]], list[str]]:
    """Map arm name -> set of resolved instance ids.

    The harness names its report ``<model_name_or_path>.<run_id>.json``, so the
    tag sits *after* the model name. Matching on a ``<tag>*`` glob therefore
    silently finds nothing, which is exactly the kind of quiet failure that
    would leave every cell looking unresolved.
    """
    verdicts: dict[str, set[str]] = {}
    seen: list[str] = []
    for path in sorted(glob.glob(os.path.join(REPO, "reports", "*.json"))):
        base = os.path.basename(path)
        if base.endswith(("_matrix.json", "_analysis.json")):
            continue
        if f".{tag}" not in base and not base.startswith(f"{tag}-"):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                payload = json.load(fh)
        except (ValueError, OSError):
            continue
        if not isinstance(payload, dict) or "resolved_ids" not in payload:
            continue
        model = base.split(f".{tag}")[0] if f".{tag}" in base else base.rsplit(".", 1)[0]
        arm = model[len(tag) + 1:] if model.startswith(f"{tag}-") else model
        verdicts[arm] = set(payload.get("resolved_ids") or [])
        seen.append(f"{arm} <- {base}")
    return verdicts, seen


def rebuild(matrix: dict) -> dict[str, cf.InstanceOutcome]:
    outcomes: dict[str, cf.InstanceOutcome] = {}
    for item in matrix.get("instances", ()):
        features = dict(item.get("features") or {})
        # Older matrices predate the derived flag; recompute it from the label
        # that was recorded rather than rewriting the run's own output.
        if "lacks_behavioural_signal" not in features:
            signal = features.get("behavioural_signal")
            if signal is not None:
                features["lacks_behavioural_signal"] = 0 if signal == "behavioural" else 1
        outcome = cf.InstanceOutcome(
            instance_id=item["instance_id"],
            features=features,
            prefix_candidate_index=(item.get("prefix") or {}).get("candidate_index"),
            prefix_cost_cny=float((item.get("prefix") or {}).get("cost_cny") or 0.0),
            prefix_calls=int((item.get("prefix") or {}).get("calls") or 0),
            prefix_tokens=int((item.get("prefix") or {}).get("tokens") or 0),
        )
        outcome.fixed_diff = "x" * int((item.get("fixed") or {}).get("diff_lines") or 0)
        outcome.fixed_cost_cny = float((item.get("fixed") or {}).get("cost_cny") or 0.0)
        outcome.fixed_calls = int((item.get("fixed") or {}).get("calls") or 0)
        outcome.interactive_cost_cny = float(
            (item.get("interactive") or {}).get("cost_cny") or 0.0
        )
        outcome.interactive_calls = int((item.get("interactive") or {}).get("calls") or 0)
        outcome.interactive_ended_by = (item.get("interactive") or {}).get("ended_by") or ""
        outcome.standalone_cost_cny = float(
            (item.get("standalone") or {}).get("cost_cny") or 0.0
        )
        outcome.router_rules = list(item.get("router_rules") or [])
        outcomes[outcome.instance_id] = outcome
    return outcomes


def first_firing(rules: list[dict]) -> dict | None:
    """The rule that actually decided, given the frozen order."""
    for rule in rules:
        if rule.get("fires"):
            return rule
    return None


def rule_firing_report(outcomes: list[cf.InstanceOutcome]) -> dict:
    """Which rule decides, and how often each of them would have fired.

    The second part matters more than the first: when every instance ends up in
    the same rule, the interesting question is whether the earlier rules were
    doing any filtering or whether the last escalation rule is simply a catch-all.
    """
    per_instance = []
    first_counts: dict[str, int] = {}
    would_fire: dict[str, int] = {}
    for outcome in outcomes:
        rules = outcome.router_rules
        winner = first_firing(rules)
        name = winner["rule"] if winner else "(no rule fired)"
        first_counts[name] = first_counts.get(name, 0) + 1
        for rule in rules:
            if rule.get("fires"):
                would_fire[rule["rule"]] = would_fire.get(rule["rule"], 0) + 1
        per_instance.append({
            "instance_id": outcome.instance_id,
            "deciding_rule": name,
            "route": winner["route"] if winner else None,
            "all_firing": [r["rule"] for r in rules if r.get("fires")],
        })
    return {
        "deciding_rule_counts": first_counts,
        "would_fire_counts": would_fire,
        "per_instance": per_instance,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag", default="cf_dev4")
    args = ap.parse_args()

    matrix_path = os.path.join(REPO, "reports", f"{args.tag}_matrix.json")
    if not os.path.exists(matrix_path):
        print(f"missing {matrix_path}; run scripts/run_cf.py first", file=sys.stderr)
        return 2
    with open(matrix_path, encoding="utf-8") as fh:
        matrix = json.load(fh)

    verdicts, sources = load_verdicts(args.tag)
    if not verdicts:
        print(f"no harness report found for tag {args.tag!r}.\n"
              f"score first:\n  /opt/swe-env/bin/python -m swebench.harness."
              f"run_evaluation --dataset_name data/harness --split dev "
              f"--predictions_path reports/{args.tag}.jsonl --run_id {args.tag} "
              f"--max_workers 3 --report_dir reports", file=sys.stderr)
        return 2

    outcomes = rebuild(matrix)
    if not outcomes:
        print("matrix has no instances", file=sys.stderr)
        return 2

    missing: list[str] = []
    for iid, outcome in outcomes.items():
        fixed_ok = verdicts.get("A")
        inter_ok = verdicts.get("ESC")
        if fixed_ok is None or inter_ok is None:
            missing.append(iid)
            continue
        outcome.fixed_resolved = iid in fixed_ok
        outcome.interactive_resolved = iid in inter_ok
        if "B" in verdicts:
            outcome.standalone_resolved = iid in verdicts["B"]

    decisions = matrix.get("decisions", {})
    ordered = [o for o in outcomes.values() if o.fixed_resolved is not None]

    def escalate_for(arm: str):
        return lambda o: (decisions.get(o.instance_id, {}).get(arm) == "interactive")

    policies = cf.build_policies()
    scores = [
        cf.score_policy("A_fixed_only", ordered, lambda o: False),
        cf.score_policy("C_escalate_all", ordered, lambda o: True),
        cf.score_policy("oracle", ordered, policies["oracle"]),
        cf.score_policy("D_actual", ordered, escalate_for("D")),
        cf.score_policy("E_actual", ordered, escalate_for("E")),
    ]
    by_name = {s.name: s for s in scores}

    equivalence = {}
    for arm in ("C", "D", "E"):
        same_as_c = all(
            decisions.get(o.instance_id, {}).get(arm)
            == decisions.get(o.instance_id, {}).get("C")
            for o in ordered
        )
        equivalence[arm] = {
            "identical_to_C": same_as_c,
            "escalations": sum(1 for o in ordered if escalate_for(arm)(o)),
        }

    analysis = {
        "tag": args.tag,
        "source_reports": sources,
        "scored_instances": len(ordered),
        "unscored_instances": missing,
        "quadrants": cf.quadrant_table(ordered),
        "features": cf.feature_report(ordered),
        "policies": [s.to_dict() for s in scores],
        "oracle_gap_closure": cf.oracle_gap_closure(
            by_name["A_fixed_only"], by_name["D_actual"], by_name["oracle"]
        ),
        "arm_equivalence": equivalence,
        "rule_firings": rule_firing_report(ordered),
        "per_instance": [
            {
                "instance_id": o.instance_id,
                "fixed_resolved": o.fixed_resolved,
                "interactive_resolved": o.interactive_resolved,
                "standalone_resolved": o.standalone_resolved,
                "quadrant": o.quadrant,
                "u_loc": o.features.get("u_loc"),
                "u_dup": o.features.get("u_dup"),
                "n_public_pass": o.features.get("n_public_pass"),
                "signal": o.features.get("behavioural_signal"),
                "prefix_cost_cny": round(o.prefix_cost_cny, 4),
                "decisions": decisions.get(o.instance_id, {}),
            }
            for o in ordered
        ],
    }

    out_path = os.path.join(REPO, "reports", f"{args.tag}_analysis.json")
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(analysis, fh, indent=2, ensure_ascii=False)

    print(f"scored instances : {len(ordered)}"
          + (f"  (unscored: {', '.join(missing)})" if missing else ""))
    table = analysis["quadrants"]
    print(f"quadrants        : " + ", ".join(
        f"{k}={v}" for k, v in table["counts"].items()))
    print(f"escalation needed: {table['escalation_necessary_share']}")
    print()
    print(f"{'policy':22s} {'resolved':>9s} {'cost CNY':>9s} {'esc':>4s}")
    for score in scores:
        print(f"{score.name:22s} {score.resolved:>4d}/{score.total:<4d} "
              f"{score.cost_cny:>9.4f} {score.escalations:>4d}")
    gap = analysis["oracle_gap_closure"]
    print()
    print(f"oracle headroom  : {gap['headroom']}   gained: {gap['gained']}   "
          f"gap closure: {gap['gap_closure']}")
    print()
    print("feature predictiveness (AUC vs 'escalation was necessary'):")
    for row in analysis["features"]:
        print(f"  {row['feature']:24s} auc={row['auc']}  n={row['n']} "
              f"pos={row['n_positive']}")
    print()
    print("deciding rule (arm D's frozen order):")
    for name, count in analysis["rule_firings"]["deciding_rule_counts"].items():
        print(f"  {name:44s} {count}")
    print("rules that would have fired (some pre-empted by an earlier rule):")
    for name, count in analysis["rule_firings"]["would_fire_counts"].items():
        print(f"  {name:44s} {count}")
    print()
    for arm, info in equivalence.items():
        flag = "IDENTICAL to C" if info["identical_to_C"] else "differs from C"
        print(f"  arm {arm}: {info['escalations']} escalation(s), {flag}")
    print()
    print(f"written: {os.path.relpath(out_path, REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
