"""Cost accounting for the DeepSeek models, from the official price list.

Prices are CNY per million tokens and are read off the published table. Two
rates matter per token class: the off-peak rate and the peak rate, where peak
is Beijing time Monday to Friday 09:00-12:00 and 14:00-18:00.

One caveat kept deliberately visible: the published definition of peak excludes
Chinese public holidays, but the holiday calendar is not encoded here. A
weekday that is a public holiday therefore gets priced at the peak rate, which
over-estimates. Pass ``holidays=`` to correct a specific window.

The estimate is for planning and for the cost curve in the write-up. The
authoritative number is whatever the provider bills.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Mapping
from zoneinfo import ZoneInfo

BEIJING = ZoneInfo("Asia/Shanghai")

PEAK_WINDOWS: tuple[tuple[time, time], ...] = (
    (time(9, 0), time(12, 0)),
    (time(14, 0), time(18, 0)),
)


class UnknownModelError(KeyError):
    """Raised when a model has no published price entry."""


@dataclass(frozen=True)
class ModelPrice:
    """CNY per million tokens."""

    cache_hit: Mapping[str, float]
    cache_miss: Mapping[str, float]
    output: Mapping[str, float]

    def rate(self, token_class: str, tier: str) -> float:
        table = {
            "cache_hit": self.cache_hit,
            "cache_miss": self.cache_miss,
            "output": self.output,
        }[token_class]
        try:
            return table[tier]
        except KeyError as exc:  # pragma: no cover - guarded by callers
            raise UnknownModelError(
                f"no {token_class} rate for tier {tier!r}"
            ) from exc


# Published 2026-10, CNY per million tokens.
PRICES: dict[str, ModelPrice] = {
    "deepseek-flash": ModelPrice(
        cache_hit={"off_peak": 0.02, "peak": 0.04},
        cache_miss={"off_peak": 1.0, "peak": 2.0},
        output={"off_peak": 4.0, "peak": 8.0},
    ),
    "deepseek-v4-pro": ModelPrice(
        cache_hit={"off_peak": 0.15, "peak": 0.30},
        cache_miss={"off_peak": 4.5, "peak": 9.0},
        output={"off_peak": 13.5, "peak": 27.0},
    ),
}

# Prices move. Anything that reports a cost should record which table it used.
PRICE_TABLE_DATE = "2026-10-15"


def is_peak(
    when: datetime,
    holidays: frozenset[date] | None = None,
) -> bool:
    """True when ``when`` falls in a peak-priced window.

    Naive datetimes are read as Beijing time. Weekends are never peak. A date
    listed in ``holidays`` is never peak either, which is the one piece of the
    published rule that needs caller-supplied data.
    """

    if when.tzinfo is None:
        local = when.replace(tzinfo=BEIJING)
    else:
        local = when.astimezone(BEIJING)

    if local.weekday() >= 5:
        return False
    if holidays and local.date() in holidays:
        return False

    clock = local.time()
    return any(start <= clock < end for start, end in PEAK_WINDOWS)


def tier_for(when: datetime, holidays: frozenset[date] | None = None) -> str:
    return "peak" if is_peak(when, holidays) else "off_peak"


def estimate_cost(
    model: str,
    *,
    cache_hit_tokens: int = 0,
    cache_miss_tokens: int = 0,
    output_tokens: int = 0,
    when: datetime | None = None,
    holidays: frozenset[date] | None = None,
    prices: Mapping[str, ModelPrice] | None = None,
) -> float:
    """Estimated cost in CNY for one call or for a total across calls.

    ``prompt_tokens`` is not a parameter on purpose: the provider bills cached
    and uncached prompt tokens at very different rates, so callers have to keep
    them apart. Use :func:`split_prompt_tokens` for responses that report only a
    combined prompt count.
    """

    table = prices or PRICES
    try:
        price = table[model]
    except KeyError as exc:
        raise UnknownModelError(f"no price entry for model {model!r}") from exc

    tier = tier_for(when or datetime.now(BEIJING), holidays)

    total = 0.0
    for token_class, count in (
        ("cache_hit", cache_hit_tokens),
        ("cache_miss", cache_miss_tokens),
        ("output", output_tokens),
    ):
        if count < 0:
            raise ValueError(f"{token_class} tokens cannot be negative")
        total += count / 1_000_000 * price.rate(token_class, tier)
    return total


def split_prompt_tokens(
    prompt_tokens: int,
    cache_hit_tokens: int | None,
) -> tuple[int, int]:
    """Return ``(cache_hit, cache_miss)`` for a response's prompt usage.

    When a response omits the cached count, every prompt token is treated as a
    miss. That is the conservative direction: it never under-states the bill.
    """

    if prompt_tokens < 0:
        raise ValueError("prompt_tokens cannot be negative")
    if cache_hit_tokens is None:
        return 0, prompt_tokens
    hit = max(0, min(cache_hit_tokens, prompt_tokens))
    return hit, prompt_tokens - hit


def compare_models(
    token_mix: Mapping[str, int],
    *,
    when: datetime | None = None,
    models: Mapping[str, ModelPrice] | None = None,
) -> dict[str, float]:
    """Cost in CNY per model for a given token mix, cheapest first."""

    table = models or PRICES
    costs = {
        name: estimate_cost(name, when=when, prices=table, **token_mix)
        for name in table
    }
    return dict(sorted(costs.items(), key=lambda item: item[1]))
