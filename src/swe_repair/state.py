"""The state recorder: the six interfaces of table 3.1 in the proposal.

    task_manifest    instance id, repo commit, config and image identity
    localization     per-pass file and symbol sets, evidence positions
    patch_history    normalised diffs, hashes, validation status
    failure_record   command, exit code, error class, relevant frames
    budget_state     consumption and remaining allowance per resource
    decision_trace   rule, branch, reason, timestamp

The recorder exists so that a routing mistake and an executor mistake can be
told apart after the fact. Two properties are therefore built in rather than
left to the driver:

* the state is JSON-serialisable and versioned, because modules pass it between
  each other and the intermediate state of a paired-branch experiment has to be
  frozen and replayed;
* the state cannot hold evaluation-side fields. ``assert_generation_only``
  raises if a payload smuggles in the gold patch, the test patch or the
  FAIL_TO_PASS / PASS_TO_PASS lists, which is the field whitelist promised in
  section 3.1.

Nothing in this module calls a model, a container or the network.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping, Sequence

from . import fingerprint as fp
from .budget import ASPECTS, Budget, BudgetState, split_prefix
from .runlog import patch_hash

STATE_VERSION = "1.0"

# Fields that exist only on the evaluation side. Their presence in a state
# payload means the whitelist leaked, and the run must not proceed.
WITHHELD_FIELDS = (
    "patch",  # the developer patch, i.e. the answer
    "test_patch",
    "FAIL_TO_PASS",
    "PASS_TO_PASS",
    "fail_to_pass",
    "pass_to_pass",
    "resolved",
    "gold",
    "evaluation_status",
    "hints_text",
    "created_at",
)

BEHAVIOURAL_SIGNALS = ("behavioural", "non_behavioural", "none")


class WithheldFieldError(ValueError):
    """Raised when generation-side state contains evaluation-side fields."""


# Columns the generation view is allowed to see, from the config's
# ``generation_view_fields`` plus the problem statement.
GENERATION_VIEW_FIELDS = (
    "instance_id",
    "repo",
    "base_commit",
    "version",
    "environment_setup_commit",
    "problem_statement",
)


def assert_generation_only(payload: Mapping[str, Any], where: str = "payload") -> None:
    """Raise if any evaluation-side field appears anywhere in the payload."""
    leaked: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, Mapping):
            for key, value in node.items():
                here = f"{path}.{key}" if path else str(key)
                if key in WITHHELD_FIELDS:
                    leaked.append(here)
                walk(value, here)
        elif isinstance(node, (list, tuple)):
            for i, value in enumerate(node):
                walk(value, f"{path}[{i}]")

    walk(payload, "")
    if leaked:
        raise WithheldFieldError(
            f"{where} carries evaluation-side field(s): {', '.join(sorted(set(leaked)))}"
        )


def generation_view(row: Mapping[str, Any]) -> dict[str, Any]:
    """Project a dataset row down to the fields generation is allowed to see.

    The dataset files ship the gold patch, the test patch and the expected test
    lists in the same row. This is the single place where they are dropped, so
    the rest of the pipeline can assert that it never saw them.
    """
    view = {k: row[k] for k in GENERATION_VIEW_FIELDS if k in row}
    assert_generation_only(view, "generation view")
    return view


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# --------------------------------------------------------------------------
# task_manifest
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TaskManifest:
    """Everything needed to reproduce the starting point of a run."""

    instance_id: str
    repo: str
    base_commit: str
    config_version: str
    config_hash: str
    image_id: str | None = None
    version: str | None = None
    environment_setup_commit: str | None = None
    repo_root: str = "/testbed"

    @classmethod
    def from_instance(cls, instance: Mapping[str, Any], config_version: str, config_hash: str, **extra: Any) -> "TaskManifest":
        """Build from a projected generation view, never from a raw dataset row."""
        assert_generation_only(instance, "task manifest input")
        return cls(
            instance_id=str(instance["instance_id"]),
            repo=str(instance["repo"]),
            base_commit=str(instance["base_commit"]),
            config_version=config_version,
            config_hash=config_hash,
            version=instance.get("version"),
            environment_setup_commit=instance.get("environment_setup_commit"),
            **extra,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------
# localization
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class LocalizationPass:
    """One localisation attempt: which files and symbols it pointed at."""

    label: str
    files: frozenset[str] = frozenset()
    symbols: frozenset[str] = frozenset()
    evidence: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "LocalizationPass":
        return cls(
            label=str(payload["label"]),
            files=frozenset(payload.get("files", ())),
            symbols=frozenset(payload.get("symbols", ())),
            evidence=tuple(payload.get("evidence", ())),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "files": sorted(self.files),
            "symbols": sorted(self.symbols),
            "evidence": list(self.evidence),
        }


@dataclass
class Localization:
    """Repeated localisation results and the disagreement derived from them."""

    passes: tuple[LocalizationPass, ...] = ()

    @classmethod
    def from_file_sets(cls, file_sets: Mapping[str, Iterable[str]]) -> "Localization":
        return cls(tuple(LocalizationPass(label, frozenset(files)) for label, files in file_sets.items()))

    def add(self, pass_: LocalizationPass) -> None:
        self.passes = self.passes + (pass_,)

    @property
    def missing(self) -> bool:
        """True when no pass found anything: a separate flag, not agreement."""
        return bool(self.passes) and all(not p.files for p in self.passes)

    def files_union(self) -> frozenset[str]:
        out: set[str] = set()
        for pass_ in self.passes:
            out |= pass_.files
        return frozenset(out)

    def symbols_union(self) -> frozenset[str]:
        out: set[str] = set()
        for pass_ in self.passes:
            out |= pass_.symbols
        return frozenset(out)

    def disagreement(self) -> float | None:
        """u_loc = 1 - mean pairwise Jaccard over file sets (section 4.2).

        Pairs where both sets are empty carry no information and are skipped;
        when no informative pair exists the value is ``None`` and the caller
        must treat the localisation as missing rather than as confident
        agreement. ``None`` therefore never satisfies a numeric threshold.
        """
        sets = [p.files for p in self.passes]
        if len(sets) < 2:
            return None
        similarities: list[float] = []
        for i in range(len(sets)):
            for j in range(i + 1, len(sets)):
                a, b = sets[i], sets[j]
                if not a and not b:
                    continue
                union = a | b
                similarities.append(len(a & b) / len(union) if union else 0.0)
        if not similarities:
            return None
        mean = sum(similarities) / len(similarities)
        return max(0.0, min(1.0, 1.0 - mean))

    def to_dict(self) -> dict[str, Any]:
        return {
            "passes": [p.to_dict() for p in self.passes],
            "files_union": sorted(self.files_union()),
            "symbols_union": sorted(self.symbols_union()),
            "disagreement": self.disagreement(),
            "missing": self.missing,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Localization":
        return cls(tuple(LocalizationPass.from_dict(p) for p in payload.get("passes", ())))


# --------------------------------------------------------------------------
# patch_history
# --------------------------------------------------------------------------


VALIDATION_STATUSES = ("pass", "fail", "not_run", "not_applicable")


@dataclass(frozen=True)
class Candidate:
    """One generated patch candidate, with its prefix-stage validation state."""

    index: int
    diff: str
    applies_cleanly: bool | None = None
    validation: str = "not_run"
    files_touched: tuple[str, ...] = ()
    diff_lines: int = 0
    origin: str = "prefix"
    syntax: str = "not_run"
    scope_valid: bool = True

    def __post_init__(self) -> None:
        if self.validation not in VALIDATION_STATUSES:
            raise ValueError(f"validation {self.validation!r} not in {VALIDATION_STATUSES}")

    @property
    def hash(self) -> str:
        """Normalised diff hash, the identity used for deduplication."""
        return patch_hash(self.diff)

    @classmethod
    def build(
        cls,
        index: int,
        diff: str,
        *,
        applies_cleanly: bool | None = None,
        validation: str = "not_run",
        origin: str = "prefix",
        syntax: str = "not_run",
        scope_valid: bool = True,
    ) -> "Candidate":
        from .patchutil import count_diff_lines, files_touched

        return cls(
            index=index,
            diff=diff,
            applies_cleanly=applies_cleanly,
            validation=validation,
            files_touched=files_touched(diff),
            diff_lines=count_diff_lines(diff),
            origin=origin,
            syntax=syntax,
            scope_valid=scope_valid,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            # The diff text travels with the snapshot: the paired-branch
            # experiment has to replay the exact candidate, and run records keep
            # only the hash.
            "diff": self.diff,
            "hash": self.hash,
            "applies_cleanly": self.applies_cleanly,
            "validation": self.validation,
            "files_touched": list(self.files_touched),
            "diff_lines": self.diff_lines,
            "origin": self.origin,
            "syntax": self.syntax,
            "scope_valid": self.scope_valid,
        }


@dataclass
class PatchHistory:
    """Ordered candidates plus the derived duplicate rate."""

    candidates: list[Candidate] = field(default_factory=list)

    def add(self, candidate: Candidate) -> None:
        self.candidates.append(candidate)

    @property
    def hashes(self) -> tuple[str, ...]:
        return tuple(c.hash for c in self.candidates)

    def duplicate_rate(self) -> float:
        """u_dup: share of candidates whose normalised diff repeats an earlier one."""
        total = len(self.candidates)
        if total < 2:
            return 0.0
        seen: set[str] = set()
        duplicates = 0
        for candidate in self.candidates:
            if candidate.hash in seen:
                duplicates += 1
            seen.add(candidate.hash)
        return duplicates / total

    def has_public_pass(self) -> bool:
        return any(c.validation == "pass" for c in self.applicable())

    def applicable(self) -> list[Candidate]:
        return [c for c in self.candidates if c.applies_cleanly is True
                and c.syntax != "fail" and c.scope_valid and c.diff.strip()]

    def best_candidate(self) -> Candidate | None:
        """Deterministic selection order frozen in the config (section 4.4).

        Applies cleanly, then public validation, then fewer files touched, then
        fewer changed lines, then generation order. It is a way to hold an
        experimental variable fixed, not a claim that smaller is better.
        """
        pool = self.applicable()
        if not pool:
            return None
        return min(
            pool,
            key=lambda c: (
                0 if c.validation == "pass" else 1,
                len(c.files_touched),
                c.diff_lines,
                c.index,
            ),
        )

    def public_validation(self) -> dict[str, Any]:
        """The runlog ``public_validation`` object for the frozen candidate."""
        best = self.best_candidate()
        if best is None:
            return {"status": "not_applicable", "detail": "no applicable candidate"}
        detail = f"candidate#{best.index} files={len(best.files_touched)} lines={best.diff_lines}"
        return {"status": best.validation, "detail": detail}

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": [c.to_dict() for c in self.candidates],
            "duplicate_rate": self.duplicate_rate(),
            "distinct_hashes": len(set(self.hashes)),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PatchHistory":
        history = cls()
        for item in payload.get("candidates", ()):
            history.add(
                Candidate(
                    index=int(item["index"]),
                    diff=str(item.get("diff", "")),
                    applies_cleanly=item.get("applies_cleanly"),
                    validation=str(item.get("validation", "not_run")),
                    files_touched=tuple(item.get("files_touched", ())),
                    diff_lines=int(item.get("diff_lines", 0)),
                    origin=str(item.get("origin", "prefix")),
                    syntax=str(item.get("syntax", "not_run")),
                    scope_valid=bool(item.get("scope_valid", True)),
                )
            )
        return history


# --------------------------------------------------------------------------
# failure_record
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class FailureRecord:
    """One executed command that did not give the outcome the run wanted."""

    stage: str
    command: str
    exit_code: int
    error_class: str
    fingerprint: str
    repo_frames: tuple[str, ...] = ()
    message_head: str = ""
    recovery_attempts: int = 0

    def __post_init__(self) -> None:
        if self.error_class not in fp.CLASSES:
            raise ValueError(f"error_class {self.error_class!r} not in {fp.CLASSES}")

    @classmethod
    def from_output(
        cls,
        command: str,
        exit_code: int,
        *,
        stage: str,
        stdout: str = "",
        stderr: str = "",
        repo_root: str | None = None,
        recovery_attempts: int = 0,
    ) -> "FailureRecord":
        summary = fp.describe(exit_code, stdout, stderr, stage=stage, repo_root=repo_root)
        return cls(
            stage=summary["stage"],
            command=command,
            exit_code=int(summary["exit_code"]),
            error_class=str(summary["error_class"]),
            fingerprint=str(summary["fingerprint"]),
            repo_frames=tuple(summary["repo_frames"]),
            message_head=str(summary["message_head"]),
            recovery_attempts=recovery_attempts,
        )

    def with_recovery(self) -> "FailureRecord":
        return FailureRecord(
            stage=self.stage,
            command=self.command,
            exit_code=self.exit_code,
            error_class=self.error_class,
            fingerprint=self.fingerprint,
            repo_frames=self.repo_frames,
            message_head=self.message_head,
            recovery_attempts=self.recovery_attempts + 1,
        )

    @property
    def is_environment(self) -> bool:
        return self.error_class == "env_setup"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FailureRecord":
        data = dict(payload)
        data["repo_frames"] = tuple(data.get("repo_frames", ()))
        return cls(**data)  # type: ignore[arg-type]


@dataclass
class FailureLog:
    """Append-only failure history, including failures of failed runs."""

    records: list[FailureRecord] = field(default_factory=list)

    def add(self, record: FailureRecord) -> None:
        self.records.append(record)

    @property
    def latest(self) -> FailureRecord | None:
        return self.records[-1] if self.records else None

    def classes(self) -> tuple[str, ...]:
        return tuple(r.error_class for r in self.records)

    def distinct_fingerprints(self) -> tuple[str, ...]:
        return fp.distinct(r.fingerprint for r in self.records)

    def environment_failure(self) -> FailureRecord | None:
        """Most recent environment failure, whether or not it was retried."""
        for record in reversed(self.records):
            if record.stage == 'env' and record.exit_code == 0:
                return None  # explicit successful deterministic recovery
            if record.is_environment:
                return record
        return None

    def needs_recovery_attempt(self) -> bool:
        """An untried deterministic recovery: the driver's job, before routing."""
        record = self.environment_failure()
        return record is not None and record.recovery_attempts == 0

    def environment_failure_after_recovery(self) -> FailureRecord | None:
        record = self.environment_failure()
        if record is not None and record.recovery_attempts >= 1:
            return record
        return None

    def out_of_scope_frames(self, observed: frozenset[str]) -> tuple[str, ...]:
        """Repository frames in the traceback that the run has never inspected.

        This is the trigger described in section 4.5: the new stack points at a
        repository file outside the current context, so the fix has to look
        somewhere the fixed prefix would not have looked.
        """
        latest = self.latest
        if latest is None:
            return ()
        seen: dict[str, None] = {}
        for path in latest.repo_frames:
            if path not in observed:
                seen.setdefault(path, None)
        return tuple(seen)

    def to_dict(self) -> dict[str, Any]:
        return {
            "records": [r.to_dict() for r in self.records],
            "distinct_fingerprints": list(self.distinct_fingerprints()),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FailureLog":
        return cls([FailureRecord.from_dict(r) for r in payload.get("records", ())])


# --------------------------------------------------------------------------
# context view (read files) and decision trace
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ContextView:
    """What the run has actually looked at, and what it can run to check itself.

    Separating this from ``Localization`` matters: the prefix may localise three
    files and read only one of them, and the out-of-scope rule is about what was
    read or indexed, not about what a retriever guessed.
    """

    indexed_paths: frozenset[str] = frozenset()
    read_files: frozenset[str] = frozenset()
    registered_test_commands: tuple[str, ...] = ()
    repro_scripts: tuple[str, ...] = ()
    checks_run: int = 0
    repro_reproduces: bool | None = None

    def observed_paths(self) -> frozenset[str]:
        return self.indexed_paths | self.read_files

    def to_dict(self) -> dict[str, Any]:
        return {
            "indexed_paths": sorted(self.indexed_paths),
            "read_files": sorted(self.read_files),
            "registered_test_commands": list(self.registered_test_commands),
            "repro_scripts": list(self.repro_scripts),
            "checks_run": self.checks_run,
            "repro_reproduces": self.repro_reproduces,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ContextView":
        return cls(
            indexed_paths=frozenset(payload.get("indexed_paths", ())),
            read_files=frozenset(payload.get("read_files", ())),
            registered_test_commands=tuple(payload.get("registered_test_commands", ())),
            repro_scripts=tuple(payload.get("repro_scripts", ())),
            checks_run=int(payload.get("checks_run", 0)),
            repro_reproduces=payload.get("repro_reproduces"),
        )


@dataclass(frozen=True)
class TraceEntry:
    seq: int
    timestamp: str
    rule: str
    route: str
    reason: str
    detail: str
    u_loc: float | None
    u_dup: float
    remaining: dict[str, float]
    config_version: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TraceEntry":
        return cls(**dict(payload))  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# the container
# --------------------------------------------------------------------------


@dataclass
class RepairState:
    """The versioned JSON object passed between the modules."""

    task: TaskManifest
    localization: Localization = field(default_factory=Localization)
    patches: PatchHistory = field(default_factory=PatchHistory)
    failures: FailureLog = field(default_factory=FailureLog)
    budget: BudgetState | None = None
    context: ContextView = field(default_factory=ContextView)
    trace: list[TraceEntry] = field(default_factory=list)
    clock: Callable[[], str] = _now
    state_version: str = STATE_VERSION

    # -- derived signals ---------------------------------------------------

    @property
    def u_loc(self) -> float | None:
        return self.localization.disagreement()

    @property
    def u_dup(self) -> float:
        return self.patches.duplicate_rate()

    def behavioural_signal(self) -> str:
        """Whether any usable behavioural check has been observed (section 4.2).

        ``behavioural``  a check produced a behaviour outcome (an assertion pass
                                or an assertion failure) or a repro script reproduces
        ``non_behavioural`` checks ran but only failed for format, syntax or
        environment reasons, so nothing was learned about behaviour
        ``none``         nothing runnable has been found or executed yet
        """
        if self.patches.has_public_pass():
            return "behavioural"
        if self.context.repro_reproduces:
            return "behavioural"
        if "behaviour_assertion" in self.failures.classes():
            return "behavioural"
        if self.context.checks_run > 0:
            return "non_behavioural"
        if self.context.registered_test_commands or self.context.repro_scripts:
            return "non_behavioural"
        return "none"

    def out_of_scope_frames(self) -> tuple[str, ...]:
        return self.failures.out_of_scope_frames(self.context.observed_paths())

    # -- trace -------------------------------------------------------------

    def record_decision(self, rule: str, route: str, reason: str, detail: str) -> TraceEntry:
        entry = TraceEntry(
            seq=len(self.trace) + 1,
            timestamp=self.clock(),
            rule=rule,
            route=route,
            reason=reason,
            detail=detail,
            u_loc=self.u_loc,
            u_dup=self.u_dup,
            remaining=self.budget.remaining.as_dict() if self.budget else {},
            config_version=self.task.config_version,
        )
        self.trace.append(entry)
        return entry

    @property
    def last_decision(self) -> TraceEntry | None:
        return self.trace[-1] if self.trace else None

    # -- serialisation -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "state_version": self.state_version,
            "task_manifest": self.task.to_dict(),
            "localization": self.localization.to_dict(),
            "patch_history": self.patches.to_dict(),
            "failure_record": self.failures.to_dict(),
            "budget_state": self.budget.to_dict() if self.budget else None,
            "context_view": self.context.to_dict(),
            "decision_trace": [t.to_dict() for t in self.trace],
            "derived": {
                "u_loc": self.u_loc,
                "u_dup": self.u_dup,
                "behavioural_signal": self.behavioural_signal(),
                "out_of_scope_frames": list(self.out_of_scope_frames()),
            },
        }

    def to_json(self, *, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, indent=indent)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any], clock: Callable[[], str] = _now) -> "RepairState":
        assert_generation_only(payload, "state")
        version = str(payload.get("state_version", STATE_VERSION))
        if version != STATE_VERSION:
            raise ValueError(f"unsupported state_version {version!r}")
        budget = payload.get("budget_state")
        return cls(
            task=TaskManifest(**dict(payload["task_manifest"])),
            localization=Localization.from_dict(payload.get("localization", {})),
            patches=PatchHistory.from_dict(payload.get("patch_history", {})),
            failures=FailureLog.from_dict(payload.get("failure_record", {})),
            budget=BudgetState.from_dict(budget) if budget else None,
            context=ContextView.from_dict(payload.get("context_view", {})),
            trace=[TraceEntry.from_dict(t) for t in payload.get("decision_trace", ())],
            clock=clock,
            state_version=version,
        )

    def snapshot_for_replay(self) -> str:
        """Frozen intermediate state, used by the paired branch experiment.

        Both branches start from byte-identical state, so any difference between
        them comes from the branch and not from an inherited artefact.
        """
        payload = self.to_dict()
        payload["decision_trace"] = []
        payload["budget_state"] = None if payload["budget_state"] is None else {
            **payload["budget_state"],
            "overrun": False,
            "exhausted_at": None,
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def budget_split_for_state(
    state: RepairState,
    prefix_fraction: float,
) -> tuple[Budget, Budget]:
    """Prefix allowance and the remainder kept for whichever branch the router picks."""
    if state.budget is None:
        raise ValueError("state has no budget")
    remainder = state.budget.remaining
    return split_prefix(remainder, prefix_fraction)


STOP_REASON_TO_TERMINATION = {
    "early_stop_public_pass": "early_stop_public_pass",
    "stop_env_failure": "stop_env_failure",
    "stop_budget_insufficient": "stop_budget_insufficient",
}


def build_run_record(
    state: RepairState,
    *,
    run_index: int,
    seed: int,
    model_version: str,
    elapsed_seconds: float,
    container_id: str | None = None,
    termination_reason: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    notes: str = "",
) -> dict[str, Any]:
    """Turn a finished run's state into one row of the run log.

    The evaluator writes ``evaluation_status`` later, in a separate file, so it
    stays ``not_run`` here. That ordering is the point: the label must not be
    able to influence anything the generation stage produced.
    """
    from .runlog import new_run_id

    decision = state.last_decision
    if decision is None:
        raise ValueError("no routing decision recorded on this state")
    if termination_reason is None:
        termination_reason = STOP_REASON_TO_TERMINATION.get(decision.reason)
        if termination_reason is None:
            raise ValueError(
                "termination_reason is required for a continuation branch: the driver knows why "
                "generation stopped, this module does not"
            )

    consumed_token = state.budget.consumed.token if state.budget else 0
    if input_tokens is None and output_tokens is None:
        input_tokens, output_tokens = consumed_token, 0
        if consumed_token:
            notes = (notes + " token split not supplied; total booked as input").strip()

    best = state.patches.best_candidate()
    return {
        "instance_id": state.task.instance_id,
        "run_id": new_run_id(state.task.instance_id, seed, run_index),
        "seed": seed,
        "model_version": model_version,
        "config_hash": state.task.config_hash,
        "base_commit": state.task.base_commit,
        "container_id": container_id or state.task.image_id,
        "prefix_budget": {
            "token": state.budget.ceiling.token if state.budget else 0,
            "model_call": state.budget.ceiling.model_call if state.budget else 0,
            "tool_call": state.budget.ceiling.tool_call if state.budget else 0,
            "wallclock_seconds": state.budget.ceiling.wallclock_seconds if state.budget else 0.0,
        },
        "route": decision.route,
        "route_reason": decision.reason,
        "patch_hash": best.hash if best else None,
        "public_validation": state.patches.public_validation(),
        "input_tokens": int(input_tokens or 0),
        "output_tokens": int(output_tokens or 0),
        "model_calls": state.budget.consumed.model_call if state.budget else 0,
        "tool_calls": state.budget.consumed.tool_call if state.budget else 0,
        "elapsed_seconds": float(elapsed_seconds),
        "termination_reason": termination_reason,
        "evaluation_status": "not_run",
        "repo": state.task.repo,
        "notes": notes,
    }


def summarise(states: Sequence[RepairState]) -> dict[str, Any]:
    """Aggregate the signals over a batch, for the prefix-stage report."""
    routes: dict[str, int] = {}
    for state in states:
        decision = state.last_decision
        if decision:
            routes[decision.reason] = routes.get(decision.reason, 0) + 1
    return {"instances": len(states), "route_reasons": routes}
