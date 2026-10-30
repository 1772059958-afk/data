"""Self-checks for the money ceiling and the plan-time cost estimates.

All offline: no key, no network, no calls. These tests are the reason the
ceiling can be trusted rather than merely intended.

Runs under pytest or as plain ``python tests/test_spend.py``.
"""

from __future__ import annotations

import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):  # pragma: no cover
    pass

from swe_repair.spend import (  # noqa: E402
    APPROVAL_PHRASE,
    ApprovalRequired,
    SpendGuard,
    SpendLimitExceeded,
    SpendPolicy,
    estimate_batch_cny,
    plan_table,
)

OFF_PEAK = dt.datetime(2026, 10, 12, 20, 0)


class FakeCall:
    """Stands in for a CallRecord; only the fields the guard reads."""

    def __init__(self, cost_cny, prompt_tokens=0, output_tokens=0):
        self.cost_cny = cost_cny
        self.prompt_tokens = prompt_tokens
        self.output_tokens = output_tokens


# ------------------------------------------------------------ fail-safe defaults

def test_the_default_ceiling_is_small():
    # Forgetting to raise the ceiling must not authorise a real experiment.
    assert SpendPolicy().ceiling_cny <= 1.0


def test_negative_ceiling_is_rejected():
    try:
        SpendPolicy(ceiling_cny=-1)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_negative_approval_threshold_is_rejected():
    try:
        SpendPolicy(approval_threshold_cny=-1)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


# --------------------------------------------------------------- pre-flight check

def test_check_before_prices_the_worst_case():
    guard = SpendGuard(SpendPolicy(ceiling_cny=10.0))
    worst = guard.check_before(
        "deepseek-flash", prompt_tokens=100_000, max_output_tokens=10_000, when=OFF_PEAK
    )
    # 0.1M uncached input at 1 CNY/M plus 0.01M output at 4 CNY/M
    assert abs(worst - (0.1 + 0.04)) < 1e-9


def test_unknown_prompt_size_uses_the_conservative_default():
    guard = SpendGuard(SpendPolicy(ceiling_cny=10.0))
    guessed = guard.check_before("deepseek-flash", max_output_tokens=0, when=OFF_PEAK)
    assert guessed == guard.policy.assumed_prompt_tokens / 1_000_000 * 1.0


def test_a_call_that_would_exceed_the_ceiling_is_refused_before_it_happens():
    guard = SpendGuard(SpendPolicy(ceiling_cny=0.1))
    try:
        guard.check_before(
            "deepseek-flash", prompt_tokens=1_000_000, max_output_tokens=1, when=OFF_PEAK
        )
    except SpendLimitExceeded as exc:
        assert "ceiling" in str(exc)
        assert guard.calls == 0
        return
    raise AssertionError("expected SpendLimitExceeded")


def test_call_limit_is_enforced():
    guard = SpendGuard(SpendPolicy(ceiling_cny=100.0, max_calls=2))
    guard.book(FakeCall(0.001))
    guard.book(FakeCall(0.001))
    try:
        guard.check_before("deepseek-flash", max_output_tokens=1, when=OFF_PEAK)
    except SpendLimitExceeded as exc:
        assert "call limit" in str(exc)
        return
    raise AssertionError("expected SpendLimitExceeded")


def test_token_limit_is_enforced():
    guard = SpendGuard(SpendPolicy(ceiling_cny=100.0, max_tokens=1000))
    guard.book(FakeCall(0.001, prompt_tokens=600, output_tokens=400))
    try:
        guard.check_before("deepseek-flash", max_output_tokens=1, when=OFF_PEAK)
    except SpendLimitExceeded as exc:
        assert "token limit" in str(exc)
        return
    raise AssertionError("expected SpendLimitExceeded")


# ------------------------------------------------------------------ bookkeeping

def test_booking_accumulates_and_reports_remaining():
    guard = SpendGuard(SpendPolicy(ceiling_cny=1.0))
    guard.book(FakeCall(0.25, 100, 20))
    guard.book(FakeCall(0.25, 100, 20))
    summary = guard.summary()
    assert summary["spent_cny"] == 0.5
    assert summary["remaining_cny"] == 0.5
    assert summary["calls"] == 2
    assert summary["tokens"] == 240


def test_crossing_the_ceiling_raises_but_still_records_the_call():
    guard = SpendGuard(SpendPolicy(ceiling_cny=0.10))
    try:
        guard.book(FakeCall(0.50))
    except SpendLimitExceeded as exc:
        assert "crossed" in str(exc)
        # The cost data must survive the refusal, exactly as budget.py does it.
        assert guard.calls == 1
        assert guard.spent_cny == 0.5
        return
    raise AssertionError("expected SpendLimitExceeded")


# -------------------------------------------------------------------- approval

def test_cheap_batches_do_not_need_approval():
    guard = SpendGuard(SpendPolicy(ceiling_cny=10.0, approval_threshold_cny=1.0))
    guard.require_approval(0.30)
    assert guard.summary()["approved"] is False


def test_expensive_batch_without_the_phrase_is_refused():
    guard = SpendGuard(SpendPolicy(ceiling_cny=5000.0, approval_threshold_cny=1.0))
    try:
        guard.require_approval(1260.0)
    except ApprovalRequired as exc:
        assert "estimate" in str(exc).lower() or "CNY" in str(exc)
        return
    raise AssertionError("expected ApprovalRequired")


def test_wrong_phrase_is_not_approval():
    guard = SpendGuard(SpendPolicy(ceiling_cny=5000.0, approval_threshold_cny=1.0))
    try:
        guard.require_approval(1260.0, phrase="ok go ahead")
    except ApprovalRequired:
        return
    raise AssertionError("expected ApprovalRequired for an inexact phrase")


def test_the_exact_phrase_approves():
    guard = SpendGuard(SpendPolicy(ceiling_cny=5000.0, approval_threshold_cny=1.0))
    guard.require_approval(1260.0, phrase=APPROVAL_PHRASE)
    assert guard.summary()["approved"] is True


# ------------------------------------------------------------- plan estimates

def test_batch_estimate_scales_with_the_number_of_runs():
    one = estimate_batch_cny(
        instances=1, prompt_tokens=200_000, output_tokens=20_000,
        model="deepseek-flash", when=OFF_PEAK,
    )
    many = estimate_batch_cny(
        instances=300, arms=5, repeats=3,
        prompt_tokens=200_000, output_tokens=20_000,
        model="deepseek-flash", when=OFF_PEAK,
    )
    assert abs(many - one * 4500) < 1e-6


def test_batch_estimate_matches_a_hand_calculation():
    cost = estimate_batch_cny(
        instances=100, prompt_tokens=100_000, output_tokens=10_000,
        model="deepseek-flash", when=OFF_PEAK,
    )
    # 100 runs: 0.1M input at 1 CNY/M and 0.01M output at 4 CNY/M
    assert abs(cost - 100 * (0.1 + 0.04)) < 1e-9


def test_cache_hits_make_a_batch_cheaper():
    common = dict(instances=100, prompt_tokens=200_000, output_tokens=0,
                  model="deepseek-flash", when=OFF_PEAK)
    assert estimate_batch_cny(cache_hit_fraction=0.8, **common) < \
           estimate_batch_cny(cache_hit_fraction=0.0, **common)


def test_cache_hit_fraction_is_validated():
    try:
        estimate_batch_cny(instances=1, prompt_tokens=1, output_tokens=1,
                           cache_hit_fraction=1.5)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_negative_scenario_values_are_rejected():
    try:
        estimate_batch_cny(instances=-1, prompt_tokens=1, output_tokens=1)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_plan_table_returns_a_cost_per_scenario():
    rows = plan_table(
        [
            {"instances": 1, "prompt_tokens": 200_000, "output_tokens": 20_000},
            {"instances": 300, "arms": 5, "repeats": 3,
             "prompt_tokens": 200_000, "output_tokens": 20_000},
        ],
        model="deepseek-flash",
        when=OFF_PEAK,
    )
    assert len(rows) == 2
    assert rows[0]["cost_cny"] < rows[1]["cost_cny"]
    assert rows[1]["cost_cny"] > 1000  # the full experiment is not pocket change


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
