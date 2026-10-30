"""Offline checks for the counterfactual bookkeeping.

These cover the arithmetic the whole write-up rests on: which cell of the
quadrant table an instance belongs to, whether a feature is predictive, and how
much of the oracle's headroom a policy captures. All of it is pure computation,
so it runs without a container, a key, or a network.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))

from swe_repair import cf  # noqa: E402


def _outcome(
    iid: str,
    fixed: bool | None,
    inter: bool | None,
    *,
    prefix_cost: float = 0.1,
    fixed_cost: float = 0.1,
    inter_cost: float = 0.3,
    features: dict | None = None,
) -> cf.InstanceOutcome:
    outcome = cf.InstanceOutcome(instance_id=iid, features=dict(features or {}))
    outcome.fixed_resolved = fixed
    outcome.interactive_resolved = inter
    outcome.prefix_cost_cny = prefix_cost
    outcome.fixed_cost_cny = fixed_cost
    outcome.interactive_cost_cny = inter_cost
    return outcome


def test_quadrant_covers_all_four_cells():
    assert cf.quadrant(True, True) == cf.Q1
    assert cf.quadrant(True, False) == cf.Q2
    assert cf.quadrant(False, True) == cf.Q3
    assert cf.quadrant(False, False) == cf.Q4


def test_quadrant_table_counts_and_shares():
    outcomes = [
        _outcome("a", True, True),
        _outcome("b", True, False),
        _outcome("c", False, True),
        _outcome("d", False, False),
    ]
    table = cf.quadrant_table(outcomes)
    assert table["scored"] == 4
    assert table["counts"][cf.Q3] == 1
    assert table["escalation_necessary_share"] == 0.25
    assert table["wasted_share"] == 0.75
    assert table["meanings"][cf.Q3] == cf.QUADRANT_MEANING[cf.Q3]


def test_unscored_instances_are_named_rather_than_dropped():
    table = cf.quadrant_table([_outcome("a", None, None), _outcome("b", False, True)])
    assert table["unscored"] == ["a"]
    assert table["scored"] == 1


def test_auc_perfect_reversed_tied_and_single_class():
    assert cf.auc([0.1, 0.9], [False, True]) == 1.0
    assert cf.auc([0.9, 0.1], [False, True]) == 0.0
    assert cf.auc([0.5, 0.5], [False, True]) == 0.5
    # Only one class present: an AUC is undefined, and reporting 0.5 would look
    # like "no signal" when the sample simply cannot speak.
    assert cf.auc([0.9, 0.8], [True, True]) is None


def test_feature_report_applies_direction_and_keeps_sample_size():
    outcomes = [
        _outcome("a", False, True, features={"u_loc": 0.9, "n_public_pass": 0}),
        _outcome("b", True, True, features={"u_loc": 0.1, "n_public_pass": 2}),
    ]
    rows = {row["feature"]: row for row in cf.feature_report(outcomes)}
    assert rows["u_loc"]["auc"] == 1.0
    assert rows["u_loc"]["n_positive"] == 1
    assert rows["u_loc"]["n"] == 2
    # Fewer passing public candidates argues for escalating, so the direction
    # flip is what makes this feature separable at all.
    assert rows["n_public_pass"]["direction"] == "lower escalates"
    assert rows["n_public_pass"]["auc"] == 1.0


def test_feature_report_is_all_none_when_every_instance_has_one_label():
    rows = cf.feature_report([_outcome("a", True, True), _outcome("b", True, True)])
    assert rows and all(row["auc"] is None for row in rows)


def test_policy_cost_pays_the_prefix_plus_the_chosen_branch():
    outcomes = [_outcome("a", True, True), _outcome("b", False, True)]
    fixed = cf.score_policy("fixed", outcomes, lambda o: False)
    assert fixed.resolved == 1
    assert round(fixed.cost_cny, 6) == round(0.1 + 0.1 + 0.1 + 0.1, 6)

    escalate = cf.score_policy("all", outcomes, lambda o: True)
    assert escalate.resolved == 2
    assert escalate.escalations == 2
    assert round(escalate.cost_cny, 6) == round(0.1 + 0.3 + 0.1 + 0.3, 6)


def test_policy_skips_instances_that_were_never_scored():
    outcomes = [_outcome("a", None, None), _outcome("b", False, True)]
    score = cf.score_policy("all", outcomes, lambda o: True)
    assert score.total == 1
    assert score.resolved == 1


def test_oracle_gap_closure_is_bounded_and_keeps_negative_results():
    fixed = cf.PolicyScore(name="f", resolved=2, total=4)
    router = cf.PolicyScore(name="r", resolved=3, total=4)
    oracle = cf.PolicyScore(name="o", resolved=5, total=4)
    gap = cf.oracle_gap_closure(fixed, router, oracle)
    assert gap["headroom"] == 3
    assert gap["gained"] == 1
    assert gap["gap_closure"] == round(1 / 3, 4)

    worse = cf.PolicyScore(name="w", resolved=1, total=4)
    gap2 = cf.oracle_gap_closure(fixed, worse, oracle)
    assert gap2["gained"] == -1
    assert gap2["gap_closure"] is not None and gap2["gap_closure"] < 0


def test_gap_closure_is_none_when_the_oracle_cannot_beat_fixed():
    fixed = cf.PolicyScore(name="f", resolved=3, total=4)
    oracle = cf.PolicyScore(name="o", resolved=3, total=4)
    gap = cf.oracle_gap_closure(fixed, fixed, oracle)
    assert gap["headroom"] == 0
    assert gap["gap_closure"] is None


def test_oracle_escalates_exactly_on_the_necessary_cell():
    outcomes = [
        _outcome("a", True, True),
        _outcome("b", True, False),
        _outcome("c", False, True),
        _outcome("d", False, False),
    ]
    oracle = cf.score_policy("oracle", outcomes, cf.build_policies()["oracle"])
    assert oracle.escalations == 1
    assert oracle.resolved == 3
