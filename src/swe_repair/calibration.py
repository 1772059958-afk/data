"""Threshold selection for the routing rules, on the dev split only.

Section 4.2 promises to pick the two thresholds from a small grid on the 23 dev
instances, then freeze them before the main experiment, and to report both the
default and the sensitivity results. This module implements exactly that and
nothing more:

* the input is a list of paired branch outcomes (the experiment of section 6.4:
  same prefix state, one fixed continuation, one interactive continuation);
* the objective is auditable and stated in advance: fewest routing regrets
  first, then most instances resolved by the branch that was chosen, and only
  then the lower escalation share and higher thresholds, because the proposal asks for the simplest rule
  that works rather than the most finely fitted one;
* the dev split is tiny. Every report carries the sample counts and warns when
  they are too small to separate two grid points.

Nothing here runs automatically during the main experiment: calibration happens
once, its output is copied into the frozen config, and the config hash then
appears in every run record.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence
from pathlib import Path

from .router import RouterConfig, route_for_arm
from .state import RepairState

# Below this many paired observations a grid comparison cannot separate two
# thresholds on the dev split, so the report says so instead of picking a winner.
MIN_USEFUL_SAMPLES = 8

WINNERS = ("fixed", "interactive", "tie")


@dataclass(frozen=True)
class PairedObservation:
    """One instance repaired twice from the same frozen prefix state."""

    instance_id: str
    fixed_resolved: bool
    interactive_resolved: bool
    u_loc: float | None = None
    u_dup: float = 0.0
    prefix_snapshot: Mapping[str, Any] | None = None
    split: str = "dev"

    @property
    def winner(self) -> str:
        if self.fixed_resolved and not self.interactive_resolved:
            return "fixed"
        if self.interactive_resolved and not self.fixed_resolved:
            return "interactive"
        return "tie"

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "fixed_resolved": self.fixed_resolved,
            "interactive_resolved": self.interactive_resolved,
            "u_loc": self.u_loc,
            "u_dup": self.u_dup,
            "winner": self.winner,
            "prefix_snapshot": self.prefix_snapshot, "split": self.split,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PairedObservation":
        return cls(
            instance_id=str(payload["instance_id"]),
            fixed_resolved=_known_bool(payload["fixed_resolved"]),
            interactive_resolved=_known_bool(payload["interactive_resolved"]),
            u_loc=payload.get("u_loc"),
            u_dup=float(payload.get("u_dup", 0.0)),
            prefix_snapshot=payload.get("prefix_snapshot"), split=payload.get("split", "dev"),
        )


def _known_bool(value):
    if not isinstance(value, bool):
        raise ValueError('calibration requires known behavioural outcomes, not missing/error verdicts')
    return value


def load_observations(path: str | os.PathLike[str]) -> list[PairedObservation]:
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    if isinstance(payload, dict) and payload.get('split', 'dev') != 'dev':
        raise ValueError('calibration is restricted to the dev split')
    rows = payload["observations"] if isinstance(payload, dict) else payload
    return [PairedObservation.from_dict(row) for row in rows]


def _default_config() -> RouterConfig:
    return RouterConfig.from_file(Path(__file__).resolve().parents[2] / 'configs/proposal_v1.json')


def decide(snapshot: Mapping[str, Any], a_loc: float, a_dup: float,
           config: RouterConfig | None = None) -> str:
    """Replay the COMPLETE D router against its real prefix state, without labels."""
    if not isinstance(snapshot, Mapping):
        raise ValueError('a full prefix snapshot is required; summary features are insufficient')
    state = RepairState.from_dict(snapshot)
    if state.budget is None:
        raise ValueError('full budget consumption is required in a calibration snapshot')
    cfg = (config or _default_config()).with_thresholds(a_loc, a_dup)
    return route_for_arm('D', state, cfg).route


@dataclass
class GridScore:
    localization_threshold: float
    duplicate_threshold: float
    regrets: int = 0
    agreements: int = 0
    interactive_share: float = 0.0
    ties: int = 0
    compared: int = 0
    resolved: int = 0
    excluded_stops: int = 0

    def key(self):
        """Frozen tie-break: regret, solved count, switch share, higher thresholds."""
        return (self.regrets, -self.resolved, self.interactive_share,
                -self.localization_threshold, -self.duplicate_threshold)

    def to_dict(self) -> dict[str, Any]:
        return {
            "localization_threshold": self.localization_threshold,
            "duplicate_threshold": self.duplicate_threshold,
            "regrets": self.regrets,
            "agreements": self.agreements,
            "ties": self.ties,
            "compared": self.compared,
            "interactive_share": self.interactive_share,
            "resolved": self.resolved, "excluded_stops": self.excluded_stops,
        }


def score_grid_point(
    observations: Sequence[PairedObservation],
    a_loc: float,
    a_dup: float,
    config: RouterConfig | None = None,
) -> GridScore:
    score = GridScore(a_loc, a_dup)
    switches = 0
    for obs in observations:
        if obs.split != 'dev':
            raise ValueError('calibration is restricted to the dev split')
        _known_bool(obs.fixed_resolved)
        _known_bool(obs.interactive_resolved)
        if obs.prefix_snapshot is None:
            raise ValueError('full prefix snapshot missing; legacy feature-only data cannot calibrate the router')
        if obs.prefix_snapshot.get('task_manifest', {}).get('instance_id') != obs.instance_id:
            raise ValueError('paired label and prefix snapshot refer to different instances')
        action = decide(obs.prefix_snapshot, a_loc, a_dup, config)
        if action == 'stop':
            score.excluded_stops += 1
            continue
        score.resolved += int(obs.interactive_resolved if action == 'interactive' else obs.fixed_resolved)
        switched = action == "interactive"
        if switched:
            switches += 1
        score.compared += 1
        if obs.winner == "tie":
            # The data cannot tell the two branches apart here, so it neither
            # rewards nor punishes the choice.
            score.ties += 1
            score.agreements += 1
            continue
        if obs.winner == action:
            score.agreements += 1
        else:
            score.regrets += 1
    score.interactive_share = (switches / score.compared) if score.compared else 0.0
    return score


@dataclass
class CalibrationReport:
    scores: list[GridScore] = field(default_factory=list)
    chosen: GridScore | None = None
    samples: int = 0
    samples_with_localization: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "samples": self.samples,
            "samples_with_localization": self.samples_with_localization,
            "chosen": self.chosen.to_dict() if self.chosen else None,
            "grid": [s.to_dict() for s in self.scores],
            "warnings": list(self.warnings),
        }

    def sensitivity(self) -> dict[str, Any]:
        """How much the outcome moves between neighbouring grid points."""
        if not self.scores:
            return {}
        best = min(s.regrets for s in self.scores)
        worst = max(s.regrets for s in self.scores)
        shares = [s.interactive_share for s in self.scores]
        return {
            "regret_range": [best, worst],
            "regret_spread": worst - best,
            "interactive_share_range": [min(shares), max(shares)],
            "stable": (worst - best) <= 1,
        }

    def write(self, path: str | os.PathLike[str]) -> str:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        payload = self.to_dict()
        payload["sensitivity"] = self.sensitivity()
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
        return os.fspath(path)


def select_thresholds(
    observations: Iterable[PairedObservation],
    grid: Sequence[float] = (0.25, 0.50, 0.75),
    config: RouterConfig | None = None,
) -> CalibrationReport:
    """Score every (u_loc, u_dup) threshold pair and pick the simplest winner."""
    obs = list(observations)
    report = CalibrationReport(samples=len(obs))
    report.samples_with_localization = sum(
        1 for o in obs if o.prefix_snapshot and RepairState.from_dict(o.prefix_snapshot).u_loc is not None)
    for a_loc in grid:
        for a_dup in grid:
            report.scores.append(score_grid_point(obs, float(a_loc), float(a_dup), config))
    if report.scores:
        candidate = min(report.scores, key=GridScore.key)
        if candidate.compared:
            report.chosen = candidate
        else:
            report.warnings.append('no eligible paired prefixes; no threshold can be selected')

    if len(obs) < MIN_USEFUL_SAMPLES:
        report.warnings.append(
            f"only {len(obs)} paired observations on the dev split; a grid comparison at this "
            "sample size is indicative, not decisive"
        )
    if report.samples_with_localization < MIN_USEFUL_SAMPLES:
        report.warnings.append(
            f"u_loc is available for only {report.samples_with_localization} instance(s): "
            "the localisation rule cannot be calibrated from this"
        )
    non_tie = [o for o in obs if o.winner != "tie"]
    if non_tie and all(o.winner == "fixed" for o in non_tie):
        report.warnings.append(
            "every paired observation favoured the fixed branch: interaction never helped on "
            "the dev split, so the routing question cannot be answered from it"
        )
    if non_tie and all(o.winner == "interactive" for o in non_tie):
        report.warnings.append(
            "every paired observation favoured the interactive branch: this is the arm C "
            "degeneracy, where routing has nothing to decide"
        )
    if report.chosen is not None and report.chosen.regrets == 0:
        ties_only = report.chosen.ties == report.chosen.compared
        if ties_only:
            report.warnings.append("all observations are ties; no threshold is justified by this data")
    return report


def select_switch_probability(decisions: Iterable[Any]) -> float:
    """Match D's dev trigger rate among ELIGIBLE prefixes, never branch win rate.

    Accept route strings or actual Decision objects. STOP prefixes are shared by
    all routed arms and excluded from the coin's conditional probability.
    """
    routes = [d if isinstance(d, str) else getattr(d, 'route', None) for d in decisions]
    if any(r not in ('fixed', 'interactive', 'stop') for r in routes):
        raise ValueError('pass actual D routing decisions, not outcome/winner labels')
    eligible = [r for r in routes if r != 'stop']
    if not eligible:
        raise ValueError('no eligible prefixes for trigger-rate matching')
    return eligible.count('interactive') / len(eligible)


def summarise_pairs(observations: Iterable[PairedObservation]) -> dict[str, Any]:
    """The headline numbers the paired-branch experiment reports (section 6.4)."""
    obs = list(observations)
    if not obs:
        return {"n": 0}
    fixed = sum(1 for o in obs if o.fixed_resolved)
    interactive = sum(1 for o in obs if o.interactive_resolved)
    return {
        "n": len(obs),
        "fixed_resolved": fixed,
        "interactive_resolved": interactive,
        "fixed_only": sum(1 for o in obs if o.winner == "fixed"),
        "interactive_only": sum(1 for o in obs if o.winner == "interactive"),
        "both": sum(1 for o in obs if o.fixed_resolved and o.interactive_resolved),
        "neither": sum(1 for o in obs if not o.fixed_resolved and not o.interactive_resolved),
        "fixed_rate": fixed / len(obs),
        "interactive_rate": interactive / len(obs),
    }
