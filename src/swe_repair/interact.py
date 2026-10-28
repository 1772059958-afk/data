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
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from .llm import DeepSeekClient, parse_tool_arguments, tool_message
from .patchutil import repair_hunk_headers
from .prefix import (
    Container,
    extract_patch,
    image_for,
    public_test_files,
    run_public_tests,
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
- One tool call per turn. Keep reading targeted: whole-file reads waste budget.
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


@dataclass
class InteractionBudget:
    """Ceiling for one interactive session. Identical across arms that use it."""

    model_calls: int = 10
    tool_calls: int = 14
    wallclock_seconds: float = 420.0


def _clip(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit] + f"\n... [{len(text)-limit} chars cut]"


def _run_shell(box: Container, command: str, timeout: int = 180) -> str:
    code, out = box.bash(command, timeout=timeout)
    return _clip(out, 4000)


def execute_tool(box: Container, name: str, args: Mapping[str, Any]) -> tuple[str, bool]:
    """Run one tool. Returns (observation, made_progress)."""
    if name == "search_symbol":
        needle = str(args.get("name") or "").strip()
        if not needle:
            return "search_symbol needs a non-empty name", False
        hits = int(args.get("max_hits") or 20)
        out = _run_shell(
            box,
            f"cd /testbed && grep -rn --include='*.py' -F '{needle}' . 2>/dev/null "
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
            box, f"cd /testbed && sed -n '{start},{end}p' -- '{path}'"
        )
        return f"{path}:{start}-{end}\n{out}" if out else f"{path}: no such range", bool(out)

    if name == "find_references":
        needle = str(args.get("name") or "").strip()
        out = _run_shell(
            box,
            f"cd /testbed && grep -rn --include='*.py' -w -F '{needle}' . 2>/dev/null | head -30",
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
        targets = [path] if path.endswith(".py") else public_test_files(box, [path])
        status, detail, _raw = run_public_tests(box, targets)
        return f"{status}: {detail}", status in ("pass", "fail")

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
    problem: str,
    *,
    client: DeepSeekClient,
    budget: InteractionBudget | None = None,
    container: Container | None = None,
    instance_id: str = "interactive",
    seed_messages: Sequence[Mapping[str, Any]] | None = None,
    on_call: Callable[[Any], None] | None = None,
) -> InteractiveResult:
    """Drive one bounded interactive session.

    ``seed_messages`` lets the escalation branch start from the prefix's
    analysis instead of from nothing; the B arm passes none.
    """
    budget = budget or InteractionBudget()
    own = container is None
    box = container or Container(image_for(instance_id), f"cf-int-{_slug(instance_id)}")
    if own:
        box.start()

    messages: list[dict[str, Any]] = list(seed_messages or [])
    if not messages:
        listing = _run_shell(box, "cd /testbed && ls", timeout=60)
        messages = [
            {"role": "system", "content": SYSTEM},
            {
                "role": "user",
                "content": (
                    f"# Bug report\n\n{problem.strip()}\n\n"
                    f"# Top-level entries\n\n{listing}\n\nBegin with an analysis step."
                ),
            },
        ]

    # State the concrete limits in the conversation. A prompt that says "bounded"
    # without numbers gets spent on exploration, which is exactly what the first
    # two smoke runs did.
    messages.append({
        "role": "user",
        "content": (
            f"Budget for this session: {budget.model_calls} model calls and "
            f"{budget.tool_calls} tool calls. Spend at most 2 tool calls on "
            "analysis, then apply_patch, then finish."
        ),
    })

    result = InteractiveResult(final_diff="")
    applied_diff = ""
    seen: dict[str, int] = {}
    stagnation = 0
    started = time.time()
    tools = tool_specs()

    try:
        while True:
            if result.calls >= budget.model_calls:
                result.ended_by = "model_call_budget"
                break
            if result.tool_calls >= budget.tool_calls:
                result.ended_by = "tool_budget"
                break
            if time.time() - started > budget.wallclock_seconds:
                result.ended_by = "wallclock"
                break

            try:
                # The tools must be on every request: without them the model has
                # no way to act and the session degrades into plain chat.
                reply = client.chat(messages, tools=tools, tool_choice="auto")
            except Exception as exc:
                result.ended_by = f"error: {type(exc).__name__}: {exc}"
                break
            result.calls += 1
            result.cost_cny = round(result.cost_cny + reply.record.cost_cny, 6)
            result.tokens += reply.record.prompt_tokens + reply.record.output_tokens
            result.finish_reason = reply.record.finish_reason
            if on_call is not None:
                on_call(reply.record)

            calls = reply.tool_calls
            if not calls:
                # A reply with no tool call but a usable diff is still a finish.
                stray = extract_patch(reply.text)
                if stray.strip():
                    repaired, _ = repair_hunk_headers(stray)
                    result.final_diff = repaired
                    result.ended_by = "patch_in_text"
                    break
                stagnation += 1
                messages.append(reply.as_history_entry())
                messages.append({
                    "role": "user",
                    "content": "Use a tool. If you are done, call finish.",
                })
                if stagnation >= STAGNATION_PATIENCE:
                    result.ended_by = "stagnation"
                    break
                continue

            messages.append(reply.as_history_entry())
            finished = False
            for call in calls:
                name = (call.get("function") or {}).get("name", "")
                args = parse_tool_arguments(call)
                result.tool_calls += 1
                result.final_state = TOOL_STATE.get(name, result.final_state)

                if name == "finish":
                    given = str(args.get("diff") or "")
                    if given.strip():
                        given, _ = repair_hunk_headers(given)
                    result.final_diff = given or applied_diff
                    result.ended_by = "finish_tool"
                    result.final_state = "finish"
                    messages.append(tool_message(call, "session closed"))
                    finished = True
                    break

                observation, progressed = execute_tool(box, name, args)
                if name == "apply_patch" and progressed:
                    applied_diff = str(args.get("diff") or "")

                key = f"{name}:{json.dumps(args, sort_keys=True, ensure_ascii=False)[:400]}"
                repeated = seen.get(key, 0) > 0
                seen[key] = seen.get(key, 0) + 1
                stagnation = 0 if (progressed and not repeated) else stagnation + 1

                result.trace.append({
                    "turn": result.calls,
                    "tool": name,
                    "state": result.final_state,
                    "progressed": progressed,
                    "repeated": repeated,
                    "observation_chars": len(observation),
                })
                messages.append(tool_message(call, _clip(observation, 2400)))

            if finished:
                break
            if stagnation >= STAGNATION_PATIENCE:
                result.ended_by = "stagnation"
                break

        if not result.final_diff and applied_diff:
            result.final_diff = applied_diff
        # One reserved call: if the session is about to return nothing, make it
        # hand over what it knows. This is the difference between "escalation
        # lost the instance" and "escalation produced a weaker patch".
        if not result.final_diff.strip():
            forced, record = force_final_patch(client, messages)
            if record is not None:
                result.calls += 1
                result.cost_cny = round(result.cost_cny + float(record.cost_cny), 6)
                result.tokens += int(record.prompt_tokens) + int(record.output_tokens)
            result.finalized_by_forced_call = bool(forced.strip())
            result.trace.append({
                "turn": result.calls,
                "tool": "forced_final",
                "state": "finish" if forced.strip() else result.final_state,
                "progressed": bool(forced.strip()),
                "repeated": False,
                "observation_chars": len(forced),
            })
            if forced.strip():
                result.final_diff = forced
                result.ended_by = f"{result.ended_by}+forced_final"
        return result
    finally:
        box.revert()
        if own:
            box.close()
