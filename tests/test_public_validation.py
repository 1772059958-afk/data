"""Actual command status survives public validation; no Docker is involved."""
from swe_repair.prefix import (Container, EnvironmentFailure, run_public_tests,
                               syntax_check, validate_candidate, recover_environment, ValidationResult)
from swe_repair.state import Candidate, RepairState, TaskManifest, FailureRecord
from dataclasses import replace
from unittest.mock import patch

DIFF = '--- a/pkg/mod.py\n+++ b/pkg/mod.py\n@@ -1 +1 @@\n-a=1\n+a=2\n'


class Box:
    def __init__(self, code=0, output='all passed\n__rc=0', syntax='__rc=0'):
        self.code, self.output, self.syntax = code, output, syntax
        self.commands, self.reverted = [], 0
    def bash(self, command, timeout=300):
        self.commands.append(command)
        if 'py_compile' in command: return 0, self.syntax
        if 'python -m pytest' in command: return self.code, self.output
        return 0, 'tests/test_mod.py\n__rc=0'
    def revert(self): self.reverted += 1
    def apply(self, diff): return True, ''


def test_collection_timeout_and_missing_tests_keep_real_status():
    cases = [(0, 'collection error\n__rc=2', 2, 'collection_error'),
             (0, 'no tests ran\n__rc=5', 5, 'missing_tests'),
             (137, '', 137, 'timeout'), (0, 'timeout\n__rc=124', 124, 'timeout')]
    for outer, output, expected, category in cases:
        result = run_public_tests(Box(outer, output), ['tests/test_mod.py'])
        assert result.status == 'not_run' and result.exit_code == expected
        assert result.category == category and 'pytest' in result.command


def test_validator_does_not_relabel_collection_or_timeout_as_exit_one():
    for output, code, error_class in [('collect failed\n__rc=2', 0, 'test_collection'), ('', 137, 'timeout')]:
        box = Box(code, output)
        result = validate_candidate(box, Candidate.build(0, DIFF))
        assert result.failures[0].exit_code == (2 if output else 137)
        assert result.failures[0].error_class == error_class
        assert result.test_exit_code == result.failures[0].exit_code
        assert result.candidate.validation == 'not_run' and box.reverted == 2


def test_import_failure_and_missing_runner_are_distinct():
    imported = validate_candidate(Box(0, 'ImportError: cannot import name x\n__rc=2'), Candidate.build(0, DIFF))
    missing = validate_candidate(Box(0, 'No module named pytest\n__rc=1'), Candidate.build(0, DIFF))
    assert imported.failures[0].error_class == 'syntax_or_import'
    assert missing.failures[0].error_class == 'env_setup'
    assert missing.test_category == 'missing_runner'


def test_syntax_timeout_keeps_status_and_candidate_is_not_selectable():
    result = validate_candidate(Box(syntax='killed\n__rc=137'), Candidate.build(0, DIFF))
    assert result.syntax_exit_code == 137 and result.candidate.syntax == 'fail'
    assert result.failures[0].exit_code == 137 and result.failures[0].error_class == 'timeout'


def test_reset_failures_are_not_hidden_as_success():
    box = Box(1, 'reset failed')
    box.workdir = '/testbed'
    box.bash = lambda *args, **kwargs: (1, 'checkout failed')
    try: Container.revert(box)
    except EnvironmentFailure: pass
    else: raise AssertionError('broken baseline reset was accepted')


def test_public_result_preserves_legacy_display_unpacking():
    result = run_public_tests(Box(), ['tests/test_mod.py'])
    status, detail, raw = result
    assert status == 'pass' and detail == raw == 'all passed'
    syntax, detail = syntax_check(Box(), ['pkg/mod.py'])
    assert syntax == 'pass'


def test_recovery_retries_original_environment_candidate_not_latest_syntax_error():
    state = RepairState(TaskManifest('demo', 'demo/repo', 'base', 'v', 'h'))
    original = Candidate.build(0, DIFF, applies_cleanly=True, syntax='pass', validation='not_run')
    latest = Candidate.build(1, DIFF.replace('+a=2', '+broken('), applies_cleanly=True, syntax='fail', validation='fail')
    state.patches.candidates = [original, latest]
    env = replace(FailureRecord.from_output('python -m pytest tests/test_mod.py -q', 1, stage='env'), candidate_index=0)
    state.failures.add(env)
    state.failures.add(FailureRecord.from_output('py_compile', 1, stage='syntax_check', stdout='SyntaxError'))
    seen = []
    def retry(box, candidate, symbols):
        seen.append(candidate.index)
        return ValidationResult(replace(candidate, validation='fail'), checks_run=1, test_command=env.command, test_exit_code=1)
    with patch('swe_repair.prefix.validate_candidate', side_effect=retry):
        assert recover_environment(Box(), state) is True
    assert seen == [0] and state.patches.candidates[1] is latest
    assert state.failures.environment_failure() is None


def test_recovery_requires_same_runnable_public_command_and_is_not_repeated():
    for runnable, command in [(0, 'python -m pytest tests/test_mod.py'), (1, 'different test command')]:
        state = RepairState(TaskManifest('demo', 'demo/repo', 'base', 'v', 'h'))
        candidate = Candidate.build(0, DIFF)
        state.patches.add(candidate)
        state.failures.add(replace(FailureRecord.from_output('python -m pytest tests/test_mod.py', 1, stage='env'), candidate_index=0))
        with patch('swe_repair.prefix.validate_candidate', return_value=ValidationResult(candidate, checks_run=runnable, test_command=command)) as retry:
            assert recover_environment(Box(), state) is False
            assert recover_environment(Box(), state) is False
            assert retry.call_count == 1
        assert state.failures.environment_failure_after_recovery() is not None
