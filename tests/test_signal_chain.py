"""The signal chain that decides whether arm D can ever differ from arm C.

Arm C escalates on every continuable failure; arm D follows the frozen rule
order. D can therefore only choose "fixed" if rules 4-7 all decline, and rule 7
declines only when ``behavioural_signal()`` is ``"behavioural"``. That makes the
following a regression test rather than a curiosity: if the prefix stops
recording classified failures, ``behavioural_signal()`` silently falls back to
``"non_behavioural"``, rule 7 becomes a catch-all, and D collapses into C with no
error anywhere.

The last test here records the *opposite* problem: rule 6 fires as soon as the
latest failure's traceback mentions a repository file the run never read, and a
pytest traceback almost always names the test file. So connecting the signal
chain is necessary but not sufficient for the two arms to diverge.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

from swe_repair.budget import BudgetState  # noqa: E402
from swe_repair.router import RouterConfig, route_cascade, route_for_arm  # noqa: E402
from swe_repair.state import (  # noqa: E402
    Candidate,
    ContextView,
    FailureRecord,
    LocalizationPass,
    PatchHistory,
    RepairState,
    TaskManifest,
)

SOURCE_FILE = "astroid/nodes/node_classes.py"
TEST_FILE = "tests/test_node_classes.py"

DIFF = (
    f"--- a/{SOURCE_FILE}\n"
    f"+++ b/{SOURCE_FILE}\n"
    "@@ -1,1 +1,1 @@\n"
    "-x = 1\n"
    "+x = 2\n"
)


def _config() -> RouterConfig:
    """The real frozen rule order, with placeholder thresholds."""
    return RouterConfig.from_file(
        os.path.join(REPO, "configs", "frozen_v1.json")
    ).with_thresholds(
        localization_disagreement=0.5, duplicate_rate=0.5
    )


def _state(*, with_failure: bool, frame_path: str = SOURCE_FILE) -> RepairState:
    state = RepairState(task=TaskManifest(
        instance_id="probe__probe-1",
        repo="probe",
        base_commit="deadbeef",
        config_version="test",
        config_hash="test",
    ))
    # Two identical localisations give u_loc = 0, so rule 4 stays quiet.
    state.localization.add(LocalizationPass("lexical", frozenset({SOURCE_FILE})))
    state.localization.add(LocalizationPass("model", frozenset({SOURCE_FILE})))

    history = PatchHistory()
    # Distinct diffs keep u_dup at 0; validation="fail" keeps rule 1 quiet.
    history.add(Candidate.build(0, DIFF, applies_cleanly=True, validation="fail"))
    history.add(Candidate.build(1, DIFF.replace("x = 2", "x = 3"),
                                applies_cleanly=True, validation="fail"))
    state.patches = history

    state.context = ContextView(
        indexed_paths=frozenset({SOURCE_FILE}),
        read_files=frozenset({SOURCE_FILE}),
        registered_test_commands=(TEST_FILE,),
        checks_run=1,
    )
    if with_failure:
        record = FailureRecord.from_output(
            "python -m pytest " + TEST_FILE,
            1,
            stage="test",
            stdout=(
                "Traceback (most recent call last):\n"
                f'  File "/testbed/{frame_path}", line 10, in foo\n'
                '    raise AssertionError("boom")\n'
                "AssertionError: boom\n"
            ),
            repo_root="/testbed",
        )
        state.failures.add(record)

    budget = BudgetState.for_tier("demo", {"demo": {
        "token": 200_000, "model_call": 12, "tool_call": 20,
        "wallclock_seconds": 600.0,
    }})
    state.budget = budget
    return state


def test_failing_public_test_is_classified_as_a_behaviour_assertion():
    record = _state(with_failure=True).failures.latest
    assert record is not None
    assert record.error_class == "behaviour_assertion"


def test_signal_is_behavioural_only_when_a_classified_failure_exists():
    assert _state(with_failure=True).behavioural_signal() == "behavioural"
    # Without the record the run knows a check ran but not what it meant.
    assert _state(with_failure=False).behavioural_signal() == "non_behavioural"


def test_rule_seven_declines_once_the_signal_is_behavioural():
    rules = {r["rule"]: r for r in _rules(_state(with_failure=True))}
    assert rules["interactive_when_no_behavioural_signal"]["fires"] is False


def test_rule_seven_takes_over_when_the_signal_is_missing():
    """This is the failure mode that made D identical to C in the first run."""
    rules = {r["rule"]: r for r in _rules(_state(with_failure=False))}
    assert rules["interactive_when_no_behavioural_signal"]["fires"] is True


def test_d_and_c_diverge_when_the_traceback_stays_inside_the_context():
    cfg = _config()
    state = _state(with_failure=True, frame_path=SOURCE_FILE)
    assert route_for_arm("C", state, cfg).route == "interactive"
    assert route_for_arm("D", state, cfg, allow_uncalibrated=True).route == "fixed"


def test_rule_six_pre_empts_when_the_traceback_names_an_unread_file():
    """Known limitation: pytest tracebacks name the test file, which is unread.

    Documented here so that "D still equals C" is read as this rule firing, not
    as the signal chain being broken again.
    """
    cfg = _config()
    state = _state(with_failure=True, frame_path=TEST_FILE)
    rules = {r["rule"]: r for r in _rules(state)}
    assert rules["interactive_on_out_of_scope_stack_evidence"]["fires"] is True
    assert route_for_arm("D", state, cfg, allow_uncalibrated=True).route == "interactive"


def _rules(state: RepairState):
    from swe_repair.router import evaluate_all
    return evaluate_all(state, _config(), allow_uncalibrated=True)
