"""Self-checks for the routing rules, the arms and the degeneracy monitor.

Section 5.3 of the proposal asks for routing tests built from explicitly
constructed failure states: early stop when a candidate already passes, exit on
environment failure, and no further action when the budget is short. Those are
the first three checks below.

Runs under pytest or as plain ``python tests/test_router.py``.
"""

from __future__ import annotations

import json
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):  # pragma: no cover
    pass

from swe_repair import runlog  # noqa: E402
from swe_repair.budget import Budget, BudgetState  # noqa: E402
from swe_repair.router import (  # noqa: E402
    RULES,
    RoutingStats,
    RouterConfig,
    UncalibratedThreshold,
    evaluate_all,
    needs_env_recovery,
    route,
    route_cascade,
    route_fixed_or_stop,
    route_for_arm,
    route_random,
)
from swe_repair.state import (  # noqa: E402
    Candidate,
    ContextView,
    FailureLog,
    FailureRecord,
    Localization,
    PatchHistory,
    RepairState,
    TaskManifest,
    build_run_record,
)

CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "configs", "proposal_v1.json"
)

DIFF = "--- a/pkg/mod.py\n+++ b/pkg/mod.py\n@@ -1,3 +1,4 @@\n x = 1\n+y = 2\n z = 3\n"


def raw_config(**router_overrides):
    router = {
        "rule_order": [
            "stop_on_env_failure_after_one_recovery",
            "stop_when_budget_insufficient",
            "freeze_when_public_candidate_passes",
            "fixed_on_local_application_or_syntax_error",
            "interactive_on_wide_localization_disagreement",
            "interactive_on_high_duplicate_rate",
            "interactive_on_out_of_scope_stack_evidence",
            "fixed_when_evidence_insufficient",
            "fixed_continuation_otherwise",
        ],
        "localization_disagreement_threshold": None,
        "duplicate_rate_threshold": None,
        "threshold_grid": [0.25, 0.50, 0.75],
    }
    router.update(router_overrides)
    return {
        "config_version": "frozen_v1",
        "budget_tiers": [
            {"tier": "small", "token": 32000, "model_call": 12, "tool_call": 20, "wallclock_seconds": 600},
        ],
        "prefix": {"prefix_fraction": 0.30},
        "interaction": {"stagnation_patience": 3},
        "router": router,
    }


def calibrated(**router_overrides) -> RouterConfig:
    cfg = raw_config(
        localization_disagreement_threshold=0.50,
        duplicate_rate_threshold=0.50,
        **router_overrides,
    )
    return RouterConfig.from_config(cfg)


def task() -> TaskManifest:
    return TaskManifest(
        instance_id="sympy__sympy-20590",
        repo="sympy/sympy",
        base_commit="abcdef",
        config_version="frozen_v1",
        config_hash=runlog.config_hash({"config_version": "frozen_v1"}),
    )


def state(**overrides) -> RepairState:
    base = RepairState(
        task=task(),
        budget=BudgetState(
            tier="small",
            ceiling=Budget(token=32000, model_call=12, tool_call=20, wallclock_seconds=600),
        ),
        clock=lambda: "2026-10-15T00:00:00Z",
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def quiet_failure(st) -> RepairState:
    """A continuable failure with a narrow localisation and a behavioural signal.

    Nothing here should trigger interaction: it is the control case that keeps
    arm D from collapsing into arm C.
    """
    st.localization = Localization.from_file_sets({"bm25": ["pkg/mod.py"], "symbol": ["pkg/mod.py"]})
    st.context = ContextView(
        indexed_paths=frozenset({"pkg/mod.py"}),
        read_files=frozenset({"pkg/mod.py"}),
        registered_test_commands=("python -m pytest tests/test_mod.py",),
        checks_run=1,
    )
    st.patches.add(Candidate.build(0, DIFF, applies_cleanly=True, validation="fail"))
    st.failures.add(
        FailureRecord.from_output(
            "python -m pytest tests/test_mod.py", 1, stage="test",
            stderr='  File "/testbed/pkg/mod.py", line 41, in parse\nE   AssertionError: nope',
        )
    )
    return st


# -- the rule order comes from the config ----------------------------------


def test_config_and_code_agree_on_the_rule_set():
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        shipped = json.load(fh)
    order = shipped["router"]["rule_order"]
    assert order == list(RouterConfig.from_config(shipped).rule_order)
    assert set(order) == set(RULES), set(order) ^ set(RULES)
    assert len(order) == 9


def test_unknown_rule_name_in_config_raises():
    cfg = raw_config()
    cfg["router"]["rule_order"] = list(cfg["router"]["rule_order"]) + ["magic_rule"]
    try:
        RouterConfig.from_config(cfg)
    except ValueError as exc:
        assert "magic_rule" in str(exc)
    else:
        raise AssertionError("config with an unimplemented rule was accepted")


def test_shipped_config_is_the_frozen_v1_and_is_not_yet_calibrated():
    cfg = RouterConfig.from_file(CONFIG_PATH)
    assert cfg.config_version == "proposal_aligned_v1"
    assert cfg.calibrated is False
    assert cfg.threshold_grid == (0.25, 0.50, 0.75)
    assert cfg.budget_tiers()["development"]["model_call"] == 12
    assert len(cfg.digest) == 64


# -- the three accepting checks from section 5.3 ---------------------------


def test_early_stop_when_a_candidate_already_passes():
    st = state()
    st.patches.add(Candidate.build(0, DIFF, applies_cleanly=True, validation="pass"))
    decision = route(st, calibrated())
    assert decision.route == "stop"
    assert decision.reason == "early_stop_public_pass"


def test_early_stop_wins_over_every_other_trigger():
    st = quiet_failure(state())
    st.patches.add(Candidate.build(1, DIFF, applies_cleanly=True, validation="pass"))
    st.localization = Localization.from_file_sets({"a": ["x.py"], "b": ["y.py"]})
    assert route(st, calibrated()).reason == "early_stop_public_pass"


def test_environment_failure_stops_only_after_the_one_recovery():
    st = quiet_failure(state())
    record = FailureRecord.from_output("pip install -e .", 1, stage="env", stderr="Connection refused")
    st.failures.add(record)
    assert needs_env_recovery(st) is True
    assert route(st, calibrated()).reason != "stop_env_failure"
    st.failures.add(record.with_recovery())
    decision = route(st, calibrated())
    assert decision.route == "stop"
    assert decision.reason == "stop_env_failure"


def test_short_budget_stops_before_any_branch_is_chosen():
    st = quiet_failure(state())
    st.budget.spend(token=31500, model_call=11, tool_call=19, wallclock_seconds=570)
    decision = route(st, calibrated())
    assert decision.route == "stop"
    assert decision.reason == "stop_budget_insufficient"
    assert "short on" in decision.detail


def test_already_overrun_budget_stops_immediately():
    st = quiet_failure(state())
    st.budget.spend(token=99999)
    assert route(st, calibrated()).reason == "stop_budget_insufficient"


# -- the four interaction triggers -----------------------------------------


def test_wide_localization_disagreement_triggers_interaction():
    st = quiet_failure(state())
    st.localization = Localization.from_file_sets({"a": ["x.py"], "b": ["y.py"]})
    decision = route(st, calibrated())
    assert decision.route == "interactive"
    assert decision.reason == "interactive_on_wide_localization_disagreement"
    assert "u_loc=1.000" in decision.detail


def test_missing_localization_does_not_trigger_interaction():
    st = quiet_failure(state())
    st.localization = Localization.from_file_sets({"a": [], "b": []})
    assert st.u_loc is None
    assert route(st, calibrated()).reason == "fixed_continuation_otherwise"


def test_high_duplicate_rate_triggers_interaction():
    st = quiet_failure(state())
    st.patches = PatchHistory()
    for index in range(4):
        st.patches.add(Candidate.build(index, DIFF, applies_cleanly=True, validation="fail"))
    st.patches.add(
        Candidate.build(4, DIFF.replace("+y = 2", "+y = 5"), applies_cleanly=True, validation="fail")
    )
    decision = route(st, calibrated())
    assert decision.route == "interactive"
    assert decision.reason == "interactive_on_high_duplicate_rate"
    assert "u_dup=0.600" in decision.detail


def test_out_of_scope_stack_frame_triggers_interaction():
    st = quiet_failure(state())
    st.failures = FailureLog()
    st.failures.add(
        FailureRecord.from_output(
            "pytest", 1, stage="test",
            stderr=(
                '  File "/testbed/pkg/mod.py", line 41, in parse\n'
                '  File "/testbed/pkg/normalise.py", line 9, in fmt\n'
                "E   AssertionError: nope"
            ),
        )
    )
    decision = route(st, calibrated())
    assert decision.route == "interactive"
    assert decision.reason == "interactive_on_out_of_scope_stack_evidence"
    assert "pkg/normalise.py" in decision.detail


def test_no_behavioural_signal_conservatively_stays_fixed():
    st = quiet_failure(state())
    st.context = ContextView(indexed_paths=frozenset({"pkg/mod.py"}))
    st.failures = FailureLog()
    decision = route(st, calibrated())
    assert decision.route == "fixed"
    assert decision.reason == "fixed_when_evidence_insufficient"


def test_quiet_failure_falls_through_to_the_fixed_branch():
    decision = route(quiet_failure(state()), calibrated())
    assert decision.route == "fixed"
    assert decision.reason == "fixed_continuation_otherwise"


# -- uncalibrated thresholds refuse to fire --------------------------------


def test_arm_d_refuses_to_route_before_calibration():
    cfg = RouterConfig.from_file(CONFIG_PATH)
    st = quiet_failure(state())
    try:
        route(st, cfg)
    except UncalibratedThreshold as exc:
        assert "localization_disagreement" in str(exc)
    else:
        raise AssertionError("arm D routed with an uncalibrated threshold")
    decision = route(st, cfg, allow_uncalibrated=True)
    assert decision.reason == "fixed_continuation_otherwise"


def test_stop_rules_work_without_calibration():
    cfg = RouterConfig.from_file(CONFIG_PATH)
    st = state()
    st.patches.add(Candidate.build(0, DIFF, applies_cleanly=True, validation="pass"))
    assert route(st, cfg).reason == "early_stop_public_pass"


# -- the arms --------------------------------------------------------------


def test_arm_c_escalates_every_continuable_failure():
    st = quiet_failure(state())
    decision = route_cascade(st, calibrated())
    assert decision.route == "interactive"
    assert decision.reason == "cascade_all_eligible_failures"
    assert route(st, calibrated()).route == "fixed"


def test_arm_c_still_respects_the_shared_stop_rules():
    st = quiet_failure(state())
    st.budget.spend(token=99999)
    assert route_cascade(st, calibrated()).route == "stop"


def test_arm_a_keeps_the_fixed_workflow():
    st = quiet_failure(state())
    st.localization = Localization.from_file_sets({"a": ["x.py"], "b": ["y.py"]})
    assert route_fixed_or_stop(st, calibrated()).route == "fixed"


def test_arm_e_is_deterministic_and_monotone_in_p():
    st = quiet_failure(state())
    cfg = calibrated(switch_probability=1.0)
    assert route_random(st, cfg, random.Random(0)).route == "interactive"
    cfg0 = calibrated(switch_probability=0.0)
    assert route_random(st, cfg0, random.Random(0)).route == "fixed"
    draws = [route_random(st, calibrated(switch_probability=0.4), random.Random(seed)).route
             for seed in range(20)]
    assert draws.count("interactive") == sum(
        1 for seed in range(20) if random.Random(seed).random() < 0.4
    )


def test_arm_e_needs_a_calibrated_probability():
    st = quiet_failure(state())
    try:
        route_random(st, calibrated())
    except UncalibratedThreshold:
        pass
    else:
        raise AssertionError("arm E routed without a switch probability")


def test_arm_b_is_not_routed_by_the_prefix_router():
    try:
        route_for_arm("B", quiet_failure(state()), calibrated())
    except ValueError as exc:
        assert "prefix" in str(exc)
    else:
        raise AssertionError("arm B was routed by the prefix router")


def test_route_for_arm_dispatches_every_other_arm():
    st = quiet_failure(state())
    assert route_for_arm("A", st, calibrated()).route == "fixed"
    assert route_for_arm("C", st, calibrated()).route == "interactive"
    assert route_for_arm("D", st, calibrated()).route == "fixed"
    cfg_e = calibrated(switch_probability=0.5)
    assert route_for_arm("E", st, cfg_e, rng=random.Random(0)).route in ("fixed", "interactive")


# -- audit and monitoring --------------------------------------------------


def test_evaluate_all_reports_every_rule_and_never_short_circuits():
    st = quiet_failure(state())
    rows = evaluate_all(st, RouterConfig.from_file(CONFIG_PATH))
    assert len(rows) == 9
    assert [r["rule"] for r in rows] == list(RouterConfig.from_file(CONFIG_PATH).rule_order)
    fired = [r["rule"] for r in rows if r["fires"]]
    assert fired == ["fixed_continuation_otherwise"]


def test_evaluate_all_marks_uncalibrated_rules():
    st = quiet_failure(state())
    rows = {
        r["rule"]: r
        for r in evaluate_all(st, RouterConfig.from_file(CONFIG_PATH), allow_uncalibrated=False)
    }
    assert rows["interactive_on_wide_localization_disagreement"]["calibrated"] is False
    assert rows["interactive_on_wide_localization_disagreement"]["fires"] is False


def test_routing_stats_flags_the_arm_c_degeneracy():
    stats = RoutingStats()
    st = quiet_failure(state())
    for _ in range(19):
        stats.add(route_cascade(st, calibrated()))
    stats.add(route(quiet_failure(state()), calibrated()))
    assert stats.total == 20
    assert abs(stats.interactive_share() - 0.95) < 1e-9
    warnings = stats.warnings()
    assert any("behaving like arm C" in w for w in warnings), warnings


def test_routing_stats_flags_a_router_that_never_switches():
    stats = RoutingStats()
    for _ in range(5):
        stats.add(route(quiet_failure(state()), calibrated()))
    assert any("no interactive trigger fired" in w for w in stats.warnings())
    assert stats.to_dict()["by_route"] == {"fixed": 5}


def test_stats_serialise_cleanly():
    stats = RoutingStats()
    stats.add(route(quiet_failure(state()), calibrated()))
    blob = json.dumps(stats.to_dict(), ensure_ascii=False)
    assert "interactive_share" in blob


# -- decision to run record, end to end ------------------------------------


def test_decision_becomes_a_valid_run_record():
    st = quiet_failure(state())
    decision = route(st, calibrated())
    st.record_decision(decision.rule, decision.route, decision.reason, decision.detail)
    st.budget.spend(token=8000, model_call=4, tool_call=6, wallclock_seconds=120)
    record = build_run_record(
        st, run_index=2, seed=0, model_version="test-model", elapsed_seconds=130.0,
        termination_reason="agent_finish",
    )
    assert record["route"] == "fixed"
    assert record["route_reason"] == "fixed_continuation_otherwise"
    assert runlog.validate(record) == [], runlog.validate(record)
    assert record["input_tokens"] + record["output_tokens"] == 8000


if __name__ == "__main__":
    failures = 0
    names = [n for n in sorted(globals()) if n.startswith("test_")]
    for name in names:
        fn = globals()[name]
        if not callable(fn):
            continue
        try:
            fn()
            print(f"PASS  {name}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL  {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(names)} checks, {failures} failed")
    raise SystemExit(1 if failures else 0)
