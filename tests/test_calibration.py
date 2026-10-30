"""Self-checks for the dev-split threshold calibration.

Runs under pytest or as plain ``python tests/test_calibration.py``.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):  # pragma: no cover
    pass

from fractions import Fraction
from swe_repair.state import RepairState, TaskManifest, Localization, ContextView, FailureRecord, Candidate
from swe_repair.budget import BudgetState, Budget

from swe_repair.calibration import (  # noqa: E402
    PairedObservation,
    decide,
    load_observations,
    score_grid_point,
    select_switch_probability,
    select_thresholds,
    summarise_pairs,
)


def snapshot(u_loc=0.0, *, syntax_error=False, public_pass=False):
    fraction = Fraction(str(u_loc))
    count = fraction.denominator
    overlap = count - fraction.numerator
    state = RepairState(TaskManifest('example__repo-1', 'example/repo', 'base', 'test', 'hash'))
    state.localization = Localization.from_file_sets({
        'one': [f'pkg/p{i}.py' for i in range(count)],
        'two': [f'pkg/p{i}.py' for i in range(overlap)],
    })
    state.context = ContextView(checks_run=1)
    state.budget = BudgetState('test', Budget(200000, 12, 80, 1200))
    state.patches.add(Candidate.build(0, '--- a/pkg/p.py\n+++ b/pkg/p.py\n@@ -1 +1 @@\n-a\n+b\n',
                                      applies_cleanly=True, validation='pass' if public_pass else 'fail'))
    state.failures.add(FailureRecord.from_output('check', 1, stage='syntax_check' if syntax_error else 'test',
                         stdout='SyntaxError: invalid' if syntax_error else 'AssertionError: behaviour'))
    return state.to_dict()


def observation(iid, fixed, interactive, u_loc=0.0, **kwargs):
    snap = snapshot(u_loc, **kwargs)
    snap['task_manifest']['instance_id'] = iid
    return PairedObservation(iid, fixed, interactive, u_loc=u_loc, prefix_snapshot=snap)


def separable() -> list[PairedObservation]:
    """Interaction wins exactly when u_loc is high; eight instances, no ties."""
    out = []
    for i in range(4):
        out.append(observation(f"hi-{i}", False, True, u_loc=0.8))
    for i in range(4):
        out.append(observation(f"lo-{i}", True, False, u_loc=0.2))
    return out


def test_decide_replays_the_complete_router():
    assert decide(snapshot(0.9), 0.5, 0.5) == 'interactive'
    assert decide(snapshot(0.4), 0.5, 0.5) == 'fixed'
    # A local syntax error pre-empts even a high numerical disagreement.
    assert decide(snapshot(0.9, syntax_error=True), 0.5, 0.5) == 'fixed'
    assert decide(snapshot(0.9, public_pass=True), 0.5, 0.5) == 'stop'


def test_grid_scoring_counts_regrets_and_agreements():
    score = score_grid_point(separable(), 0.5, 0.5)
    assert score.compared == 8
    assert score.regrets == 0
    assert score.agreements == 8
    assert score.interactive_share == 0.5
    bad = score_grid_point(separable(), 1.0, 1.0)  # never switch
    assert bad.regrets == 4
    assert bad.interactive_share == 0.0


def test_calibration_picks_the_separating_threshold():
    report = select_thresholds(separable(), grid=(0.25, 0.50, 0.75))
    assert report.chosen is not None
    # 0.25, 0.50 and 0.75 separate this data equally well, so the tie-break
    # picks the least-switching rule.
    assert report.chosen.localization_threshold == 0.75
    assert report.chosen.duplicate_threshold == 0.75
    assert report.chosen.regrets == 0
    assert report.warnings == [], report.warnings


def test_calibration_report_is_serialisable_and_has_sensitivity():
    report = select_thresholds(separable(), grid=(0.25, 0.50, 0.75))
    blob = json.dumps(report.to_dict(), ensure_ascii=False)
    assert "localization_threshold" in blob
    sensitivity = report.sensitivity()
    assert sensitivity["stable"] is True
    assert sensitivity["regret_range"] == [0, 0]
    with tempfile.TemporaryDirectory() as tmp:
        path = report.write(os.path.join(tmp, "calibration.json"))
        with open(path, encoding="utf-8") as fh:
            written = json.load(fh)
        assert written["chosen"]["regrets"] == 0


def test_calibration_separates_thresholds_when_the_data_allows_it():
    boundary = []
    for i in range(3):
        boundary.append(observation(f"hi{i}", False, True, u_loc=0.85))
        boundary.append(observation(f"mid{i}", False, True, u_loc=0.70))
        boundary.append(observation(f"lo{i}", True, False, u_loc=0.30))
    report = select_thresholds(boundary, grid=(0.25, 0.50, 0.75))
    assert report.chosen.localization_threshold == 0.50  # 0.75 would regret the 0.70 cases
    assert report.chosen.regrets == 0
    sensitivity = report.sensitivity()
    assert sensitivity["stable"] is False
    assert sensitivity["regret_spread"] == 3


def test_small_sample_and_ties_are_called_out():
    tiny = [
        observation("a", True, True, u_loc=0.9),
        observation("b", False, False, u_loc=0.1),
    ]
    report = select_thresholds(tiny)
    assert any("indicative, not decisive" in w for w in report.warnings), report.warnings
    assert any("all observations are ties" in w for w in report.warnings), report.warnings


def test_one_sided_outcome_is_reported_as_uninformative():
    fixed_always = [
        observation(f"i{i}", True, False, u_loc=0.9)
        for i in range(10)
    ]
    warnings = select_thresholds(fixed_always).warnings
    assert any("interaction never helped" in w for w in warnings), warnings

    interactive_always = [
        observation(f"j{i}", False, True, u_loc=0.1)
        for i in range(10)
    ]
    warnings = select_thresholds(interactive_always).warnings
    assert any("arm C degeneracy" in w for w in warnings), warnings


def test_switch_probability_matches_d_trigger_rate_excluding_stops():
    assert select_switch_probability(['interactive', 'fixed', 'stop']) == 0.5
    assert select_switch_probability(['fixed', 'fixed']) == 0.0
    assert select_switch_probability(['interactive', 'interactive', 'fixed']) == 2 / 3
    try:
        select_switch_probability(separable())
    except ValueError:
        pass
    else:
        raise AssertionError('outcome win rate was incorrectly accepted as a routing probability')


def test_calibration_rejects_feature_only_legacy_and_test_split():
    for obs in [PairedObservation('legacy', False, True, u_loc=0.9),
                PairedObservation('test', False, True, prefix_snapshot=snapshot(0.9), split='test')]:
        try:
            select_thresholds([obs])
        except ValueError:
            pass
        else:
            raise AssertionError('invalid calibration input accepted')


def test_shared_stops_are_excluded_from_branch_calibration():
    observations = separable() + [observation('stopped', True, False, 0.9, public_pass=True)]
    score = score_grid_point(observations, 0.5, 0.5)
    assert score.compared == 8 and score.excluded_stops == 1
    assert score.interactive_share == 0.5


def test_pair_summary_counts_the_four_outcome_cells():
    summary = summarise_pairs(separable())
    assert summary["n"] == 8
    assert summary["fixed_only"] == 4
    assert summary["interactive_only"] == 4
    assert summary["both"] == 0
    assert summary["neither"] == 0
    assert summary["fixed_rate"] == 0.5


def test_observations_load_from_disk():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "pairs.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"observations": [o.to_dict() for o in separable()]}, fh)
        loaded = load_observations(path)
        assert len(loaded) == 8
        assert loaded[0].winner == "interactive"


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


def test_empty_calibration_does_not_invent_thresholds():
    report = select_thresholds([])
    assert report.chosen is None
    assert any('no eligible' in w for w in report.warnings)
