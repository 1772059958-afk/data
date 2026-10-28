"""Print what the planned experiments would cost, before spending anything.

    python scripts/estimate_cost.py
    python scripts/estimate_cost.py --input-tokens 200000 --output-tokens 20000

No network, no key, no calls. The point is to have a number to approve or reject
before a run starts, rather than discovering it on a bill.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):  # pragma: no cover
    pass

from swe_repair import pricing  # noqa: E402
from swe_repair.spend import APPROVAL_PHRASE, estimate_batch_cny  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input-tokens", type=int, default=200_000,
                    help="prompt tokens per instance, summed over its calls")
    ap.add_argument("--output-tokens", type=int, default=20_000,
                    help="completion tokens per instance, summed over its calls")
    ap.add_argument("--model", default="deepseek-flash")
    ap.add_argument("--cache-hit", type=float, default=0.0,
                    help="fraction of prompt tokens served from the context cache")
    args = ap.parse_args()

    print(f"model          : {args.model}")
    print(f"price table    : {pricing.PRICE_TABLE_DATE}, CNY per million tokens")
    print(f"assumed per instance: {args.input_tokens:,} input / {args.output_tokens:,} output")
    print(f"cache hit share: {args.cache_hit:.0%}")
    print()

    tiers = [
        ("one smoke instance", dict(instances=1)),
        ("dev split, one arm", dict(instances=23)),
        ("dev split, five arms", dict(instances=23, arms=5)),
        ("dev split, all arms, 3 repeats", dict(instances=23, arms=5, repeats=3)),
        ("test split, one arm", dict(instances=300)),
        ("test split, five arms", dict(instances=300, arms=5)),
        ("test split, all arms, 3 repeats", dict(instances=300, arms=5, repeats=3)),
    ]

    print(f"{'scenario':<34}{'calls':>8}{'off-peak':>12}{'peak':>12}")
    print("-" * 66)
    for label, shape in tiers:
        calls = shape.get("instances", 1) * shape.get("arms", 1) * shape.get("repeats", 1)
        common = dict(
            prompt_tokens=args.input_tokens,
            output_tokens=args.output_tokens,
            model=args.model,
            cache_hit_fraction=args.cache_hit,
            **shape,
        )
        # 2026-10-12 is a Monday; 10:00 is peak, 20:00 is off-peak.
        import datetime as dt

        off = estimate_batch_cny(when=dt.datetime(2026, 10, 12, 20, 0), **common)
        peak = estimate_batch_cny(when=dt.datetime(2026, 10, 12, 10, 0), **common)
        print(f"{label:<34}{calls:>8}{off:>11.2f} {peak:>11.2f}")

    print()
    print("Peak is Beijing time Mon-Fri 09:00-12:00 and 14:00-18:00; everything")
    print("else is half price. Running long sweeps outside those windows halves")
    print("the bill without changing the experiment.")
    print()
    print("Anything above the agreed ceiling needs the user's explicit go-ahead.")
    print(f"In code that is: phrase={APPROVAL_PHRASE!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
