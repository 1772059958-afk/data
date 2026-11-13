"""The explicit test20 single-run design changes repetition, not safety gates."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('single_run_runner', ROOT / 'scripts/run_cf.py')
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)
CONFIG = ROOT / 'configs/test20_single_20261111.json'
SAMPLE = ROOT / 'runs/test20_preparation_20261111/instances.json'


def config():
    return json.loads(CONFIG.read_text(encoding='utf-8'))


def arguments(*extra):
    return RUNNER.parser().parse_args([
        '--config', str(CONFIG), '--mode', 'formal', '--split', 'test',
        '--instances-file', str(SAMPLE), '--seed', '20261111', '--repeat-index', '0',
        '--tag', 'synthetic_test20_plan', *extra])


def test_single_run_registration_changes_only_repeat_requirement():
    raw = config()
    before = copy.deepcopy(raw)
    assert RUNNER.single_run_design_errors(raw) == []
    errors = RUNNER.frozen_config_errors(raw)
    assert not any('three repeats' in message for message in errors)
    assert all(any(section in message for message in errors) for section in
               ('overall', 'model.calibration', 'prefix.calibration', 'router.calibration',
                'fixed_continuation.calibration', 'candidate_selection.frozen',
                'evaluation.frozen', 'model version', 'thresholds'))
    assert raw == before and raw['execution']['live_authorized'] is False


def test_single_repeat_without_explicit_registration_is_rejected():
    raw = config()
    del raw['evaluation']['design']
    assert 'formal evaluation requires at least three repeats' in RUNNER.frozen_config_errors(raw)


def test_single_run_offline_plan_has_exact_twenty_and_no_execution():
    _, plan = RUNNER.load_plan(arguments('--dry-run'))
    assert len(plan['designated_instances']) == 20
    assert plan['mode'] == 'formal' and plan['split'] == 'test'
    assert plan['seed'] == 20261111 and plan['repeat_index'] == 0
    assert plan['execute'] is False and plan['live_authorized'] is False


def test_single_run_cannot_expand_seed_repeat_population_or_mode():
    for extra in (('--seed', '1'), ('--repeat-index', '1'), ('--mode', 'diagnostic'),
                  ('--split', 'dev'), ('--instances-file', str(ROOT / 'data/frozen/instances_test.txt'))):
        try:
            RUNNER.load_plan(arguments(*extra))
        except ValueError:
            pass
        else:
            raise AssertionError('single-run registered scope was expanded')


def test_single_run_execute_remains_blocked_by_authorization():
    try:
        RUNNER.load_plan(arguments('--execute', '--allow-paid'))
    except ValueError as exc:
        assert 'paid execution disabled' in str(exc)
    else:
        raise AssertionError('pending single-run configuration executed')


def test_single_run_manifest_and_statistics_tampering_is_rejected():
    for key, value in [('sample_manifest_sha256', '0' * 64),
                       ('preregistration_sha256', '0' * 64), ('inference', True),
                       ('repeats', True), ('statistics', 'bootstrap')]:
        raw = config()
        raw['evaluation'][key] = value
        assert RUNNER.single_run_design_errors(raw)


def test_single_run_scope_cannot_omit_restrictions():
    for key, value in [('allowed_modes', ['formal', 'diagnostic']),
                       ('allowed_splits', ['test', 'dev']), ('max_instances', 300),
                       ('allowed_instances', config()['execution']['allowed_instances'][:-1])]:
        raw = config()
        raw['execution'][key] = value
        assert RUNNER.single_run_design_errors(raw)


def test_single_run_changed_registration_is_rejected_even_with_new_hash():
    raw = config()
    path = ROOT / raw['evaluation']['preregistration']
    registration = json.loads(path.read_text(encoding='utf-8'))
    registration['arms'] = ['A', 'D']
    with tempfile.TemporaryDirectory(dir=ROOT / 'runs') as tmp:
        changed = Path(tmp) / 'registration.json'
        changed.write_text(json.dumps(registration), encoding='utf-8')
        raw['evaluation']['preregistration'] = str(changed)
        raw['evaluation']['preregistration_sha256'] = hashlib.sha256(changed.read_bytes()).hexdigest()
        assert RUNNER.single_run_design_errors(raw)
