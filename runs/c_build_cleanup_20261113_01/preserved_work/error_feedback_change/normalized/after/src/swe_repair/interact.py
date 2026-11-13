"""Bounded interactive continuation: six tools, four states, one stop rule.

This is the branch the router may switch into. It is deliberately narrow,
because the claim under test is about *when* to escalate, not about how clever
the agent is. The bound comes from three places and none of them is optional:

* a hard model-call and tool-call ceiling, checked before each call;
* the four-state machine, so "validate" cannot silently become unbounded editing;
* stagnation patience -- three turns that teach the run nothing end it.

Every tool call is executed inside the instance's container and every result is
appended to the conversation, so the transcript is a complete record of what the
run did. Nothing here can read the evaluation tests: the tools only see the
checkout.
"""

from __future__ import annotations

import json
import re
import time
import shlex
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from .llm import DeepSeekClient, parse_tool_arguments, tool_message
from .feedback import error_evidence, failure_feedback, read_failure_log, LOG_REF, ToolFeedback
from .patchutil import repair_hunk_headers, safe_repo_path, patch_scope_valid, is_test_path
from .prefix import (
    Container,
    extract_patch,
    image_for,
    public_test_files,
    run_public_tests,
    validate_candidate,
    recover_environment,
    EnvironmentFailure,
)

STATES = ("analyse", "edit", "validate", "finish")

# Which state a tool call moves the run into.
TOOL_STATE = {
    "search_symbol": "analyse",
    "read_region": "analyse",
    "find_references": "analyse",
    "apply_patch": "edit",
    "run_test": "validate",
    "finish": "finish",
}

ALLOWED_TRANSITIONS = {
    'analyse': frozenset(('analyse', 'edit', 'validate', 'finish')),
    'edit': frozenset(('analyse', 'edit', 'validate', 'finish')),
    'validate': frozenset(('analyse', 'edit', 'validate', 'finish')),
    'finish': frozenset(),
}


@dataclass
class InteractionStateMachine:
    state: str = 'analyse'

    def transition(self, tool: str, *, has_candidate: bool, commit: bool = True) -> str | None:
        """Commit one legal transition, or return a refusal without changing state.

        A prefix candidate can justify analyse->validate after it is restored.
        Every validation needs a valid candidate; finish is terminal.
        """
        target = TOOL_STATE.get(tool)
        if target is None:
            return f'unknown tool {tool!r}'
        if self.state not in ALLOWED_TRANSITIONS or target not in ALLOWED_TRANSITIONS[self.state]:
            return f'invalid transition {self.state} -> {target}'
        if target == 'validate' and not has_candidate:
            return 'run_test requires an applicable, syntax-valid candidate first'
        if commit:
            self.state = target
        return None


STAGNATION_PATIENCE = 3

SYSTEM = """You are repairing a bug in a real Python repository. You are in a bounded
interactive session.

Repository root: /testbed. You have six tools and a fixed budget. Work like this:

Error feedback selects key exceptions, assertions and frames with original line
numbers. For full captured output, call read_region with its log:<sha256> path,
1-based start/end lines and optional offset within the first line. Follow the
returned cursor to read more. Only this branch's public generation logs exist.

1. analyse  - search_symbol / read_region / find_references to find the cause.
2. edit     - apply_patch supplies a COMPLETE diff against the clean base, with
              a/ and b/ paths. It automatically applies, compiles and runs the
              discovered public tests, then reports the result.
3. validate - run_test may run an additional public check on a valid candidate.
              It is unavailable until a valid candidate exists.
4. finish   - optionally supply a complete diff; omit it to keep the best valid
              candidate already recorded. No tool runs after finish.

Rules:
- One tool call per turn. Every apply_patch/finish diff is a COMPLETE candidate against the clean base, not an incremental edit. Never modify tests. Keep reading targeted: whole-file reads waste budget.
- A patch that does not apply costs you a turn and teaches nothing, so read the
  exact lines before editing.
- Do not add tests. The repository's own tests decide whether you are right.
- Budget discipline: you get a small, fixed number of tool calls. Spend at most
  two on analysis, then call apply_patch. A session that ends with no patch is
  the worst outcome -- a wrong patch costs exactly the same as no patch.
- If you are running out of budget, call finish with your best patch so far
  rather than starting a new line of investigation.
"""


def tool_specs() -> list[dict[str, Any]]:
    """The six tools in the wire format the client expects."""
    return [
        {
            "type": "function",
            "function": {
                "name": "search_symbol",
                "description": "Find where a symbol/identifier is defined or used.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "identifier to search"},
                        "max_hits": {"type": "integer", "description": "1-40, default 20"},
                    },
                    "required": ["name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_region",
                "description": "Read source lines or a captured public log:<sha256>; follow the returned cursor for more log text.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "path relative to /testbed, or an issued log:<sha256> reference"},
                        "start": {"type": "integer", "description": "1-based first line"},
                        "end": {"type": "integer", "description": "1-based last line"},
                        "offset": {"type": "integer", "description": "log only: character offset in the first line, default 0"},
                    },
                    "required": ["path", "start", "end"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "find_references",
                "description": "Find every place a name is referenced.",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "apply_patch",
                "description": "Submit a complete diff against the clean base; automatically apply, compile and validate it.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "diff": {"type": "string", "description": "unified diff text"},
                    },
                    "required": ["diff"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "run_test",
                "description": "Run one test file, or the tests next to a source file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "test or source path"},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "finish",
                "description": "End the session, optionally supplying the final patch.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "diff": {
                            "type": "string",
                            "description": "final complete unified diff; omit to retain the best recorded valid candidate",
                        },
                    },
                },
            },
        },
    ]


@dataclass
class InteractiveResult:
    final_diff: str
    calls: int = 0
    tool_calls: int = 0
    cost_cny: float = 0.0
    tokens: int = 0
    finish_reason: str = ""
    ended_by: str = ""          # finish_tool | stagnation | model_call_budget | tool_budget | error
    final_state: str = "analyse"
    finalized_by_forced_call: bool = False
    trace: list[dict[str, Any]] = field(default_factory=list)
    transcript: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class InteractionBudget:
    """Ceiling for one interactive session. Identical across arms that use it."""

    model_calls: int = 10
    tool_calls: int = 14
    wallclock_seconds: float = 420.0
    stagnation_patience: int = STAGNATION_PATIENCE


def _clip(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit] + f"\n... [{len(text)-limit} chars cut]"


def _run_shell(box: Container, command: str, timeout: int = 180) -> str:
    code, out = box.bash(command, timeout=timeout)
    return _clip(out, 4000)


def validate_tool_arguments(name: str, args: Any) -> tuple[dict[str, Any] | None, str]:
    """Validate the declared tool schema before coercion or shell execution."""
    specs = {tool['function']['name']: tool['function']['parameters'] for tool in tool_specs()}
    if name not in specs:
        return None, f'unknown tool {name!r}'
    if not isinstance(args, Mapping):
        return None, f'Invalid arguments for {name}: expected an object'
    spec = specs[name]
    for key in spec.get('required', ()):
        if key not in args:
            return None, f'Invalid arguments for {name}: missing {key}'
    checked = dict(args)
    for key, value in checked.items():
        prop = spec['properties'].get(key)
        if prop is None:
            return None, f'Invalid arguments for {name}: unknown field {key}'
        if prop['type'] == 'string' and not isinstance(value, str):
            return None, f'Invalid arguments for {name}: {key} must be a string'
        if prop['type'] == 'integer' and (not isinstance(value, int) or isinstance(value, bool)):
            return None, f'Invalid arguments for {name}: {key} must be an integer'
    if name in ('search_symbol', 'find_references') and not checked['name'].strip():
        return None, f'Invalid arguments for {name}: name must be non-empty'
    if name == 'search_symbol' and not 1 <= checked.get('max_hits', 20) <= 40:
        return None, 'Invalid arguments for search_symbol: max_hits must be within 1-40'
    if name == 'read_region' and (checked['start'] < 1 or checked['end'] < 1):
        return None, 'Invalid arguments for read_region: line numbers must be positive'
    if name == 'read_region' and 'offset' in checked:
        if checked['offset'] < 0 or not checked['path'].startswith('log:'):
            return None, 'Invalid arguments for read_region: offset requires a log reference and must be nonnegative'
    if name == 'read_region' and checked['path'].startswith('log:'):
        if not LOG_REF.fullmatch(checked['path']) or checked['end'] < checked['start']:
            return None, 'Invalid arguments for read_region: invalid log reference or range'
        return checked, ''
    if name in ('read_region', 'run_test'):
        try:
            checked['path'] = safe_repo_path(checked['path'].strip())
            if checked['path'] == '.':
                raise ValueError('a file path is required')
        except ValueError as exc:
            return None, f'Invalid arguments for {name}: {exc}'
    if name == 'apply_patch' and not checked['diff'].strip():
        return None, 'Invalid arguments for apply_patch: diff must be non-empty'
    return checked, ''


def execute_tool(box: Container, name: str, args: Mapping[str, Any]) -> tuple[str, bool] | ToolFeedback:
    """Run one tool. Returns (observation, made_progress)."""
    args, error = validate_tool_arguments(name, args)
    if error:
        return error, False
    if name == 'read_region' and args['path'].startswith('log:'):
        return 'Captured log access requires this branch session state.', False
    if name == "search_symbol":
        needle = str(args.get("name") or "").strip()
        if not needle:
            return "search_symbol needs a non-empty name", False
        hits = int(args.get("max_hits") or 20)
        out = _run_shell(
            box,
            f"cd /testbed && grep -rn --include='*.py' -F {shlex.quote(needle)} . 2>/dev/null "
            f"| head -{max(1, min(hits, 40))}",
        )
        return out or f"no occurrence of {needle!r}", bool(out)

    if name == "read_region":
        path = str(args.get("path") or "").strip().lstrip("./")
        start = int(args.get("start") or 1)
        end = int(args.get("end") or start + 60)
        if end < start:
            start, end = end, start
        if end - start > 400:
            end = start + 400
        out = _run_shell(
            box, f"cd /testbed && test \"$(realpath -- {shlex.quote(path)})\" != /testbed && case $(realpath -- {shlex.quote(path)}) in /testbed/*) sed -n '{max(1,start)},{max(1,end)}p' -- {shlex.quote(path)};; *) exit 1;; esac"
        )
        return f"{path}:{start}-{end}\n{out}" if out else f"{path}: no such range", bool(out)

    if name == "find_references":
        needle = str(args.get("name") or "").strip()
        out = _run_shell(
            box,
            f"cd /testbed && grep -rn --include='*.py' -w -F {shlex.quote(needle)} . 2>/dev/null | head -30",
        )
        return out or f"no reference to {needle!r}", bool(out)

    if name == "apply_patch":
        diff = str(args.get("diff") or "")
        if not diff.strip():
            return "apply_patch needs a diff", False
        # Fix a wrong @@ header before trying: it is a formatting slip, and
        # letting it read as "the patch is wrong" would blame the wrong stage.
        # Written back into args so the caller records what was really applied.
        repaired, fixes = repair_hunk_headers(diff)
        if fixes:
            args["diff"] = repaired
            diff = repaired
        if not patch_scope_valid(diff):
            return "forbidden patch scope", False
        box.revert()
        ok, detail = box.apply(diff)
        if ok:
            note = f"patch applied ({fixes} @@ header(s) had wrong counts)" if fixes else "patch applied"
            return note, True
        return f"patch did not apply:\n{_clip(detail, 1500)}", False

    if name == "run_test":
        path = str(args.get("path") or "").strip().lstrip("./")
        if not path:
            return "run_test needs a path", False
        targets = [path] if is_test_path(path) else public_test_files(box, [path])
        tested = run_public_tests(box, targets)
        status, detail, raw = tested
        if status in ('fail', 'not_run'):
            from .state import FailureRecord
            record = FailureRecord.from_output(getattr(tested, 'command', 'public validation'),
                getattr(tested, 'exit_code', None), stage='test', stdout=raw or detail, repo_root='/testbed')
            return ToolFeedback(f'{status}:\n{failure_feedback(record)}', status == 'fail', record)
        return f"{status}: {detail}\n{error_evidence(raw)}", status in ("pass", "fail")

    return f"unknown tool {name!r}", False


def _slug(instance_id: str) -> str:
    """Deterministic container name.

    ``hash()`` is salted per process, so the old version produced a different
    container name on every run and could not be reasoned about afterwards.
    """
    return re.sub(r"[^a-zA-Z0-9_.-]", "-", instance_id)[:36]


FORCE_FINAL_PROMPT = (
    "Your budget is exhausted. Reply with ONE ```diff fenced block containing "
    "your single best patch for the bug, and nothing else: no tools, no "
    "explanation, no commentary. Paths relative to /testbed with a/ and b/ "
    "prefixes. If you have not edited anything yet, write the smallest diff that "
    "changes the behaviour the report describes."
)


def force_final_patch(client: Any, messages: Sequence[Mapping[str, Any]]) -> tuple[str, Any]:
    """One last no-tools call that must cash out whatever the session learned.

    In the seven-instance run six of seven interactive sessions ended with an
    empty patch, which turned escalation into a net loss: it replaced a working
    fixed patch with nothing. A session that explored well but never wrote
    anything is indistinguishable from one that learned nothing, so exactly one
    call is reserved to convert its findings into a diff.

    Returns ``(patch, record)``; ``record`` is ``None`` only if the call failed.
    """
    try:
        reply = client.chat(
            list(messages) + [{"role": "user", "content": FORCE_FINAL_PROMPT}]
        )
    except Exception:
        return "", None
    patch = extract_patch(reply.text)
    if patch.strip():
        patch, _ = repair_hunk_headers(patch)
    return patch, reply.record


def run_interactive(
    problem: str, *, client: DeepSeekClient, budget: InteractionBudget | None = None,
    container: Container | None = None, instance_id: str = "interactive",
    seed_messages: Sequence[Mapping[str, Any]] | None = None,
    on_call: Callable[[Any], None] | None = None, state=None, clock=time.monotonic,
) -> InteractiveResult:
    """Complete candidates, common selection, one tool/turn, final call INSIDE limit."""
    from .state import RepairState, TaskManifest, Candidate
    from .execution import ResourceLimit
    budget = budget or InteractionBudget()
    own = container is None
    box = container or Container(image_for(instance_id), f"int-{_slug(instance_id)}")
    if own:
        box.start()
    state = state or RepairState(TaskManifest(instance_id, 'unknown', 'unknown', 'interactive', ''))
    messages = list(seed_messages or [{"role": "system", "content": SYSTEM},
                                     {"role": "user", "content": problem}])
    messages.append({"role": "user", "content":
                     f"Limits including final submission: {budget.model_calls} model calls, {budget.tool_calls} tools. "
                     "Supply complete patches against the clean base. Prior valid candidates are retained."})
    result = InteractiveResult(final_diff='')
    started = clock()
    runtime = getattr(client, 'runtime', None)
    call_start = runtime.state.consumed.model_call if runtime is not None else 0
    token_start = runtime.state.consumed.token if runtime is not None else 0
    record_start = len(runtime.records) if runtime is not None else 0
    old_call_limit = runtime.model_call_limit if runtime is not None else None
    old_deadline = runtime.deadline if runtime is not None else None
    if runtime is not None:
        runtime.deadline = min(runtime.deadline or float('inf'), runtime.clock() + budget.wallclock_seconds)
    seen, stagnation = set(), 0
    machine = InteractionStateMachine()
    active_candidate = None

    def calls_used():
        return runtime.state.consumed.model_call - call_start if runtime is not None else result.calls

    def phase(tool):
        error = machine.transition(tool, has_candidate=state.patches.best_candidate() is not None)
        if error:
            raise AssertionError(error)  # all model-controlled requests are preflighted below
        result.final_state = machine.state

    def request(*, final=False):
        if runtime is not None:
            allowance = call_start + max(0, budget.model_calls - (0 if final else 1))
            runtime.model_call_limit = allowance if old_call_limit is None else min(old_call_limit, allowance)
        else:
            result.calls += 1  # Test doubles have no attempt hook; count their calls.
        try:
            if final:
                reply = client.chat(messages + [{'role': 'user', 'content': FORCE_FINAL_PROMPT}])
            else:
                reply = client.chat(messages, tools=tool_specs(), tool_choice='auto')
        finally:
            if runtime is not None:
                result.calls = calls_used()
        result.cost_cny += reply.record.cost_cny
        result.tokens += reply.record.prompt_tokens + reply.record.output_tokens
        result.finish_reason = reply.record.finish_reason
        if on_call:
            on_call(reply.record)
        messages.append(reply.as_history_entry())
        return reply

    def submit(diff):
        nonlocal active_candidate
        if not diff.strip():
            return 'empty candidate', False, None
        phase('apply_patch')
        active_candidate = None  # validation starts from, and returns to, the clean base
        repaired, _ = repair_hunk_headers(diff)
        idx = max((c.index for c in state.patches.candidates), default=-1) + 1
        validated = validate_candidate(box, Candidate.build(idx, repaired, origin='interactive'),
                                       tuple(state.localization.symbols_union()))
        state.patches.add(validated.candidate)
        for failure in validated.failures:
            state.failures.add(failure)
        recovered = state.failures.needs_recovery_attempt()
        if recovered and not recover_environment(box, state):
            raise EnvironmentFailure('public validation remains unrunnable after its deterministic retry')
        candidate = next(c for c in state.patches.candidates if c.index == idx)
        detail = (failure_feedback(validated.failures[-1]) if validated.failures
                  else error_evidence(validated.raw_output))
        if recovered:
            detail += '\nDeterministic public-validation recovery completed.'
        best = state.patches.best_candidate()
        result.final_diff = best.diff if best else ''
        if candidate in state.patches.applicable():
            phase('run_test')  # apply_patch performs this validation automatically
        return (f'applies={candidate.applies_cleanly}, syntax={candidate.syntax}, public={candidate.validation}\n{detail}',
                bool(best and best.validation == 'pass'), candidate)

    try:
        # Keep the last allowed call for a no-tools submission, never add one.
        while calls_used() < max(0, budget.model_calls - 1):
            if clock() - started >= budget.wallclock_seconds:
                result.ended_by = 'wallclock'
                break
            if result.tool_calls >= budget.tool_calls:
                result.ended_by = 'tool_budget'
                break
            try:
                reply = request()
            except ResourceLimit as exc:
                if runtime is not None and max(0, budget.model_calls - 1) <= calls_used() < budget.model_calls:
                    result.ended_by = 'model_call_budget'
                    result.trace.append({'event': 'ordinary_request_stopped', 'detail': str(exc), 'calls': calls_used()})
                    break
                raise
            if not reply.tool_calls:
                patch = extract_patch(reply.text)
                if patch:
                    observation, passed, candidate = submit(patch)
                    phase('finish')
                    result.trace.append({'tool': 'patch_in_text', 'observation': observation})
                    result.ended_by = 'patch_in_text'
                    break
                stagnation += 1
                messages.append({'role': 'user', 'content': 'Use one tool, or submit a complete diff.'})
            else:
                for offset, call in enumerate(reply.tool_calls):
                    call = call if isinstance(call, Mapping) else {}
                    if result.ended_by or machine.state == 'finish':
                        messages.append(tool_message(call, 'Not executed: session already finished.'))
                        continue
                    if offset or result.tool_calls >= budget.tool_calls:
                        messages.append(tool_message(call, 'Not executed: one tool per turn and strict tool limit.'))
                        continue
                    result.tool_calls += 1
                    function = call.get('function')
                    name = function.get('name', '') if isinstance(function, Mapping) else ''
                    name = name if isinstance(name, str) else ''
                    args = parse_tool_arguments(call) if isinstance(function, Mapping) else {}
                    args, refusal = validate_tool_arguments(name, args)
                    before_state = machine.state
                    refusal = refusal or machine.transition(name, has_candidate=state.patches.best_candidate() is not None, commit=False)
                    if refusal:
                        observation, progressed = refusal, False
                    elif name in ('apply_patch', 'finish'):
                        diff = args.get('diff', '')
                        if name == 'finish' and not diff.strip():
                            best = state.patches.best_candidate()
                            observation = f'keeping candidate#{best.index}' if best else 'finished with no valid candidate'
                            passed, progressed, candidate = bool(best and best.validation == 'pass'), False, None
                        else:
                            observation, passed, candidate = submit(diff)
                            progressed = bool(candidate and candidate.diff.strip())
                        if name == 'finish' or passed:
                            result.ended_by = 'public_pass' if passed else 'finish_tool'
                            phase('finish')
                        elif candidate in state.patches.applicable():
                            ok, detail = box.apply(candidate.diff)
                            if ok:
                                active_candidate = candidate
                            else:
                                observation += '\nCould not restore candidate for further inspection: ' + _clip(detail, 500)
                                progressed = False
                    elif name == 'run_test':
                        candidate = active_candidate or state.patches.best_candidate()
                        if active_candidate is None:
                            box.revert()
                            ok, detail = box.apply(candidate.diff)
                            if ok:
                                active_candidate = candidate
                        else:
                            ok, detail = True, ''
                        if ok:
                            phase(name)
                            checked = execute_tool(box, name, args)
                            observation, progressed = checked
                            if isinstance(checked, ToolFeedback):
                                from dataclasses import replace
                                state.failures.tool_records.append(replace(checked.record, candidate_index=candidate.index))
                            observation = f'candidate#{candidate.index}\n' + observation
                        else:
                            observation, progressed = 'Could not restore candidate: ' + _clip(detail, 500), False
                    else:
                        phase(name)
                        if name == 'read_region' and args['path'].startswith('log:'):
                            observation, progressed = read_failure_log(
                                state.failures.records + state.failures.tool_records,
                                args['path'], args['start'], args['end'], args.get('offset', 0))
                        else:
                            observation, progressed = execute_tool(box, name, args)
                    key = json.dumps([name, args, observation], sort_keys=True)
                    repeated = key in seen
                    seen.add(key)
                    stagnation = 0 if progressed and not repeated else stagnation + 1
                    messages.append(tool_message(call, _clip(observation, 3500)))
                    result.trace.append({'turn': result.calls, 'tool': name, 'state_before': before_state, 'state': result.final_state,
                                         'progressed': progressed, 'repeated': repeated,
                                         'observation': _clip(observation, 3500)})
                if result.ended_by:
                    break
            if budget.stagnation_patience > 0 and stagnation >= budget.stagnation_patience:
                result.ended_by = 'stagnation'
                break
        if not result.ended_by:
            result.ended_by = 'model_call_budget'
        if (not state.patches.has_public_pass() and result.ended_by not in ('finish_tool', 'patch_in_text', 'wallclock')
                and calls_used() < budget.model_calls and clock() - started < budget.wallclock_seconds):
            reply = request(final=True)
            patch = extract_patch(reply.text)
            if patch:
                observation, passed, candidate = submit(patch)
                result.finalized_by_forced_call = True
                result.trace.append({'tool': 'reserved_final', 'observation': observation})
            phase('finish')
    except Exception as exc:
        result.ended_by = f'{type(exc).__name__}: {exc}'
    finally:
        if runtime is not None:
            result.calls = calls_used()
            result.tokens = runtime.state.consumed.token - token_start
            result.cost_cny = sum(float(r['cost_cny']) for r in runtime.records[record_start:])
            runtime.model_call_limit = old_call_limit
            runtime.deadline = old_deadline
        best = state.patches.best_candidate()
        result.final_diff = best.diff if best else ''
        result.transcript = messages
        try:
            box.revert()
        finally:
            if own:
                box.close()
    return result
