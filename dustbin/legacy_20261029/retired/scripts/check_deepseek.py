"""Verify the DeepSeek key and measure what one call costs.

    python scripts/check_deepseek.py
    python scripts/check_deepseek.py --model deepseek-v4-pro

Four small calls, on purpose:

  1. a one-word answer with thinking off, the cheapest possible call
  2. the same question with thinking on, so the extra reasoning tokens and
     their cost are visible rather than guessed at
  3. a tool call, to confirm function calling works before the interactive arm
     depends on it
  4. nothing else -- this script is not a benchmark

It prints the model the service says it served, because the published model
name is an alias and the alias is what has to be recorded with every run.
The key is never printed.
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

from swe_repair.llm import (  # noqa: E402
    DeepSeekClient,
    MissingApiKeyError,
    ModelConfig,
    parse_tool_arguments,
)
from swe_repair import pricing  # noqa: E402
from swe_repair.spend import SpendGuard, SpendPolicy  # noqa: E402

WEATHER_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "read_region",
            "description": "Read a range of lines from a file in the repository.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "file path"},
                    "start": {"type": "integer"},
                    "end": {"type": "integer"},
                },
                "required": ["path"],
            },
        },
    }
]


def report(label: str, result) -> None:
    record = result.record
    print(f"  {label}")
    print(f"    served model      : {record.served_model}")
    print(f"    thinking          : {record.thinking} (effort {record.effort})")
    print(f"    prompt tokens     : {record.prompt_tokens}"
          f"  (cached {record.cache_hit_tokens}, uncached {record.cache_miss_tokens})")
    print(f"    output tokens     : {record.output_tokens}"
          f"  (reasoning {record.reasoning_tokens})")
    print(f"    latency           : {record.latency_seconds}s   attempts: {record.attempts}")
    print(f"    price tier        : {record.price_tier} (Beijing time)")
    print(f"    estimated cost    : CNY {record.cost_cny:.6f}")
    if result.text:
        print(f"    answer            : {result.text.strip()[:120]!r}")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default="deepseek-flash")
    ap.add_argument("--effort", default="high", choices=["low", "high", "max"])
    ap.add_argument("--max-cost", type=float, default=0.5,
                    help="hard ceiling in CNY for this check (default 0.5)")
    args = ap.parse_args()

    # Three tiny calls. The ceiling is here so that a mistake in this script
    # cannot turn into a surprise; the estimate is printed either way.
    guard = SpendGuard(SpendPolicy(ceiling_cny=args.max_cost, max_calls=6))
    print(f"spend ceiling for this check: CNY {args.max_cost:.2f}, at most 6 calls")
    print("this script sends 3 small calls and prints what they actually cost")
    print()

    try:
        client_no_think = DeepSeekClient(
            ModelConfig(model=args.model, thinking=False, max_tokens=64), guard=guard
        )
        client_think = DeepSeekClient(
            ModelConfig(model=args.model, thinking=True, effort=args.effort, max_tokens=256),
            guard=guard,
        )
    except MissingApiKeyError as exc:
        print(exc)
        print()
        print("Create .env in the repository root containing:")
        print("    DEEPSEEK_API_KEY=sk-...")
        return 2

    question = [{"role": "user", "content": "Reply with exactly: ready"}]

    print(f"price table dated {pricing.PRICE_TABLE_DATE}, CNY per million tokens")
    print(f"models known to the estimator: {', '.join(pricing.PRICES)}")
    print()

    print("call 1/3  minimal call, thinking off")
    report("thinking off", client_no_think.chat(question, tool_choice=None))

    print("call 2/3  same question, thinking on")
    report("thinking on", client_think.chat(question))

    print("call 3/3  tool calling")
    tool_result = client_think.chat(
        [{"role": "user", "content": "Read lines 1 to 20 of setup.py. Use the tool."}],
        tools=WEATHER_TOOL,
        tool_choice="auto",
    )
    report("tool call", tool_result)
    if tool_result.tool_calls:
        for call in tool_result.tool_calls:
            name = (call.get("function") or {}).get("name")
            print(f"    requested tool    : {name}  args={parse_tool_arguments(call)}")
    else:
        print("    no tool call was requested; check the tool schema before")
        print("    building the interactive arm on top of it")

    print()
    print("If all three printed a served model and a cost, the key works and the")
    print("accounting path is wired up.")
    print()
    print(f"spent on this check: CNY {guard.spent_cny:.6f}  "
          f"({guard.calls} calls, {guard.spent_tokens} tokens, "
          f"CNY {guard.remaining_cny:.4f} of the ceiling left)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
