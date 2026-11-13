"""Behavioral regressions for the bounded interaction protocol; no live services."""
import json
from types import SimpleNamespace as NS
from unittest.mock import patch

from swe_repair import interact
from swe_repair.budget import Budget, BudgetState
from swe_repair.execution import BudgetedClient, Runtime
from swe_repair.fingerprint import classify
from swe_repair.llm import ChatResult, DeepSeekClient, ModelConfig
from swe_repair.prefix import ValidationResult
from swe_repair.state import Candidate, RepairState, TaskManifest, FailureRecord

DIFF = '--- a/pkg/x.py\n+++ b/pkg/x.py\n@@ -1,1 +1,1 @@\n-x=1\n+x=2\n'


def tool(name, args=None, identifier='tool'):
    return {'id': identifier, 'function': {'name': name, 'arguments': json.dumps(args or {})}}


def reply(calls=None, text=''):
    record = NS(cost_cny=.01, prompt_tokens=10, output_tokens=5, finish_reason='stop', served_model='fake')
    return ChatResult(record, {'role': 'assistant', 'content': text, 'tool_calls': calls or []}, text, '', calls or [])


class Client:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.requests = []
    def chat(self, messages, **kwargs):
        self.requests.append((list(messages), kwargs))
        return next(self.replies)


class Box:
    def __init__(self):
        self.applied, self.execs, self.reverts = [], [], 0
    def apply(self, diff):
        self.applied.append(diff)
        return True, ''
    def revert(self): self.reverts += 1
    def close(self): pass
    def bash(self, script, timeout=300):
        self.execs.append(script)
        return 0, 'synthetic observation'


def state():
    return RepairState(TaskManifest('synthetic__repo-1', 'synthetic/repo', 'base', 'test', 'test'))


def test_state_machine_rejects_validation_without_candidate_and_is_terminal_after_finish():
    machine = interact.InteractionStateMachine()
    assert machine.transition('run_test', has_candidate=False)
    assert machine.state == 'analyse'
    assert machine.transition('apply_patch', has_candidate=False) is None
    assert machine.state == 'edit'
    assert machine.transition('run_test', has_candidate=True) is None
    assert machine.state == 'validate'
    assert machine.transition('search_symbol', has_candidate=True) is None
    assert machine.transition('finish', has_candidate=True) is None
    assert machine.transition('search_symbol', has_candidate=True)
    assert machine.state == 'finish'


def test_empty_apply_patch_is_an_observation_not_an_index_error():
    observed = state()
    box = Box()
    client = Client([reply([tool('apply_patch', {'diff': ''})]), reply([tool('finish')])])
    result = interact.run_interactive('bug', client=client, container=box, state=observed,
        budget=interact.InteractionBudget(model_calls=3))
    assert result.ended_by == 'finish_tool' and result.calls == 2
    assert not observed.patches.candidates and not box.applied
    assert 'diff must be non-empty' in result.trace[0]['observation']
    assert result.trace[0]['state'] == 'analyse' and not result.trace[0]['progressed']


def test_bad_tool_arguments_are_refused_without_running_shell_or_ending_as_error():
    invalid = [tool('search_symbol', {'name': 'x', 'max_hits': 'many'}),
               tool('read_region', {'path': 'pkg/x.py', 'start': [], 'end': 8}),
               tool('finish', {'diff': {'not': 'a string'}}),
               {'id': 'broken', 'function': {'name': 'search_symbol', 'arguments': '{broken json'}},
               {'id': 'broken', 'function': 'not an object'}]
    for bad in invalid:
        box = Box()
        client = Client([reply([bad]), reply([tool('finish')])])
        result = interact.run_interactive('bug', client=client, container=box,
            budget=interact.InteractionBudget(model_calls=3))
        assert result.ended_by == 'finish_tool', result.ended_by
        assert not box.execs and not box.applied
        assert not result.trace[0]['progressed'] and result.trace[0]['state'] == 'analyse'


def test_no_candidate_run_test_is_refused_and_contributes_to_stagnation():
    client = Client([reply([tool('run_test', {'path': 'tests/test_x.py'})]), reply()])
    box = Box()
    result = interact.run_interactive('bug', client=client, container=box,
        budget=interact.InteractionBudget(model_calls=3, stagnation_patience=1))
    assert result.ended_by == 'stagnation' and not box.execs
    assert 'requires an applicable' in result.trace[0]['observation']
    assert result.final_state == 'finish' and len(client.requests) == 2
    assert 'tools' not in client.requests[-1][1]


def test_finish_without_diff_retains_best_candidate_and_refuses_later_tools():
    observed = state()
    candidate = Candidate.build(2, DIFF, applies_cleanly=True, syntax='pass', validation='fail')
    observed.patches.add(candidate)
    box = Box()
    client = Client([reply([tool('finish'), tool('search_symbol', {'name': 'x'}, 'later')])])
    with patch.object(interact, 'validate_candidate', side_effect=AssertionError('must retain without revalidation')):
        result = interact.run_interactive('bug', client=client, container=box, state=observed)
    assert result.final_diff == DIFF and result.final_state == 'finish'
    assert result.tool_calls == 1 and not box.execs and not box.applied
    assert 'keeping candidate#2' in result.trace[0]['observation']
    assert 'session already finished' in result.transcript[-1]['content']


def test_apply_patch_automatically_enters_validation_and_preserves_complete_candidate():
    observed, box = state(), Box()
    client = Client([reply([tool('apply_patch', {'diff': DIFF})]), reply([tool('finish')])])
    def validate(container, candidate, *args):
        return ValidationResult(Candidate.build(candidate.index, candidate.diff, applies_cleanly=True,
            syntax='pass', validation='fail', origin='interactive'), syntax='pass')
    with patch.object(interact, 'validate_candidate', side_effect=validate):
        result = interact.run_interactive('bug', client=client, container=box, state=observed,
            budget=interact.InteractionBudget(model_calls=3))
    assert result.trace[0]['state_before'] == 'analyse' and result.trace[0]['state'] == 'validate'
    assert result.final_diff == DIFF and box.applied == [DIFF]


def test_prefix_candidate_is_restored_before_additional_public_test():
    observed, box = state(), Box()
    observed.patches.add(Candidate.build(1, DIFF, applies_cleanly=True, syntax='pass', validation='fail'))
    client = Client([reply([tool('run_test', {'path': 'tests/fixture.py'})]), reply([tool('finish')])])
    def checked(container, name, args):
        assert container.applied == [DIFF]
        return 'pass: synthetic', True
    with patch.object(interact, 'execute_tool', side_effect=checked):
        result = interact.run_interactive('bug', client=client, container=box, state=observed,
            budget=interact.InteractionBudget(model_calls=3))
    assert result.trace[0]['state'] == 'validate'
    assert 'candidate#1' in result.trace[0]['observation']


def test_run_test_recognizes_test_directory_without_test_filename_prefix():
    with patch.object(interact, 'public_test_files', side_effect=AssertionError('already a test path')), \
         patch.object(interact, 'run_public_tests', return_value=('fail', '1 failed', 'AssertionError')) as run:
        observation, progressed = interact.execute_tool(Box(), 'run_test', {'path': 'tests/fixture.py'})
    assert run.call_args.args[1] == ['tests/fixture.py'] and progressed


def test_runtime_session_cap_counts_retries_and_reserves_one_actual_final_attempt():
    class Response:
        def __init__(self, status, payload): self.status_code, self.payload = status, payload
        def json(self): return self.payload
    class Session:
        def __init__(self): self.requests = []
        def post(self, *args, **kwargs):
            self.requests.append(json.loads(kwargs['data']))
            if len(self.requests) == 1:
                return Response(500, {'error': 'synthetic retry'})
            return Response(200, {'model': 'fake', 'choices': [{'message': {'content': ''}, 'finish_reason': 'stop'}],
                                  'usage': {'prompt_tokens': 10, 'completion_tokens': 5}})
    session = Session()
    runtime = Runtime(BudgetState('test', Budget(100000, 12, 80, 1200)))
    runtime.model_call_limit = 9
    client = DeepSeekClient(ModelConfig(max_tokens=100, max_retries=3), api_key='fake', session=session, sleeper=lambda s: None)
    wrapped = BudgetedClient(client, runtime)
    result = interact.run_interactive('bug', client=wrapped, container=Box(),
        budget=interact.InteractionBudget(model_calls=2))
    assert result.calls == runtime.state.consumed.model_call == len(session.requests) == 2
    assert 'tools' in session.requests[0] and 'tools' not in session.requests[1]
    assert result.ended_by == 'model_call_budget' and runtime.model_call_limit == 9
    assert runtime.records[0]['billing'] == 'unknown'
    assert result.cost_cny == sum(r['cost_cny'] for r in runtime.records)


def test_timeout_and_collection_keep_distinct_error_categories():
    for code in (124, 137, -9):
        assert classify(code, 'synthetic termination', 'test') == 'timeout'
    assert classify(2, 'ERROR collecting tests/test_x.py', 'test') == 'test_collection'
    assert classify(2, "ModuleNotFoundError: No module named 'x'", 'test') == 'syntax_or_import'


def test_interactive_environment_failure_is_retried_once_then_stops_without_more_model_calls():
    from dataclasses import replace
    observed, box = state(), Box()
    client = Client([reply([tool('apply_patch', {'diff': DIFF})])])
    def unrunnable(container, candidate, *args):
        record = replace(FailureRecord.from_output('python -m pytest tests/test_x.py', 1, stage='env',
                         stdout='No module named pytest'), candidate_index=candidate.index)
        return ValidationResult(Candidate.build(candidate.index, candidate.diff, applies_cleanly=True,
            syntax='pass', validation='not_run', origin='interactive'), syntax='pass', failures=(record,),
            test_command=record.command)
    # Use the real recovery helper; it validates the same candidate one time.
    with patch.object(interact, 'validate_candidate', side_effect=unrunnable), \
         patch('swe_repair.prefix.validate_candidate', side_effect=unrunnable) as recovery:
        result = interact.run_interactive('bug', client=client, container=box, state=observed)
    assert result.ended_by.startswith('EnvironmentFailure:') and len(client.requests) == 1
    assert recovery.call_count == 1
    assert observed.failures.environment_failure_after_recovery() is not None
    assert result.final_diff == DIFF


def test_interactive_successful_environment_recovery_uses_updated_candidate_and_continues():
    from dataclasses import replace
    observed, box = state(), Box()
    client = Client([reply([tool('apply_patch', {'diff': DIFF})]), reply([tool('finish')])])
    command = 'python -m pytest tests/test_x.py'
    def initial(container, candidate, *args):
        record = replace(FailureRecord.from_output(command, 1, stage='env', stdout='No module named pytest'),
                         candidate_index=candidate.index)
        return ValidationResult(Candidate.build(candidate.index, candidate.diff, applies_cleanly=True,
            syntax='pass', validation='not_run', origin='interactive'), syntax='pass', failures=(record,), test_command=command)
    def restored(container, candidate, *args):
        return ValidationResult(Candidate.build(candidate.index, candidate.diff, applies_cleanly=True,
            syntax='pass', validation='fail', origin='interactive'), syntax='pass', checks_run=1, test_command=command)
    with patch.object(interact, 'validate_candidate', side_effect=initial), \
         patch('swe_repair.prefix.validate_candidate', side_effect=restored) as recovery:
        result = interact.run_interactive('bug', client=client, container=box, state=observed,
            budget=interact.InteractionBudget(model_calls=3))
    assert result.ended_by == 'finish_tool' and len(client.requests) == 2
    assert recovery.call_count == 1 and observed.failures.environment_failure() is None
    assert observed.patches.candidates[0].validation == 'fail'
    assert 'public=fail' in result.trace[0]['observation'] and 'recovery completed' in result.trace[0]['observation']
