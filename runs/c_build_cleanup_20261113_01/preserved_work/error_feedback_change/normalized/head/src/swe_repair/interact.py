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
from .patchutil import repair_hunk_headers, safe_repo_path, patch_scope_valid
from .prefix import (
    Container,
    extract_patch,
    image_for,
    public_test_files,
    run_public_tests,
    validate_candidate,
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

STAGNATION_PATIENCE = 3

SYSTEM = """You are repairing a bug in a real Python repository. You are in a bounded
interactive session.

Repository root: /testbed. You have six tools and a fixed budget. Work like this:

1. analyse  - search_symbol / read_region / find_references to find the cause.
2. edit     - apply_patch with a unified diff, paths relative to /testbed with
              a/ and b/ prefixes.
3. validate - run_test to check the repository's own tests near what you edited.
4. finish   - call finish when the patch is your best answer.

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
                "description": "Read a line range of one file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "path relative to /testbed"},
                        "start": {"type": "integer", "description": "1-based first line"},
                        "end": {"type": "integer", "description": "1-based last line"},
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
                "description": "Apply a unified diff to the checkout.",
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
                            "description": "final unified diff; omit to keep what is applied",
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


def execute_tool(box: Container, name: str, args: Mapping[str, Any]) -> tuple[str, bool]:
    """Run one tool. Returns (observation, made_progress)."""
    if name in ("read_region", "run_test"):
        try:
            args = dict(args, path=safe_repo_path(str(args.get("path") or "")))
        except ValueError as exc:
            return str(exc), False
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
        is_test = path.rsplit("/", 1)[-1].startswith("test_") or path.endswith("_test.py")
        targets = [path] if is_test else public_test_files(box, [path])
        status, detail, raw = run_public_tests(box, targets)
        return f"{status}: {detail}\n{_clip(raw, 3500)}", status in ("pass", "fail")

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
    if runtime is not None:
        runtime.deadline = min(runtime.deadline or float('inf'), runtime.clock() + budget.wallclock_seconds)
    seen, stagnation = set(), 0

    def request(*, final=False):
        result.calls += 1  # Failed requests consume a call too.
        if final:
            reply = client.chat(messages + [{'role': 'user', 'content': FORCE_FINAL_PROMPT}])
        else:
            reply = client.chat(messages, tools=tool_specs(), tool_choice='auto')
        result.cost_cny += reply.record.cost_cny
        result.tokens += reply.record.prompt_tokens + reply.record.output_tokens
        result.finish_reason = reply.record.finish_reason
        if on_call:
            on_call(reply.record)
        messages.append(reply.as_history_entry())
        return reply

    def submit(diff):
        if not diff.strip():
            return 'empty candidate', False
        repaired, _ = repair_hunk_headers(diff)
        idx = max((c.index for c in state.patches.candidates), default=-1) + 1
        validated = validate_candidate(box, Candidate.build(idx, repaired, origin='interactive'),
                                       tuple(state.localization.symbols_union()))
        state.patches.add(validated.candidate)
        for failure in validated.failures:
            state.failures.add(failure)
        detail = validated.raw_output or '; '.join(f.message_head for f in validated.failures)
        best = state.patches.best_candidate()
        result.final_diff = best.diff if best else ''
        return f'applies={validated.candidate.applies_cleanly}, syntax={validated.syntax}, public={validated.candidate.validation}\n{detail}', bool(best and best.validation == 'pass')

    try:
        # Keep the last allowed call for a no-tools submission, never add one.
        while result.calls < max(0, budget.model_calls - 1):
            if clock() - started >= budget.wallclock_seconds:
                result.ended_by = 'wallclock'
                break
            if result.tool_calls >= budget.tool_calls:
                result.ended_by = 'tool_budget'
                break
            reply = request()
            if not reply.tool_calls:
                patch = extract_patch(reply.text)
                if patch:
                    observation, passed = submit(patch)
                    result.trace.append({'tool': 'patch_in_text', 'observation': observation})
                    result.ended_by = 'patch_in_text'
                    break
                stagnation += 1
                messages.append({'role': 'user', 'content': 'Use one tool, or submit a complete diff.'})
            else:
                for offset, call in enumerate(reply.tool_calls):
                    if offset or result.tool_calls >= budget.tool_calls:
                        messages.append(tool_message(call, 'Not executed: one tool per turn and strict tool limit.'))
                        continue
                    result.tool_calls += 1
                    name = (call.get('function') or {}).get('name', '')
                    args = parse_tool_arguments(call)
                    result.final_state = TOOL_STATE.get(name, result.final_state)
                    if name in ('apply_patch', 'finish'):
                        observation, passed = submit(str(args.get('diff') or ''))
                        progressed = bool(str(args.get('diff') or '').strip())
                        if name == 'finish' or passed:
                            result.ended_by = 'public_pass' if passed else 'finish_tool'
                            result.final_state = 'finish'
                        elif (state.patches.candidates[-1].applies_cleanly and state.patches.candidates[-1].scope_valid
                              and state.patches.candidates[-1].syntax != 'fail'):
                            box.apply(state.patches.candidates[-1].diff)
                    else:
                        observation, progressed = execute_tool(box, name, args)
                    key = json.dumps([name, args, observation], sort_keys=True)
                    repeated = key in seen
                    seen.add(key)
                    stagnation = 0 if progressed and not repeated else stagnation + 1
                    messages.append(tool_message(call, _clip(observation, 3500)))
                    result.trace.append({'turn': result.calls, 'tool': name, 'state': result.final_state,
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
                and result.calls < budget.model_calls and clock() - started < budget.wallclock_seconds):
            reply = request(final=True)
            patch = extract_patch(reply.text)
            if patch:
                observation, passed = submit(patch)
                result.finalized_by_forced_call = True
                result.trace.append({'tool': 'reserved_final', 'observation': observation})
    except Exception as exc:
        result.ended_by = f'{type(exc).__name__}: {exc}'
    finally:
        best = state.patches.best_candidate()
        result.final_diff = best.diff if best else ''
        result.transcript = messages
        try:
            box.revert()
        finally:
            if own:
                box.close()
    return result
