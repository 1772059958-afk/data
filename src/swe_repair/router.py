"""The router: the frozen rule order from section 4.2 of the proposal.

The router reads the observable state and returns one of three branches:

* ``stop``        freeze the candidate (public tests passed) or give up
                  (environment failure after one recovery, budget insufficient)
* ``interactive`` continue in the restricted interactive executor
* ``fixed``       continue in the fixed workflow

Three properties are deliberate:

1. the rule *order* comes from ``configs/proposal_v1.json``, not from this file.
   A rule name in the config with no implementation raises at load time, so the
   protocol cannot drift away from the code silently;
2. a numeric rule whose threshold is still ``null`` in the config refuses to
   fire instead of quietly using a default. Until the dev-split calibration is
   recorded, the honest answer is "not decided yet";
3. the arms share the same stop rules and differ only in how a *continuable*
   failure is routed. Arm C sends every eligible failure to interaction, arm E
   switches at a fixed probability, arm D decides from evidence.

The router never sees evaluation labels. It only reads a ``RepairState``.
"""

from __future__ import annotations

import json
import os
import random
import copy
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, NamedTuple

from .budget import ASPECTS, Budget, tier_table
from .patchutil import is_source_path
from .runlog import config_hash as _config_hash
from .state import RepairState

ARMS = ("A", "B", "C", "D", "E")

# Engineering floors, not tuned parameters: below these a continuation cannot
# produce a usable observation, so continuing would only burn budget. They are
# overridable from the config so the frozen values stay in one place.
DEFAULT_MIN_CONTINUATION = Budget(token=2048, model_call=1, tool_call=1, wallclock_seconds=30.0)


class UncalibratedThreshold(RuntimeError):
    """Raised when a rule needs a threshold that is still pending calibration."""


class Decision(NamedTuple):
    """One routing decision: which rule fired, which branch, and why."""

    rule: str
    route: str
    reason: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"rule": self.rule, "route": self.route, "reason": self.reason, "detail": self.detail}


@dataclass
class RouterConfig:
    """The routing-relevant part of the frozen experiment config."""

    rule_order: tuple[str, ...]
    localization_disagreement_threshold: float | None
    duplicate_rate_threshold: float | None
    threshold_grid: tuple[float, ...] = (0.25, 0.50, 0.75)
    prefix_fraction: float = 0.30
    stagnation_patience: int = 3
    switch_probability: float | None = None
    min_continuation: Budget = DEFAULT_MIN_CONTINUATION
    config_version: str = "unknown"
    raw: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_config(cls, raw: Mapping[str, Any]) -> "RouterConfig":
        raw = copy.deepcopy(dict(raw))
        router = raw.get("router", {})
        order = tuple(router.get("rule_order", ()))
        unknown = [name for name in order if name not in RULES]
        if unknown:
            raise ValueError(
                "config names routing rules with no implementation: " + ", ".join(unknown)
            )
        if not order:
            raise ValueError("config has an empty rule order")
        if len(set(order)) != len(order):
            raise ValueError('duplicate routing rule')
        for key in ('localization_disagreement_threshold', 'duplicate_rate_threshold', 'switch_probability'):
            value = router.get(key)
            if value is not None and (not isinstance(value, (int, float)) or not 0 <= value <= 1):
                raise ValueError(f'{key} must be within [0, 1]')
        grid = tuple(float(x) for x in router.get("threshold_grid", (0.25, 0.50, 0.75)))
        floor = router.get("min_continuation")
        return cls(
            rule_order=order,
            localization_disagreement_threshold=router.get("localization_disagreement_threshold"),
            duplicate_rate_threshold=router.get("duplicate_rate_threshold"),
            threshold_grid=grid,
            prefix_fraction=float(raw.get("prefix", {}).get("prefix_fraction", 0.30)),
            stagnation_patience=int(raw.get("interaction", {}).get("stagnation_patience", 3)),
            switch_probability=router.get("switch_probability"),
            min_continuation=Budget.from_mapping(floor) if floor else DEFAULT_MIN_CONTINUATION,
            config_version=str(raw.get("config_version", "unknown")),
            raw=raw,
        )

    @classmethod
    def from_file(cls, path: str | os.PathLike[str]) -> "RouterConfig":
        with open(path, encoding="utf-8") as fh:
            return cls.from_config(json.load(fh))

    @property
    def digest(self) -> str:
        """Must equal the ``config_hash`` written into every run record."""
        return _config_hash(self.effective_config())

    def effective_config(self):
        raw = copy.deepcopy(dict(self.raw))
        raw.setdefault('router', {}).update({
            'rule_order': list(self.rule_order),
            'localization_disagreement_threshold': self.localization_disagreement_threshold,
            'duplicate_rate_threshold': self.duplicate_rate_threshold,
            'switch_probability': self.switch_probability,
            'min_continuation': self.min_continuation.as_dict(),
        })
        raw.setdefault('prefix', {})['prefix_fraction'] = self.prefix_fraction
        raw.setdefault('interaction', {})['stagnation_patience'] = self.stagnation_patience
        return raw

    def budget_tiers(self) -> dict[str, dict[str, Any]]:
        return tier_table(self.raw.get("budget_tiers", ()))

    def threshold(self, name: str, allow_uncalibrated: bool = False) -> float | None:
        values = {
            "localization_disagreement": self.localization_disagreement_threshold,
            "duplicate_rate": self.duplicate_rate_threshold,
        }
        if name not in values:
            raise KeyError(name)
        value = values[name]
        if value is None and not allow_uncalibrated:
            raise UncalibratedThreshold(
                f"{name} threshold is still pending calibration; fix it on the dev split first"
            )
        return value

    def threshold_or_none(self, name: str) -> float | None:
        """The raw value, for rule bodies: the caller has already enforced calibration."""
        return self.threshold(name, allow_uncalibrated=True)

    def with_thresholds(
        self,
        localization_disagreement: float | None = None,
        duplicate_rate: float | None = None,
    ) -> "RouterConfig":
        """Copy with explicit thresholds, used by the calibration grid."""
        return RouterConfig(
            rule_order=self.rule_order,
            localization_disagreement_threshold=(
                self.localization_disagreement_threshold
                if localization_disagreement is None
                else localization_disagreement
            ),
            duplicate_rate_threshold=(
                self.duplicate_rate_threshold if duplicate_rate is None else duplicate_rate
            ),
            threshold_grid=self.threshold_grid,
            prefix_fraction=self.prefix_fraction,
            stagnation_patience=self.stagnation_patience,
            switch_probability=self.switch_probability,
            min_continuation=self.min_continuation,
            config_version=self.config_version,
            raw=self.raw,
        )

    @property
    def calibrated(self) -> bool:
        return (
            self.localization_disagreement_threshold is not None
            and self.duplicate_rate_threshold is not None
        )


# --------------------------------------------------------------------------
# individual rules
# --------------------------------------------------------------------------


def _stop_freeze(state: RepairState, cfg: RouterConfig) -> str | None:
    passing = [c.index for c in state.patches.applicable() if c.validation == "pass"]
    if not passing:
        return None
    best = state.patches.best_candidate()
    chosen = best.index if best else passing[0]
    return f"public validation passed on candidate#{passing[0]}; frozen candidate#{chosen}"


def _stop_env_failure(state: RepairState, cfg: RouterConfig) -> str | None:
    record = state.failures.environment_failure_after_recovery()
    if record is None:
        return None
    first_line = record.message_head.splitlines()[0] if record.message_head else record.command
    return (
        f"environment failure survived {record.recovery_attempts} deterministic "
        f"recovery attempt(s): {first_line}"
    )


def _stop_budget(state: RepairState, cfg: RouterConfig) -> str | None:
    if state.budget is None:
        return None
    if state.budget.allows_continuation(cfg.min_continuation):
        return None
    remaining = state.budget.remaining
    short = [a for a in ASPECTS if getattr(remaining, a) < getattr(cfg.min_continuation, a)]
    return (
        f"remaining {remaining.as_dict()} cannot fund one more step; "
        f"short on {', '.join(short) or 'none'}"
    )


def _interactive_localization(state: RepairState, cfg: RouterConfig) -> str | None:
    threshold = cfg.threshold_or_none("localization_disagreement")
    if threshold is None:
        return None
    u_loc = state.u_loc
    if u_loc is None:
        return None  # no informative pair: missing, which is not disagreement
    if u_loc <= threshold:
        return None
    return (
        f"u_loc={u_loc:.3f} > {threshold:.3f} over "
        f"{len(state.localization.passes)} localisation passes"
    )


def _interactive_duplicates(state: RepairState, cfg: RouterConfig) -> str | None:
    threshold = cfg.threshold_or_none("duplicate_rate")
    if threshold is None:
        return None
    u_dup = state.u_dup
    if u_dup <= threshold:
        return None
    return (
        f"u_dup={u_dup:.3f} > {threshold:.3f} over "
        f"{len(state.patches.candidates)} candidates"
    )


def _interactive_out_of_scope(state: RepairState, cfg: RouterConfig) -> str | None:
    # Test runners and test files do not establish an unseen SOURCE dependency.
    frames = tuple(p for p in state.out_of_scope_frames() if is_source_path(p))
    if not frames:
        return None
    return "stack points outside the inspected context: " + ", ".join(frames[:3])


def _fixed_no_signal(state: RepairState, cfg: RouterConfig) -> str | None:
    signal = state.behavioural_signal()
    if signal == "behavioural":
        return None
    return f"insufficient evidence ({signal}); conservatively continue fixed"


def _fixed_local_error(state: RepairState, cfg: RouterConfig) -> str | None:
    latest = state.failures.latest
    if latest and latest.error_class in ('patch_format', 'syntax_or_import'):
        if not _interactive_out_of_scope(state, cfg):
            return 'local application or syntax/import error without unseen source evidence'
    return None


def _fixed_otherwise(state: RepairState, cfg: RouterConfig) -> str | None:
    return "no interactive trigger fired; continue the fixed workflow"


class _Rule(NamedTuple):
    name: str
    route: str
    reason: str
    fn: Callable[[RepairState, RouterConfig], str | None]
    needs_threshold: str | None = None


RULES: dict[str, _Rule] = {
    rule.name: rule
    for rule in (
        _Rule("stop_on_env_failure_after_one_recovery", "stop", "stop_env_failure", _stop_env_failure),
        _Rule("stop_when_budget_insufficient", "stop", "stop_budget_insufficient", _stop_budget),
        _Rule("freeze_when_public_candidate_passes", "stop", "early_stop_public_pass", _stop_freeze),
        _Rule("fixed_on_local_application_or_syntax_error", "fixed", "fixed_on_local_application_or_syntax_error", _fixed_local_error),
        _Rule(
            "interactive_on_wide_localization_disagreement",
            "interactive",
            "interactive_on_wide_localization_disagreement",
            _interactive_localization,
            needs_threshold="localization_disagreement",
        ),
        _Rule(
            "interactive_on_high_duplicate_rate",
            "interactive",
            "interactive_on_high_duplicate_rate",
            _interactive_duplicates,
            needs_threshold="duplicate_rate",
        ),
        _Rule(
            "interactive_on_out_of_scope_stack_evidence",
            "interactive",
            "interactive_on_out_of_scope_stack_evidence",
            _interactive_out_of_scope,
        ),
        _Rule(
            "fixed_when_evidence_insufficient",
            "fixed",
            "fixed_when_evidence_insufficient",
            _fixed_no_signal,
        ),
        _Rule("fixed_continuation_otherwise", "fixed", "fixed_continuation_otherwise", _fixed_otherwise),
    )
}

STOP_RULES: tuple[str, ...] = tuple(n for n, r in RULES.items() if r.route == "stop")


# --------------------------------------------------------------------------
# the decision
# --------------------------------------------------------------------------


def route(state: RepairState, cfg: RouterConfig, *, allow_uncalibrated: bool = False) -> Decision:
    """Apply the frozen rule order and return the first rule that fires."""
    if state.budget is not None and state.budget.overrun:
        rule = RULES["stop_when_budget_insufficient"]
        return Decision(rule.name, rule.route, rule.reason, "budget ceiling already crossed")
    for name in cfg.rule_order:
        rule = RULES[name]
        if rule.needs_threshold:
            cfg.threshold(rule.needs_threshold, allow_uncalibrated)
        detail = rule.fn(state, cfg)
        if detail is not None:
            return Decision(name, rule.route, rule.reason, detail)
    raise AssertionError("rule order has no fallback continuation")


def evaluate_all(
    state: RepairState,
    cfg: RouterConfig,
    *,
    allow_uncalibrated: bool = True,
) -> list[dict[str, Any]]:
    """Evaluate every rule without short-circuiting, for reports and debugging."""
    out: list[dict[str, Any]] = []
    for name in cfg.rule_order:
        rule = RULES[name]
        try:
            if rule.needs_threshold and not allow_uncalibrated:
                cfg.threshold(rule.needs_threshold)
            detail = rule.fn(state, cfg) if rule.needs_threshold or allow_uncalibrated else rule.fn(state, cfg)
        except UncalibratedThreshold as exc:
            out.append(
                {
                    "rule": name,
                    "route": rule.route,
                    "fires": False,
                    "detail": str(exc),
                    "calibrated": False,
                }
            )
            continue
        out.append(
            {
                "rule": name,
                "route": rule.route,
                "reason": rule.reason,
                "fires": detail is not None,
                "detail": detail or "",
                "calibrated": True,
            }
        )
    return out


def needs_env_recovery(state: RepairState) -> bool:
    """The single deterministic recovery the protocol allows, checked before routing.

    Section 4.2 stops the run when an environment failure *survives* one
    recovery. Retrying the environment is not a routing decision, so it lives
    here as a precondition for the driver.
    """
    return state.failures.needs_recovery_attempt()


def apply_decision(state: RepairState, decision: Decision) -> Any:
    """Append the decision to the state's audit trace and return the entry."""
    return state.record_decision(decision.rule, decision.route, decision.reason, decision.detail)


def _shared_stop(state: RepairState, cfg: RouterConfig) -> Decision | None:
    if state.budget is not None and state.budget.overrun:
        return Decision('stop_when_budget_insufficient', 'stop', 'stop_budget_insufficient', 'budget overrun')
    for name in cfg.rule_order:
        rule = RULES[name]
        if rule.route != "stop":
            continue
        detail = rule.fn(state, cfg)
        if detail is not None:
            return Decision(name, rule.route, rule.reason, detail)
    return None


# --------------------------------------------------------------------------
# arms
# --------------------------------------------------------------------------


def route_fixed_or_stop(state: RepairState, cfg: RouterConfig) -> Decision:
    """Arm A: the fixed workflow, with only the shared stop rules in front."""
    stop = _shared_stop(state, cfg)
    if stop is not None:
        return stop
    return Decision(
        "fixed_continuation_otherwise",
        "fixed",
        "fixed_continuation_otherwise",
        "arm A: fixed workflow continues within budget",
    )


def route_cascade(state: RepairState, cfg: RouterConfig) -> Decision:
    """Arm C: the same prefix, but every continuable failure escalates.

    The shared stop rules still apply. The difference from arm D is exactly that
    no evidence is consulted before switching.
    """
    stop = _shared_stop(state, cfg)
    if stop is not None:
        return stop
    return Decision(
        "cascade_all_eligible_failures",
        "interactive",
        "cascade_all_eligible_failures",
        "arm C: every continuable failure enters the interactive branch",
    )


def route_random(
    state: RepairState,
    cfg: RouterConfig,
    rng: random.Random | None = None,
    probability: float | None = None,
) -> Decision:
    """Arm E: switch with a probability fixed on the dev split."""
    stop = _shared_stop(state, cfg)
    if stop is not None:
        return stop
    p = cfg.switch_probability if probability is None else probability
    if p is None:
        raise UncalibratedThreshold(
            "arm E needs a switch probability; set router.switch_probability on the dev split"
        )
    if not 0.0 <= p <= 1.0:
        raise ValueError("switch probability must be within [0, 1]")
    stop = _shared_stop(state, cfg)
    if stop is not None:
        return stop
    generator = rng if rng is not None else random.Random(0)
    draw = generator.random()
    if draw < p:
        return Decision(
            "random_routing",
            "interactive",
            "random_routing_switch",
            f"arm E: draw {draw:.3f} < p={p:.3f}, interactive",
        )
    return Decision(
        "random_routing",
        "fixed",
        "random_routing_stay",
        f"arm E: draw {draw:.3f} >= p={p:.3f}, fixed",
    )


def route_for_arm(
    arm: str,
    state: RepairState,
    cfg: RouterConfig,
    *,
    rng: random.Random | None = None,
    allow_uncalibrated: bool = False,
) -> Decision:
    arm = arm.upper()
    if arm == "A":
        return route_fixed_or_stop(state, cfg)
    if arm == "B":
        raise ValueError("arm B has no fixed prefix, so the prefix router does not apply to it")
    if arm == "C":
        return route_cascade(state, cfg)
    if arm == "D":
        return route(state, cfg, allow_uncalibrated=allow_uncalibrated)
    if arm == "E":
        return route_random(state, cfg, rng)
    raise ValueError(f"unknown arm {arm!r}; known: {', '.join(ARMS)}")


# --------------------------------------------------------------------------
# monitoring: make the degeneracy risk visible instead of discovering it later
# --------------------------------------------------------------------------


@dataclass
class RoutingStats:
    """Counts of what the router did, and the warning that matters most.

    If arm D sends almost every instance to interaction, then D is arm C with
    extra steps and the main result cannot support the routing claim. That is a
    property of the data rather than of the implementation, so it is measured
    from the first dev-split run onwards.
    """

    by_reason: dict[str, int] = field(default_factory=dict)
    by_route: dict[str, int] = field(default_factory=dict)
    interactive_degeneracy_threshold: float = 0.95

    def add(self, decision: Decision) -> None:
        self.by_reason[decision.reason] = self.by_reason.get(decision.reason, 0) + 1
        self.by_route[decision.route] = self.by_route.get(decision.route, 0) + 1

    def add_state(self, state: RepairState, cfg: RouterConfig, **kwargs: Any) -> Decision:
        decision = route(state, cfg, **kwargs)
        self.add(decision)
        return decision

    @property
    def total(self) -> int:
        return sum(self.by_route.values())

    def interactive_share(self) -> float:
        return (self.by_route.get("interactive", 0) / self.total) if self.total else 0.0

    def warnings(self) -> tuple[str, ...]:
        out: list[str] = []
        if self.total and self.interactive_share() >= self.interactive_degeneracy_threshold:
            out.append(
                f"arm D routed {self.interactive_share():.1%} of instances to interaction: it is "
                "behaving like arm C, so the main result cannot support the routing claim"
            )
        if self.total and self.by_reason.get("fixed_continuation_otherwise", 0) == self.total:
            out.append(
                "no interactive trigger fired at all: check the calibration and the signal plumbing"
            )
        return tuple(out)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "by_route": dict(sorted(self.by_route.items())),
            "by_reason": dict(sorted(self.by_reason.items())),
            "interactive_share": self.interactive_share(),
            "warnings": list(self.warnings()),
        }
