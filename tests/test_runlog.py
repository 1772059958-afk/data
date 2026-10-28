"""Self-checks for the run-record schema. Runs under pytest or plain python."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):  # pragma: no cover
    pass

from swe_repair import runlog  # noqa: E402


def sample(**overrides):
    record = {
        "instance_id": "django__django-11099",
        "run_id": runlog.new_run_id("django__django-11099", 0, 1),
        "seed": 0,
        "model_version": "placeholder-model-v1",
        "config_hash": runlog.config_hash({"config_version": "frozen_v1"}),
        "base_commit": "0f3b3b0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f",
        "container_id": None,
        "prefix_budget": {
            "token": 19200,
            "model_call": 8,
            "tool_call": 12,
            "wallclock_seconds": 360,
            "prefix_fraction": 0.30,
        },
        "route": "interactive",
        "route_reason": "interactive_on_out_of_scope_stack_evidence",
        "patch_hash": runlog.patch_hash("--- a/x.py\n+++ b/x.py\n"),
        "public_validation": {"status": "fail", "tests_total": 4, "tests_passed": 1},
        "input_tokens": 18342,
        "output_tokens": 2210,
        "model_calls": 9,
        "tool_calls": 14,
        "elapsed_seconds": 412.7,
        "termination_reason": "stagnation",
        "evaluation_status": "not_run",
    }
    record.update(overrides)
    return record


def test_schema_has_nineteen_required_fields():
    schema = runlog.json_schema()
    assert len(schema["required"]) == 19, len(schema["required"])
    assert schema["additionalProperties"] is False


def test_valid_record_passes():
    assert runlog.validate(sample()) == []


def test_missing_field_is_reported():
    bad = sample()
    del bad["seed"]
    problems = runlog.validate(bad)
    assert any("seed" in p for p in problems), problems


def test_bad_enum_is_reported():
    problems = runlog.validate(sample(route="magic"))
    assert any("route" in p for p in problems), problems


def test_branch_without_reason_is_rejected():
    problems = runlog.validate(sample(route_reason=""))
    assert any("route_reason" in p for p in problems), problems


def test_stop_route_needs_stop_reason():
    problems = runlog.validate(sample(route="stop", termination_reason="stagnation"))
    assert any("route=stop" in p for p in problems), problems


def test_prefix_fraction_bounds():
    rec = sample()
    rec["prefix_budget"]["prefix_fraction"] = 1.4
    problems = runlog.validate(rec)
    assert any("prefix_fraction" in p for p in problems), problems


def test_passed_must_not_exceed_total():
    rec = sample(public_validation={"status": "pass", "tests_total": 2, "tests_passed": 5})
    problems = runlog.validate(rec)
    assert any("tests_passed" in p for p in problems), problems


def test_round_trip_and_reproducible_digest():
    with tempfile.TemporaryDirectory() as tmp:
        a, b = os.path.join(tmp, "a.jsonl"), os.path.join(tmp, "b.jsonl")
        with runlog.RunLogger(a) as log:
            log.write(sample(instance_id="sympy__sympy-20590"))
            log.write(sample(instance_id="django__django-11099"))
        with runlog.RunLogger(b) as log:
            for rec in reversed(runlog.read_records(a)):
                log.write({k: v for k, v in rec.items() if k != "schema_version"})
        assert runlog.log_digest(a) == runlog.log_digest(b)
        assert runlog.validate_file(a) == []


def test_strict_logger_raises_on_invalid_record():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "c.jsonl")
        with runlog.RunLogger(path) as log:
            try:
                log.write(sample(route="nonsense"))
            except ValueError:
                pass
            else:
                raise AssertionError("strict logger accepted an invalid record")
        assert runlog.read_records(path) == []


def test_json_schema_is_serialisable():
    blob = json.dumps(runlog.json_schema(), ensure_ascii=False)
    assert "evaluation_status" in blob


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS  {name}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"FAIL  {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len([n for n in globals() if n.startswith('test_')])} checks, {failures} failed")
    raise SystemExit(1 if failures else 0)
