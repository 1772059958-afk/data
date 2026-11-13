"""Account access/usage failures stop new requests without erasing their costs."""
from swe_repair.budget import Budget, BudgetState
from swe_repair.execution import BudgetedClient, Runtime
from swe_repair.llm import DeepSeekClient, ModelConfig
from swe_repair.spend import SpendGuard, SpendLimitExceeded, SpendPolicy
from pathlib import Path
import tempfile


class Session:
    def __init__(self, status):
        self.status, self.sent = status, 0

    def post(self, *args, **kwargs):
        self.sent += 1
        status = self.status
        class Response:
            status_code = status
            def json(self):
                return {'error': 'provider body with a credential-like secret that must not be logged'}
        return Response()


def runtime():
    return Runtime(BudgetState('offline', Budget(10000, 4, 0, 120)),
                   money=SpendGuard(SpendPolicy(ceiling_cny=1)))


def test_access_or_quota_failure_is_booked_once_then_blocks_all_fresh_runtimes():
    for status in (0, 400, 401, 402, 403, 404, 429, 500, 503):
        session = Session(status)
        batch = SpendGuard(SpendPolicy(ceiling_cny=1))
        client = DeepSeekClient(ModelConfig(max_tokens=64, max_retries=3, stop_on_api_breakpoint=True),
                                api_key='offline-fake', guard=batch, session=session,
                                sleeper=lambda _: (_ for _ in ()).throw(AssertionError('quota retry')))
        first = runtime()
        try:
            BudgetedClient(client, first).chat([])
        except RuntimeError as exc:
            assert f'api_http_{status}' in str(exc)
            assert 'credential-like secret' not in str(exc)
        else:
            raise AssertionError('account breakpoint accepted')
        assert session.sent == batch.calls == 1
        assert first.state.consumed.model_call == 1
        assert first.records[0]['billing'] == 'unknown'
        # Unknown batch requests reserve the worst published price tier;
        # the stage's provisional estimate may use the observed time tier.
        assert batch.spent_cny >= first.cost_cny > 0
        assert client._api_breakpoint == f'api_http_{status}'
        second = runtime()
        for call in [lambda: BudgetedClient(client, second).chat([]), lambda: client.chat([])]:
            try:
                call()
            except RuntimeError as exc:
                assert 'breakpoint' in str(exc)
            else:
                raise AssertionError('fresh branch bought another request')
        assert session.sent == 1 and second.state.consumed.model_call == 0
        assert not second.records and second.cost_cny == 0


def test_global_batch_money_refusal_stops_without_sending_or_booking_a_request():
    session = Session(200)
    guard = SpendGuard(SpendPolicy(ceiling_cny=0.000001))
    client = DeepSeekClient(ModelConfig(max_tokens=64, max_retries=0, stop_on_api_breakpoint=True),
                            api_key='offline-fake', guard=guard, session=session)
    local = runtime()
    try:
        BudgetedClient(client, local).chat([])
    except SpendLimitExceeded:
        pass
    else:
        raise AssertionError('global batch spend limit bypassed')
    assert client._api_breakpoint == 'batch_spend_limit_or_unreconciled_request'
    assert session.sent == guard.calls == local.state.consumed.model_call == 0
    assert not local.records and local.cost_cny == 0


def test_operator_stop_preserves_completed_charge_and_blocks_next_request():
    with tempfile.TemporaryDirectory() as folder:
        stop = Path(folder) / 'stop.json'
        session = Session(200)
        def response(*args, **kwargs):
            session.sent += 1
            class Response:
                status_code = 200
                def json(self):
                    return {'id': 'offline', 'model': 'deepseek-flash',
                            'choices': [{'finish_reason': 'stop', 'message': {'content': 'ok'}}],
                            'usage': {'prompt_tokens': 10, 'completion_tokens': 5}}
            return Response()
        session.post = response
        guard = SpendGuard(SpendPolicy(ceiling_cny=1))
        client = DeepSeekClient(ModelConfig(max_tokens=64, workflow_stop_file=str(stop)),
                                api_key='offline-fake', guard=guard, session=session)
        client.chat([])
        charged = guard.spent_cny
        assert charged > 0 and session.sent == guard.calls == 1
        stop.write_text('{}', encoding='utf-8')
        try:
            client.chat([])
        except RuntimeError:
            pass
        else:
            raise AssertionError('operator stop ignored')
        assert client._api_breakpoint == 'workflow_stop_requested'
        assert session.sent == guard.calls == 1 and guard.spent_cny == charged
