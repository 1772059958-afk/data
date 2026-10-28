"""Per-task run record for the repair pipeline.

Implements the minimum record fields specified in Appendix A.2 of the proposal,
plus a hand-rolled validator so the schema can be enforced without extra
dependencies. Every finished task, successful or not, must produce exactly one
record: cost analysis is only meaningful if failed runs are logged too.

The evaluation label is written into a separate file by the offline evaluator;
it never feeds back into generation. To keep that separation visible, the
generation log carries ``evaluation_status`` only as a status placeholder that
starts at ``not_run``.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Iterable, NamedTuple

try:  # keep console output readable when redirected; never replace the stream
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):  # pragma: no cover
    pass

SCHEMA_VERSION = "1.0"

ROUTES = ("fixed", "interactive", "stop")

TERMINATION_REASONS = (
    "early_stop_public_pass",
    "stop_env_failure",
    "stop_budget_insufficient",
    "stagnation",
    "budget_exhausted",
    "step_limit",
    "agent_finish",
    "error",
)

EVALUATION_STATUSES = ("not_run", "resolved", "unresolved", "empty_patch", "error")

# A ``stop`` route closes generation, which happens either because a candidate
# already passed the public tests or because continuing is pointless or unsafe.
STOP_TERMINATION_REASONS = (
    "early_stop_public_pass",
    "stop_env_failure",
    "stop_budget_insufficient",
    "error",
)

VALIDATION_STATUSES = ("pass", "fail", "not_run", "not_applicable")


class Field(NamedTuple):
    name: str
    type: str
    description: str
    allowed: tuple[str, ...] | None = None


FIELDS: tuple[Field, ...] = (
    Field("instance_id", "string", "SWE-bench instance identifier"),
    Field("run_id", "string", "unique id of this run of this instance"),
    Field("seed", "integer", "random seed used for sampling"),
    Field("model_version", "string", "exact model identifier as reported by the service"),
    Field("config_hash", "string", "sha256 of the frozen experiment config"),
    Field("base_commit", "string", "commit the repository snapshot was taken at"),
    Field("container_id", "string|null", "container or isolated environment id"),
    Field("prefix_budget", "object", "budget allotted to the fixed prefix and its remainder"),
    Field("route", "string", "branch chosen by the router", ROUTES),
    Field("route_reason", "string", "identifier of the frozen rule that fired"),
    Field("patch_hash", "string|null", "sha256 of the normalised candidate diff that was frozen"),
    Field("public_validation", "object", "outcome of the public tests on the frozen candidate"),
    Field("input_tokens", "integer", "cumulative billed input tokens"),
    Field("output_tokens", "integer", "cumulative billed output tokens"),
    Field("model_calls", "integer", "cumulative model invocations"),
    Field("tool_calls", "integer", "cumulative tool invocations"),
    Field("elapsed_seconds", "number", "wall-clock seconds for the generation stage"),
    Field("termination_reason", "string", "why generation stopped", TERMINATION_REASONS),
    Field("evaluation_status", "string", "independent evaluation label", EVALUATION_STATUSES),
)

REQUIRED = tuple(f.name for f in FIELDS)
OPTIONAL = ("schema_version", "repo", "split", "notes")


def json_schema() -> dict[str, Any]:
    """Return a JSON Schema for one run record."""
    props: dict[str, Any] = {"schema_version": {"const": SCHEMA_VERSION}}
    for f in FIELDS:
        if f.type == "string":
            spec: dict[str, Any] = {"type": "string"}
        elif f.type == "string|null":
            spec = {"type": ["string", "null"]}
        elif f.type == "integer":
            spec = {"type": "integer", "minimum": 0}
        elif f.type == "number":
            spec = {"type": "number", "minimum": 0}
        else:
            spec = {"type": "object"}
        if f.allowed:
            spec["enum"] = list(f.allowed)
        spec["description"] = f.description
        props[f.name] = spec

    props["prefix_budget"] = {
        "type": "object",
        "description": "budget allotted to the fixed prefix",
        "required": ["token", "model_call", "tool_call", "wallclock_seconds"],
        "properties": {
            "token": {"type": "integer", "minimum": 0},
            "model_call": {"type": "integer", "minimum": 0},
            "tool_call": {"type": "integer", "minimum": 0},
            "wallclock_seconds": {"type": "number", "minimum": 0},
            "prefix_fraction": {"type": "number", "minimum": 0, "maximum": 1},
        },
    }
    props["public_validation"] = {
        "type": "object",
        "description": "outcome of the public tests on the frozen candidate",
        "required": ["status"],
        "properties": {
            "status": {"enum": list(VALIDATION_STATUSES)},
            "tests_total": {"type": "integer", "minimum": 0},
            "tests_passed": {"type": "integer", "minimum": 0},
            "detail": {"type": "string"},
        },
    }

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "swe-repair run record",
        "type": "object",
        "required": list(REQUIRED),
        "additionalProperties": False,
        "properties": props,
        "$comment": f"optional extras permitted: {', '.join(OPTIONAL)}",
    }


def _type_ok(value: Any, kind: str) -> bool:
    if kind == "string":
        return isinstance(value, str)
    if kind == "string|null":
        return value is None or isinstance(value, str)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0
    if kind == "object":
        return isinstance(value, dict)
    return False


def validate(record: dict[str, Any]) -> list[str]:
    """Return a list of problems; empty list means the record is valid."""
    problems: list[str] = []
    for name in REQUIRED:
        if name not in record:
            problems.append(f"missing required field: {name}")
    for name in record:
        if name not in REQUIRED and name not in OPTIONAL:
            problems.append(f"unknown field: {name}")
    for f in FIELDS:
        if f.name not in record:
            continue
        value = record[f.name]
        if not _type_ok(value, f.type):
            problems.append(f"{f.name}: expected {f.type}, got {type(value).__name__}")
            continue
        if f.allowed and value not in f.allowed:
            problems.append(f"{f.name}: {value!r} not in {f.allowed}")
    if "schema_version" in record and record["schema_version"] != SCHEMA_VERSION:
        problems.append(f"schema_version: expected {SCHEMA_VERSION}")

    pb = record.get("prefix_budget")
    if isinstance(pb, dict):
        for key in ("token", "model_call", "tool_call", "wallclock_seconds"):
            if key not in pb:
                problems.append(f"prefix_budget: missing {key}")
        frac = pb.get("prefix_fraction")
        if frac is not None and not (isinstance(frac, (int, float)) and 0 <= frac <= 1):
            problems.append("prefix_budget.prefix_fraction: must be within [0, 1]")

    pv = record.get("public_validation")
    if isinstance(pv, dict):
        status = pv.get("status")
        if status not in VALIDATION_STATUSES:
            problems.append(f"public_validation.status: {status!r} not in {VALIDATION_STATUSES}")
        total, passed = pv.get("tests_total"), pv.get("tests_passed")
        if isinstance(total, int) and isinstance(passed, int) and passed > total:
            problems.append("public_validation: tests_passed exceeds tests_total")

    # Structural guard: a router that reports a branch must justify it.
    if record.get("route") in ("fixed", "interactive") and not record.get("route_reason"):
        problems.append("route_reason: required when route selects a branch")
    if record.get("route") == "stop" and record.get("termination_reason") not in STOP_TERMINATION_REASONS:
        problems.append(
            "route=stop requires a termination reason from " + ", ".join(STOP_TERMINATION_REASONS)
        )

    return problems


def canonical_line(record: dict[str, Any]) -> str:
    """Serialise one record deterministically (sorted keys, compact separators)."""
    payload = {"schema_version": SCHEMA_VERSION, **record}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def config_hash(config: dict[str, Any]) -> str:
    """sha256 over a config dict, order-insensitive."""
    blob = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def patch_hash(diff_text: str) -> str:
    """sha256 of a patch after normalising line endings and trailing whitespace."""
    normalised = "\n".join(line.rstrip() for line in diff_text.replace("\r\n", "\n").split("\n"))
    return hashlib.sha256(normalised.strip().encode()).hexdigest()


class RunLogger:
    """Append-only JSONL writer; one line per finished task run."""

    def __init__(self, path: str | os.PathLike[str], strict: bool = True) -> None:
        self.path = os.fspath(path)
        self.strict = strict
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        self._fh = open(self.path, "a", encoding="utf-8", newline="\n")

    def write(self, record: dict[str, Any]) -> dict[str, Any]:
        problems = validate(record)
        if problems and self.strict:
            raise ValueError("invalid run record: " + "; ".join(problems))
        self._fh.write(canonical_line(record) + "\n")
        self._fh.flush()
        os.fsync(self._fh.fileno())
        return record

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()

    def __enter__(self) -> "RunLogger":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def read_records(path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    out = []
    with open(path, encoding="utf-8") as fh:
        for i, line in enumerate(fh, 1):
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{i}: {exc}") from exc
    return out


def log_digest(path: str | os.PathLike[str]) -> str:
    """sha256 over the canonical form of every record, so reordering is visible."""
    lines = sorted(canonical_line({k: v for k, v in r.items() if k != "schema_version"})
                   for r in read_records(path))
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def new_run_id(instance_id: str, seed: int, run_index: int) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{instance_id}__s{seed}__r{run_index}__{stamp}"


def validate_file(path: str | os.PathLike[str]) -> list[str]:
    problems: list[str] = []
    for i, record in enumerate(read_records(path), 1):
        payload = {k: v for k, v in record.items() if k != "schema_version"}
        for problem in validate(payload):
            problems.append(f"line {i}: {problem}")
    return problems


def _cli(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="run-record schema utilities")
    ap.add_argument("--schema", action="store_true", help="print the JSON Schema")
    ap.add_argument("--validate", metavar="LOG.jsonl", help="validate an existing log file")
    ap.add_argument("--digest", metavar="LOG.jsonl", help="print the log digest")
    args = ap.parse_args(list(argv) if argv is not None else None)

    if args.schema:
        print(json.dumps(json_schema(), indent=2, ensure_ascii=False))
        return 0
    if args.validate:
        problems = validate_file(args.validate)
        for p in problems:
            print(p)
        print(f"{len(problems)} problem(s)")
        return 1 if problems else 0
    if args.digest:
        print(log_digest(args.digest))
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
