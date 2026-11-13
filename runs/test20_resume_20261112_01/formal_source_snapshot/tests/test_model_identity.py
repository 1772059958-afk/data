"""Provider identity observations and paid-response fail-closed enforcement."""
import copy

from swe_repair.budget import Budget, BudgetState
from swe_repair.execution import BudgetedClient, Runtime
from swe_repair.llm import DeepSeekClient, ModelConfig
from swe_repair.spend import SpendGuard, SpendPolicy


def payload(**identity):
    result = {
        'id': 'offline-request-1', 'model': 'deepseek-flash',
        'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': 'OK'}}],
        'usage': {'prompt_tokens': 100, 'completion_tokens': 20,
                  'prompt_cache_hit_tokens': 0},
    }
    result.update(identity)
    return result


class Response:
    status_code = 200

    def __init__(self, data):
        self.data = data

    def json(self):
        return copy.deepcopy(self.data)


class Session:
    def __init__(self, data):
        self.data = data
        self.sent = 0

    def post(self, *args, **kwargs):
        self.sent += 1
        return Response(self.data)


def guarded(data):
    session = Session(data)
    batch = SpendGuard(SpendPolicy(ceiling_cny=1))
    local = SpendGuard(SpendPolicy(ceiling_cny=1))
    client = DeepSeekClient(ModelConfig(max_tokens=64, max_retries=3), api_key='offline-fake',
                            guard=batch, session=session, sleeper=lambda _: None)
    runtime = Runtime(BudgetState('offline', Budget(10000, 4, 0, 120)), money=local)
    return client, runtime, session, batch, local


def test_call_record_keeps_actual_fingerprint_and_provider_timestamp_without_version_claim():
    client, runtime, session, batch, local = guarded(
        payload(system_fingerprint='backend-one', created=1793084842))
    result = BudgetedClient(client, runtime, expected_system_fingerprint='backend-one').chat([])
    record = result.record.as_dict()
    assert record['system_fingerprint'] == 'backend-one'
    assert record['provider_created'] == 1793084842
    assert record['served_model'] == 'deepseek-flash'
    assert 'immutable_version' not in record
    assert session.sent == 1 and batch.spent_cny == local.spent_cny > 0


def test_missing_or_malformed_identity_metadata_is_unknown_not_synthesised():
    cases = [{}, {'system_fingerprint': None, 'created': None},
             {'system_fingerprint': '', 'created': -1},
             {'system_fingerprint': '  ', 'created': True},
             {'system_fingerprint': 123, 'created': 1793084842.0},
             {'system_fingerprint': {'value': 'backend-one'}, 'created': '1793084842'}]
    for identity in cases:
        client, runtime, _, _, _ = guarded(payload(**identity))
        record = BudgetedClient(client, runtime).chat([]).record
        assert record.system_fingerprint is None and record.provider_created is None
        assert record.served_model == 'deepseek-flash'


def test_fingerprint_mismatch_or_missing_stops_after_booking_usage_and_cost():
    for actual, expected_code in [('backend-two', 'system_fingerprint_mismatch'),
                                  (None, 'system_fingerprint_missing')]:
        client, runtime, session, batch, local = guarded(payload(system_fingerprint=actual))
        try:
            BudgetedClient(client, runtime, expected_system_fingerprint='backend-one').chat([])
        except RuntimeError as exc:
            assert 'fingerprint' in str(exc)
        else:
            raise AssertionError('changed/missing provider fingerprint was accepted')
        assert session.sent == 1  # An HTTP success with wrong identity is never retried.
        assert batch.calls == local.calls == 1
        assert batch.spent_cny == local.spent_cny == runtime.cost_cny > 0
        assert runtime.state.consumed.model_call == 1
        assert runtime.state.consumed.token == 120
        assert runtime.records[0]['system_fingerprint'] == actual
        assert runtime.records[0]['billing'] == 'estimated_from_usage'
        assert client._identity_violation == expected_code


def test_identity_violation_blocks_same_client_with_a_new_runtime_before_another_request():
    client, runtime, session, batch, _ = guarded(payload(system_fingerprint='changed'))
    first = BudgetedClient(client, runtime, expected_system_fingerprint='expected')
    try:
        first.chat([])
    except RuntimeError:
        pass
    else:
        raise AssertionError('fingerprint mismatch did not halt the first response')
    next_money = SpendGuard(SpendPolicy(ceiling_cny=1))
    next_runtime = Runtime(BudgetState('other-branch', Budget(10000, 4, 0, 120)), money=next_money)
    # Removing the expectation on a new wrapper cannot reset the shared fuse.
    next_client = BudgetedClient(client, next_runtime)
    try:
        next_client.chat([])
    except RuntimeError as exc:
        assert 'prior identity violation' in str(exc)
    else:
        raise AssertionError('new branch bought an answer after an identity violation')
    assert session.sent == batch.calls == 1
    assert next_runtime.state.consumed.model_call == 0
    assert not next_runtime.records and next_money.spent_cny == 0


def test_alias_mismatch_or_missing_also_sets_the_shared_identity_fuse():
    for data, expected in [(payload(model='different-model'), 'served_model_mismatch'),
                           (payload(model=None), 'served_model_missing')]:
        client, runtime, session, batch, local = guarded(data)
        try:
            BudgetedClient(client, runtime, expected_served_model='deepseek-flash').chat([])
        except RuntimeError:
            pass
        else:
            raise AssertionError('wrong alias identity was accepted')
        assert client._identity_violation == expected
        assert session.sent == 1 and batch.spent_cny == local.spent_cny > 0


def test_fingerprint_expectation_must_not_silently_accept_an_empty_or_nonstring_lock():
    for expected in ('', '  ', True, 123):
        client, runtime, session, _, _ = guarded(payload())
        try:
            BudgetedClient(client, runtime, expected_system_fingerprint=expected)
        except ValueError:
            pass
        else:
            raise AssertionError('invalid fingerprint expectation disabled the identity check')
        assert session.sent == 0
