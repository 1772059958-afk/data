"""A hard money ceiling for model calls, enforced before each call is made.

The rule this module exists to keep: no live API call happens by accident, and
no batch runs past an agreed amount without a fresh decision. It is deliberately
blunt, because the failure mode it guards against is not a wrong number -- it is
a long-running experiment quietly spending real money.

Two enforcement points, mirroring the per-run resource budget in ``budget.py``:

* ``check_before`` runs *before* a call, using a worst-case token estimate. If
  the remaining allowance cannot cover it, the call is refused.
* ``book`` runs after the call and refuses to continue once the ceiling is
  crossed. The overrun is still recorded, so the cost data is not lost.

A batch whose *estimated* cost exceeds ``approval_threshold_cny`` will not start
unless the caller passes the approval phrase. The phrase is a literal string so
that approval is an explicit act in the code, not an inferred mood.

Defaults are deliberately tiny: a fresh ``SpendPolicy`` tops out well below the
cost of one real experiment, so forgetting to raise it fails safe.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

from . import pricing

# Say this exactly to authorise a batch above the threshold.
APPROVAL_PHRASE = "I approve this spend"

DEFAULT_CEILING_CNY = 1.0
DEFAULT_APPROVAL_THRESHOLD_CNY = 1.0

# When a caller does not know how big the prompt will be, assume this much.
# Guessing high keeps the guard protective rather than decorative.
ASSUMED_PROMPT_TOKENS = 100_000


class SpendLimitExceeded(RuntimeError):
    """Raised instead of spending past the ceiling."""


class ApprovalRequired(RuntimeError):
    """Raised when a batch is above the threshold but was not approved."""


@dataclasses.dataclass(frozen=True)
class SpendPolicy:
    """What may be spent, and how much of it needs saying out loud first."""

    ceiling_cny: float = DEFAULT_CEILING_CNY
    approval_threshold_cny: float = DEFAULT_APPROVAL_THRESHOLD_CNY
    max_calls: int | None = None
    max_tokens: int | None = None
    assumed_prompt_tokens: int = ASSUMED_PROMPT_TOKENS
    note: str = ""

    def __post_init__(self) -> None:
        if self.ceiling_cny < 0:
            raise ValueError("ceiling_cny cannot be negative")
        if self.approval_threshold_cny < 0:
            raise ValueError("approval_threshold_cny cannot be negative")

    def requires_approval(self, estimate_cny: float) -> bool:
        return estimate_cny > self.approval_threshold_cny

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


class SpendGuard:
    """Books model calls against a ceiling and refuses to cross it."""

    def __init__(self, policy: SpendPolicy | None = None, *, approved: bool = False) -> None:
        self.policy = policy or SpendPolicy()
        self.records: list[Any] = []
        self._approved = approved

    # ------------------------------------------------------------- accounting

    @property
    def spent_cny(self) -> float:
        return round(sum(float(r.cost_cny) for r in self.records), 6)

    @property
    def spent_tokens(self) -> int:
        return sum(int(r.prompt_tokens) + int(r.output_tokens) for r in self.records)

    @property
    def calls(self) -> int:
        return len(self.records)

    @property
    def remaining_cny(self) -> float:
        return round(self.policy.ceiling_cny - self.spent_cny, 6)

    def summary(self) -> dict[str, Any]:
        return {
            "ceiling_cny": self.policy.ceiling_cny,
            "spent_cny": self.spent_cny,
            "remaining_cny": self.remaining_cny,
            "calls": self.calls,
            "tokens": self.spent_tokens,
            "approved": self._approved,
        }

    # --------------------------------------------------------------- approval

    def require_approval(self, estimate_cny: float, *, phrase: str = "") -> None:
        """Refuse a batch that is above the threshold and was not approved.

        Call this once, before a batch, with the up-front estimate. A single
        call that is cheap does not need approval; a sweep of hundreds of
        instances does.
        """

        if not self.policy.requires_approval(estimate_cny):
            return
        if phrase.strip() != APPROVAL_PHRASE:
            raise ApprovalRequired(
                f"estimated cost CNY {estimate_cny:.2f} is above the approval "
                f"threshold of CNY {self.policy.approval_threshold_cny:.2f}. "
                f"Get the user's explicit go-ahead first, then repeat with "
                f"phrase={APPROVAL_PHRASE!r}."
            )
        self._approved = True

    # ------------------------------------------------------------- pre-flight

    def worst_case_cny(
        self,
        model: str,
        *,
        prompt_tokens: int | None = None,
        max_output_tokens: int,
        when: datetime | None = None,
    ) -> float:
        """Cost of the next call if every prompt token misses the cache.

        Cache hits are cheaper, so pricing everything as a miss is the safe
        direction for a ceiling check.
        """

        prompt = self.policy.assumed_prompt_tokens if prompt_tokens is None else prompt_tokens
        return pricing.estimate_cost(
            model,
            cache_miss_tokens=prompt,
            output_tokens=max_output_tokens,
            when=when,
        )

    def check_before(
        self,
        model: str,
        *,
        prompt_tokens: int | None = None,
        max_output_tokens: int,
        when: datetime | None = None,
    ) -> float:
        """Return the worst-case cost, or raise if it does not fit."""

        if self.policy.max_calls is not None and self.calls >= self.policy.max_calls:
            raise SpendLimitExceeded(
                f"call limit reached: {self.calls} of {self.policy.max_calls} used"
            )
        if self.policy.max_tokens is not None and self.spent_tokens >= self.policy.max_tokens:
            raise SpendLimitExceeded(
                f"token limit reached: {self.spent_tokens} of {self.policy.max_tokens}"
            )

        worst = self.worst_case_cny(
            model, prompt_tokens=prompt_tokens, max_output_tokens=max_output_tokens, when=when
        )
        if worst > self.remaining_cny + 1e-9:
            raise SpendLimitExceeded(
                f"next call could cost up to CNY {worst:.4f} but only "
                f"CNY {self.remaining_cny:.4f} of the CNY "
                f"{self.policy.ceiling_cny:.2f} ceiling is left. Raise the "
                f"ceiling deliberately, or stop."
            )
        return worst

    # -------------------------------------------------------------- bookkeeping

    def book(self, record: Any) -> None:
        """Record a completed call. Raises once the ceiling is crossed."""

        self.records.append(record)
        if self.spent_cny > self.policy.ceiling_cny + 1e-9:
            raise SpendLimitExceeded(
                f"ceiling crossed: spent CNY {self.spent_cny:.4f} against a "
                f"ceiling of CNY {self.policy.ceiling_cny:.2f}. The call is "
                f"recorded; do not continue without raising the ceiling."
            )


def estimate_batch_cny(
    *,
    instances: int,
    arms: int = 1,
    repeats: int = 1,
    calls_per_instance: int = 1,
    prompt_tokens: int,
    output_tokens: int,
    model: str = "deepseek-flash",
    when: datetime | None = None,
    cache_hit_fraction: float = 0.0,
) -> float:
    """Plan-time estimate for a batch, in CNY.

    ``cache_hit_fraction`` lets a plan assume part of the prompt is served from
    the provider's context cache, which is ten to fifty times cheaper. The
    default of 0 assumes no caching at all, which is the safe direction.
    """

    if not 0.0 <= cache_hit_fraction <= 1.0:
        raise ValueError("cache_hit_fraction must be within [0, 1]")
    for name, value in (
        ("instances", instances),
        ("arms", arms),
        ("repeats", repeats),
        ("calls_per_instance", calls_per_instance),
        ("prompt_tokens", prompt_tokens),
        ("output_tokens", output_tokens),
    ):
        if value < 0:
            raise ValueError(f"{name} cannot be negative")

    total_calls = instances * arms * repeats * calls_per_instance
    hit = int(prompt_tokens * cache_hit_fraction)
    miss = prompt_tokens - hit
    return pricing.estimate_cost(
        model,
        cache_hit_tokens=hit * total_calls,
        cache_miss_tokens=miss * total_calls,
        output_tokens=output_tokens * total_calls,
        when=when,
    )


def plan_table(
    scenarios: Sequence[Mapping[str, Any]],
    *,
    model: str = "deepseek-flash",
    when: datetime | None = None,
) -> list[dict[str, Any]]:
    """Cost each scenario from a list of keyword arguments for the above."""

    out = []
    for scenario in scenarios:
        row = dict(scenario)
        row["cost_cny"] = round(estimate_batch_cny(model=model, when=when, **scenario), 4)
        out.append(row)
    return out
