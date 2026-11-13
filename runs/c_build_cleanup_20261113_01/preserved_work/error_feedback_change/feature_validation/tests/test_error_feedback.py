"""Public error handoff and bounded log retrieval, using no live services."""
import json
import re
from dataclasses import replace
from types import SimpleNamespace as NS
from unittest.mock import patch

from swe_repair import interact
from swe_repair.experiment import clone_prefix, seed_messages
from swe_repair.feedback import (error_evidence, failure_feedback, log_reference,
                                 read_failure_log, PAGE_LIMIT)
from swe_repair.llm import ChatResult
from swe_repair.prefix import PrefixResult, ValidationResult, validate_candidate
from swe_repair.state import Candidate, FailureRecord, RepairState, TaskManifest

DIFF = '--- a/pkg/x.py\n+++ b/pkg/x.py\n@@ -1 +1 @@\n-x=1\n+x=2\n'
RAW = ('setup noise\n' * 900 + '  File "/testbed/pkg/x.py", line 237, in compute\n'
       '    assert actual == expected\nE       assert 4 == 5\nAssertionError: wrong boundary\n')


def new_state():
    return RepairState(TaskManifest('example__repo-1', 'example/repo', 'base', 'v1', 'config'))


def tool(name, args=None):
    calls = [{'id': name, 'function': {'name': name, 'arguments': json.dumps(args or {})}}]
    record = NS(cost_cny=0, prompt_tokens=10, output_tokens=5, finish_reason='stop')
    return ChatResult(record, {'role': 'assistant', 'content': '', 'tool_calls': calls}, '', '', calls)


class Client:
    def __init__(self, replies): self.replies, self.requests = iter(replies), []
    def chat(self, messages, **kwargs):
        self.requests.append(list(messages))
        return next(self.replies)


class Box:
    def __init__(self): self.commands, self.applied = [], []
    def revert(self): pass
    def close(self): pass
    def apply(self, diff): self.applied.append(diff); return True, ''
    def bash(self, command, timeout=300):
        self.commands.append(command)
        return 0, ''


def test_evidence_keeps_buried_assertions_and_exact_frame_lines_within_bound():
    raw = RAW + 'trailing noise\n' * 900
    evidence = error_evidence(raw)
    assert len(evidence) <= 2400
    assert 'AssertionError: wrong boundary' in evidence
    assert 'assert 4 == 5' in evidence
    assert '/testbed/pkg/x.py' in evidence and 'line 237' in evidence
    assert 'L901:' in evidence


def test_long_exception_line_keeps_both_exception_type_and_terminal_value():
    evidence = error_evidence('ValueError: ' + 'x' * 20000 + ' UNIQUE_END')
    assert 'ValueError:' in evidence and 'UNIQUE_END' in evidence and len(evidence) <= 2400


def test_failure_snapshot_preserves_raw_bytes_and_recovery_but_prompt_excludes_noise():
    state = new_state()
    record = FailureRecord.from_output('pytest tests/test_x.py', 1, stage='test', stdout=RAW)
    state.failures.add(record)
    state.failures.tool_records.append(record.with_recovery())
    restored = RepairState.from_dict(json.loads(state.to_json()))
    assert restored.failures.records[0].raw_output == RAW
    assert restored.failures.tool_records[0].raw_output == RAW
    assert restored.failures.tool_records[0].recovery_attempts == 1
    view = record.prompt_view()
    assert 'raw_output' not in view and view['log_ref'] == log_reference(RAW)
    assert 'AssertionError: wrong boundary' in view['evidence']
    assert len(failure_feedback(record)) <= 3000


def test_legacy_failure_explicitly_has_no_fabricated_raw_log():
    record = FailureRecord.from_output('pytest', 1, stage='test', stdout='AssertionError: old')
    payload = record.to_dict()
    payload.pop('raw_output')
    restored = FailureRecord.from_dict(payload)
    assert restored.prompt_view()['raw_available'] is False
    assert restored.prompt_view()['log_ref'] is None
    assert 'unavailable' in failure_feedback(restored)


def test_prefix_seed_uses_key_error_evidence_without_full_log_and_branches_stay_isolated():
    state = new_state()
    state.failures.add(FailureRecord.from_output('pytest', 1, stage='test', stdout=RAW))
    prefix = PrefixResult(state, 'base', (), (), context_text='public source')
    fixed, interactive = clone_prefix(prefix), clone_prefix(prefix)
    fixed.state.failures.add(FailureRecord.from_output('pytest', 1, stage='test', stdout='FIXED_ONLY'))
    message = seed_messages('bug', interactive)[1]['content']
    assert 'wrong boundary' in message and 'line 237' in message
    assert log_reference(RAW) in message and RAW not in message and 'FIXED_ONLY' not in message
    assert read_failure_log(interactive.state.failures.records, log_reference('FIXED_ONLY'), 1, 1)[1] is False


def test_log_ranges_are_exact_and_unknown_or_path_like_ids_never_execute_shell():
    raw = 'first\r\nsecond\nthird'
    record = FailureRecord.from_output('public check', 1, stage='test', stdout=raw)
    page, ok = read_failure_log([record], log_reference(raw), 1, 2)
    assert ok and 'first\r\nsecond\n' in page and 'start=3' in page
    for reference in ('log:../../.env', '/tmp/result.json', 'log:' + '0' * 64):
        assert read_failure_log([record], reference, 1, 2)[1] is False
    box = Box()
    assert interact.execute_tool(box, 'read_region', {'path': log_reference(raw), 'start': 1, 'end': 2})[1] is False
    assert not box.commands


def test_oversized_single_line_can_be_fully_read_with_bounded_cursor_pages():
    raw = 'A' * 10000 + '\nfinal\n'
    record = FailureRecord.from_output('public check', 1, stage='test', stdout=raw)
    start, offset, recovered = 1, 0, ''
    for _ in range(12):
        page, ok = read_failure_log([record], log_reference(raw), start, 2, offset)
        assert ok and len(page) <= PAGE_LIMIT
        body = page.split('\n', 1)[1]
        if '\nNext:' in body:
            chunk, cursor = body.rsplit('\nNext:', 1)
            recovered += chunk
            start, offset = map(int, re.search(r'start=(\d+) end=\d+ offset=(\d+)', cursor).groups())
        else:
            recovered += body.rsplit('\nEnd of captured log.', 1)[0]
            break
    assert recovered == raw


def test_bad_log_ranges_and_offset_cannot_escape_validation():
    reference = log_reference('public')
    for start, end, offset in ((0, 1, 0), (2, 1, 0), (1, 1, -1), (1, 1, 99), (True, 1, 0)):
        record = FailureRecord.from_output('check', 1, stage='test', stdout='public')
        assert not read_failure_log([record], reference, start, end, offset)[1]
    if hasattr(interact, 'validate_tool_arguments'):
        for args in ({'path': reference, 'start': 2, 'end': 1},
                     {'path': reference, 'start': 1, 'end': 1, 'offset': -1},
                     {'path': 'pkg/x.py', 'start': 1, 'end': 1, 'offset': 1}):
            assert interact.validate_tool_arguments('read_region', args)[1]


def test_apply_error_reaches_next_model_request_and_log_reads_consume_named_tools():
    state, box = new_state(), Box()
    client = Client([tool('apply_patch', {'diff': DIFF}),
                     tool('read_region', {'path': log_reference(RAW), 'start': 901, 'end': 904}),
                     tool('finish')])
    def validate(container, candidate, *args):
        failure = FailureRecord.from_output('pytest tests/test_x.py', 1, stage='test', stdout=RAW)
        return ValidationResult(replace(candidate, applies_cleanly=True, syntax='pass', validation='fail'),
                                syntax='pass', failures=(failure,), raw_output=RAW)
    with patch.object(interact, 'validate_candidate', side_effect=validate):
        result = interact.run_interactive('bug', client=client, container=box, state=state,
            budget=interact.InteractionBudget(model_calls=4, tool_calls=3))
    assert result.ended_by == 'finish_tool' and result.calls == 3 and result.tool_calls == 3
    assert not box.commands
    feedback = client.requests[1][-1]['content']
    assert 'wrong boundary' in feedback and 'line 237' in feedback and log_reference(RAW) in feedback
    assert 'assert actual == expected' in client.requests[2][-1]['content']


def test_log_read_cannot_bypass_named_tool_limit_or_reveal_another_branch_log():
    state, box = new_state(), Box()
    state.failures.add(FailureRecord.from_output('check', 1, stage='test', stdout='own log'))
    client = Client([tool('read_region', {'path': log_reference('other branch'), 'start': 1, 'end': 1}),
                     tool('finish')])
    result = interact.run_interactive('bug', client=client, container=box, state=state,
        budget=interact.InteractionBudget(model_calls=3, tool_calls=1))
    assert result.tool_calls == 1 and not box.commands
    assert 'not available in this branch' in result.trace[0]['observation']
    assert result.ended_by == 'tool_budget'


def test_additional_public_check_keeps_raw_log_separate_from_router_failures():
    state, box = new_state(), Box()
    state.patches.add(Candidate.build(0, DIFF, applies_cleanly=True, syntax='pass', validation='fail'))
    client = Client([tool('run_test', {'path': 'tests/test_x.py'}),
                     tool('read_region', {'path': log_reference(RAW), 'start': 901, 'end': 904}),
                     tool('finish')])
    with patch.object(interact, 'run_public_tests', return_value=('fail', '1 failed', RAW)):
        result = interact.run_interactive('bug', client=client, container=box, state=state,
            budget=interact.InteractionBudget(model_calls=4))
    assert result.ended_by == 'finish_tool'
    assert not state.failures.records and state.failures.tool_records[0].raw_output == RAW
    assert 'wrong boundary' in client.requests[1][-1]['content']
    assert 'line 237' in client.requests[2][-1]['content']


def test_real_apply_and_syntax_failure_capture_complete_output_for_log_access():
    class Invalid(Box):
        def apply(self, diff): return False, RAW
    result = validate_candidate(Invalid(), Candidate.build(0, DIFF))
    assert result.failures[0].raw_output == RAW
    class Syntax(Box):
        def bash(self, script, timeout=300): return 0, RAW + '__rc=1'
    result = validate_candidate(Syntax(), Candidate.build(0, DIFF))
    assert 'wrong boundary' in result.failures[0].raw_output
    assert 'line 237' in result.failures[0].prompt_view()['evidence']
