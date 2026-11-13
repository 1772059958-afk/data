"""Extract public operational evidence from corrected DEV screens, entirely offline.

This reads generation matrices only. It does not consume official verdicts,
choose router thresholds, call models, or execute containers.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))
from swe_repair.router import RouterConfig

ASPECTS = ('token', 'model_call', 'tool_call', 'wallclock_seconds')
OLD_TAG = 'dev_screen_baseline_20261111_01'
OLD_PYVISTA_IMAGE = 'sha256:c3d02ef66da989070d532ea6993104f9d4b76e3d5f86fea85d7e4da1fba2e230'
NORMAL_REASONS = {'', 'finish_tool', 'patch_in_text', 'public_pass', 'fixed_step_limit',
                  'model_call_budget', 'tool_budget', 'wallclock', 'stagnation', 'budget_exhausted'}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def read(path):
    path = Path(path).resolve()
    if not path.is_relative_to(ROOT / 'runs'):
        raise ValueError('inputs must be project run artifacts')
    contents = path.read_bytes()
    value = json.loads(contents)
    if not isinstance(value, dict):
        raise ValueError('expected a JSON object')
    return value, {'path': str(path), 'sha256': hashlib.sha256(contents).hexdigest()}


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def legal(candidate):
    return (candidate.get('applies_cleanly') is True and candidate.get('syntax') == 'pass'
            and candidate.get('scope_valid') is True
            and isinstance(candidate.get('diff'), str) and bool(candidate['diff'].strip()))


def candidates(stage):
    return stage.get('state', {}).get('patch_history', {}).get('candidates', [])


def active_budget(config):
    return next(row for row in config['budget_tiers'] if row['tier'] == config['active_tier'])


def comparison_config(config):
    """Only the two prospective parameter variations and descriptive note differ."""
    value = deepcopy(config)
    value.pop('note', None)  # Annotation, not an execution parameter.
    value['prefix'].pop('prefix_fraction', None)
    value['interaction'].pop('model_calls', None)
    return value


def validate_matrix(matrix, ids, protocol, baseline=None):
    if matrix.get('tag') == OLD_TAG or matrix.get('historical') is not False:
        raise ValueError('the original failed-environment screen is audit-only and excluded')
    for key, expected in {'mode': 'diagnostic', 'split': 'dev', 'seed': 20261111,
                          'repeat_index': 0, 'calibration': True, 'execute': True}.items():
        if matrix.get(key) != expected or type(matrix.get(key)) is not type(expected):
            raise ValueError('screen identity mismatch: ' + key)
    if matrix.get('designated_instances') != ids:
        raise ValueError('screen must designate the same complete ordered three-case selection')
    config = matrix['effective_config']
    if RouterConfig.from_config(config).digest != matrix.get('config_hash'):
        raise ValueError('effective configuration hash differs from the recorded screen')
    provenance = config.get('provenance', {})
    if not re.fullmatch(r'[0-9a-f]{64}', provenance.get('code_sha256', '')):
        raise ValueError('a real source-code hash is required')
    model = config['model']
    if not all(isinstance(model.get(key), str) and model[key].strip()
               for key in ('model', 'model_version', 'system_fingerprint')):
        raise ValueError('actual requested/served alias and expected fingerprint must be recorded')
    images = config['execution'].get('images', {})
    if set(images) != set(ids) or any(not re.fullmatch(r'sha256:[0-9a-f]{64}', images[i]) for i in ids):
        raise ValueError('the three exact prepared image identities are required')
    if images['pyvista__pyvista-4315'] == OLD_PYVISTA_IMAGE:
        raise ValueError('the unrepaired PyVista image is excluded from corrected-screen selection')
    budget = active_budget(config)
    expected = protocol['baseline']
    for name in ASPECTS:
        if budget.get(name) != expected[name]:
            raise ValueError('base resource tier changed: ' + name)
    checks = [(model.get('max_tokens'), expected['max_output_tokens']),
              (model.get('thinking'), expected['thinking']), (model.get('effort'), expected['reasoning_effort']),
              (model.get('temperature'), expected['temperature']), (model.get('top_p'), expected['top_p']),
              (config['prefix'].get('n_candidates'), expected['prefix_candidates']),
              (config['fixed_continuation'].get('max_candidates'), expected['fixed_candidates']),
              (config['interaction'].get('tool_calls'), expected['interaction_tool_calls']),
              (config['interaction'].get('wallclock_seconds'), expected['interaction_seconds'])]
    if any(actual != wanted for actual, wanted in checks):
        raise ValueError('a non-variant execution parameter changed from the prospective screen')
    if config['prefix'].get('prefix_fraction') not in protocol['prefix_grid']:
        raise ValueError('prefix fraction lies outside the prospective grid')
    calls = config['interaction'].get('model_calls')
    if type(calls) is not int or calls not in (6, 10):
        raise ValueError('only the predeclared six/ten interaction-call settings are accepted')
    if baseline is None:
        if config['prefix']['prefix_fraction'] != .3 or calls != 6:
            raise ValueError('the corrected baseline must be prefix .30 and six interaction calls')
    elif comparison_config(config) != comparison_config(baseline['effective_config']):
        raise ValueError('variants changed more than prefix_fraction/interaction.model_calls')
    cases = matrix.get('cases', [])
    case_ids = [case.get('instance_id') for case in cases]
    if len(case_ids) != len(set(case_ids)) or set(case_ids) - set(ids):
        raise ValueError('duplicate or out-of-selection screen cases')
    for case in cases:
        if (case.get('seed') != 20261111 or case.get('repeat_index') != 0
                or case.get('config_hash') != matrix['config_hash']):
            raise ValueError('case identity differs from its matrix')
        if case.get('image_digest') not in (None, images[case['instance_id']]):
            raise ValueError('actual case image differs from the prepared image')


def stage_observation(stage, name, config, inherited=None):
    if not isinstance(stage, dict):
        return {'present': False, 'usable_with_legal_submission': False}
    calls = stage.get('calls', [])
    history = candidates(stage)
    pool = [item for item in history if legal(item)]
    novel = [item for item in history if item.get('origin') not in (None, 'prefix')]
    budget = stage.get('budget', {})
    ceiling, used = budget.get('ceiling', {}), budget.get('consumed', {})
    complete_budget = all(finite(ceiling.get(k)) and ceiling[k] > 0
                          and finite(used.get(k)) and used[k] >= 0 for k in ASPECTS)
    overruns = [k for k in ASPECTS if complete_budget and used[k] > ceiling[k] + 1e-8]
    overrun = budget.get('overrun') is True or bool(overruns)
    failures = stage.get('state', {}).get('failure_record', {}).get('records', [])
    env_errors = sum(item.get('error_class') == 'env_setup' for item in failures)
    reason = str(stage.get('termination_reason') or stage.get('ended_by') or '')
    normal_stop = reason in NORMAL_REASONS or reason.startswith(('ResourceLimit:', 'SpendLimitExceeded:'))
    status_ok = stage.get('status') in ('completed', 'budget_exhausted')
    identities = [row for row in calls if row.get('event') != 'failed_request']
    identities_ok = bool(identities) and all(
        row.get('served_model_reported') is True
        and row.get('served_model') == config['model']['model_version']
        and row.get('system_fingerprint') == config['model']['system_fingerprint'] for row in identities)
    failed_requests = sum(row.get('event') == 'failed_request' or row.get('usage_reported') is not True
                          or row.get('billing') == 'unknown' for row in calls)
    submitted_legal = bool(stage.get('patch', '').strip()) and any(
        stage['patch'] == item['diff'] for item in pool)
    submitted_public_pass = submitted_legal and any(stage['patch'] == item['diff']
                                                   and item.get('validation') == 'pass' for item in pool)
    prefix_trace = [item for item in stage.get('trace', []) if isinstance(item, dict)] if name == 'prefix' else []
    stops = [str(item.get('reason', '')) for item in prefix_trace if item.get('step') == 'prefix_stop']
    errors = [str(item.get('reason', '')) for item in prefix_trace if item.get('step') == 'prefix_error']
    consumed_before = (inherited or {}).get('budget_state', {}).get('consumed', {})
    inherited_count = consumed_before.get('model_call', 0) if name in ('fixed', 'interactive') else 0
    cumulative_calls = used.get('model_call')
    call_count_matches = finite(cumulative_calls) and cumulative_calls - inherited_count == len(calls)
    session = name in ('interactive', 'standalone')
    named_tools = stage.get('named_tool_calls') if session else None
    session_calls_overrun = session and len(calls) > config['interaction']['model_calls']
    session_tools_overrun = session and finite(named_tools) and named_tools > config['interaction']['tool_calls']
    prefix_limit_overrun = (name == 'prefix' and complete_budget
                            and used['token'] > ceiling['token'] * config['prefix']['prefix_fraction'] + 1e-8)
    overrun = overrun or session_calls_overrun or session_tools_overrun or prefix_limit_overrun
    expected_ceiling = active_budget(config)
    ceiling_matches = complete_budget and all(ceiling[k] == expected_ceiling[k] for k in ASPECTS)
    return {
        'present': True, 'status': stage.get('status'), 'termination_reason': reason,
        'actual_request_records': len(calls), 'request_events': sum(e.get('event') == 'model_request' for e in stage.get('events', [])),
        'cumulative_model_calls': cumulative_calls, 'request_count_matches_budget_delta': call_count_matches,
        'finish_reason_length': sum(row.get('finish_reason') == 'length' for row in calls),
        'failed_or_unknown_request_records': failed_requests, 'observed_identities_match': identities_ok,
        'named_tool_calls': named_tools, 'session_call_overrun': session_calls_overrun,
        'session_tool_overrun': bool(session_tools_overrun), 'prefix_token_allowance_overrun': bool(prefix_limit_overrun),
        'session_request_limit_reached': session and len(calls) >= config['interaction']['model_calls'],
        'global_request_limit_reached': complete_budget and used['model_call'] >= ceiling['model_call'],
        'candidate_count': len(history), 'legal_candidate_count': len(pool),
        'has_legal_candidate': bool(pool), 'has_legal_submitted_candidate': submitted_legal,
        'new_origin_candidate_count': len(novel), 'has_new_origin_candidate': bool(novel),
        'new_origin_legal_candidate_count': sum(legal(item) for item in novel),
        'public_pass_legal_candidate': any(item.get('validation') == 'pass' for item in pool),
        'submitted_legal_public_pass': submitted_public_pass,
        'candidate_origins': dict(Counter(str(item.get('origin')) for item in history)),
        'candidate_hashes': [item.get('hash') for item in history],
        'prefix_localization_completed': any(item.get('step') == 'localize' for item in prefix_trace),
        'prefix_candidate_attempts': [item['step'] for item in prefix_trace if re.fullmatch(r'candidate_\d+', str(item.get('step')))],
        'prefix_stop_reasons': stops, 'prefix_error_reasons': errors,
        'environment_error_records': env_errors, 'budget_complete': complete_budget,
        'budget_ceiling_matches_config': ceiling_matches,
        'budget_overrun': overrun, 'overrun_aspects': overruns, 'budget_consumed': used,
        'normal_budget_or_workflow_termination': normal_stop,
        'session_or_tool_hard_stop': reason if reason in ('model_call_budget', 'tool_budget', 'wallclock') or reason.startswith(('ResourceLimit:', 'SpendLimitExceeded:')) else None,
        'normal_budget_stop_with_legal_candidate': normal_stop and reason not in ('', 'finish_tool', 'public_pass', 'patch_in_text', 'stagnation') and submitted_legal and not overrun,
        'no_legal_candidate_at_stop': not submitted_legal,
        'usable_with_legal_submission': bool(status_ok and normal_stop and complete_budget and ceiling_matches and not overrun
            and not env_errors and not errors and identities_ok and not failed_requests
            and len(calls) >= 1 and call_count_matches and submitted_legal),
    }


def inherited_budget_checks(case):
    """Check recorded evidence only; do not reconstruct unrecorded initial states."""
    snapshot = case.get('prefix_snapshot')
    prefix = case.get('stages', {}).get('prefix', {})
    if not isinstance(snapshot, dict):
        return {'prefix_snapshot_present': False, 'observable_checks_pass': False}
    budget = snapshot.get('budget_state', {})
    consumed = budget.get('consumed', {})
    checks = {}
    for name in ('fixed', 'interactive'):
        stage = case.get('stages', {}).get(name, {})
        request = next((e for e in stage.get('events', []) if e.get('event') == 'model_request'), None)
        current = (request or {}).get('budget', {})
        used = current.get('consumed', {})
        observed = bool(request and current.get('ceiling') == budget.get('ceiling')
                        and all(used.get(k) == consumed.get(k) for k in ('token', 'tool_call'))
                        and used.get('model_call') == consumed.get('model_call', -2) + 1)
        checks[name] = {'first_request_budget_observed': request is not None,
                        'inherits_recorded_consumption_and_ceiling': observed}
    same_manifest = all(case.get('stages', {}).get(name, {}).get('state', {}).get('task_manifest')
                        == snapshot.get('task_manifest') for name in ('fixed', 'interactive'))
    return {'prefix_snapshot_present': True, 'prefix_snapshot_sha256': digest(snapshot),
            'prefix_stage_matches_snapshot': prefix.get('state') == snapshot,
            'branch_task_identities_match_snapshot': same_manifest, 'branches': checks,
            'independent_initial_snapshots_inferred': False,
            'observable_checks_pass': prefix.get('state') == snapshot and same_manifest
                and all(item['inherits_recorded_consumption_and_ceiling'] for item in checks.values())}


def case_observation(case, config):
    stages = {name: stage_observation(case.get('stages', {}).get(name), name, config,
                                       case.get('prefix_snapshot'))
              for name in ('prefix', 'fixed', 'interactive', 'standalone')}
    prefix, standalone = stages['prefix'], stages['standalone']
    shared = (prefix.get('submitted_legal_public_pass', False)
              and all(case.get('decisions', {}).get(arm, {}).get('route') == 'stop' for arm in ('A', 'C', 'D')))
    expected_attempts = {f'candidate_{i}' for i in range(config['prefix']['n_candidates'])}
    complete_prefix = bool(prefix.get('present') and not prefix.get('budget_overrun', True)
        and prefix.get('budget_complete') and prefix.get('budget_ceiling_matches_config')
        and prefix.get('request_count_matches_budget_delta')
        and not prefix.get('environment_error_records') and not prefix.get('prefix_error_reasons')
        and prefix.get('observed_identities_match') and not prefix.get('failed_or_unknown_request_records')
        and (shared or (prefix.get('status') == 'completed' and not prefix.get('prefix_stop_reasons')
                       and prefix.get('prefix_localization_completed')
                       and set(prefix.get('prefix_candidate_attempts', [])) == expected_attempts)))
    remaining = case.get('prefix_snapshot', {}).get('budget_state', {}).get('remaining', {}) if case.get('prefix_snapshot') else {}
    minimum = config['router']['min_continuation']
    continuation_available = all(finite(remaining.get(k)) and remaining[k] >= minimum[k] for k in ASPECTS)
    paired = inherited_budget_checks(case)
    branches_ok = case.get('paired_eligible') is True and continuation_available and paired['observable_checks_pass'] \
        and stages['fixed']['usable_with_legal_submission'] and stages['interactive']['usable_with_legal_submission']
    lifecycle_ok = not case.get('cleanup_errors') and not any(e.get('event') == 'start_failed' or e.get('error') for e in case.get('lifecycle', []))
    image = config['execution']['images'][case['instance_id']]
    actual_image_ok = case.get('image_digest') == image and all(
        event.get('image_digest') == image for event in case.get('lifecycle', []) if event.get('event') == 'start')
    flow = bool(complete_prefix and standalone['usable_with_legal_submission'] and lifecycle_ok
                and actual_image_ok and (shared or branches_ok))
    return {'instance_id': case['instance_id'], 'recorded_status': case.get('status'),
            'stages': stages, 'prefix_complete_or_legal_public_shared_stop': complete_prefix,
            'legal_public_shared_stop': shared, 'paired_eligible': case.get('paired_eligible'),
            'minimum_continuation_available': continuation_available, 'pair_observable_checks': paired,
            'lifecycle_without_recorded_errors': lifecycle_ok, 'paired_flow_usable': bool(branches_ok),
            'actual_images_match_prepared_identity': actual_image_ok,
            'standalone_B_usable': standalone['usable_with_legal_submission'], 'usable_flow': flow,
            'prefix_legal_candidate_coverage': prefix.get('has_legal_candidate', False),
            'prefix_reused': case.get('prefix_reused', False),
            'new_prefix_requests_this_run': 0 if case.get('prefix_reused') else prefix.get('actual_request_records', 0)}


def extract(matrix, ids):
    indexed = {case['instance_id']: case for case in matrix['cases']}
    rows = [case_observation(indexed[i], matrix['effective_config']) if i in indexed else
            {'instance_id': i, 'missing': True, 'usable_flow': False, 'prefix_legal_candidate_coverage': False}
            for i in ids]
    return {'tag': matrix['tag'], 'config_hash': matrix['config_hash'],
            'prefix_fraction': matrix['effective_config']['prefix']['prefix_fraction'],
            'interaction_model_calls': matrix['effective_config']['interaction']['model_calls'],
            'designated_cases': len(ids), 'recorded_cases': len(indexed),
            'usable_flow_count': sum(row['usable_flow'] for row in rows),
            'prefix_legal_candidate_coverage_count': sum(row['prefix_legal_candidate_coverage'] for row in rows),
            'prefix_setting_eligible': all(row.get('prefix_complete_or_legal_public_shared_stop', False)
                and (row.get('legal_public_shared_stop', False) or row.get('minimum_continuation_available', False)) for row in rows),
            'batch_stopped': matrix.get('batch_stopped'), 'cases': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--variant', action='append', default=[], metavar='NAME=PATH')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    if not out.is_relative_to(HERE) or out.exists():
        parser.error('output must be a new file in this execution audit directory')
    try:
        protocol, protocol_input = read(HERE / 'resource_screen_protocol.json')
        metrics, metrics_input = read(HERE / 'screen_operational_metrics_01.json')
        if metrics['resource_screen_protocol_sha256'] != protocol_input['sha256']:
            raise ValueError('prospective operational definitions no longer match the resource protocol')
        selection, selection_input = read(ROOT / protocol['selection_manifest'])
        ids = selection['instance_ids']
        if ids != metrics['designated_instances'] or len(ids) != 3:
            raise ValueError('operational definitions require the exact three-case screen selection')
        baseline, baseline_input = read(args.baseline)
        validate_matrix(baseline, ids, protocol)
        matrices = [('baseline', baseline, baseline_input)]
        names, settings = {'baseline'}, {(baseline['effective_config']['prefix']['prefix_fraction'], 6)}
        for item in args.variant:
            name, separator, value = item.partition('=')
            if not separator or not name or name in names:
                raise ValueError('variant requires a unique NAME=PATH')
            matrix, source = read(value)
            validate_matrix(matrix, ids, protocol, baseline)
            setting = (matrix['effective_config']['prefix']['prefix_fraction'], matrix['effective_config']['interaction']['model_calls'])
            if setting in settings:
                raise ValueError('duplicate parameter setting: reference its existing actual run instead of rerunning or cherry-picking')
            names.add(name); settings.add(setting); matrices.append((name, matrix, source))
        result = {'kind': 'corrected_dev_screen_operational_observations', 'official_labels_read': False,
                  'thresholds_selected': False, 'setting_selected': False,
                  'inputs': {'protocol': protocol_input, 'operational_metrics': metrics_input, 'selection': selection_input},
                  'observations': [dict(name=name, source=source, **extract(matrix, ids)) for name, matrix, source in matrices],
                  'notes': ['No official solved labels enter these observations.',
                            'Normal bounded termination with a legal candidate is not automatically model inability.',
                            'The original failed-environment screen remains excluded; its costs and records are preserved elsewhere.',
                            'The extractor checks observable inherited budgets and identities, not unrecorded independent initial snapshots.']}
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False); stream.write('\n')
    except (ValueError, KeyError, TypeError, StopIteration) as exc:
        parser.error(str(exc))
    print(out)


if __name__ == '__main__':
    main()
