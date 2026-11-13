"""Offline execution contracts, exercising real loops with injected transports."""
from types import SimpleNamespace as NS
from unittest.mock import patch
import json

from swe_repair.budget import Budget, BudgetState
from swe_repair.execution import Runtime, BudgetedClient, BudgetedContainer, ResourceLimit
from swe_repair.llm import ModelConfig, DeepSeekClient, ChatResult
from swe_repair.spend import SpendGuard, SpendPolicy, SpendLimitExceeded
from swe_repair.state import Candidate, PatchHistory, RepairState, TaskManifest, FailureRecord
from swe_repair import interact, prefix, router

DIFF = '--- a/pkg/mod.py\n+++ b/pkg/mod.py\n@@ -1 +1 @@\n-a=1\n+a=2\n'


def budget(**overrides):
    values = dict(token=100000, model_call=10, tool_call=30, wallclock_seconds=100)
    values.update(overrides)
    return BudgetState('offline', Budget(**values))


def record(**overrides):
    values = dict(cost_cny=0.01, prompt_tokens=20, output_tokens=10, finish_reason='stop',
                  served_model='pinned', reasoning_tokens=0)
    values.update(overrides)
    return NS(**values)


def reply(text='', calls=None):
    calls = calls or []
    return ChatResult(record(), {'role': 'assistant', 'content': text, 'tool_calls': calls}, text, '', calls)


class FakeClient:
    config = ModelConfig(max_tokens=100)
    def __init__(self, replies):
        self.replies, self.requests = iter(replies), []
    def chat(self, messages, **kwargs):
        self.requests.append((list(messages), kwargs))
        item = next(self.replies)
        if isinstance(item, Exception):
            raise item
        return item


class FakeBox:
    workdir, name, image = '/testbed', 'offline', 'offline-image'
    def __init__(self):
        self.reverts, self.execs = 0, []
    def revert(self):
        self.reverts += 1
    def bash(self, script, timeout=300):
        self.execs.append((script, timeout))
        return 0, 'observation'
    def close(self):
        pass


def test_runtime_refuses_a_model_before_transport_when_tokens_do_not_fit():
    client = FakeClient([reply()])
    wrapped = BudgetedClient(client, Runtime(budget(token=10)))
    try:
        wrapped.chat([{'role': 'user', 'content': 'a'}])
    except ResourceLimit:
        pass
    else:
        raise AssertionError('oversized model request was allowed')
    assert not client.requests


def test_failed_requests_reserve_tokens_and_money_and_emit_evidence():
    client = FakeClient([RuntimeError('transport interrupted')])
    seen = []
    rt = Runtime(budget(), money=SpendGuard(SpendPolicy(ceiling_cny=1)), event_sink=seen.append)
    try:
        BudgetedClient(client, rt).chat([{'role': 'user', 'content': 'a'}])
    except RuntimeError:
        pass
    assert rt.state.consumed.model_call == 1
    assert rt.state.consumed.token >= 1124
    assert rt.money.spent_cny > 0
    assert rt.records[0]['billing'] == 'unknown'
    assert any(e['event'] == 'model_request' and e['messages'] for e in seen)
    assert any(e['event'] == 'failed_request' for e in seen)


def test_runtime_model_drift_keeps_usage_and_cost_before_raising():
    rt = Runtime(budget())
    try:
        BudgetedClient(FakeClient([reply()]), rt, expected_served_model='other').chat([])
    except RuntimeError as exc:
        assert 'drift' in str(exc)
    else:
        raise AssertionError('server model drift was accepted')
    assert rt.state.consumed.token == 30 and rt.cost_cny == 0.01


def test_tool_limit_and_deadline_are_checked_before_exec_and_cleanup_still_runs():
    now = [0.0]
    rt = Runtime(budget(tool_call=1), clock=lambda: now[0])
    box = FakeBox()
    wrapped = BudgetedContainer(box, rt)
    wrapped.bash('first')
    try:
        wrapped.bash('second')
    except ResourceLimit:
        pass
    else:
        raise AssertionError('second tool crossed limit')
    assert len(box.execs) == 1
    now[0] = 200
    wrapped.revert()
    assert box.reverts == 1 and rt.state.overrun


def test_shared_deadline_caps_tool_timeout():
    rt = Runtime(budget(), clock=lambda: 0)
    rt.deadline = 3
    box = FakeBox()
    BudgetedContainer(box, rt).bash('one', timeout=180)
    assert box.execs[0][1] == 3


def test_syntax_scope_and_unvalidated_candidates_cannot_win():
    history = PatchHistory()
    history.add(Candidate.build(0, DIFF, applies_cleanly=True, syntax='fail', validation='pass'))
    history.add(Candidate.build(1, DIFF, applies_cleanly=True, scope_valid=False, validation='pass'))
    history.add(Candidate.build(2, DIFF, validation='pass'))
    assert history.best_candidate() is None and not history.has_public_pass()
    history.add(Candidate.build(3, DIFF, applies_cleanly=True, syntax='pass', validation='not_run'))
    assert history.best_candidate().index == 3


def test_successful_recovery_clears_active_environment_failure_without_erasing_history():
    from swe_repair.state import FailureLog
    failures = FailureLog()
    failures.add(FailureRecord.from_output('validation', 1, stage='env'))
    failures.add(FailureRecord.from_output('validation recovery', 0, stage='env'))
    assert failures.environment_failure() is None and len(failures.records) == 2


def test_interactive_many_tools_do_not_bypass_tool_cap_or_reserved_final_call():
    calls = [{'id': str(i), 'function': {'name': 'search_symbol', 'arguments': json.dumps({'name': str(i)})}}
             for i in range(3)]
    client, box = FakeClient([reply(calls=calls), reply()]), FakeBox()
    with patch.object(interact, 'execute_tool', return_value=('mock observation', True)) as tool:
        result = interact.run_interactive('bug', client=client, container=box,
                    budget=interact.InteractionBudget(model_calls=2, tool_calls=1))
    assert tool.call_count == 1 and result.tool_calls == 1
    assert result.calls == 2 and len(client.requests) == 2
    assert 'tools' not in client.requests[-1][1]
    assert box.reverts == 1


def test_zero_call_budget_makes_no_forced_request_and_retains_prefix_candidate():
    client, box = FakeClient([]), FakeBox()
    state = RepairState(TaskManifest('x', 'repo', 'base', 'v', 'hash'))
    state.patches.add(Candidate.build(0, DIFF, applies_cleanly=True, syntax='pass'))
    result = interact.run_interactive('bug', client=client, container=box, state=state,
                                     budget=interact.InteractionBudget(model_calls=0))
    assert not client.requests and result.final_diff == DIFF


def test_source_run_test_discovers_tests_and_preserves_traceback():
    with patch.object(interact, 'public_test_files', return_value=['tests/test_mod.py']) as discover, \
         patch.object(interact, 'run_public_tests', return_value=('fail', '1 failed', 'AssertionError: root cause')) as run:
        observation, progressed = interact.execute_tool(FakeBox(), 'run_test', {'path': 'pkg/mod.py'})
    discover.assert_called_once()
    assert run.call_args.args[1] == ['tests/test_mod.py']
    assert progressed and 'AssertionError: root cause' in observation


def test_scope_and_tool_paths_reject_traversal_without_shell():
    from swe_repair.patchutil import patch_scope_valid
    assert not patch_scope_valid(DIFF.replace('pkg/mod.py', '../secret.py'))
    assert not patch_scope_valid(DIFF.replace('pkg/mod.py', 'tests/test_mod.py'))
    box = FakeBox()
    observation, progressed = interact.execute_tool(box, 'read_region', {'path': '../../secret'})
    assert not progressed and not box.execs


def test_local_error_precedes_high_disagreement_but_budget_precedes_passing_candidate():
    from pathlib import Path
    cfg = router.RouterConfig.from_file(Path(__file__).parents[1] / 'configs/proposal_v1.json').with_thresholds(.5, .5)
    from swe_repair.state import Localization
    state = RepairState(TaskManifest('x', 'repo', 'base', 'v', 'hash'), budget=budget())
    state.localization = Localization.from_file_sets({'one': ['a.py'], 'two': ['b.py']})
    state.failures.add(FailureRecord.from_output('git apply', 1, stage='apply_patch'))
    assert router.route(state, cfg).rule == 'fixed_on_local_application_or_syntax_error'
    state.patches.add(Candidate.build(0, DIFF, applies_cleanly=True, syntax='pass', validation='pass'))
    state.budget.spend(token=999999)
    for arm in ('A', 'C', 'D', 'E'):
        assert router.route_for_arm(arm, state, cfg).reason == 'stop_budget_insufficient'


def test_effective_hash_changes_with_threshold_and_external_mutation_is_not_shared():
    from pathlib import Path
    cfg = router.RouterConfig.from_file(Path(__file__).parents[1] / 'configs/proposal_v1.json')
    other = cfg.with_thresholds(.5, .5)
    assert cfg.digest != other.digest
    raw = cfg.effective_config()
    cfg2 = router.RouterConfig.from_config(raw)
    before = cfg2.digest
    raw['execution']['per_instance_cny'] += 1
    assert cfg2.digest == before


def test_prefix_generic_error_returns_partial_trace_without_network():
    box = FakeBox()
    box.head = lambda: 'base'
    box.bash = lambda *a, **kw: (0, 'pkg\ntests')
    client = FakeClient([RuntimeError('transport failed')])
    out = prefix.run_prefix({'instance_id': 'x', 'repo': 'repo', 'base_commit': 'base'}, client,
                            config_version='v', config_hash='h', container=box)
    assert out.state.task.instance_id == 'x'
    assert out.trace[-1]['step'] == 'prefix_error'
