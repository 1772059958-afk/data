"""Offline checks for the bounded interactive executor.

Only the parts that can be checked without a container or a model are covered
here: that the six tools and four states line up with the protocol, that the
budget defaults are sane, and that the browser-facing helpers behave. The
session loop itself needs a live container, so it is exercised by the smoke run
and not here.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))

from swe_repair.interact import (  # noqa: E402
    FORCE_FINAL_PROMPT,
    STATES,
    STAGNATION_PATIENCE,
    TOOL_STATE,
    InteractionBudget,
    _clip,
    _slug,
    force_final_patch,
    tool_specs,
)

PATTERN = "```diff\n--- a/x.py\n+++ b/x.py\n@@ -1,1 +1,1 @@\n-a\n+b\n```\n"


class _Record:
    cost_cny = 0.01
    prompt_tokens = 120
    output_tokens = 60


class _Reply:
    def __init__(self, text: str) -> None:
        self.text = text
        self.record = _Record()


class _FakeClient:
    """Stands in for the model client: records how it was called."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.kwargs: dict = {}
        self.messages: list = []

    def chat(self, messages, **kwargs):
        self.messages = list(messages)
        self.kwargs = kwargs
        return _Reply(self.text)

EXPECTED_TOOLS = {
    "search_symbol",
    "read_region",
    "find_references",
    "apply_patch",
    "run_test",
    "finish",
}


def test_exactly_six_tools_and_four_states():
    names = {spec["function"]["name"] for spec in tool_specs()}
    assert names == EXPECTED_TOOLS
    assert set(TOOL_STATE) == EXPECTED_TOOLS
    assert STATES == ("analyse", "edit", "validate", "finish")


def test_every_tool_maps_into_a_declared_state():
    assert set(TOOL_STATE.values()) <= set(STATES)


def test_tool_state_mapping_matches_the_protocol():
    assert TOOL_STATE["search_symbol"] == "analyse"
    assert TOOL_STATE["read_region"] == "analyse"
    assert TOOL_STATE["find_references"] == "analyse"
    assert TOOL_STATE["apply_patch"] == "edit"
    assert TOOL_STATE["run_test"] == "validate"
    assert TOOL_STATE["finish"] == "finish"


def test_each_tool_declares_an_object_schema():
    for spec in tool_specs():
        assert spec["type"] == "function"
        function = spec["function"]
        assert function["description"]
        assert function["parameters"]["type"] == "object"


def test_budget_defaults_are_all_positive():
    budget = InteractionBudget()
    assert budget.model_calls > 0
    assert budget.tool_calls > 0
    assert budget.wallclock_seconds > 0


def test_stagnation_patience_matches_the_proposal():
    assert STAGNATION_PATIENCE == 3


def test_clip_keeps_short_text_and_marks_truncation():
    assert _clip("abc", 10) == "abc"
    clipped = _clip("x" * 50, 10)
    assert clipped.startswith("x" * 10)
    assert "cut" in clipped


def test_slug_is_deterministic_and_safe():
    assert _slug("pylint-dev__astroid-1196") == "pylint-dev__astroid-1196"
    assert _slug("a/b c:d") == "a-b-c-d"
    assert len(_slug("x" * 100)) <= 36


def test_forced_final_call_returns_the_patch_and_uses_no_tools():
    client = _FakeClient(PATTERN)
    patch, record = force_final_patch(client, [{"role": "user", "content": "go"}])
    assert patch.startswith("--- a/x.py")
    assert record is not None
    # The whole point is that this call cannot explore any further.
    assert "tools" not in client.kwargs or not client.kwargs.get("tools")
    assert client.messages[-1]["content"] == FORCE_FINAL_PROMPT


def test_forced_final_call_returns_empty_when_the_model_stalls():
    client = _FakeClient("I could not find the bug.")
    patch, record = force_final_patch(client, [{"role": "user", "content": "go"}])
    assert patch == ""
    assert record is not None


def test_forced_final_call_survives_a_transport_error():
    class _Broken:
        def chat(self, messages, **kwargs):
            raise RuntimeError("network")

    patch, record = force_final_patch(_Broken(), [])
    assert patch == ""
    assert record is None
