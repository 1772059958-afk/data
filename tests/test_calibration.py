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

from swe_repair.calibration import (  # noqa: E402
    PairedObservation,
    decide,
    load_observations,
    score_grid_point,
    select_switch_probability,
    select_thresholds,
    summarise_pairs,
)


def separable() -> list[PairedObservation]:
    """Interaction wins exactly when u_loc is high; eight instances, no ties."""
    out = []
    for i in range(4):
        out.append(PairedObservation(f"hi-{i}", fixed_resolved=False, interactive_resolved=True,
                                    u_loc=0.8, u_dup=0.0))
    for i in range(4):
        out.append(PairedObservation(f"lo-{i}", fixed_resolved=True, interactive_resolved=False,
                                    u_loc=0.2, u_dup=0.0))
    return out


def test_decide_mirrors_the_rule_semantics():
    assert decide(0.9, 0.0, 0.5, 0.5) == "interactive"
    assert decide(0.4, 0.0, 0.5, 0.5) == "fixed"
    assert decide(None, 0.9, 0.5, 0.5) == "interactive"  # missing u_loc is not disagreement
    assert decide(None, 0.1, 0.5, 0.5) == "fixed"


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
        boundary.append(PairedObservation(f"hi{i}", False, True, u_loc=0.85))
        boundary.append(PairedObservation(f"mid{i}", False, True, u_loc=0.70))
        boundary.append(PairedObservation(f"lo{i}", True, False, u_loc=0.30))
    report = select_thresholds(boundary, grid=(0.25, 0.50, 0.75))
    assert report.chosen.localization_threshold == 0.50  # 0.75 would regret the 0.70 cases
    assert report.chosen.regrets == 0
    sensitivity = report.sensitivity()
    assert sensitivity["stable"] is False
    assert sensitivity["regret_spread"] == 3


def test_small_sample_and_ties_are_called_out():
    tiny = [
        PairedObservation("a", True, True, u_loc=0.9),
        PairedObservation("b", False, False, u_loc=0.1),
    ]
    report = select_thresholds(tiny)
    assert any("indicative, not decisive" in w for w in report.warnings), report.warnings
    assert any("all observations are ties" in w for w in report.warnings), report.warnings


def test_one_sided_outcome_is_reported_as_uninformative():
    fixed_always = [
        PairedObservation(f"i{i}", fixed_resolved=True, interactive_resolved=False, u_loc=0.9)
        for i in range(10)
    ]
    warnings = select_thresholds(fixed_always).warnings
    assert any("interaction never helped" in w for w in warnings), warnings

    interactive_always = [
        PairedObservation(f"j{i}", fixed_resolved=False, interactive_resolved=True, u_loc=0.1)
        for i in range(10)
    ]
    warnings = select_thresholds(interactive_always).warnings
    assert any("arm C degeneracy" in w for w in warnings), warnings


def test_switch_probability_is_the_observed_win_rate():
    assert select_switch_probability(separable()) == 0.5
    only_fixed = [PairedObservation("a", True, False)]
    assert select_switch_probability(only_fixed) == 0.0


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
