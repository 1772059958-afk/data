"""Resource accounting for one repair run (proposal sections 3.2 and 5.2).

The resource vector is ``b = (token, model_call, tool_call, wallclock_seconds)``.
Two rules from the proposal are enforced here rather than left to convention:

* a call is checked *before* it is made, using the known prompt length plus the
  maximum output length (``check_model_call``), so a run cannot be pushed over a
  hard ceiling by a single unlucky response;
* switching branch never resets consumption -- both continuation branches spend
  from the same ``BudgetState`` instance.

Overspending is recorded, not hidden: if a single call crosses the ceiling the
usage is still booked and ``overrun`` becomes true, which the driver reads as a
stop condition. Raising instead would lose the cost data that makes the
comparison between arms meaningful.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping

ASPECTS = ("token", "model_call", "tool_call", "wallclock_seconds")


class OverBudgetError(RuntimeError):
    """Raised by ``spend(strict=True)`` when a ceiling is crossed."""


@dataclass(frozen=True)
class Budget:
    """An amount of resource, used both as a ceiling and as a consumption."""

    token: int = 0
    model_call: int = 0
    tool_call: int = 0
    wallclock_seconds: float = 0.0

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "Budget":
        if not payload:
            return cls()
        missing = [a for a in ASPECTS if a not in payload]
        if missing:
            raise ValueError(f"budget is missing {', '.join(missing)}")
        return cls(
            token=int(payload["token"]),
            model_call=int(payload["model_call"]),
            tool_call=int(payload["tool_call"]),
            wallclock_seconds=float(payload["wallclock_seconds"]),
        )

    def __add__(self, other: "Budget") -> "Budget":
        return Budget(
            self.token + other.token,
            self.model_call + other.model_call,
            self.tool_call + other.tool_call,
            self.wallclock_seconds + other.wallclock_seconds,
        )

    def __sub__(self, other: "Budget") -> "Budget":
        return Budget(
            max(0, self.token - other.token),
            max(0, self.model_call - other.model_call),
            max(0, self.tool_call - other.tool_call),
            max(0.0, self.wallclock_seconds - other.wallclock_seconds),
        )

    def covers(self, need: "Budget") -> bool:
        """True when this amount is enough for ``need`` on every aspect."""
        return all(getattr(self, a) >= getattr(need, a) for a in ASPECTS)

    def excess(self, other: "Budget") -> dict[str, float]:
        """How far this amount exceeds ``other``, per aspect (never negative)."""
        return {
            a: max(0.0, getattr(self, a) - getattr(other, a)) for a in ASPECTS
        }

    def scale(self, factor: float) -> "Budget":
        return Budget(
            int(self.token * factor),
            int(self.model_call * factor),
            int(self.tool_call * factor),
            self.wallclock_seconds * factor,
        )

    def __bool__(self) -> bool:
        return any(getattr(self, a) > 0 for a in ASPECTS)

    def as_dict(self) -> dict[str, float]:
        return {a: _tidy(getattr(self, a)) for a in ASPECTS}


def _tidy(value: float) -> float:
    """Keep whole numbers whole so a JSON round trip is byte-stable."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


@dataclass
class BudgetState:
    """Ceiling plus consumption for one instance run, shared by both branches."""

    tier: str
    ceiling: Budget
    consumed: Budget = field(default_factory=Budget)
    overrun: bool = False
    exhausted_at: str | None = None  # which aspect first hit its ceiling

    @classmethod
    def for_tier(cls, tier: str, tiers: Mapping[str, Mapping[str, Any]]) -> "BudgetState":
        if tier not in tiers:
            raise KeyError(f"unknown budget tier {tier!r}; known: {sorted(tiers)}")
        return cls(tier=tier, ceiling=Budget.from_mapping(tiers[tier]))

    @property
    def remaining(self) -> Budget:
        return self.ceiling - self.consumed

    def fraction_used(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for a in ASPECTS:
            ceiling = getattr(self.ceiling, a)
            out[a] = (getattr(self.consumed, a) / ceiling) if ceiling else 0.0
        return out

    def can_afford(self, need: Budget) -> bool:
        return self.remaining.covers(need)

    def check_model_call(self, prompt_tokens: int, max_output_tokens: int, model_call: int = 1) -> Budget:
        """Return what a prospective model call needs, before it is made."""
        return Budget(token=max(0, prompt_tokens) + max(0, max_output_tokens), model_call=model_call)

    def spend(
        self,
        *,
        token: int = 0,
        model_call: int = 0,
        tool_call: int = 0,
        wallclock_seconds: float = 0.0,
        strict: bool = False,
    ) -> Budget:
        """Book actual usage. Returns the new remaining amount."""
        attempt = Budget(token, model_call, tool_call, wallclock_seconds)
        for aspect in ASPECTS:
            if getattr(attempt, aspect) < 0:
                raise ValueError(f"{aspect} cannot be negative")
        before = self.remaining
        self.consumed = self.consumed + attempt
        if not before.covers(attempt):
            self.overrun = True
            if self.exhausted_at is None:
                for aspect in ASPECTS:
                    if getattr(attempt, aspect) > getattr(before, aspect):
                        self.exhausted_at = aspect
                        break
            if strict:
                raise OverBudgetError(
                    f"{self.tier}: spent {attempt.as_dict()}, only {before.as_dict()} remained"
                )
        return self.remaining

    def allows_continuation(self, floor: Budget) -> bool:
        """Whether one more meaningful step fits inside the remaining budget."""
        return self.remaining.covers(floor) and not self.overrun

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "ceiling": self.ceiling.as_dict(),
            "consumed": self.consumed.as_dict(),
            "remaining": self.remaining.as_dict(),
            "fraction_used": self.fraction_used(),
            "overrun": self.overrun,
            "exhausted_at": self.exhausted_at,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BudgetState":
        state = cls(
            tier=str(payload["tier"]),
            ceiling=Budget.from_mapping(payload["ceiling"]),
            consumed=Budget.from_mapping(payload.get("consumed", {})),
            overrun=bool(payload.get("overrun", False)),
            exhausted_at=payload.get("exhausted_at"),
        )
        return state

    def copy(self) -> "BudgetState":
        """Snapshot, used when storing an intermediate state for later replay."""
        return replace(self, consumed=self.consumed, ceiling=self.ceiling)


def split_prefix(ceiling: Budget, prefix_fraction: float) -> tuple[Budget, Budget]:
    """Split a ceiling into (prefix budget, remainder kept for a continuation).

    The proposal fixes the prefix at a fraction of the *token* ceiling and notes
    that call-level granularity means actual use only approximates it.
    """
    if not 0.0 < prefix_fraction <= 1.0:
        raise ValueError("prefix_fraction must be within (0, 1]")
    prefix = ceiling.scale(prefix_fraction)
    return prefix, ceiling - prefix


def tier_table(tiers: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Turn the config's list of tiers into a name -> amounts mapping."""
    out: dict[str, dict[str, Any]] = {}
    for entry in tiers:
        name = entry["tier"]
        out[name] = {a: entry[a] for a in ASPECTS}
    return out
