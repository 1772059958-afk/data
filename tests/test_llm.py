"""Self-checks for the model client, price table and call accounting.

Everything here runs offline. The client takes an injected transport, so the
response handling, retry policy and cost arithmetic are all exercised without a
network call and without a credential.

Runs under pytest or as plain ``python tests/test_llm.py``.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):  # pragma: no cover
    pass

from swe_repair import pricing  # noqa: E402
from swe_repair.llm import (  # noqa: E402
    DEFAULT_MODEL,
    DeepSeekClient,
    Ledger,
    MissingApiKeyError,
    ModelConfig,
    ModelConfigError,
    load_api_key,
    parse_tool_arguments,
    read_dotenv,
    tool_message,
)
from swe_repair.spend import (  # noqa: E402
    SpendGuard,
    SpendLimitExceeded,
    SpendPolicy,
)

BEIJING = pricing.BEIJING


class FakeResponse:
    def __init__(self, status, payload, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    """Replays scripted responses and remembers what was sent."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.sent = []

    def post(self, url, headers=None, data=None, timeout=None):
        self.sent.append({"url": url, "headers": headers, "body": json.loads(data)})
        if not self.responses:
            raise AssertionError("no scripted response left")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def ok_payload(**usage):
    base = {
        "id": "req-1",
        "model": "deepseek-flash",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "hello"},
            }
        ],
        "usage": {
            "prompt_tokens": 1000,
            "completion_tokens": 200,
            "total_tokens": 1200,
            "prompt_cache_hit_tokens": 400,
            "prompt_cache_miss_tokens": 600,
        },
    }
    base["usage"].update(usage)
    return base


def client_with(responses, **cfg):
    config = ModelConfig(**cfg)
    session = FakeSession(responses)
    return DeepSeekClient(config, api_key="test-key", session=session, sleeper=lambda _s: None), session


def guarded_client(responses, policy, **cfg):
    config = ModelConfig(**cfg)
    session = FakeSession(responses)
    guard = SpendGuard(policy)
    client = DeepSeekClient(
        config, api_key="test-key", guard=guard, session=session, sleeper=lambda _s: None
    )
    return client, session, guard


# --------------------------------------------------------------- price table

def test_peak_windows_are_beijing_weekday_hours():
    monday_10 = dt.datetime(2026, 10, 12, 10, 0)   # Monday
    monday_13 = dt.datetime(2026, 10, 12, 13, 0)
    monday_15 = dt.datetime(2026, 10, 12, 15, 0)
    monday_19 = dt.datetime(2026, 10, 12, 19, 0)
    assert pricing.is_peak(monday_10) is True
    assert pricing.is_peak(monday_13) is False
    assert pricing.is_peak(monday_15) is True
    assert pricing.is_peak(monday_19) is False


def test_weekends_and_holidays_are_off_peak():
    saturday = dt.datetime(2026, 10, 10, 10, 0)
    assert pricing.is_peak(saturday) is False
    weekday = dt.datetime(2026, 10, 12, 10, 0)
    assert pricing.is_peak(weekday, holidays=frozenset({dt.date(2026, 10, 12)})) is False


def test_boundary_times_are_half_open():
    assert pricing.is_peak(dt.datetime(2026, 10, 12, 9, 0)) is True
    assert pricing.is_peak(dt.datetime(2026, 10, 12, 12, 0)) is False


def test_naive_datetimes_are_read_as_beijing():
    naive = dt.datetime(2026, 10, 12, 10, 0)
    aware = naive.replace(tzinfo=BEIJING)
    assert pricing.is_peak(naive) == pricing.is_peak(aware) is True


def test_cost_matches_the_published_rates():
    off = dt.datetime(2026, 10, 12, 20, 0)
    peak = dt.datetime(2026, 10, 12, 10, 0)
    # 1M cache hit + 1M miss + 1M output at off-peak = .02 + 1 + 4
    assert pricing.estimate_cost(
        "deepseek-flash", cache_hit_tokens=10**6, cache_miss_tokens=10**6,
        output_tokens=10**6, when=off,
    ) == 5.02
    # same mix at peak doubles every rate
    assert pricing.estimate_cost(
        "deepseek-flash", cache_hit_tokens=10**6, cache_miss_tokens=10**6,
        output_tokens=10**6, when=peak,
    ) == 10.04


def test_cached_prompt_tokens_are_cheaper_than_uncached():
    when = dt.datetime(2026, 10, 12, 20, 0)
    hit = pricing.estimate_cost("deepseek-flash", cache_hit_tokens=10**6, when=when)
    miss = pricing.estimate_cost("deepseek-flash", cache_miss_tokens=10**6, when=when)
    assert hit < miss
    assert hit == 0.02 and miss == 1.0


def test_missing_cache_detail_is_treated_as_uncached():
    assert pricing.split_prompt_tokens(500, None) == (0, 500)
    assert pricing.split_prompt_tokens(500, 200) == (200, 300)
    assert pricing.split_prompt_tokens(500, 9999) == (500, 0)


def test_unknown_model_is_rejected():
    try:
        pricing.estimate_cost("gpt-nope", output_tokens=1)
    except pricing.UnknownModelError:
        return
    raise AssertionError("expected UnknownModelError")


def test_negative_token_counts_are_rejected():
    try:
        pricing.estimate_cost("deepseek-flash", cache_miss_tokens=-1)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_pro_costs_more_than_flash():
    when = dt.datetime(2026, 10, 12, 20, 0)
    mix = {"cache_miss_tokens": 10**6, "output_tokens": 10**6}
    ranked = pricing.compare_models(mix, when=when)
    assert list(ranked) == ["deepseek-flash", "deepseek-v4-pro"]
    assert ranked["deepseek-v4-pro"] > ranked["deepseek-flash"]


# ------------------------------------------------------------- config guards

def test_thinking_defaults_on_with_high_effort():
    cfg = ModelConfig()
    body = cfg.request_body([{"role": "user", "content": "hi"}])
    assert body["thinking"] == {"type": "enabled"}
    assert body["model"] == DEFAULT_MODEL
    # effort high is the default, so it is left implicit
    assert "reasoning_effort" not in body


def test_effort_is_sent_when_it_differs_from_the_default():
    body = ModelConfig(effort="max").request_body([{"role": "user", "content": "hi"}])
    assert body["reasoning_effort"] == "max"


def test_bad_effort_is_rejected():
    try:
        ModelConfig(effort="medium")
    except ModelConfigError:
        return
    raise AssertionError("expected ModelConfigError; medium is not a real level")


def test_temperature_is_rejected_in_thinking_mode():
    try:
        ModelConfig(temperature=0.2)
    except ModelConfigError:
        return
    raise AssertionError("expected ModelConfigError")


def test_temperature_is_allowed_once_thinking_is_off():
    cfg = ModelConfig(thinking=False, temperature=0.2)
    body = cfg.request_body([{"role": "user", "content": "hi"}])
    assert body["thinking"] == {"type": "disabled"}
    assert body["temperature"] == 0.2


def test_top_p_outside_the_honoured_range_is_rejected():
    try:
        ModelConfig(top_p=0.5)
    except ModelConfigError:
        return
    raise AssertionError("expected ModelConfigError; below 0.95 has no effect")


def test_top_p_is_allowed_inside_the_honoured_range():
    body = ModelConfig(top_p=0.98).request_body([{"role": "user", "content": "hi"}])
    assert body["top_p"] == 0.98


def test_tools_are_passed_through_untouched():
    tools = [{"type": "function", "function": {"name": "read_region"}}]
    body = ModelConfig().request_body(
        [{"role": "user", "content": "hi"}], tools=tools, tool_choice="auto"
    )
    assert body["tools"] == tools
    assert body["tool_choice"] == "auto"


def test_no_tools_key_when_there_are_no_tools():
    body = ModelConfig().request_body([{"role": "user", "content": "hi"}])
    assert "tools" not in body and "tool_choice" not in body


# --------------------------------------------------------------- key loading

def test_key_comes_from_the_environment_first():
    assert load_api_key(env={"DEEPSEEK_API_KEY": "from-env"}) == "from-env"


def test_key_falls_back_to_the_dotenv_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, ".env")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("# comment\nDEEPSEEK_API_KEY=from-file\nOTHER=x\n")
        assert load_api_key(env={}, dotenv_path=path) == "from-file"


def test_dotenv_tolerates_quotes_and_blank_lines():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, ".env")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('\n\nDEEPSEEK_API_KEY="quoted-key"\n\n')
        assert read_dotenv(path)["DEEPSEEK_API_KEY"] == "quoted-key"


def test_missing_key_is_reported_clearly():
    try:
        load_api_key(env={}, dotenv_path=os.path.join(tempfile.gettempdir(), "nope.env"))
    except MissingApiKeyError as exc:
        assert "DEEPSEEK_API_KEY" in str(exc)
        return
    raise AssertionError("expected MissingApiKeyError")


def test_client_repr_never_leaks_the_key():
    client, _ = client_with([FakeResponse(200, ok_payload())])
    assert "test-key" not in repr(client)
    assert "test-key" not in str(client)
    assert "redacted" in repr(client)


# -------------------------------------------------------------- call handling

def test_successful_call_records_usage_and_cost():
    client, _ = client_with([FakeResponse(200, ok_payload())])
    result = client.chat([{"role": "user", "content": "hi"}])
    record = result.record
    assert record.prompt_tokens == 1000
    assert record.cache_hit_tokens == 400
    assert record.cache_miss_tokens == 600
    assert record.output_tokens == 200
    assert record.served_model == "deepseek-flash"
    assert record.attempts == 1
    assert record.cost_cny > 0
    assert result.text == "hello"


def test_usage_arithmetic_reaches_the_run_log_fields():
    client, _ = client_with([FakeResponse(200, ok_payload())])
    fields = client.chat([{"role": "user", "content": "hi"}]).record.runlog_fields()
    assert fields["input_tokens"] == 1000
    assert fields["output_tokens"] == 200
    assert fields["model_version"] == "deepseek-flash"
    assert set(fields) == {"model_version", "input_tokens", "output_tokens", "elapsed_seconds"}


def test_request_body_carries_the_pinned_settings():
    client, session = client_with([FakeResponse(200, ok_payload())], effort="max", max_tokens=1234)
    client.chat([{"role": "user", "content": "hi"}])
    body = session.sent[0]["body"]
    assert body["model"] == "deepseek-flash"
    assert body["max_tokens"] == 1234
    assert body["reasoning_effort"] == "max"
    assert session.sent[0]["headers"]["Authorization"].startswith("Bearer ")


def test_reasoning_content_is_echoed_back_only_when_tools_are_in_play():
    payload = ok_payload()
    payload["choices"][0]["message"]["reasoning_content"] = "thought"
    payload["choices"][0]["message"]["tool_calls"] = [
        {"id": "c1", "type": "function", "function": {"name": "read_region", "arguments": "{}"}}
    ]
    payload["choices"][0]["finish_reason"] = "tool_calls"
    client, _ = client_with([FakeResponse(200, payload)])
    result = client.chat([{"role": "user", "content": "hi"}])
    assert result.as_history_entry()["reasoning_content"] == "thought"

    plain = ok_payload()
    plain["choices"][0]["message"]["reasoning_content"] = "thought"
    client2, _ = client_with([FakeResponse(200, plain)])
    assert "reasoning_content" not in client2.chat([{"role": "user", "content": "hi"}]).as_history_entry()


def test_retryable_status_is_retried_then_succeeds():
    client, session = client_with(
        [FakeResponse(429, {"error": {"message": "rate limited"}}), FakeResponse(200, ok_payload())]
    )
    record = client.chat([{"role": "user", "content": "hi"}]).record
    assert record.attempts == 2
    assert len(session.sent) == 2


def test_transport_error_is_retried():
    client, _ = client_with([ConnectionError("boom"), FakeResponse(200, ok_payload())])
    assert client.chat([{"role": "user", "content": "hi"}]).record.attempts == 2


def test_non_retryable_status_fails_fast():
    client, session = client_with([FakeResponse(400, {"error": {"message": "bad request"}})])
    try:
        client.chat([{"role": "user", "content": "hi"}])
    except RuntimeError as exc:
        assert "400" in str(exc)
        assert len(session.sent) == 1
        return
    raise AssertionError("expected RuntimeError")


def test_retries_are_bounded():
    client, session = client_with([FakeResponse(503, {}) for _ in range(10)], max_retries=2)
    try:
        client.chat([{"role": "user", "content": "hi"}])
    except RuntimeError:
        assert len(session.sent) == 3  # first attempt plus two retries
        return
    raise AssertionError("expected RuntimeError")


def test_missing_usage_block_does_not_crash():
    payload = ok_payload()
    payload.pop("usage")
    client, _ = client_with([FakeResponse(200, payload)])
    record = client.chat([{"role": "user", "content": "hi"}]).record
    assert record.prompt_tokens == 0 and record.output_tokens == 0
    assert record.cost_cny == 0.0


def test_response_without_cached_count_is_priced_as_all_miss():
    payload = ok_payload()
    payload["usage"].pop("prompt_cache_hit_tokens")
    client, _ = client_with([FakeResponse(200, payload)])
    record = client.chat([{"role": "user", "content": "hi"}]).record
    assert record.cache_hit_tokens == 0
    assert record.cache_miss_tokens == 1000


# ------------------------------------------------------------- ledger & tools

def test_ledger_accumulates_across_calls():
    client, _ = client_with([FakeResponse(200, ok_payload()), FakeResponse(200, ok_payload())])
    ledger = Ledger()
    for _ in range(2):
        ledger.add(client.chat([{"role": "user", "content": "hi"}]).record)
    summary = ledger.summary()
    assert summary["model_calls"] == 2
    assert summary["input_tokens"] == 2000
    assert summary["output_tokens"] == 400
    assert summary["models"] == ["deepseek-flash"]


def test_tool_arguments_decode_from_json():
    call = {"function": {"name": "read_region", "arguments": '{"path": "a.py"}'}}
    assert parse_tool_arguments(call) == {"path": "a.py"}


def test_malformed_tool_arguments_are_flagged_not_raised():
    call = {"function": {"name": "read_region", "arguments": "{not json"}}
    assert "_unparsed" in parse_tool_arguments(call)


def test_tool_message_matches_the_call_id():
    message = tool_message({"id": "c9"}, "ok")
    assert message == {"role": "tool", "tool_call_id": "c9", "content": "ok"}


def test_ledger_cost_is_the_sum_of_the_records():
    client, _ = client_with([FakeResponse(200, ok_payload()), FakeResponse(200, ok_payload())])
    ledger = Ledger()
    for _ in range(2):
        ledger.add(client.chat([{"role": "user", "content": "hi"}]).record)
    assert abs(ledger.cost_cny - 2 * ledger.records[0].cost_cny) < 1e-9


# ---------------------------------------------------------------- spend ceiling

def test_guard_blocks_the_call_before_any_request_is_sent():
    client, session, guard = guarded_client(
        [FakeResponse(200, ok_payload())], SpendPolicy(ceiling_cny=0.01)
    )
    try:
        client.chat([{"role": "user", "content": "hi"}])
    except SpendLimitExceeded:
        assert session.sent == []          # nothing left the machine
        assert guard.calls == 0
        return
    raise AssertionError("expected SpendLimitExceeded")


def test_guard_books_the_call_after_it_succeeds():
    client, _, guard = guarded_client(
        [FakeResponse(200, ok_payload())], SpendPolicy(ceiling_cny=50.0)
    )
    client.chat([{"role": "user", "content": "hi"}])
    assert guard.calls == 1
    assert guard.spent_cny > 0
    assert guard.summary()["ceiling_cny"] == 50.0


def test_guard_stops_the_second_call_once_the_call_limit_is_reached():
    client, session, _ = guarded_client(
        [FakeResponse(200, ok_payload()), FakeResponse(200, ok_payload())],
        SpendPolicy(ceiling_cny=50.0, max_calls=1),
    )
    client.chat([{"role": "user", "content": "hi"}])
    try:
        client.chat([{"role": "user", "content": "hi"}])
    except SpendLimitExceeded:
        assert len(session.sent) == 1
        return
    raise AssertionError("expected SpendLimitExceeded on the second call")


def test_client_without_a_guard_still_works():
    # Tests pass no guard; scripts that reach the real service always attach one.
    client, _ = client_with([FakeResponse(200, ok_payload())])
    assert client.chat([{"role": "user", "content": "hi"}]).record.cost_cny > 0
    assert "no spend ceiling" in repr(client)


if __name__ == "__main__":
    failures = 0
    names = [n for n in sorted(globals()) if n.startswith("test_")]
    for name in names:
        fn = globals()[name]
        if not callable(fn):
            continue
        try:
            fn()
            print(f"PASS  {name}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL  {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(names)} checks, {failures} failed")
    raise SystemExit(1 if failures else 0)
