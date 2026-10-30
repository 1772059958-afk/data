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
import math
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


@dataclass(frozen=True)
class CalibrationInputs:
    """Labels and the complete eligible population have different denominators."""

    observations: tuple[PairedObservation, ...]
    eligible_prefixes: tuple[Mapping[str, Any], ...]
    config_hash: str
    missing_pair_ids: tuple[str, ...]

    def trigger_rate(self, config: RouterConfig) -> dict[str, Any]:
        decisions = [route_for_arm('D', RepairState.from_dict(row['prefix_snapshot']), config)
                     for row in self.eligible_prefixes]
        if any(d.route == 'stop' for d in decisions):
            raise ValueError('an eligible calibration prefix became a shared stop')
        return {'probability': select_switch_probability(decisions),
                'denominator': len(decisions),
                'interactive': sum(d.route == 'interactive' for d in decisions),
                'complete_pair_count': len(self.observations),
                'missing_pair_ids': list(self.missing_pair_ids),
                'source': 'all_eligible_dev_prefixes'}


def calibration_inputs(payload: Mapping[str, Any], config: RouterConfig, *,
                       allowed_ids: Iterable[str] | None = None) -> CalibrationInputs:
    """Validate the complete DEV prefix population before producing a candidate.

    Feature-only/legacy input may still be read for diagnostic utilities, but it
    cannot determine E's deployment probability. Missing paired labels are fine;
    missing prefixes or a mismatched snapshot are not.
    """
    if (not isinstance(payload, Mapping) or payload.get('split') != 'dev'
            or payload.get('mode') != 'diagnostic' or payload.get('historical_diagnostic_only')):
        raise ValueError('calibration requires a new dev diagnostic analysis')
    if payload.get('eligible_population_complete') is not True or payload.get('prefix_unavailable_instance_ids'):
        raise ValueError('the designated prefix population is incomplete; do not estimate E from complete pairs')
    def identifiers(values, label):
        if (not isinstance(values, list) or any(not isinstance(i, str) or not i.strip() for i in values)
                or len(values) != len(set(values))):
            raise ValueError(f'{label} must be a unique instance list')
        return values
    designated = identifiers(payload.get('designated_instances'), 'designated_instances')
    eligible = identifiers(payload.get('eligible_instance_ids'), 'eligible_instance_ids')
    if not designated or set(eligible) - set(designated):
        raise ValueError('eligible prefixes must belong to the designated dev population')
    if allowed_ids is not None and set(designated) - set(allowed_ids):
        raise ValueError('calibration population contains instances outside the frozen dev split')
    if payload.get('paired_eligible') != len(eligible):
        raise ValueError('eligible count does not match the frozen eligible instance list')
    source_hash = payload.get('config_hash')
    if not isinstance(source_hash, str) or not source_hash:
        raise ValueError('calibration analysis has no source configuration identity')
    effective = payload.get('effective_config')
    if not isinstance(effective, Mapping) or RouterConfig.from_config(effective).digest != source_hash:
        raise ValueError('source effective configuration is missing or does not match its hash')
    source_settings = dict(effective)
    requested_settings = config.effective_config()
    source_settings.pop('provenance', None)
    requested_settings.pop('provenance', None)
    if source_settings != requested_settings:
        raise ValueError('calibration configuration differs from the configuration that generated the prefixes')
    rows = payload.get('eligible_prefixes')
    if not isinstance(rows, list):
        raise ValueError('all eligible dev prefix snapshots are required')
    indexed = {}
    for row in rows:
        if not isinstance(row, Mapping) or row.get('split') != 'dev':
            raise ValueError('eligible prefix must explicitly belong to dev')
        iid = row.get('instance_id')
        if iid in indexed or iid not in eligible:
            raise ValueError('duplicate or out-of-population eligible prefix')
        snapshot = row.get('prefix_snapshot')
        if not isinstance(snapshot, Mapping):
            raise ValueError('full eligible prefix snapshot required')
        state = RepairState.from_dict(snapshot)
        if (state.task.instance_id != iid or state.task.config_hash != source_hash
                or state.task.config_version != config.config_version or state.budget is None):
            raise ValueError('eligible snapshot instance/configuration/budget identity mismatch')
        if route_for_arm('A', state, config).route == 'stop':
            raise ValueError('shared-stop prefix cannot enter the eligible population')
        indexed[iid] = row
    if set(indexed) != set(eligible):
        raise ValueError('some eligible dev snapshots are missing')
    raw_observations = payload.get('observations')
    if not isinstance(raw_observations, list):
        raise ValueError('paired observations must be supplied separately')
    observations = [PairedObservation.from_dict(row) for row in raw_observations]
    _validate_observations(observations)
    for obs in observations:
        if obs.instance_id not in indexed or obs.split != 'dev':
            raise ValueError('paired label lies outside the eligible dev population')
        if obs.prefix_snapshot != indexed[obs.instance_id]['prefix_snapshot']:
            raise ValueError('paired label and eligible population use different snapshots')
    missing = sorted(set(eligible) - {obs.instance_id for obs in observations})
    if (payload.get('paired_complete') != len(observations)
            or sorted(identifiers(payload.get('unscored_paired_instances'), 'unscored_paired_instances')) != missing):
        raise ValueError('paired completeness metadata does not match observations')
    return CalibrationInputs(tuple(observations), tuple(indexed[i] for i in eligible), source_hash, tuple(missing))


def load_calibration_inputs(path: str | os.PathLike[str], config: RouterConfig, *,
                            allowed_ids: Iterable[str] | None = None) -> CalibrationInputs:
    with open(path, encoding='utf-8') as stream:
        return calibration_inputs(json.load(stream), config, allowed_ids=allowed_ids)


def _validate_observations(observations: Sequence[PairedObservation]) -> None:
    seen, hashes = set(), set()
    for obs in observations:
        if obs.instance_id in seen:
            raise ValueError('duplicate paired calibration observation')
        seen.add(obs.instance_id)
        _known_bool(obs.fixed_resolved)
        _known_bool(obs.interactive_resolved)
        if obs.split != 'dev' or not isinstance(obs.prefix_snapshot, Mapping):
            raise ValueError('calibration needs full dev prefix snapshots')
        state = RepairState.from_dict(obs.prefix_snapshot)
        if state.task.instance_id != obs.instance_id or state.budget is None or not state.task.config_hash:
            raise ValueError('paired label and prefix snapshot identity/budget mismatch')
        hashes.add(state.task.config_hash)
    if len(hashes) > 1:
        raise ValueError('calibration observations mix source configurations')


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
    _validate_observations(observations)
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
    _validate_observations(obs)
    if not grid or any(not math.isfinite(float(t)) or not 0 <= float(t) <= 1 for t in grid):
        raise ValueError('threshold grid must contain finite values within [0, 1]')
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
    if config is not None:
        count = config.raw.get('prefix', {}).get('n_candidates', 2)
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            raise ValueError('prefix.n_candidates must be a positive integer')
        maximum = (count - 1) / count
        dormant = [float(t) for t in grid if float(t) >= maximum]
        if dormant:
            report.warnings.append(
                f'duplicate-rate rule is unreachable at thresholds {dormant}: '
                f'{count} prefix candidates have maximum repeat rate {maximum:g}, '
                'and the trigger uses a strict greater-than comparison')
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
