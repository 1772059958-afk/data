"""The shared prefix: index, localise, read, generate candidates, validate.

Every arm except B runs this exact code before it is allowed to differ. The
proposal makes the prefix the unit that keeps the comparison honest (section
4.1): if two arms generate different candidates on the same instance, the
difference between them stops being about routing.

Three properties are enforced here rather than left to convention:

* The prefix never sees ``FAIL_TO_PASS``, ``PASS_TO_PASS`` or ``test_patch``,
  not even the test file names. Localisation comes from the report text and from
  a model pass over it, which is what B2 of the protocol demands.
* Validation is limited to checks the repository already offers: whether the
  diff applies, whether the touched files still compile, and whether the
  repository's own tests that sit next to the touched modules still pass. Those
  are "public" in the sense the proposal uses the word -- discoverable from the
  checkout alone -- and are never the hidden evaluation tests.
* Every candidate is reverted before the next one is tried, so a candidate's
  validation result cannot depend on what was tried before it.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import time
import shlex
from dataclasses import replace
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from .execution import ResourceLimit
from .llm import ChatResult, DeepSeekClient, ModelConfig
from .patchutil import count_diff_lines, files_touched, repair_hunk_headers, patch_scope_valid, safe_repo_path
from .state import (
    Candidate,
    ContextView,
    FailureLog,
    FailureRecord,
    Localization,
    LocalizationPass,
    PatchHistory,
    RepairState,
    TaskManifest,
)

# Deliberately small: the prefix is a third of the budget and the remainder has
# to fund whichever branch the router picks.
MAX_FILES = 4
MAX_CONTEXT_CHARS = 60_000
MAX_LISTING_LINES = 80

PYTEST_TIMEOUT = 180


# --------------------------------------------------------------------------
# containers
# --------------------------------------------------------------------------


def image_for(instance_id: str) -> str:
    return f"swebench/sweb.eval.x86_64.{instance_id.replace('__', '_1776_')}:latest"


class Container:
    """A long-lived container for one instance.

    The harness starts a fresh container per instance, but a repair run needs to
    apply and revert several candidates in place, so this keeps one alive for the
    length of the prefix and tears it down afterwards.
    """

    def __init__(self, image: str, name: str, workdir: str = "/testbed") -> None:
        self.image = image
        self.name = name
        self.workdir = workdir
        self._started = False

    def start(self) -> None:
        subprocess.run(["docker", "rm", "-f", self.name], capture_output=True, text=True)
        proc = subprocess.run(
            [
                "docker", "run", "-d", "--network", "none", "--name", self.name,
                "--entrypoint", "/bin/bash", self.image, "-lc", "sleep infinity",
            ],
            capture_output=True, text=True, errors="replace",
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"could not start {self.image}: {proc.stderr.strip()[:300]}"
            )
        self._started = True

    def bash(self, script: str, timeout: int = 300) -> tuple[int, str]:
        """Run a shell script inside the container. Exit code is returned, not raised."""
        proc = subprocess.run(
            ["docker", "exec", self.name, "bash", "-lc",
             f"timeout --signal=KILL {float(timeout)}s bash -lc {shlex.quote(script)}"],
            capture_output=True, text=True, errors="replace", timeout=timeout + 5,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")

    def write_file(self, path: str, text: str) -> None:
        """Push text into the container without depending on shell quoting."""
        blob = base64.b64encode(text.encode("utf-8")).decode("ascii")
        code, out = self.bash(f"printf '%s' '{blob}' | base64 -d > {shlex.quote(path)}")
        if code != 0:
            raise RuntimeError(f"could not write {path}: {out[:300]}")

    def close(self) -> None:
        if self._started:
            subprocess.run(["docker", "rm", "-f", self.name], capture_output=True, text=True)
            self._started = False

    # -- convenience ------------------------------------------------------

    def apply(self, diff: str, *, check_only: bool = False) -> tuple[bool, str]:
        """Try a diff. ``check_only`` leaves the checkout untouched."""
        if not diff.strip():
            return False, "empty diff"
        self.write_file("/tmp/candidate.diff", diff)
        flag = " --check" if check_only else ""
        return self._git_apply(f"git apply{flag} /tmp/candidate.diff")

    def _git_apply(self, command: str) -> tuple[bool, str]:
        code, out = self.bash(
            f"cd {self.workdir} && {command} 2>&1; echo \"__rc=$?\""
        )
        rc = _trailing_rc(out)
        return rc == 0, _strip_rc(out)

    def revert(self) -> None:
        self.bash(
            f"cd {self.workdir} && git checkout -- . && git clean -fdq "
            "> /dev/null 2>&1; true"
        )

    def head(self) -> str:
        code, out = self.bash(f"cd {self.workdir} && git rev-parse HEAD")
        return _strip_rc(out).strip().splitlines()[0] if code == 0 else ""

    def image_digest(self) -> str:
        proc = subprocess.run(['docker', 'image', 'inspect', '--format', '{{.Id}}', self.image],
                              capture_output=True, text=True, timeout=30)
        if proc.returncode:
            raise RuntimeError('image identity unavailable')
        return proc.stdout.strip()


def _trailing_rc(text: str) -> int:
    match = re.search(r"__rc=(\d+)\s*$", text or "")
    return int(match.group(1)) if match else 1


def _strip_rc(text: str) -> str:
    return re.sub(r"__rc=\d+\s*$", "", text or "").strip()


# --------------------------------------------------------------------------
# localisation: two independent passes, so u_loc is defined
# --------------------------------------------------------------------------

_LEXICAL = re.compile(r"[/\w.\-]+\.py")


def lexical_localize(problem: str) -> frozenset[str]:
    """Paths quoted in the report. Cheap, independent of the model."""
    tails: list[str] = []
    for raw in _LEXICAL.findall(problem or ""):
        parts = raw.lstrip("/").split("/")
        for marker in ("site-packages", "src", "lib"):
            if marker in parts:
                parts = parts[parts.index(marker) + 1:]
                break
        tail = "/".join(parts[-3:])
        if tail.endswith(".py") and tail not in tails and not tail.startswith("python"):
            tails.append(tail)
    return frozenset(tails[:MAX_FILES])


LOCALIZE_SYSTEM = """You are locating the source of a bug in a Python repository.

You get a bug report and the names of the repository's top-level entries. Reply
with JSON only, no prose:

{"files": ["path/one.py", "path/two.py"], "symbols": ["name_one"]}

Rules:
- At most 4 files, most likely first. Repository-relative paths only.
- Pick files that would have to change to fix the bug, not test files.
- If you cannot tell, return fewer files rather than guessing broadly.
"""


def localize_messages(problem: str, listing: Sequence[str]) -> list[dict[str, Any]]:
    body = (
        f"# Bug report\n\n{problem.strip()}\n\n"
        f"# Top-level entries\n\n" + "\n".join(listing[:MAX_LISTING_LINES])
    )
    return [
        {"role": "system", "content": LOCALIZE_SYSTEM},
        {"role": "user", "content": body},
    ]


_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def parse_localization(text: str) -> tuple[frozenset[str], frozenset[str]]:
    match = _JSON_OBJECT.search(text or "")
    if not match:
        return frozenset(), frozenset()
    try:
        payload = json.loads(match.group(0))
    except ValueError:
        return frozenset(), frozenset()
    files = {
        safe_repo_path(p.strip())
        for p in (payload.get("files") or [])
        if isinstance(p, str) and p.strip()
    }
    symbols = {str(s).strip() for s in (payload.get("symbols") or []) if isinstance(s, str)}
    return frozenset(sorted(files)[:MAX_FILES]), frozenset(sorted(symbols))


def resolve_paths(container: Container, wanted: Iterable[str]) -> list[str]:
    """Map report-style path tails onto real paths in the checkout."""
    tails = [safe_repo_path(t) for t in wanted if t]
    if not tails:
        return []
    script = ["cd /testbed", "while IFS= read -r tail; do", '  [ -z "$tail" ] && continue']
    script.append(
        '  found=$(find . -path ./.git -prune -o -type f -name "$(basename "$tail")" '
        "-print 2>/dev/null | grep -E \"/${tail}$|^${tail}$\" | head -1) || found=\"\""
    )
    script.append(
        '  if [ -z "$found" ]; then found=$(find . -path ./.git -prune -o -type f '
        '-name "$(basename "$tail")" -print 2>/dev/null | head -1) || found=""; fi'
    )
    script.append('  [ -n "$found" ] && echo "$found"')
    script.append("done <<'TAILS'")
    script.extend(tails)
    script.append("TAILS")
    script.append("echo __rc=0")
    code, out = container.bash("\n".join(script))
    paths: list[str] = []
    for line in _strip_rc(out).splitlines():
        path = line.strip().lstrip("./")
        if path and path.endswith(".py") and path not in paths:
            paths.append(path)
    return paths[:MAX_FILES]


def read_files(container: Container, paths: Sequence[str]) -> dict[str, str]:
    """Read the localised files, newest text last, under a character cap."""
    bodies: dict[str, str] = {}
    budget = MAX_CONTEXT_CHARS
    for path in paths:
        if budget <= 0:
            break
        path = safe_repo_path(path)
        code, out = container.bash(f"cd /testbed && cat -- {shlex.quote(path)}")
        if code != 0:
            continue
        body = _strip_rc(out)
        if len(body) > budget:
            body = body[:budget] + "\n... [truncated]\n"
        budget -= len(body)
        bodies[path] = body
    return bodies


def context_block(bodies: Mapping[str, str]) -> str:
    if not bodies:
        return "(no file from the report could be located in the checkout)"
    return "\n\n".join(
        f"### {path}\n```python\n{body}\n```" for path, body in bodies.items()
    )


# --------------------------------------------------------------------------
# candidate generation
# --------------------------------------------------------------------------

CANDIDATE_SYSTEM = """You are fixing a bug in a real Python repository.

You will be given a bug report and the contents of the files the report points
at. Reply with a single unified diff that fixes the bug.

Rules:
- Output the diff inside one ```diff fenced block, and nothing else outside it.
- Every hunk must be preceded by its own `--- a/<path>` and `+++ b/<path>` lines.
- Paths must be relative to the repository root, with a/ and b/ prefixes.
- Change as little as possible. Do not reformat code you are not fixing.
- Do not add tests. The repository's own tests decide whether you are right.
- If you are unsure, make your best single attempt rather than asking.
"""

NUDGES = (
    "",
    "\n\nTake a different angle from an obvious first attempt: re-read the trace in "
    "the report and fix the actual cause, not the symptom.",
)

DIFF_BLOCK = re.compile(r"```(?:diff|patch)?\s*\n(.*?)```", re.DOTALL)


def extract_patch(text: str) -> str:
    match = DIFF_BLOCK.search(text or "")
    candidate = match.group(1) if match else (text or "")
    lines = candidate.splitlines()
    start = next(
        (i for i, line in enumerate(lines)
         if line.startswith("--- ") or line.startswith("diff --git")),
        None,
    )
    if start is None:
        return ""
    return "\n".join(lines[start:]).rstrip() + "\n"


def candidate_messages(problem: str, context: str, attempt: int) -> list[dict[str, Any]]:
    """Prompt for candidate ``attempt``.

    The invariant text comes first and the nudge last, so the prefix of the
    prompt is byte-identical across attempts and the provider's context cache
    can serve it after the first call.

    ``hints_text`` is deliberately absent: it is on the withheld list in
    ``state.WITHHELD_FIELDS``, so the prefix must not read it even though the
    dataset carries it.
    """
    body = f"# Bug report\n\n{problem.strip()}\n"
    body += f"\n# Repository files\n\n{context}\n"
    body += NUDGES[min(attempt, len(NUDGES) - 1)]
    return [
        {"role": "system", "content": CANDIDATE_SYSTEM},
        {"role": "user", "content": body},
    ]


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------


def syntax_check(container: Container, touched: Iterable[str]) -> tuple[str, str]:
    """``py_compile`` the touched files. Returns (status, detail)."""
    files = [f for f in touched if f.endswith(".py")]
    if not files:
        return "not_applicable", "no python file touched"
    quoted = " ".join(shlex.quote(safe_repo_path(f)) for f in files)
    code, out = container.bash(
        f"cd /testbed && python -m py_compile {quoted} 2>&1; echo \"__rc=$?\""
    )
    rc = _trailing_rc(out)
    if rc == 0:
        return "pass", f"compiled {len(files)} file(s)"
    return "fail", _strip_rc(out)[:300]


def public_test_files(
    container: Container,
    touched: Iterable[str],
    symbols: Sequence[str] = (),
) -> list[str]:
    """Test files discoverable from the checkout for the touched modules.

    Name matching alone is not enough: it finds ``test_<module>.py`` and nothing
    else, which returned ``not_applicable`` for every astroid and sqlfluff
    instance in the seven-instance run. Their tests are organised by feature
    (``tests/test_nodes.py``), not one file per module. So a second, content-based
    search looks for the module stem or a localised symbol *inside* test files.

    This is still a public signal: it reads only the checkout, never the
    evaluation metadata.
    """
    stems: list[str] = []
    for path in touched:
        if not path.endswith(".py"):
            continue
        stem = os.path.basename(path)[:-3]
        if stem and stem not in stems:
            stems.append(stem)

    needles = [n for n in list(stems) + list(symbols) if n and len(n) >= 3][:8]
    if not stems and not needles:
        return []

    script = ["cd /testbed"]
    if stems:
        script.append("for stem in " + " ".join(f"'{s}'" for s in stems) + "; do")
        script.append(
            "  find . -path ./.git -prune -o -type f "
            '\\( -name "test_${stem}.py" -o -name "${stem}_test.py" \\) -print '
            "2>/dev/null"
        )
        script.append("done")
    if needles:
        args = " ".join(f"-e {shlex.quote(n)}" for n in needles)
        script.append("if [ -d tests ] || [ -d test ]; then")
        script.append(
            f"  grep -rlF {args} --include='test_*.py' --include='*_test.py' "
            "tests test 2>/dev/null || true"
        )
        script.append("fi")
    script.append("echo __rc=0")

    code, out = container.bash("\n".join(script))
    found: list[str] = []
    for line in _strip_rc(out).splitlines():
        path = line.strip().lstrip("./")
        if path.endswith(".py") and path not in found:
            found.append(path)
    # Prefer a real test directory, then the shortest path.
    found.sort(key=lambda p: (0 if ("/test" in p or p.startswith("test")) else 1, len(p)))
    return found[:3]


def run_public_tests(
    container: Container, files: Sequence[str]
) -> tuple[str, str, str]:
    """Run the discovered test files. Missing pytest is not a failure.

    Returns ``(status, detail, raw_output)``. The raw output is returned because
    the failure has to be *classified* before it can inform routing: a pytest
    run that fails on an assertion tells us something about behaviour, while one
    that fails on import tells us nothing, and only the text can separate them.
    """
    if not files:
        return "not_applicable", "no repository test file next to the touched modules", ""
    quoted = " ".join(shlex.quote(safe_repo_path(f)) for f in files)
    code, out = container.bash(
        f"cd /testbed && timeout {PYTEST_TIMEOUT} python -m pytest {quoted} -q "
        "--no-header -p no:cacheprovider 2>&1; echo \"__rc=$?\"",
        timeout=PYTEST_TIMEOUT + 60,
    )
    rc = _trailing_rc(out)
    text = _strip_rc(out)
    if "No module named pytest" in text or "No module named 'pytest'" in text:
        return "not_run", "pytest is not installed in this image", text
    if rc == 0:
        return "pass", _summary_line(text), text
    if rc == 1:
        return "fail", _summary_line(text), text
    # Collection errors and timeouts say nothing about behaviour.
    return "not_run", f"pytest exit {rc}: {_summary_line(text)}", text


def _summary_line(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    for line in reversed(lines):
        if "passed" in line or "failed" in line or "error" in line:
            return line[:200]
    return (lines[-1][:200] if lines else "")


@dataclass(frozen=True)
class ValidationResult:
    """A validated candidate plus what the validation actually exercised.

    The extra fields exist because ``RepairState.behavioural_signal()`` reads
    ``ContextView.checks_run``: if the prefix runs tests but does not record that
    it did, the router believes nothing was ever checked and escalates every
    time, which makes arm D indistinguishable from arm C.
    """

    candidate: Candidate
    checks_run: int = 0
    test_files: tuple[str, ...] = ()
    syntax: str = "not_run"
    #: Classified failures. Without these the state machine cannot distinguish
    #: "a check ran and told us the patch is behaviourally wrong" from "nothing
    #: was learned", and the router's rule 7 then escalates unconditionally.
    failures: tuple[FailureRecord, ...] = ()
    raw_output: str = ""
    test_command: str = ""


def validate_candidate(
    container: Container, candidate: Candidate, symbols: Sequence[str] = ()
) -> ValidationResult:
    """Apply, compile, run public tests, then revert."""
    if not patch_scope_valid(candidate.diff):
        return ValidationResult(candidate=replace(candidate, applies_cleanly=False, scope_valid=False),
                                failures=(FailureRecord.from_output('scope_check', 1, stage='apply_patch',
                                          stdout='invalid patch or forbidden modification scope'),))
    container.revert()
    applies, detail = container.apply(candidate.diff)
    if not applies:
        return ValidationResult(
            candidate=Candidate.build(
                candidate.index, candidate.diff,
                applies_cleanly=False,
                validation="not_run",
                origin=candidate.origin,
            ),
            failures=(FailureRecord.from_output('git apply', 1, stage='apply_patch', stdout=detail),)
        )
    try:
        touched = files_touched(candidate.diff)
        syntax, syntax_detail = syntax_check(container, touched)
        if syntax == "fail":
            return ValidationResult(
                candidate=Candidate.build(
                    candidate.index, candidate.diff,
                    applies_cleanly=True, validation="fail", origin=candidate.origin, syntax='fail',
                ),
                syntax="fail",
                failures=(FailureRecord.from_output(
                    f"python -m py_compile {' '.join(touched)}", 1,
                    stage="syntax_check", stdout=syntax_detail, repo_root="/testbed",
                ),),
            )
        targets = public_test_files(container, touched, symbols)
        status, _detail, raw = run_public_tests(container, targets)
        records: tuple[FailureRecord, ...] = ()
        if status in ("fail", "not_run") and raw:
            records = (FailureRecord.from_output(
                f"python -m pytest {' '.join(targets)}", 1,
                stage='env' if status == 'not_run' and 'No module named' in raw and 'pytest' in raw else 'test',
                stdout=raw, repo_root="/testbed",
            ),)
        return ValidationResult(
            candidate=Candidate.build(
                candidate.index, candidate.diff,
                applies_cleanly=True, validation=status, origin=candidate.origin, syntax=syntax,
            ),
            checks_run=1 if status in ("pass", "fail") else 0,
            test_files=tuple(targets),
            syntax=syntax,
            failures=records,
            raw_output=raw,
            test_command=f"python -m pytest {' '.join(targets)}",
        )
    finally:
        container.revert()


# --------------------------------------------------------------------------
# the prefix run
# --------------------------------------------------------------------------


@dataclass
class PrefixResult:
    """What the prefix produced, plus what the router is allowed to look at."""

    state: RepairState
    base_commit: str
    context_files: tuple[str, ...]
    listing: tuple[str, ...]
    #: The exact file text the prefix worked from. The escalation branch is
    #: seeded with this so it does not start out knowing less than the fixed
    #: branch, which would handicap the very comparison being run.
    context_text: str = ""
    calls: int = 0
    cost_cny: float = 0.0
    tokens: int = 0
    trace: list[dict[str, Any]] = field(default_factory=list)

    def features(self) -> dict[str, Any]:
        """The router's entire input. Protocol B2 fixes this list."""
        applicable = self.state.patches.applicable()
        signal = self.state.behavioural_signal()
        return {
            "n_candidates": len(self.state.patches.candidates),
            "n_applicable": len(applicable),
            "n_public_pass": sum(
                1 for c in applicable if c.validation == "pass"
            ),
            "u_loc": self.state.u_loc,
            "u_dup": self.state.u_dup,
            "behavioural_signal": signal,
            # Derived so the analysis has a numeric feature to score rather than
            # a three-valued label; equals rule 7's condition.
            "lacks_behavioural_signal": 0 if signal == "behavioural" else 1,
            "localization_missing": self.state.localization.missing,
            "context_files": list(self.context_files),
            "remaining_token": (
                self.state.budget.remaining.token if self.state.budget else 0
            ),
        }


def run_prefix(
    instance: Mapping[str, Any],
    client: DeepSeekClient,
    *,
    config_version: str,
    config_hash: str,
    n_candidates: int = 2,
    container: Container | None = None,
) -> PrefixResult:
    """Run the shared prefix exactly once per instance.

    ``instance`` must be a generation view: the caller is responsible for
    projecting the row first, and ``TaskManifest.from_instance`` re-checks it.
    """
    iid = str(instance["instance_id"])
    manifest = TaskManifest.from_instance(
        instance, config_version, config_hash,
        image_id=image_for(iid),
    )
    state = RepairState(task=manifest)
    own_container = container is None
    box = container or Container(image_for(iid), f"cf-{_slug(iid)}")
    if own_container:
        box.start()
    calls = 0
    cost = 0.0
    tokens = 0
    trace: list[dict[str, Any]] = []
    listing, bodies, context = [], {}, ''
    checks_run, test_files = 0, []
    try:
        state = _replace(state, base_commit=box.head())
        listing = _index(box)
        problem = str(instance.get("problem_statement") or "")

        # pass 1: lexical (free)
        lexical = lexical_localize(problem)
        # pass 2: model
        result = client.chat(localize_messages(problem, listing))
        calls += 1
        cost += result.record.cost_cny
        tokens += result.record.prompt_tokens + result.record.output_tokens
        model_files, symbols = parse_localization(result.text)
        trace.append({
            "step": "localize", "calls": 1, "cost_cny": round(cost, 6),
            "files": sorted(model_files), "symbols": sorted(symbols),
            "finish_reason": result.record.finish_reason,
        })

        lexical_resolved = frozenset(resolve_paths(box, sorted(lexical)))
        model_resolved = frozenset(resolve_paths(box, sorted(model_files)))
        state.localization.add(LocalizationPass("lexical", lexical_resolved))
        state.localization.add(
            LocalizationPass("model", model_resolved, symbols)
        )

        # Model-localised files come first. Ordering matters because the read
        # budget is finite: with lexical tails first, the file the model
        # actually wanted to edit fell outside the cut, and it then wrote a diff
        # for a file whose contents it had never been shown. Those diffs cannot
        # apply, and the failure looks like a bad fix rather than a bad context.
        wanted = sorted(model_resolved)
        for tail in sorted(lexical_resolved):
            if tail not in wanted:
                wanted.append(tail)
        paths = resolve_paths(box, wanted)
        bodies = read_files(box, paths)
        state.context = ContextView(
            indexed_paths=frozenset(listing),
            read_files=frozenset(bodies),
        )
        context = context_block(bodies)

        history = PatchHistory()
        checks_run = 0
        test_files: list[str] = []
        for attempt in range(n_candidates):
            messages = candidate_messages(problem, context, attempt)
            reply: ChatResult = client.chat(messages)
            calls += 1
            cost += reply.record.cost_cny
            tokens += reply.record.prompt_tokens + reply.record.output_tokens
            raw = extract_patch(reply.text)
            hunk_fixes = 0
            if raw.strip():
                # A wrong @@ header is a formatting defect, not a wrong fix, so
                # correcting it here keeps it from being counted as a bad patch.
                raw, hunk_fixes = repair_hunk_headers(raw)
            candidate = Candidate.build(attempt, raw, origin="prefix") if raw.strip() \
                else Candidate.build(attempt, "", applies_cleanly=False,
                                     validation="not_run", origin="prefix")
            failure_classes: list[str] = []
            if candidate.diff.strip():
                validation = validate_candidate(box, candidate, tuple(symbols))
                candidate = validation.candidate
                checks_run += validation.checks_run
                for path in validation.test_files:
                    if path not in test_files:
                        test_files.append(path)
                for record in validation.failures:
                    # This is what connects the checks to the router: without a
                    # classified failure, behavioural_signal() cannot tell "the
                    # check failed on an assertion" from "nothing was checked".
                    state.failures.add(record)
                    failure_classes.append(record.error_class)
            history.add(candidate)
            state.patches = history
            state.context = ContextView(indexed_paths=frozenset(listing), read_files=frozenset(bodies),
                                        registered_test_commands=tuple(test_files), checks_run=checks_run)
            trace.append({
                "step": f"candidate_{attempt}", "calls": 1,
                "cost_cny": round(cost, 6),
                "diff_lines": candidate.diff_lines,
                "validation": candidate.validation,
                "applies_cleanly": candidate.applies_cleanly,
                "hunk_headers_repaired": hunk_fixes,
                "finish_reason": reply.record.finish_reason,
                "output_tokens": reply.record.output_tokens,
                "reasoning_tokens": reply.record.reasoning_tokens,
                "reply_head": (reply.text or "")[:200].replace("\n", " "),
                # A patch for a file the model was never shown cannot carry
                # correct context lines; recording it separates "bad fix" from
                # "bad context" when the run is read back later.
                "targets_outside_context": [
                    path for path in candidate.files_touched if path not in bodies
                ],
                "failure_classes": failure_classes,
                "raw_reply": reply.message,
                "raw_validation_output": validation.raw_output if candidate.diff.strip() else '',
            })

        state.patches = history
        # Record that checks actually ran, so behavioural_signal() reflects the
        # prefix's real evidence instead of reporting "none" unconditionally.
        state.context = ContextView(
            indexed_paths=frozenset(listing),
            read_files=frozenset(bodies),
            registered_test_commands=tuple(test_files),
            checks_run=checks_run,
        )
        return PrefixResult(
            state=state,
            base_commit=state.task.base_commit,
            context_files=tuple(bodies),
            listing=tuple(listing),
            context_text=context,
            calls=calls,
            cost_cny=round(cost, 6),
            tokens=tokens,
            trace=trace,
        )
    except ResourceLimit as exc:
        trace.append({'step': 'prefix_stop', 'reason': str(exc)})
        return PrefixResult(state, state.task.base_commit, tuple(bodies), tuple(listing),
                            context_text=context, calls=calls, cost_cny=cost, tokens=tokens, trace=trace)
    except Exception as exc:
        trace.append({'step': 'prefix_error', 'reason': f'{type(exc).__name__}: {exc}'})
        return PrefixResult(state, state.task.base_commit, tuple(bodies), tuple(listing),
                            context_text=context, calls=calls, cost_cny=cost, tokens=tokens, trace=trace)
    finally:
        if own_container:
            box.close()


def _replace(state: RepairState, *, base_commit: str) -> RepairState:
    """Return the state with the commit the container actually reports."""
    state.task = TaskManifest(
        instance_id=state.task.instance_id,
        repo=state.task.repo,
        base_commit=base_commit or state.task.base_commit,
        config_version=state.task.config_version,
        config_hash=state.task.config_hash,
        image_id=state.task.image_id,
        version=state.task.version,
        environment_setup_commit=state.task.environment_setup_commit,
        repo_root=state.task.repo_root,
    )
    return state


def _index(box: Container) -> list[str]:
    code, out = box.bash("cd /testbed && ls -a")
    if code != 0:
        return []
    entries = [
        line.strip() for line in _strip_rc(out).splitlines()
        if line.strip() and line.strip() not in (".", "..", ".git")
    ]
    return entries[:MAX_LISTING_LINES]


def _slug(instance_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "-", instance_id)[:40]
