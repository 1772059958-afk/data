"""Counterfactual bookkeeping: quadrants, feature predictiveness, oracle gap.

The paired-branch design (proposal section 6.4) runs both continuations on the
same instance, so every instance lands in one of four cells:

    fixed succeeds            fixed fails
    +---------------------+---------------------+
    | 1  double success   | 3  interactive only |
    |    (escalation is   |    (escalation is   |
    |     pure waste)     |     necessary)      |
    +---------------------+---------------------+
    | 2  fixed only       | 4  double failure   |
    |    (escalation is   |    (escalation is   |
    |     harmful)        |     futile)         |
    +---------------------+---------------------+

Only cell 3 justifies escalating. Everything in this module exists to measure
how much of the pool is cell 3, whether the prefix features can find it, and how
much of the achievable gain a rule captures. "Achievable" is defined by an
oracle that reads the quadrant table directly, which is why the gap closure
metric exposes both gains and negative results. Unknown verdicts stay unknown.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Callable, Iterable, Mapping, Sequence

Q1 = "Q1_double_success"
Q2 = "Q2_fixed_only"
Q3 = "Q3_interactive_only"
Q4 = "Q4_double_failure"

QUADRANT_MEANING = {
    Q1: "both branches solve it: escalating wastes the interactive budget",
    Q2: "only the fixed branch solves it: escalating makes the answer worse",
    Q3: "only interaction solves it: this is what the router must find",
    Q4: "neither solves it: escalating is futile",
}


def quadrant(fixed_ok: bool, interactive_ok: bool) -> str:
    if fixed_ok and interactive_ok:
        return Q1
    if fixed_ok and not interactive_ok:
        return Q2
    if not fixed_ok and interactive_ok:
        return Q3
    return Q4


@dataclass
class InstanceOutcome:
    """One instance's counterfactual record, before any routing is applied."""

    instance_id: str
    features: dict[str, Any]
    prefix_candidate_index: int | None = None
    prefix_cost_cny: float = 0.0
    prefix_calls: int = 0
    prefix_tokens: int = 0

    fixed_diff: str = ""
    fixed_cost_cny: float = 0.0
    fixed_calls: int = 0
    fixed_resolved: bool | None = None

    interactive_diff: str = ""
    interactive_cost_cny: float = 0.0
    interactive_calls: int = 0
    interactive_resolved: bool | None = None
    interactive_ended_by: str = ""

    standalone_diff: str = ""
    standalone_cost_cny: float = 0.0
    standalone_calls: int = 0
    standalone_resolved: bool | None = None

    prefix_resolved: bool | None = None
    routes: dict[str, str] = field(default_factory=dict)
    arm_statuses: dict[str, str] = field(default_factory=dict)
    paired_eligible: bool = True
    notes: list[str] = field(default_factory=list)
    #: Per-step prefix diagnostics (finish_reason, output tokens, whether the
    #: diff applied). Kept because "the patch was empty" has several causes and
    #: the record has to say which one.
    prefix_trace: list[dict[str, Any]] = field(default_factory=list)
    #: Full rule table from ``router.evaluate_all`` at the decision point. This
    #: is the diagnostic that says *which* rule decides, and which ones would
    #: have fired had an earlier rule not already done so.
    router_rules: list[dict[str, Any]] = field(default_factory=list)

    @property
    def quadrant(self) -> str | None:
        if not self.paired_eligible or self.fixed_resolved is None or self.interactive_resolved is None:
            return None
        return quadrant(self.fixed_resolved, self.interactive_resolved)

    @property
    def escalation_necessary(self) -> bool:
        return self.fixed_resolved is False and self.interactive_resolved is True

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "features": self.features,
            "quadrant": self.quadrant,
            "escalation_necessary": self.escalation_necessary,
            "prefix": {
                "candidate_index": self.prefix_candidate_index,
                "cost_cny": round(self.prefix_cost_cny, 6),
                "calls": self.prefix_calls,
                "tokens": self.prefix_tokens,
            },
            "fixed": {
                "cost_cny": round(self.fixed_cost_cny, 6),
                "calls": self.fixed_calls,
                "resolved": self.fixed_resolved,
                "diff_lines": len(self.fixed_diff.splitlines()),
            },
            "interactive": {
                "cost_cny": round(self.interactive_cost_cny, 6),
                "calls": self.interactive_calls,
                "resolved": self.interactive_resolved,
                "ended_by": self.interactive_ended_by,
                "diff_lines": len(self.interactive_diff.splitlines()),
            },
            "standalone": {
                "cost_cny": round(self.standalone_cost_cny, 6),
                "calls": self.standalone_calls,
                "resolved": self.standalone_resolved,
                "diff_lines": len(self.standalone_diff.splitlines()),
            },
            "notes": self.notes,
            "prefix_trace": self.prefix_trace,
            "router_rules": self.router_rules,
        }


# --------------------------------------------------------------------------
# feature predictiveness
# --------------------------------------------------------------------------

#: Direction in which each feature is expected to push towards escalation.
#: ``+1`` means "larger value argues for escalating".
FEATURE_DIRECTION = {
    "u_loc": +1,
    "u_dup": +1,
    "lacks_behavioural_signal": +1,
    "n_public_pass": -1,
    "n_applicable": -1,
}


def _oriented(value: float, direction: int) -> float:
    return value * direction


def auc(scores: Sequence[float], labels: Sequence[bool]) -> float | None:
    """Rank AUC of ``scores`` against boolean ``labels`` (Mann-Whitney form).

    Returns ``None`` when only one class is present, because an AUC is not
    defined then -- reporting 0.5 there would look like "no signal" when in fact
    the sample cannot say anything.
    """
    if len(scores) != len(labels) or any(not math.isfinite(s) for s in scores):
        raise ValueError('AUC requires equally sized finite scores and labels')
    pairs = list(zip(scores, labels))
    positives = [s for s, y in pairs if y]
    negatives = [s for s, y in pairs if not y]
    if not positives or not negatives:
        return None
    wins = 0.0
    for p in positives:
        for n in negatives:
            if p > n:
                wins += 1.0
            elif p == n:
                wins += 0.5
    return wins / (len(positives) * len(negatives))


def feature_report(outcomes: Sequence[InstanceOutcome]) -> list[dict[str, Any]]:
    """AUC of each single feature against "escalation was necessary"."""
    usable = [
        o for o in outcomes
        if o.paired_eligible and o.fixed_resolved is not None and o.interactive_resolved is not None
    ]
    labels = [o.escalation_necessary for o in usable]
    rows: list[dict[str, Any]] = []
    for name, direction in FEATURE_DIRECTION.items():
        values: list[float] = []
        kept: list[bool] = []
        for outcome, label in zip(usable, labels):
            raw = outcome.features.get(name)
            if raw is None:
                continue
            if isinstance(raw, bool):
                raw = 1.0 if raw else 0.0
            values.append(_oriented(float(raw), direction))
            kept.append(label)
        value = auc(values, kept)
        rows.append({
            "feature": name,
            "direction": "higher escalates" if direction > 0 else "lower escalates",
            "n": len(values),
            "n_positive": sum(1 for y in kept if y),
            "auc": None if value is None else round(value, 4),
        })
    return rows


# --------------------------------------------------------------------------
# policy evaluation against the counterfactual table
# --------------------------------------------------------------------------

Decision = Callable[[InstanceOutcome], bool]  # True => escalate


@dataclass
class PolicyScore:
    name: str
    resolved: int = 0
    total: int = 0
    cost_cny: float = 0.0
    escalations: int = 0
    not_scored: int = 0
    stops: int = 0
    status_counts: dict[str, int] = field(default_factory=dict)

    @property
    def resolved_rate(self) -> float | None:
        return self.resolved / self.total if self.total and not self.not_scored else None

    @property
    def cost_per_resolved(self) -> float | None:
        return self.cost_cny / self.resolved if self.resolved and not self.not_scored else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": self.name,
            "resolved": self.resolved,
            "total": self.total,
            "resolved_rate": None if self.resolved_rate is None else round(self.resolved_rate, 4),
            "resolved_rate_lower_bound": round(self.resolved / self.total, 4) if self.total else None,
            "not_scored": self.not_scored, "stops": self.stops,
            "status_counts": dict(self.status_counts),
            "cost_cny": round(self.cost_cny, 6),
            "cost_per_resolved_cny": (
                None if self.cost_per_resolved is None
                else round(self.cost_per_resolved, 4)
            ),
            "escalations": self.escalations,
            "escalation_share": round(
                self.escalations / self.total if self.total else 0.0, 4
            ),
        }


def score_policy(
    name: str,
    outcomes: Sequence[InstanceOutcome],
    escalate: Decision,
) -> PolicyScore:
    """Cost and outcome of a routing policy, read off the counterfactual table.

    A policy that escalates pays the prefix plus the interactive branch; one that
    stays pays the prefix plus the fixed continuation. Both totals include the
    prefix because every arm except B runs it.
    """
    score = PolicyScore(name=name)
    for outcome in outcomes:
        score.total += 1
        wants_interactive = escalate(outcome)
        if not isinstance(wants_interactive, bool):
            raise ValueError('diagnostic policy must explicitly return a boolean escalation decision')
        score.cost_cny += outcome.prefix_cost_cny
        if wants_interactive:
            score.escalations += 1
            score.cost_cny += outcome.interactive_cost_cny
            ok = outcome.interactive_resolved
        else:
            score.cost_cny += outcome.fixed_cost_cny
            ok = outcome.fixed_resolved
        status = 'not_scored' if ok is None else ('resolved' if ok else 'unresolved')
        score.status_counts[status] = score.status_counts.get(status, 0) + 1
        score.not_scored += int(ok is None)
        score.resolved += int(ok is True)
    return score


def oracle_gap_closure(
    fixed: PolicyScore, router: PolicyScore, oracle: PolicyScore
) -> dict[str, Any]:
    """How much of the achievable gain the router captures; losses stay negative.

    The oracle escalates on exactly the instances where it pays and stays
    everywhere else, so ``oracle.resolved`` is the ceiling for any policy that
    must choose between these two branches. A router that lands below the fixed
    baseline gets a negative number; that is reported as it is rather than
    clamped, because it is the most interesting outcome there is.
    """

    if len({fixed.total, router.total, oracle.total}) != 1:
        raise ValueError('oracle comparison requires an identical designated denominator')
    complete = not any(s.not_scored for s in (fixed, router, oracle))
    headroom = oracle.resolved - fixed.resolved
    gained = router.resolved - fixed.resolved
    closure = None if headroom <= 0 or not complete else gained / headroom
    return {
        "fixed_resolved": fixed.resolved,
        "router_resolved": router.resolved,
        "oracle_resolved": oracle.resolved,
        "headroom": headroom,
        "gained": gained,
        "gap_closure": None if closure is None else round(closure, 4),
        "complete": complete,
        "fixed_cost_cny": round(fixed.cost_cny, 6),
        "router_cost_cny": round(router.cost_cny, 6),
        "oracle_cost_cny": round(oracle.cost_cny, 6),
        "note": (
            "gap_closure is undefined when the oracle cannot beat the fixed "
            "branch, because there is no headroom to close"
        ),
    }


def quadrant_table(outcomes: Sequence[InstanceOutcome]) -> dict[str, Any]:
    counts = {Q1: 0, Q2: 0, Q3: 0, Q4: 0}
    unscored: list[str] = []
    for outcome in outcomes:
        cell = outcome.quadrant
        if cell is None:
            unscored.append(outcome.instance_id)
            continue
        counts[cell] += 1
    total = sum(counts.values())
    return {
        "counts": counts,
        "meanings": QUADRANT_MEANING,
        "scored": total,
        "unscored": unscored,
        "escalation_necessary_share": round(counts[Q3] / total, 4) if total else None,
        "wasted_share": round((counts[Q1] + counts[Q2] + counts[Q4]) / total, 4)
        if total else None,
    }


def build_policies() -> dict[str, Decision]:
    """The reference policies every routing rule is compared against."""
    return {
        "A_fixed_only": lambda o: False,
        "forced_ESC_diagnostic_only": lambda o: True,
        "oracle": lambda o: bool(o.interactive_resolved and not o.fixed_resolved),
        "never_escalate_if_ready": lambda o: not (
            (o.features.get("n_public_pass") or 0) > 0
        ),
    }


# Harness statuses, independent of generation status. Absence is NEVER a failure.
VERDICT_FIELDS = {
    'resolved_ids': 'resolved', 'unresolved_ids': 'unresolved',
    'empty_patch_ids': 'empty_patch', 'error_ids': 'error',
    'infra_failure_ids': 'infra_error', 'ambiguous_failure_ids': 'ambiguous_error',
}
SCORED_STATUSES = frozenset(VERDICT_FIELDS.values())
BEHAVIOURAL_STATUSES = frozenset(('resolved', 'unresolved', 'empty_patch'))


def verdict_status(report: Mapping[str, Any] | None, instance_id: str) -> str:
    if report is None:
        return 'not_scored'
    found = {status for field, status in VERDICT_FIELDS.items()
             if instance_id in set(report.get(field) or [])}
    if len(found) > 1:
        raise ValueError(f'conflicting harness verdicts for {instance_id}: {sorted(found)}')
    return next(iter(found), 'not_scored')


def resolved_value(status: str) -> bool | None:
    # Infrastructure and other errors remain separate from behavioural labels.
    return (status == 'resolved') if status in BEHAVIOURAL_STATUSES else None


def score_actual_policy(name: str, outcomes: Sequence[InstanceOutcome], arm: str) -> PolicyScore:
    """Read each actual frozen route, including STOP without continuation cost."""
    score = PolicyScore(name=name)
    for outcome in outcomes:
        score.total += 1
        route = outcome.routes.get(arm)
        if arm == 'B':
            score.cost_cny += outcome.standalone_cost_cny
            fallback = outcome.standalone_resolved
        else:
            score.cost_cny += outcome.prefix_cost_cny
            if route == 'interactive':
                score.escalations += 1
                score.cost_cny += outcome.interactive_cost_cny
                fallback = outcome.interactive_resolved
            elif route == 'fixed':
                score.cost_cny += outcome.fixed_cost_cny
                fallback = outcome.fixed_resolved
            elif route == 'stop':
                score.stops += 1
                fallback = outcome.prefix_resolved
            else:
                fallback = None
        status = outcome.arm_statuses.get(arm)
        if status is None:
            status = 'not_scored' if fallback is None else ('resolved' if fallback else 'unresolved')
        if status not in SCORED_STATUSES and status != 'not_scored':
            raise ValueError(f'unknown evaluation status {status}')
        score.not_scored += int(status == 'not_scored')
        score.resolved += int(status == 'resolved')
        score.status_counts[status] = score.status_counts.get(status, 0) + 1
    return score
