"""Constructed failure states -> routing decisions, as promised in section 5.3.

Section 5.3 asks the routing tests to use explicitly constructed failure states
and to check three behaviours: early stop when a candidate already passes, exit
on environment failure, and no further action when the budget is short. This
script runs those cases plus one case per interaction trigger, prints the
decision table and writes it to ``reports/router_demo.md`` for the slides.

It needs no container, no model and no network. Run it with:

    python scripts/router_demo.py

Exit status is non-zero if any constructed case routes differently from what it
declares, so this doubles as a smoke test of the frozen rule order.
"""

from __future__ import annotations

import json
import os
import random
import sys
from typing import Callable, NamedTuple

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):  # pragma: no cover
    pass

from swe_repair import runlog  # noqa: E402
from swe_repair.budget import Budget, BudgetState  # noqa: E402
from swe_repair.router import (  # noqa: E402
    RouterConfig,
    RoutingStats,
    evaluate_all,
    route,
    route_cascade,
    route_fixed_or_stop,
    route_random,
)
from swe_repair.state import (  # noqa: E402
    Candidate,
    ContextView,
    FailureLog,
    FailureRecord,
    Localization,
    RepairState,
    TaskManifest,
    build_run_record,
)

CONFIG_PATH = os.path.join(ROOT, "configs", "frozen_v1.json")
OUT_DIR = os.path.join(ROOT, "reports")

DIFF = (
    "--- a/pkg/parse.py\n"
    "+++ b/pkg/parse.py\n"
    "@@ -10,3 +10,4 @@\n"
    " def parse(text):\n"
    "-    return datetime.strptime(text, FMT)\n"
    "+    if not text:\n"
    "+        raise ValueError('empty')\n"
    "+    return datetime.strptime(text, FMT)\n"
)

DIFF_VARIANT = DIFF.replace("raise ValueError('empty')", "return None")


def base_state(tier: str = "small") -> RepairState:
    ceilings = {
        "small": Budget(token=32000, model_call=12, tool_call=20, wallclock_seconds=600),
        "medium": Budget(token=64000, model_call=24, tool_call=40, wallclock_seconds=1200),
    }
    return RepairState(
        task=TaskManifest(
            instance_id="django__django-11099",
            repo="django/django",
            base_commit="0f3b3b0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f",
            config_version="frozen_v1",
            config_hash=runlog.config_hash({"config_version": "frozen_v1"}),
            image_id="swebench/sweb.eval.x86_64.django_1776_django-11099:latest",
        ),
        budget=BudgetState(tier=tier, ceiling=ceilings[tier]),
        clock=lambda: "2026-10-15T12:00:00Z",
    )


def with_prefix_failure(
    *,
    localization_files: dict[str, list[str]] | None = None,
    candidates: list[tuple[str, str]] | None = None,
    observed: list[str] | None = None,
    test_command: str | None = "python -m pytest tests/test_parse.py",
    checks_run: int = 1,
    stack: str | None = None,
) -> RepairState:
    """A prefix that located, generated and validated, and did not succeed."""
    state = base_state()
    state.localization = Localization.from_file_sets(
        localization_files or {"bm25": ["pkg/parse.py"], "symbol": ["pkg/parse.py"]}
    )
    observed = observed if observed is not None else ["pkg/parse.py"]
    state.context = ContextView(
        indexed_paths=frozenset(observed),
        read_files=frozenset(observed),
        registered_test_commands=((test_command,) if test_command else ()),
        checks_run=checks_run,
    )
    for index, (diff, validation) in enumerate(candidates or [(DIFF, "fail")]):
        state.patches.add(Candidate.build(index, diff, applies_cleanly=True, validation=validation))
    if stack:
        state.failures.add(
            FailureRecord.from_output("python -m pytest tests/test_parse.py", 1, stage="test", stderr=stack)
        )
    return state


SUCCESS_STACK = (
    '  File "/testbed/pkg/parse.py", line 12, in parse\n'
    "E   AssertionError: parse('') should raise\n"
)

OUT_OF_SCOPE_STACK = (
    '  File "/testbed/pkg/parse.py", line 12, in parse\n'
    '  File "/testbed/pkg/normalise.py", line 9, in fmt\n'
    "E   AssertionError: parse('') should raise\n"
)


class Scenario(NamedTuple):
    name: str
    signal: str
    build: Callable[[], RepairState]
    expect_route: str
    expect_reason: str


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        "public candidate already passes",
        "prefix: public validation passed",
        lambda: with_prefix_failure(
            candidates=[(DIFF, "fail"), (DIFF_VARIANT, "pass")], stack=SUCCESS_STACK
        ),
        "stop",
        "early_stop_public_pass",
    ),
    Scenario(
        "environment failure survived one recovery",
        "failure: env_setup, 1 recovery attempt",
        lambda: _env_state(),
        "stop",
        "stop_env_failure",
    ),
    Scenario(
        "budget too small for another step",
        "budget: 500 tokens left, floor is 2048",
        lambda: _broke_state(),
        "stop",
        "stop_budget_insufficient",
    ),
    Scenario(
        "localisation passes disagree",
        "u_loc = 1.000 over 2 passes",
        lambda: with_prefix_failure(
            localization_files={"bm25": ["pkg/parse.py"], "symbol": ["pkg/normalise.py"]},
            stack=SUCCESS_STACK,
        ),
        "interactive",
        "interactive_on_wide_localization_disagreement",
    ),
    Scenario(
        "candidates repeat themselves",
        "u_dup = 0.600 over 5 candidates",
        lambda: with_prefix_failure(
            candidates=[(DIFF, "fail")] * 4 + [(DIFF_VARIANT, "fail")], stack=SUCCESS_STACK
        ),
        "interactive",
        "interactive_on_high_duplicate_rate",
    ),
    Scenario(
        "stack points outside the inspected context",
        "frames: pkg/parse.py, pkg/normalise.py (unread)",
        lambda: with_prefix_failure(stack=OUT_OF_SCOPE_STACK),
        "interactive",
        "interactive_on_out_of_scope_stack_evidence",
    ),
    Scenario(
        "nothing runnable to check behaviour with",
        "signal: none, checks_run = 0",
        lambda: with_prefix_failure(test_command=None, checks_run=0),
        "interactive",
        "interactive_when_no_behavioural_signal",
    ),
    Scenario(
        "no interactive trigger fires",
        "narrow localisation, distinct candidates, signal present",
        lambda: with_prefix_failure(stack=SUCCESS_STACK),
        "fixed",
        "fixed_continuation_otherwise",
    ),
)


def _env_state() -> RepairState:
    state = with_prefix_failure(stack=SUCCESS_STACK)
    record = FailureRecord.from_output(
        "pip install -e .", 1, stage="env",
        stderr="Could not find a version that satisfies the requirement django==4.2",
    )
    state.failures.add(record)
    state.failures.add(record.with_recovery())
    return state


def _broke_state() -> RepairState:
    state = with_prefix_failure(stack=SUCCESS_STACK)
    state.budget.spend(token=31500, model_call=11, tool_call=19, wallclock_seconds=560)
    return state


def main() -> int:
    cfg = RouterConfig.from_file(CONFIG_PATH)
    # The shipped config is deliberately uncalibrated. The demo supplies the
    # grid values explicitly instead of inventing a default, and says so.
    demo_cfg = cfg.with_thresholds(localization_disagreement=0.50, duplicate_rate=0.50)

    rows: list[dict[str, object]] = []
    stats = RoutingStats()
    failures = 0

    print(f"config: {cfg.config_version}  hash={cfg.digest[:12]}  thresholds=pending calibration")
    print(f"demo thresholds supplied explicitly: u_loc>0.50, u_dup>0.50\n")
    header = f"{'constructed state':<44} {'route':<12} {'rule that fired':<48}"
    print(header)
    print("-" * len(header))

    for scenario in SCENARIOS:
        state = scenario.build()
        decision = route(state, demo_cfg, allow_uncalibrated=True)
        stats.add(decision)
        ok = decision.route == scenario.expect_route and decision.reason == scenario.expect_reason
        failures += 0 if ok else 1
        print(f"{scenario.name:<44} {decision.route:<12} {decision.reason:<48}"
              + ("" if ok else "  <-- UNEXPECTED"))
        rows.append(
            {
                "state": scenario.name,
                "signal": scenario.signal,
                "route": decision.route,
                "rule": decision.rule,
                "reason": decision.reason,
                "detail": decision.detail,
                "expected": {"route": scenario.expect_route, "reason": scenario.expect_reason},
                "matched": ok,
                "all_rules": evaluate_all(state, demo_cfg),
            }
        )

    comparison_state = with_prefix_failure(stack=SUCCESS_STACK)
    arms = {
        "A fixed workflow": route_fixed_or_stop(comparison_state, demo_cfg),
        "C simple cascade": route_cascade(comparison_state, demo_cfg),
        "D adaptive (this rule set)": route(comparison_state, demo_cfg, allow_uncalibrated=True),
        "E random p=0.30 (seed 0)": route_random(comparison_state, demo_cfg, random.Random(0), 0.30),
    }
    print("\nsame prefix state, one row per arm:")
    for label, decision in arms.items():
        print(f"  {label:<28} -> {decision.route:<12} ({decision.reason})")

    record = None
    st = with_prefix_failure(candidates=[(DIFF_VARIANT, "pass")], stack=SUCCESS_STACK)
    decision = route(st, demo_cfg, allow_uncalibrated=True)
    st.record_decision(decision.rule, decision.route, decision.reason, decision.detail)
    st.budget.spend(token=6400, model_call=3, tool_call=5, wallclock_seconds=95)
    record = build_run_record(
        st, run_index=1, seed=0, model_version="demo-model-placeholder", elapsed_seconds=100.0
    )
    problems = runlog.validate(record)
    print("\nrun record from the same state: " + ("valid" if not problems else "; ".join(problems)))
    failures += len(problems)

    for warning in stats.warnings():
        print(f"WARNING: {warning}")

    payload = {
        "config_version": cfg.config_version,
        "config_hash": cfg.digest,
        "thresholds_used": {"localization_disagreement": 0.50, "duplicate_rate": 0.50},
        "thresholds_note": "the shipped config is uncalibrated; the demo passes values explicitly",
        "scenarios": rows,
        "arm_comparison_on_one_state": {k: v.to_dict() for k, v in arms.items()},
        "run_record": record,
        "routing_stats": stats.to_dict(),
        "run_record_valid": not problems,
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    json_path = os.path.join(OUT_DIR, "router_demo.json")
    with open(json_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")

    md_path = os.path.join(OUT_DIR, "router_demo.md")
    with open(md_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# 路由规则自检（构造状态，未调用模型）\n\n")
        fh.write(f"- 配置版本：`{cfg.config_version}`，配置哈希：`{cfg.digest}`\n")
        fh.write("- 演示阈值：u_loc > 0.50、u_dup > 0.50（正式阈值须在开发集上定稿）\n\n")
        fh.write("| 构造状态 | 观测信号 | 路由 | 生效规则 |\n| --- | --- | --- | --- |\n")
        for row in rows:
            fh.write(f"| {row['state']} | {row['signal']} | `{row['route']}` | `{row['reason']}` |\n")
        fh.write("\n## 同一前缀状态下的各组对比\n\n| 组别 | 路由 | 原因 |\n| --- | --- | --- |\n")
        for label, decision in arms.items():
            fh.write(f"| {label} | `{decision.route}` | `{decision.reason}` |\n")
        fh.write("\n## 运行记录校验\n\n")
        fh.write(f"由上述状态生成的运行记录：{'通过 schema 校验' if not problems else '未通过'}\n")
        for warning in stats.warnings():
            fh.write(f"\n- 警告：{warning}")
        fh.write("\n")

    print(f"\nwrote {md_path}")
    print(f"wrote {json_path}")
    print(f"\n{len(SCENARIOS)} constructed states, {failures} expectation mismatch(es)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
