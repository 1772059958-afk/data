"""Model client with explicit token and cost accounting.

The generation side needs three things from a model call: the answer, an exact
record of what it cost, and a guarantee that the model version cannot drift
mid-experiment. This module provides all three against DeepSeek's
OpenAI-compatible endpoint.

Two settings are treated as experiment parameters rather than conveniences,
because leaving them implicit would let two arms differ in ways the write-up
does not describe:

* ``thinking``  - DeepSeek defaults it to on with effort ``high``. Every arm
  must state it explicitly, and the value is stored on every record.
* ``effort``    - the reasoning effort, one of the published levels.

The API key is read from ``DEEPSEEK_API_KEY`` or from a ``.env`` file at the
repository root. It is never written to a log or a record: records carry the
model name and the token counts, never the credential.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import os
import random
import time
from typing import Any, Iterable, Mapping, Sequence

from . import pricing
from .spend import SpendGuard

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"
API_KEY_ENV = "DEEPSEEK_API_KEY"
DOTENV_NAME = ".env"

# The published mapping collapses several requested levels onto the same real
# level; accepting only the real ones keeps runs comparable.
VALID_EFFORTS = ("low", "high", "max")

RETRY_STATUSES = frozenset({408, 409, 429, 500, 502, 503, 504})

# A transport-level failure is reported internally as this status, so that it
# follows the same retry path as a server error.
TRANSPORT_ERROR_STATUS = 0


class MissingApiKeyError(RuntimeError):
    """No credential was found in the environment or in .env."""


class ModelConfigError(ValueError):
    """A setting was requested that the provider would silently ignore."""


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def read_dotenv(path: str | None = None) -> dict[str, str]:
    """Parse a minimal ``KEY=value`` file. Blank lines and ``#`` are ignored."""

    target = path or os.path.join(_repo_root(), DOTENV_NAME)
    values: dict[str, str] = {}
    if not os.path.exists(target):
        return values
    with open(target, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values[key.strip()] = value
    return values


def load_api_key(
    env: Mapping[str, str] | None = None,
    dotenv_path: str | None = None,
) -> str:
    """Return the API key, preferring the environment over the file."""

    environ = os.environ if env is None else env
    key = (environ.get(API_KEY_ENV) or "").strip()
    if not key:
        key = (read_dotenv(dotenv_path).get(API_KEY_ENV) or "").strip()
    if not key:
        raise MissingApiKeyError(
            f"{API_KEY_ENV} is not set. Put it in the environment, or create "
            f"{os.path.join(_repo_root(), DOTENV_NAME)} with a line reading "
            f"{API_KEY_ENV}=<your key>."
        )
    return key


@dataclasses.dataclass(frozen=True)
class ModelConfig:
    """Everything that must be identical across arms for a fair comparison."""

    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    thinking: bool = True
    effort: str = "high"
    max_tokens: int = 8192
    temperature: float | None = None
    top_p: float | None = None
    timeout_seconds: float = 600.0
    max_retries: int = 4

    def __post_init__(self) -> None:
        if self.effort not in VALID_EFFORTS:
            raise ModelConfigError(
                f"effort must be one of {VALID_EFFORTS}, got {self.effort!r}"
            )
        if self.max_tokens <= 0:
            raise ModelConfigError("max_tokens must be positive")

        if self.thinking:
            # The provider accepts these and ignores them, which is worse than
            # an error: the run would look configured when it is not.
            if self.temperature is not None:
                raise ModelConfigError(
                    "temperature has no effect in thinking mode; set "
                    "thinking=False or drop the temperature"
                )
            if self.top_p is not None:
                if not 0.95 <= self.top_p <= 1.0:
                    raise ModelConfigError(
                        "top_p is only honoured in thinking mode and only "
                        f"within 0.95-1.0, got {self.top_p}"
                    )
        else:
            if self.top_p is not None:
                raise ModelConfigError(
                    "top_p is ignored when thinking is off; drop it"
                )
            if self.temperature is not None and not 0 <= self.temperature <= 2:
                raise ModelConfigError("temperature must be within 0-2")

    def request_body(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]] | None = None,
        tool_choice: str | Mapping[str, Any] | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [dict(m) for m in messages],
            "max_tokens": self.max_tokens,
            "stream": stream,
            # Sent through extra_body by the OpenAI SDK, so it is a top-level
            # key on the wire.
            "thinking": {"type": "enabled" if self.thinking else "disabled"},
        }
        if self.thinking and self.effort != "high":
            body["reasoning_effort"] = self.effort
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if self.top_p is not None:
            body["top_p"] = self.top_p
        if tools:
            body["tools"] = [dict(t) for t in tools]
            if tool_choice is not None:
                body["tool_choice"] = tool_choice
        return body

    def describe(self) -> str:
        mode = f"thinking={self.effort}" if self.thinking else "thinking=off"
        return f"{self.model} ({mode}, max_tokens={self.max_tokens})"


@dataclasses.dataclass
class CallRecord:
    """What one model call cost, in the form the run log wants."""

    requested_model: str
    served_model: str
    thinking: bool
    effort: str
    prompt_tokens: int
    cache_hit_tokens: int
    cache_miss_tokens: int
    output_tokens: int
    reasoning_tokens: int
    latency_seconds: float
    finish_reason: str
    attempts: int
    request_id: str
    started_at: str
    cost_cny: float
    price_tier: str

    @property
    def input_tokens(self) -> int:
        return self.prompt_tokens

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    def runlog_fields(self) -> dict[str, Any]:
        """The subset that feeds the run log's accounting columns."""

        return {
            "model_version": self.served_model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "elapsed_seconds": round(self.latency_seconds, 3),
        }


@dataclasses.dataclass
class ChatResult:
    record: CallRecord
    message: dict[str, Any]
    text: str
    reasoning: str
    tool_calls: list[dict[str, Any]]

    def as_history_entry(self) -> dict[str, Any]:
        """The assistant turn to append before the next request.

        When tools are in play the provider requires the earlier
        ``reasoning_content`` to be echoed back, and it does get folded into the
        context. Without tools it is ignored, so it is dropped to keep the
        prompt small.
        """

        entry: dict[str, Any] = {"role": "assistant"}
        entry["content"] = self.message.get("content")
        if self.reasoning and self.tool_calls:
            entry["reasoning_content"] = self.reasoning
        if self.tool_calls:
            entry["tool_calls"] = self.tool_calls
        return entry


class Ledger:
    """Running totals, so a run can be checked against its budget tier."""

    def __init__(self) -> None:
        self.records: list[CallRecord] = []

    def add(self, record: CallRecord) -> None:
        self.records.append(record)

    @property
    def model_calls(self) -> int:
        return len(self.records)

    @property
    def input_tokens(self) -> int:
        return sum(r.prompt_tokens for r in self.records)

    @property
    def output_tokens(self) -> int:
        return sum(r.output_tokens for r in self.records)

    @property
    def cost_cny(self) -> float:
        return round(sum(r.cost_cny for r in self.records), 6)

    @property
    def elapsed_seconds(self) -> float:
        return round(sum(r.latency_seconds for r in self.records), 3)

    def summary(self) -> dict[str, Any]:
        return {
            "model_calls": self.model_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "elapsed_seconds": self.elapsed_seconds,
            "cost_cny": self.cost_cny,
            "models": sorted({r.served_model for r in self.records}),
        }


class DeepSeekClient:
    """Thin client over the OpenAI-compatible chat completions endpoint."""

    def __init__(
        self,
        config: ModelConfig | None = None,
        *,
        api_key: str | None = None,
        guard: SpendGuard | None = None,
        session: Any = None,
        sleeper: Any = time.sleep,
    ) -> None:
        self.config = config or ModelConfig()
        self._api_key = api_key or load_api_key()
        # No guard means no ceiling, which is only acceptable in tests. Every
        # script that talks to the real service attaches one.
        self._guard = guard
        self._sleeper = sleeper
        if session is None:
            import requests

            session = requests.Session()
        self._session = session

    def __repr__(self) -> str:  # never print the key
        ceiling = (
            f"ceiling CNY {self._guard.policy.ceiling_cny:.2f}"
            if self._guard
            else "no spend ceiling"
        )
        return f"DeepSeekClient({self.config.describe()}, {ceiling}, key=<redacted>)"

    __str__ = __repr__

    def _post(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        import requests

        url = self.config.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        response = self._session.post(
            url,
            headers=headers,
            data=json.dumps(body),
            timeout=self.config.timeout_seconds,
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": getattr(response, "text", "")[:500]}
        return response.status_code, payload

    def chat(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
        tool_choice: str | Mapping[str, Any] | None = None,
    ) -> ChatResult:
        if self._guard is not None:
            # Worst-case check before anything leaves the machine.
            self._guard.check_before(
                self.config.model, max_output_tokens=self.config.max_tokens
            )

        body = self.config.request_body(messages, tools, tool_choice)
        started = time.time()
        attempts = 0
        last_error: Exception | None = None

        while attempts <= self.config.max_retries:
            attempts += 1
            try:
                status, payload = self._post(body)
            except Exception as exc:  # transport-level failure
                last_error = exc
                status, payload = TRANSPORT_ERROR_STATUS, {}

            if status == 200:
                break

            retryable = status == TRANSPORT_ERROR_STATUS or status in RETRY_STATUSES
            if not retryable or attempts > self.config.max_retries:
                detail = payload.get("error") if isinstance(payload, dict) else None
                raise RuntimeError(
                    f"model call failed with HTTP {status}: "
                    f"{detail or payload or last_error}"
                )
            # Exponential backoff with jitter, to avoid synchronised retries
            # when several workers hit the rate limit together.
            delay = min(2 ** (attempts - 1), 30) * (0.5 + random.random())
            self._sleeper(delay)
        else:  # pragma: no cover - loop always breaks or raises
            raise RuntimeError("model call failed after retries")

        latency = time.time() - started
        result = self._to_result(payload, latency, attempts, started)
        if self._guard is not None:
            self._guard.book(result.record)
        return result

    def _to_result(
        self,
        payload: Mapping[str, Any],
        latency: float,
        attempts: int,
        started: float,
    ) -> ChatResult:
        choices = payload.get("choices") or []
        choice = choices[0] if choices else {}
        message = dict(choice.get("message") or {})
        usage = dict(payload.get("usage") or {})

        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        hit_raw = usage.get("prompt_cache_hit_tokens")
        if hit_raw is None:
            hit_raw = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
        hit, miss = pricing.split_prompt_tokens(
            prompt_tokens, None if hit_raw is None else int(hit_raw)
        )
        output_tokens = int(usage.get("completion_tokens") or 0)
        reasoning_tokens = int(
            (usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
        )

        served_model = str(payload.get("model") or self.config.model)
        when = dt.datetime.fromtimestamp(started, pricing.BEIJING)
        cost = pricing.estimate_cost(
            self.config.model,
            cache_hit_tokens=hit,
            cache_miss_tokens=miss,
            output_tokens=output_tokens,
            when=when,
        )

        record = CallRecord(
            requested_model=self.config.model,
            served_model=served_model,
            thinking=self.config.thinking,
            effort=self.config.effort,
            prompt_tokens=prompt_tokens,
            cache_hit_tokens=hit,
            cache_miss_tokens=miss,
            output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens,
            latency_seconds=round(latency, 4),
            finish_reason=str(choice.get("finish_reason") or ""),
            attempts=attempts,
            request_id=str(payload.get("id") or ""),
            started_at=when.isoformat(),
            cost_cny=cost,
            price_tier=pricing.tier_for(when),
        )

        tool_calls = list(message.get("tool_calls") or [])
        return ChatResult(
            record=record,
            message=message,
            text=message.get("content") or "",
            reasoning=message.get("reasoning_content") or "",
            tool_calls=tool_calls,
        )


def parse_tool_arguments(call: Mapping[str, Any]) -> dict[str, Any]:
    """Decode a tool call's arguments, tolerating malformed JSON."""

    function = call.get("function") or {}
    raw = function.get("arguments")
    if raw in (None, ""):
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        return {"_unparsed": raw}
    return decoded if isinstance(decoded, dict) else {"_unparsed": decoded}


def tool_message(call: Mapping[str, Any], content: str) -> dict[str, Any]:
    """Build the reply that answers one tool call."""

    return {
        "role": "tool",
        "tool_call_id": call.get("id", ""),
        "content": content,
    }
