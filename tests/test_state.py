"""Self-checks for the state recorder, the signals and the run-record bridge.

Runs under pytest or as plain ``python tests/test_state.py``.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):  # pragma: no cover
    pass

from swe_repair import patchutil, runlog  # noqa: E402
from swe_repair.budget import Budget, BudgetState  # noqa: E402
from swe_repair.state import (  # noqa: E402
    Candidate,
    ContextView,
    FailureLog,
    FailureRecord,
    Localization,
    LocalizationPass,
    PatchHistory,
    RepairState,
    TaskManifest,
    assert_generation_only,
    build_run_record,
    generation_view,
    WithheldFieldError,
)

DIFF = "--- a/pkg/mod.py\n+++ b/pkg/mod.py\n@@ -1,3 +1,4 @@\n x = 1\n+y = 2\n z = 3\n"


def task() -> TaskManifest:
    return TaskManifest(
        instance_id="django__django-11099",
        repo="django/django",
        base_commit="0f3b3b0f",
        config_version="frozen_v1",
        config_hash=runlog.config_hash({"config_version": "frozen_v1"}),
        image_id="swebench/sweb.eval.x86_64.django_1776_django-11099:latest",
    )


def tier() -> BudgetState:
    return BudgetState(
        tier="small",
        ceiling=Budget(token=32000, model_call=12, tool_call=20, wallclock_seconds=600),
    )


def state(**overrides) -> RepairState:
    base = RepairState(task=task(), budget=tier(), clock=lambda: "2026-10-15T00:00:00Z")
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


# -- information boundary --------------------------------------------------


def test_generation_view_drops_withheld_fields():
    row = {
        "instance_id": "django__django-11099",
        "repo": "django/django",
        "base_commit": "abc",
        "version": "4.0",
        "problem_statement": "date parsing blows up",
        "patch": "--- a/x\n+++ b/x\n",
        "test_patch": "--- a/t\n+++ b/t\n",
        "FAIL_TO_PASS": ["tests/test_x.py::test_y"],
        "PASS_TO_PASS": ["tests/test_z.py::test_w"],
        "hints_text": "the answer is in utils.py",
        "created_at": "2022-01-01",
    }
    view = generation_view(row)
    assert "patch" not in view and "test_patch" not in view
    assert "FAIL_TO_PASS" not in view and "hints_text" not in view
    assert view["problem_statement"] == "date parsing blows up"
    assert_generation_only(view, "view")  # must not raise


def test_withheld_field_nested_is_rejected():
    payload = {"task": {"instance_id": "x"}, "extra": [{"PASS_TO_PASS": []}]}
    try:
        assert_generation_only(payload, "state")
    except WithheldFieldError as exc:
        assert "PASS_TO_PASS" in str(exc), exc
    else:
        raise AssertionError("nested withheld field was accepted")


def test_state_round_trip_rejects_withheld_field():
    payload = json.loads(state().to_json())
    payload["extra"] = {"test_patch": "nope"}
    try:
        RepairState.from_dict(payload)
    except WithheldFieldError:
        pass
    else:
        raise AssertionError("state payload with test_patch was accepted")


# -- localization ----------------------------------------------------------


def test_identical_localization_passes_disagree_zero():
    loc = Localization.from_file_sets({"a": ["x.py", "y.py"], "b": ["y.py", "x.py"]})
    assert loc.disagreement() == 0.0


def test_disjoint_localization_passes_disagree_one():
    loc = Localization.from_file_sets({"a": ["x.py"], "b": ["y.py"]})
    assert loc.disagreement() == 1.0


def test_three_passes_use_mean_pairwise_jaccard():
    # |A∩B|/|A∪B| = 1.0, |A∩C|/|A∪C| = 0.0, |B∩C|/|B∪C| = 0.0 -> mean 1/3
    loc = Localization(
        (
            LocalizationPass("a", frozenset({"f1.py"})),
            LocalizationPass("b", frozenset({"f1.py"})),
            LocalizationPass("c", frozenset({"f2.py"})),
        )
    )
    assert abs(loc.disagreement() - (1 - 1 / 3)) < 1e-9, loc.disagreement()


def test_two_empty_passes_are_missing_not_agreeing():
    loc = Localization.from_file_sets({"a": [], "b": []})
    assert loc.missing is True
    assert loc.disagreement() is None


def test_single_pass_cannot_yield_disagreement():
    loc = Localization.from_file_sets({"a": ["x.py"]})
    assert loc.disagreement() is None
    assert loc.missing is False


# -- patch history ---------------------------------------------------------


def test_duplicate_rate_counts_repeats():
    history = PatchHistory()
    history.add(Candidate.build(0, DIFF))
    history.add(Candidate.build(1, DIFF))
    history.add(Candidate.build(2, DIFF.replace("+y = 2", "+y = 3")))
    assert abs(history.duplicate_rate() - 1 / 3) < 1e-9
    assert len(set(history.hashes)) == 2


def test_duplicate_rate_of_single_candidate_is_zero():
    history = PatchHistory()
    history.add(Candidate.build(0, DIFF))
    assert history.duplicate_rate() == 0.0


def test_candidate_selection_prefers_public_pass_then_smaller():
    history = PatchHistory()
    history.add(Candidate.build(0, DIFF, applies_cleanly=True, validation="fail"))
    history.add(
        Candidate.build(
            1,
            DIFF.replace("pkg/mod.py", "pkg/mod.py").replace("+y = 2", "+y = 2\n+w = 4"),
            applies_cleanly=True,
            validation="pass",
        )
    )
    assert history.best_candidate().index == 1
    assert history.public_validation()["status"] == "pass"


def test_candidate_selection_ignores_non_applicable():
    history = PatchHistory()
    history.add(Candidate.build(0, DIFF, applies_cleanly=False, validation="pass"))
    assert history.best_candidate() is None
    assert history.public_validation()["status"] == "not_applicable"


def test_diff_helpers_read_paths_and_sizes():
    assert patchutil.files_touched(DIFF) == ("pkg/mod.py",)
    assert patchutil.count_diff_lines(DIFF) == 1
    assert patchutil.parse_ok(DIFF) is True
    assert patchutil.parse_ok("not a diff") is False


def test_diff_helpers_handle_new_file_and_rename_paths():
    diff = (
        "diff --git a/new/mod.py b/new/mod.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/new/mod.py\n"
        "@@ -0,0 +1,2 @@\n"
        "+a = 1\n"
        "+b = 2\n"
    )
    assert patchutil.files_touched(diff) == ("new/mod.py",)
    assert patchutil.count_diff_lines(diff) == 2


# -- failure records -------------------------------------------------------


def test_classification_covers_the_five_categories():
    assert FailureRecord.from_output("git apply", 1, stage="apply_patch",
                                     stderr="error: patch failed: x.py:1").error_class == "patch_format"
    assert FailureRecord.from_output("pytest", 1, stage="test",
                                     stderr="E   AssertionError: assert 1 == 2").error_class == "behaviour_assertion"
    assert FailureRecord.from_output("pytest", 2, stage="test",
                                     stderr="ModuleNotFoundError: No module named 'requests'").error_class == "syntax_or_import"
    assert FailureRecord.from_output("pytest", 5, stage="test",
                                     stderr="=== no tests ran in 0.01s ===").error_class == "public_test_missing"
    assert FailureRecord.from_output("pip install -e .", 1, stage="env",
                                     stderr="Could not find a version that satisfies the requirement django==4.0").error_class == "env_setup"


def test_same_failure_hashes_equal_and_different_differs():
    text = 'Traceback:\n  File "/testbed/pkg/mod.py", line 41, in parse\nValueError: bad date'
    other_line = 'Traceback:\n  File "/testbed/pkg/mod.py", line 87, in parse\nValueError: bad date'
    assert FailureRecord.from_output("c", 1, stage="test", stderr=text).fingerprint == \
        FailureRecord.from_output("c", 1, stage="test", stderr=other_line).fingerprint
    different = text.replace("ValueError: bad date", "TypeError: nope")
    assert FailureRecord.from_output("c", 1, stage="test", stderr=text).fingerprint != \
        FailureRecord.from_output("c", 1, stage="test", stderr=different).fingerprint


def test_paths_are_normalised_relative_to_the_repo():
    record = FailureRecord.from_output(
        "pytest", 1, stage="test",
        stderr='  File "/testbed/django/db/models/query.py", line 12, in run',
    )
    assert record.repo_frames == ("django/db/models/query.py",)


def test_out_of_scope_frames_exclude_inspected_files():
    log = FailureLog()
    log.add(
        FailureRecord.from_output(
            "pytest", 1, stage="test",
            stderr=(
                '  File "/testbed/pkg/mod.py", line 41, in parse\n'
                '  File "/testbed/pkg/normalise.py", line 7, in fmt\n'
                "ValueError: bad date"
            ),
        )
    )
    inside = frozenset({"pkg/mod.py"})
    assert log.out_of_scope_frames(inside) == ("pkg/normalise.py",)
    assert log.out_of_scope_frames(frozenset({"pkg/mod.py", "pkg/normalise.py"})) == ()


def test_environment_recovery_bookkeeping():
    log = FailureLog()
    record = FailureRecord.from_output("pip install", 1, stage="env", stderr="Connection refused")
    log.add(record)
    assert log.needs_recovery_attempt() is True
    assert log.environment_failure_after_recovery() is None
    log.add(record.with_recovery())
    assert log.needs_recovery_attempt() is False
    assert log.environment_failure_after_recovery() is not None


# -- behavioural signal ----------------------------------------------------


def test_behavioural_signal_levels():
    quiet = state()
    assert quiet.behavioural_signal() == "none"

    ran_but_useless = state(
        context=ContextView(
            registered_test_commands=("python -m pytest tests/test_query.py",),
            checks_run=2,
        )
    )
    assert ran_but_useless.behavioural_signal() == "non_behavioural"

    ran_with_assertion = state(
        context=ContextView(registered_test_commands=("pytest",), checks_run=1)
    )
    ran_with_assertion.failures.add(
        FailureRecord.from_output("pytest", 1, stage="test", stderr="E   AssertionError: nope")
    )
    assert ran_with_assertion.behavioural_signal() == "behavioural"

    old_pass = state()
    old_pass.patches.add(Candidate.build(0, DIFF, applies_cleanly=True, validation="pass"))
    assert old_pass.behavioural_signal() == "behavioural"


# -- budget ----------------------------------------------------------------


def test_budget_spend_and_floor():
    budget = tier()
    budget.spend(token=1000, model_call=1, tool_call=2, wallclock_seconds=30)
    assert budget.consumed.token == 1000
    assert budget.remaining.model_call == 11
    assert budget.overrun is False
    assert budget.allows_continuation(Budget(token=2048, model_call=1, tool_call=1, wallclock_seconds=30))


def test_budget_overrun_is_recorded_not_hidden():
    budget = tier()
    budget.spend(token=99000, model_call=1)
    assert budget.overrun is True
    assert budget.exhausted_at == "token"
    assert budget.allows_continuation(Budget(token=1)) is False


def test_model_call_precheck_uses_prompt_plus_max_output():
    budget = tier()
    need = budget.check_model_call(prompt_tokens=25000, max_output_tokens=4096)
    assert need.token == 29096
    assert budget.can_afford(need) is True
    budget.spend(token=31000)
    assert budget.can_afford(need) is False
    # A single call whose prompt plus maximum output exceeds the ceiling is
    # refused before it is made, whatever the model would actually emit.
    assert tier().can_afford(tier().check_model_call(30000, 4096)) is False


# -- trace and serialisation ----------------------------------------------


def test_decision_trace_is_recorded_with_signals():
    st = state()
    st.patches.add(Candidate.build(0, DIFF, applies_cleanly=True, validation="fail"))
    entry = st.record_decision(
        "fixed_continuation_otherwise", "fixed", "fixed_continuation_otherwise", "nothing fired"
    )
    assert entry.seq == 1
    assert entry.u_dup == 0.0
    assert entry.remaining["model_call"] == 12
    assert st.last_decision.reason == "fixed_continuation_otherwise"


def test_state_json_round_trip_is_stable():
    st = state()
    st.localization = Localization.from_file_sets({"a": ["x.py"], "b": ["y.py"]})
    st.patches.add(Candidate.build(0, DIFF, validation="fail"))
    st.record_decision("interactive_on_high_duplicate_rate", "interactive",
                       "interactive_on_high_duplicate_rate", "detail")
    again = RepairState.from_dict(json.loads(st.to_json()))
    assert again.to_json() == st.to_json()
    assert again.budget.tier == "small"
    assert again.u_loc == st.u_loc


def test_replay_snapshot_clears_the_trace_and_budget_history():
    st = state()
    st.record_decision("x", "fixed", "y", "z")
    snapshot = json.loads(st.snapshot_for_replay())
    assert snapshot["decision_trace"] == []
    assert snapshot["budget_state"] is None or snapshot["budget_state"]["overrun"] is False
    assert json.loads(st.snapshot_for_replay()) == snapshot


# -- run record bridge -----------------------------------------------------


def test_run_record_from_stop_route_validates():
    st = state()
    st.patches.add(Candidate.build(0, DIFF, applies_cleanly=True, validation="pass"))
    st.record_decision("freeze_when_public_candidate_passes", "stop", "early_stop_public_pass", "done")
    st.budget.spend(token=1000, model_call=1, tool_call=1, wallclock_seconds=10)
    record = build_run_record(
        st, run_index=1, seed=0, model_version="test-model", elapsed_seconds=12.5
    )
    assert record["termination_reason"] == "early_stop_public_pass"
    assert record["evaluation_status"] == "not_run"
    assert record["route_reason"] == "early_stop_public_pass"
    assert runlog.validate(record) == [], runlog.validate(record)
    assert record["patch_hash"] == st.patches.candidates[0].hash


def test_run_record_requires_a_reason_for_continuation():
    st = state()
    st.record_decision(
        "fixed_continuation_otherwise", "fixed", "fixed_continuation_otherwise", "nothing fired"
    )
    try:
        build_run_record(st, run_index=1, seed=0, model_version="m", elapsed_seconds=1.0)
    except ValueError as exc:
        assert "termination_reason" in str(exc)
    else:
        raise AssertionError("continuation record was built without a termination reason")
    record = build_run_record(
        st, run_index=1, seed=0, model_version="m", elapsed_seconds=1.0,
        termination_reason="stagnation",
    )
    assert runlog.validate(record) == [], runlog.validate(record)


def test_run_record_without_decision_is_refused():
    try:
        build_run_record(state(), run_index=1, seed=0, model_version="m", elapsed_seconds=1.0)
    except ValueError as exc:
        assert "routing decision" in str(exc)
    else:
        raise AssertionError("record was built without a routing decision")


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
