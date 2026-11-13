"""Verdicts require frozen artifact identity; all harness invocations are fake."""
from __future__ import annotations

import copy
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from swe_repair.evaluation import (build_provenance, frozen_predictions, prediction_manifest,
                                   sidecar_path, validate_artifact_files, validate_provenance)

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


analysis = load('identity_analysis', 'scripts/analyse_cf.py')
scoring = load('identity_scoring', 'scripts/score_run.py')
runner = load('identity_generation_runner', 'scripts/run_cf.py')


def fixture():
    diff = '--- a/pkg/a.py\n+++ b/pkg/a.py\n@@ -1 +1 @@\n-old\n+new\n'
    matrix = {'tag': 'identity_dev', 'config_hash': 'synthetic_config', 'mode': 'formal', 'arm': 'D',
              'split': 'dev', 'seed': 42, 'repeat_index': 0, 'designated_instances': ['synthetic__repo-1'],
              'cases': [{'instance_id': 'synthetic__repo-1', 'mode': 'formal', 'arm': 'D',
                         'selected_route': 'fixed', 'submitted_patch': diff, 'policy_cost_cny': .3,
                         'stages': {'prefix': {'cost_cny': .1}, 'fixed': {'cost_cny': .2, 'status': 'completed',
                                    'budget': {'consumed': {'token': 100, 'model_call': 2, 'tool_call': 3, 'wallclock_seconds': 4}}}}}]}
    report = {'resolved_ids': ['synthetic__repo-1']}
    predictions = (json.dumps({'instance_id': 'synthetic__repo-1', 'model_name_or_path': 'identity_dev-D',
                               'model_patch': diff}) + '\n').encode()
    binding = build_provenance(matrix, 'D', predictions, report,
                               matrix_bytes=json.dumps(matrix).encode(), report_bytes=json.dumps(report).encode())
    return matrix, report, predictions, binding


def rejected(call):
    try:
        call()
    except (ValueError, FileExistsError, FileNotFoundError):
        return
    raise AssertionError('mismatched evaluation artifacts were accepted')


def test_unbound_foreign_report_cannot_be_used_even_by_in_memory_analysis():
    matrix, report, _, _ = fixture()
    report.update(run_id='OTHER_RUN', config_hash='OTHER_CONFIG', predictions_sha256='other')
    rejected(lambda: analysis.analyze(matrix, {'D': report}))


def test_valid_binding_preserves_run_and_policy_resource_identity():
    matrix, report, _, binding = fixture()
    result = analysis.analyze(matrix, {'D': report}, {'D': binding})
    row = result['records'][0]
    assert row['status'] == 'resolved' and row['seed'] == 42
    assert row['run_id'] == 'identity_dev'
    assert row['prediction_sha256'] == binding['predictions_sha256']
    assert row['patch_sha256'] == binding['prediction_patch_sha256'][row['instance_id']]
    assert row['resources'] == {'token': 100, 'model_call': 2, 'tool_call': 3, 'wallclock_seconds': 4}
    assert all(row['resources_complete'].values())


def test_binding_rejects_changed_verdict_run_arm_seed_split_config_and_patch():
    matrix, report, _, binding = fixture()
    for field, value in [('tag', 'other'), ('split', 'test'), ('seed', 9), ('repeat_index', 2), ('config_hash', 'other')]:
        modified = copy.deepcopy(matrix)
        modified[field] = value
        rejected(lambda: validate_provenance(modified, 'D', report, binding))
    rejected(lambda: validate_provenance(matrix, 'C', report, binding))
    rejected(lambda: validate_provenance(matrix, 'D', {'unresolved_ids': ['synthetic__repo-1']}, binding))
    modified = copy.deepcopy(matrix)
    modified['cases'][0]['submitted_patch'] += '# different\n'
    rejected(lambda: validate_provenance(modified, 'D', report, binding))


def test_self_consistent_sidecar_still_rejects_contradictory_report_claims():
    matrix, report, predictions, _ = fixture()
    for field, value in [('run_id', 'other'), ('split', 'test'), ('arm', 'C'), ('seed', 1),
                         ('model_name_or_path', 'other'), ('predictions_sha256', '0' * 64)]:
        modified = dict(report, **{field: value})
        rejected(lambda: build_provenance(matrix, 'D', predictions, modified,
                                         matrix_bytes=json.dumps(matrix).encode(), report_bytes=json.dumps(modified).encode()))


def test_prediction_rows_must_match_frozen_patches_and_labels():
    matrix, _, predictions, _ = fixture()
    row = json.loads(predictions)
    for changes in ({'model_patch': 'different'}, {'model_name_or_path': 'OTHER-D'}, {'instance_id': 'other'}):
        modified = (json.dumps(dict(row, **changes)) + '\n').encode()
        rejected(lambda: prediction_manifest(matrix, 'D', modified))
    rejected(lambda: prediction_manifest(matrix, 'D', predictions + predictions))


def test_report_cannot_supply_verdict_for_instance_not_in_submitted_patches():
    matrix, report, predictions, _ = fixture()
    report['resolved_ids'].append('not_submitted')
    rejected(lambda: build_provenance(matrix, 'D', predictions, report,
                                     matrix_bytes=json.dumps(matrix).encode(), report_bytes=json.dumps(report).encode()))


def materialize(directory):
    matrix, report, predictions, binding = fixture()
    (directory / 'matrix.json').write_text(json.dumps(matrix), encoding='utf-8')
    (directory / 'predictions_D.jsonl').write_bytes(predictions)
    return matrix, report, binding


def test_file_verification_detects_prediction_bytes_and_matrix_whitespace_tampering():
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        matrix, report, binding = materialize(directory)
        report_path = directory / 'report.json'
        report_path.write_text(json.dumps(report), encoding='utf-8')
        validate_artifact_files(directory / 'matrix.json', report_path, 'D', binding)
        original = (directory / 'predictions_D.jsonl').read_bytes()
        (directory / 'predictions_D.jsonl').write_bytes(original + b'\n')
        rejected(lambda: validate_artifact_files(directory / 'matrix.json', report_path, 'D', binding))
        (directory / 'predictions_D.jsonl').write_bytes(original)
        (directory / 'matrix.json').write_text(json.dumps(matrix, indent=2), encoding='utf-8')
        rejected(lambda: validate_artifact_files(directory / 'matrix.json', report_path, 'D', binding))


def test_scoring_freezes_inputs_before_fake_harness_and_refuses_existing_scoring():
    with tempfile.TemporaryDirectory(prefix='scoring_identity_', dir=ROOT / 'runs') as tmp:
        directory = Path(tmp)
        matrix, report, _ = materialize(directory)
        seen = []
        def fake(command, **kwargs):
            seen.append(command)
            output = Path(command[command.index('--report_dir') + 1])
            assert (output / 'input_manifest.json').exists()
            (output / 'identity_dev-D.identity_dev.json').write_text(json.dumps(report), encoding='utf-8')
            return SimpleNamespace(returncode=0)
        reports = scoring.execute_scoring(directory, runner=fake)
        assert len(seen) == len(reports) == 1
        report_path = Path(reports[0])
        binding = json.loads(sidecar_path(report_path).read_text(encoding='utf-8'))
        validate_artifact_files(directory / 'matrix.json', report_path, 'D', binding)
        rejected(lambda: scoring.execute_scoring(directory, runner=fake))
        assert len(seen) == 1


def test_failed_harness_never_gets_a_success_sidecar():
    with tempfile.TemporaryDirectory(prefix='scoring_identity_', dir=ROOT / 'runs') as tmp:
        directory = Path(tmp)
        materialize(directory)
        try:
            scoring.execute_scoring(directory, runner=lambda *a, **kw: SimpleNamespace(returncode=1))
        except RuntimeError:
            pass
        else:
            raise AssertionError('failed harness was accepted')
        assert not list((directory / 'scoring').rglob('*.provenance.json'))


def test_scoring_default_cli_only_plans_without_dispatch_or_output_directory():
    with tempfile.TemporaryDirectory(prefix='scoring_identity_', dir=ROOT / 'runs') as tmp:
        directory = Path(tmp)
        materialize(directory)
        output = io.StringIO()
        with patch.object(scoring, 'execute_scoring', side_effect=AssertionError('default cannot execute')), \
             patch.object(scoring.subprocess, 'run', side_effect=AssertionError('default cannot dispatch')), \
             contextlib.redirect_stdout(output):
            assert scoring.main([str(directory)]) == 0
        plan = json.loads(output.getvalue())
        assert plan['execute'] is False and plan['model_calls'] == 0
        assert len(plan['jobs']) == 1
        assert not (directory / 'scoring').exists()


def test_frozen_prediction_recovery_matches_runner_for_partial_and_failed_cases():
    matrix, _, _, _ = fixture()
    for mode in ('formal', 'diagnostic'):
        current = copy.deepcopy(matrix)
        current['mode'] = mode
        current['designated_instances'] = ['ok', 'start_error', 'prefix_error', 'shared_stop', 'branch_error', 'missing']
        cases = [
            {'instance_id': 'ok', 'mode': mode, 'arm': 'D', 'submitted_patch': 'selected',
             'decisions': {a: {'route': 'fixed' if a in ('A', 'D') else 'interactive'} for a in ('A', 'C', 'D', 'E')},
             'stages': {'prefix': {'patch': 'prior'}, 'fixed': {'patch': 'fixed'},
                        'interactive': {'patch': 'interactive'}, 'standalone': {'patch': 'solo'}}},
            {'instance_id': 'start_error', 'mode': mode, 'arm': 'D', 'submitted_patch': '',
             'status': 'environment_error', 'decisions': {}, 'stages': {}},
            {'instance_id': 'prefix_error', 'mode': mode, 'arm': 'D',
             'status': 'generation_error', 'decisions': {'A': {'route': 'fixed'}, 'D': {'route': 'fixed'},
                                                      'C': {'route': 'interactive'}},
             'stages': {'prefix': {'patch': 'prior'}}},
            {'instance_id': 'shared_stop', 'mode': mode, 'arm': 'D', 'submitted_patch': 'prior',
             'decisions': {a: {'route': 'stop'} for a in ('A', 'C', 'D', 'E')},
             'stages': {'prefix': {'patch': 'prior'}}},
            {'instance_id': 'branch_error', 'mode': mode, 'arm': 'D', 'submitted_patch': 'prior',
             'decisions': {a: {'route': 'fixed' if a in ('A', 'D') else 'interactive'} for a in ('A', 'C', 'D', 'E')},
             'stages': {'prefix': {'patch': 'prior'}, 'fixed': {'status': 'generation_error', 'patch': 'prior'}}},
        ]
        current['cases'] = cases
        for arm in ('A', 'B', 'C', 'D', 'E', 'FIXED', 'ESC'):
            actual = {case['instance_id']: rows[arm] for case in cases
                      if arm in (rows := runner.predictions(case, mode, 'D'))}
            assert frozen_predictions(current, arm) == actual
            if actual:
                payload = ('\n'.join(json.dumps({'instance_id': iid, 'model_name_or_path': current['tag'] + '-' + arm,
                                                  'model_patch': diff}) for iid, diff in actual.items()) + '\n').encode()
                prediction_manifest(current, arm, payload)


def test_duplicate_unpredicted_cases_are_rejected_before_scoring():
    matrix, _, _, _ = fixture()
    matrix['mode'] = 'diagnostic'
    case = {'instance_id': matrix['designated_instances'][0], 'stages': {}, 'decisions': {}}
    matrix['cases'] = [case, copy.deepcopy(case)]
    rejected(lambda: frozen_predictions(matrix, 'D'))


def test_failed_and_missing_cases_keep_primary_population_and_partial_resources():
    matrix, report, _, _ = fixture()
    failed_id, missing_id = 'synthetic__repo-2', 'synthetic__repo-3'
    matrix['designated_instances'] += [failed_id, missing_id]
    matrix['cases'].append({'instance_id': failed_id, 'mode': 'formal', 'arm': 'D', 'submitted_patch': '',
                            'status': 'generation_error', 'termination_reason': 'generation_error',
                            'decisions': {'D': {'route': 'fixed'}},
                            'stages': {'prefix': {'cost_cny': .1, 'status': 'generation_error',
                                                  'budget': {'consumed': {'token': 50, 'model_call': 1,
                                                                          'tool_call': 2, 'wallclock_seconds': 3}}}}})
    report['empty_patch_ids'] = [failed_id]
    predictions = ('\n'.join(json.dumps({'instance_id': iid, 'model_name_or_path': 'identity_dev-D',
                                          'model_patch': diff}) for iid, diff in frozen_predictions(matrix, 'D').items()) + '\n').encode()
    binding = build_provenance(matrix, 'D', predictions, report,
                               matrix_bytes=json.dumps(matrix).encode(), report_bytes=json.dumps(report).encode())
    result = analysis.analyze(matrix, {'D': report}, {'D': binding})
    summary = result['primary_summaries']['D']
    assert summary['total'] == 3 and summary['resolved'] == 1
    assert summary['status_counts'] == {'resolved': 1, 'empty_patch': 1, 'not_scored': 1}
    assert summary['resolved_rate'] is None and summary['resolved_rate_lower_bound'] == 1 / 3
    failed, missing = result['records'][1:]
    assert failed['cost_cny'] == .1 and failed['resources']['token'] == 50
    assert not any(failed['resources_complete'].values())
    assert failed['generation_status'] == 'generation_error'
    assert missing['status'] == 'not_scored' and missing['generation_status'] == 'missing_case'
    assert missing['resources']['model_call'] is None


def test_diagnostic_stop_reason_has_priority_over_unrelated_branch_error():
    expected = {'stop_env_failure': 'environment_error', 'stop_budget_insufficient': 'budget_exhausted',
                'early_stop_public_pass': 'completed'}
    for reason, status in expected.items():
        matrix, _, _, _ = fixture()
        matrix['mode'] = 'diagnostic'
        case = matrix['cases'][0]
        case.update(mode='diagnostic', status='generation_error', termination_reason='generation_error',
                    decisions={a: {'route': 'stop', 'reason': reason} for a in ('A', 'C', 'D', 'E')})
        case['stages'] = {'prefix': {'status': 'completed', 'termination_reason': 'completed', 'patch': '', 'cost_cny': .1},
                           'standalone': {'status': 'generation_error', 'termination_reason': 'unrelated_B_error',
                                          'patch': '', 'cost_cny': .1}}
        records = {row['arm']: row for row in analysis.analyze(matrix, {})['records']}
        for arm in ('A', 'C', 'D', 'E'):
            assert records[arm]['termination_reason'] == reason
            assert records[arm]['generation_status'] == status
        assert records['B']['termination_reason'] == 'unrelated_B_error'
        assert records['B']['generation_status'] == 'generation_error'


def test_scoring_to_analysis_cli_roundtrip_checks_source_bytes():
    with tempfile.TemporaryDirectory(prefix='scoring_identity_', dir=ROOT / 'runs') as tmp:
        directory = Path(tmp)
        _, report, _ = materialize(directory)
        def fake(command, **kwargs):
            output = Path(command[command.index('--report_dir') + 1])
            (output / 'identity_dev-D.identity_dev.json').write_text(json.dumps(report), encoding='utf-8')
            return SimpleNamespace(returncode=0)
        report_path = scoring.execute_scoring(directory, runner=fake)[0]
        argv = ['analyse_cf.py', '--matrix', str(directory / 'matrix.json'), '--report', 'D=' + report_path,
                '--out', str(directory / 'analysis.json'), '--records-out', str(directory / 'records.jsonl')]
        with patch('sys.argv', argv), contextlib.redirect_stdout(io.StringIO()):
            assert analysis.main() == 0
        saved = json.loads((directory / 'analysis.json').read_text(encoding='utf-8'))
        assert saved['primary_summaries']['D']['resolved_rate'] == 1
        assert saved['source_reports'][0]['provenance_sha256']
        prediction_path = directory / 'predictions_D.jsonl'
        prediction_path.write_bytes(prediction_path.read_bytes() + b'\n')
        argv[argv.index('--out') + 1] = str(directory / 'tampered_analysis.json')
        with patch('sys.argv', argv), contextlib.redirect_stderr(io.StringIO()):
            try:
                analysis.main()
            except SystemExit as exc:
                assert exc.code == 2
            else:
                raise AssertionError('CLI trusted predictions changed after scoring')
        assert not (directory / 'tampered_analysis.json').exists()


def test_all_eligible_prefixes_remain_available_when_one_pair_has_no_verdict():
    matrix, report, predictions, binding = fixture()
    matrix.update(mode='diagnostic', cases=[], designated_instances=['synthetic__repo-1', 'synthetic__repo-2'])
    for iid in matrix['designated_instances']:
        matrix['cases'].append({'instance_id': iid, 'paired_eligible': True,
                                'prefix_snapshot': {'task_manifest': {'instance_id': iid}},
                                'stages': {'prefix': {'status': 'completed'}}, 'decisions': {}})
    result = analysis.analyze(matrix, {})
    assert result['eligible_population_complete'] is True
    assert result['paired_eligible'] == 2 and result['paired_complete'] == 0
    assert len(result['eligible_prefixes']) == 2 and result['observations'] == []
    assert result['eligible_instance_ids'] == matrix['designated_instances']
    matrix['cases'].pop()
    result = analysis.analyze(matrix, {})
    assert not result['eligible_population_complete']
    assert result['prefix_unavailable_instance_ids'] == ['synthetic__repo-2']


def test_unrelated_unknown_diagnostic_branch_does_not_taint_selected_policy_cost():
    matrix, _, _, _ = fixture()
    case = matrix['cases'][0]
    case['stages']['standalone'] = {'cost_cny': 1, 'calls': [{'billing': 'unknown'}]}
    row = analysis.analyze(matrix, {})['records'][0]
    assert row['cost_complete'] and row['resources_complete']['token']
    case['stages']['fixed']['calls'] = [{'billing': 'unknown'}]
    row = analysis.analyze(matrix, {})['records'][0]
    assert not row['cost_complete'] and not row['resources_complete']['token']
    assert row['resources_complete']['model_call']
