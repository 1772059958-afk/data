"""Resource enforcement shared by prefix, fixed continuation and interaction.

Each alternative gets a COPY of the consumed prefix budget. The experiment's
money guard is separate from this per-policy resource accounting. Container
execs (including validation) are the globally counted tool unit.
"""
from __future__ import annotations

import json
import copy
import time
from types import SimpleNamespace
from typing import Any

from .budget import Budget, BudgetState
from .spend import SpendGuard, SpendPolicy


class ResourceLimit(RuntimeError):
    pass


class Runtime:
    def __init__(self, state: BudgetState, *, money: SpendGuard | None = None,
                 clock=time.monotonic, token_limit: int | None = None, event_sink=None):
        self.state = state
        self.money = money
        self.clock = clock
        self.started = clock()
        self.elapsed_booked = 0.0
        self.token_limit = token_limit
        # Optional cumulative request cap within the global resource ceiling.
        # A session may tighten it to reserve its last actual HTTP attempt.
        self.model_call_limit: int | None = None
        self.records: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.deadline: float | None = None
        self.event_sink = event_sink

    def emit(self, event):
        self.sync()
        payload = copy.deepcopy(dict(event, budget=self.state.to_dict()))
        self.events.append(payload)
        if self.event_sink:
            self.event_sink(payload)

    @property
    def remaining_seconds(self):
        self.sync()
        remaining = self.state.remaining.wallclock_seconds
        return remaining if self.deadline is None else min(remaining, self.deadline - self.clock())

    def sync(self):
        elapsed = max(0.0, self.clock() - self.started)
        delta = max(0.0, elapsed - self.elapsed_booked)
        self.state.spend(wallclock_seconds=delta)
        self.elapsed_booked = elapsed

    def require(self, need: Budget):
        self.sync()
        if (self.state.overrun or not self.state.can_afford(need)
                or self.remaining_seconds <= 0):
            raise ResourceLimit('resource ceiling reached')
        if (self.token_limit is not None
                and self.state.consumed.token + need.token > self.token_limit):
            raise ResourceLimit('prefix token allowance reached')
        if (self.model_call_limit is not None
                and self.state.consumed.model_call + need.model_call > self.model_call_limit):
            raise ResourceLimit('session model request allowance reached')

    def tool(self, timeout):
        self.require(Budget(tool_call=1))
        self.state.spend(tool_call=1, strict=True)
        return max(0.001, min(float(timeout), self.remaining_seconds))

    @property
    def cost_cny(self):
        return sum(float(r['cost_cny']) for r in self.records)


class BudgetedClient:
    def __init__(self, client, runtime: Runtime, expected_served_model: str | None = None):
        self.client, self.runtime = client, runtime
        self.config = client.config
        self.expected_served_model = expected_served_model

    def chat(self, messages, **kwargs):
        # A byte-based upper estimate, with protocol overhead. Actual billed
        # usage is booked afterwards; overruns remain visible and stop the run.
        prompt = len(json.dumps({'messages': messages, **kwargs}, ensure_ascii=False).encode('utf-8')) + 1024
        output = self.config.max_tokens
        rt = self.runtime
        def hook(phase, record=None):
            if phase == 'remaining':
                return rt.remaining_seconds
            if phase == 'before':
                rt.require(Budget(token=prompt + output, model_call=1))
                if rt.money:
                    rt.money.check_before(self.config.model, prompt_tokens=prompt,
                                          max_output_tokens=output)
                rt.state.spend(model_call=1, strict=True)
                rt.emit({'event': 'model_request', 'model': self.config.model,
                         'messages': messages, 'request_options': kwargs,
                         'prompt_tokens_reserved': prompt, 'max_output_tokens': output})
                return rt.remaining_seconds
            if phase == 'failed':
                # Usage of an interrupted request is unknown. Reserve its
                # worst-case tokens rather than pretending it was free.
                rt.state.spend(token=prompt + output)
                from . import pricing
                cost = pricing.estimate_cost(self.config.model, cache_miss_tokens=prompt, output_tokens=output)
                reservation = {'event': 'failed_request', 'prompt_tokens': prompt, 'output_tokens': output,
                               'cost_cny': cost, 'billing': 'unknown', 'served_model': None}
                rt.records.append(reservation)
                rt.emit(dict(reservation, reserved_tokens=prompt + output))
                if rt.money:
                    rt.money.book(SimpleNamespace(**reservation))
            elif phase == 'success':
                rt.state.spend(token=record.prompt_tokens + record.output_tokens)
                row = record.as_dict() if hasattr(record, 'as_dict') else dict(vars(record))
                rt.records.append(row)
                rt.emit({'event': 'model_response', 'record': row})
                if rt.money:
                    rt.money.book(record)
            rt.sync()
        from .llm import DeepSeekClient
        if isinstance(self.client, DeepSeekClient):
            result = self.client.chat(messages, attempt_hook=hook,
                                      prompt_tokens_estimate=prompt, **kwargs)
            rt.emit({'event': 'model_message', 'message': result.message})
            self._check_served_model(result)
            return result
        hook('before')
        try:
            result = self.client.chat(messages, **kwargs)
        except Exception:
            hook('failed')
            raise
        hook('success', result.record)
        rt.emit({'event': 'model_message', 'message': result.message})
        self._check_served_model(result)
        return result

    def _check_served_model(self, result):
        if self.expected_served_model and result.record.served_model != self.expected_served_model:
            raise RuntimeError(f'served model drift: expected {self.expected_served_model}, '
                               f'got {result.record.served_model}')


class BudgetedContainer:
    """Bind the existing Container methods to counted execs, including helpers."""
    def __init__(self, box, runtime: Runtime):
        self.box, self.runtime = box, runtime
        self.workdir = box.workdir
        self.name, self.image = box.name, box.image

    def bash(self, script, timeout=300):
        timeout = self.runtime.tool(timeout)
        event = {'event': 'container_exec', 'command': script, 'timeout': timeout}
        self.runtime.emit(event)
        try:
            code, output = self.box.bash(script, timeout=timeout)
            event.update(exit_code=code, output=output)
            return code, output
        except Exception as exc:
            event.update(error=f'{type(exc).__name__}: {exc}')
            raise
        finally:
            self.runtime.emit(dict(event, event='container_result'))

    def __getattr__(self, name):
        # Container's helpers call self.bash, so bind to THIS wrapper.
        from .prefix import Container
        method = getattr(Container, name, None)
        if callable(method):
            return method.__get__(self, type(self))
        return getattr(self.box, name)

    def close(self):
        return self.box.close()

    def revert(self):
        # Reset is lifecycle cleanup, not a model-visible observation. It must
        # still run after resource exhaustion, to keep alternatives isolated.
        try:
            return self.box.revert()
        finally:
            self.runtime.sync()


def runtime_for(state: BudgetState, ceiling_cny: float):
    return Runtime(state, money=SpendGuard(SpendPolicy(ceiling_cny=ceiling_cny)))
