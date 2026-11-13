"""Dev pilot runs remain real single-policy executions, separate from formal evidence."""
import copy
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

from swe_repair import experiment as ex
from swe_repair.evaluation import (build_provenance, frozen_predictions, run_identity,
                                   validate_provenance)
from swe_repair.state import Candidate
from swe_repair.statistics import validate_formal_records, paired_cluster_bootstrap

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('pilot_fixtures', ROOT / 'tests/test_experiment.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


def run(arm='D', *, raw=None, prefix=fixture.prefix, **kwargs):
    client = fixture.Client()
    with patch.object(ex, 'run_prefix', prefix), \
         patch.object(ex, 'validate_candidate', fixture.validation), \
         patch.object(ex, 'run_interactive', fixture.interactive):
        result = ex.run_case(fixture.ROW, client, raw or fixture.config(), mode='pilot',
                             arm=arm, split='dev', box_factory=fixture.Box, **kwargs)
    return result, client


def test_pilot_each_arm_runs_only_its_selected_branch_and_keeps_pending_status():
    raw = fixture.config()
    before = copy.deepcopy(raw)
    assert raw['status'] == 'draft-pending-calibration'
    for arm in 'ABCDE':
        result, client = run(arm, raw=raw)
        assert result['mode'] == 'pilot' and result['arm'] == arm
        assert result['status'] == 'completed', result
        route = result['selected_route']
        if arm == 'B':
            assert route == 'standalone' and set(result['stages']) == {'standalone'}
            assert result['prefix_snapshot'] is None and len(client.requests) == 1
        else:
            assert route in ('fixed', 'interactive')
            assert set(result['stages']) == {'prefix', route} and len(client.requests) == 2
            if arm in ('A', 'D'):
                assert route == 'fixed'
            elif arm == 'C':
                assert route == 'interactive'
        assert result['submitted_patch'] == result['stages'][route]['patch']
    assert raw == before


def test_pilot_reuses_identical_prefix_for_all_routed_arms_with_full_policy_cost():
    first, _ = run('A')
    cached = {'config_hash': first['config_hash'], 'image_digest': first['image_digest'],
              'stage': first['stages']['prefix']}
    for arm in 'CDE':
        result, client = run(arm, cached_prefix=cached)
        assert result['prefix_reused'] and result['prefix_snapshot'] == first['prefix_snapshot']
        assert len(client.requests) == 1
        assert result['policy_cost_cny'] == .02 and result['new_generation_cost_cny'] == .01
        assert set(result['stages']) == {'prefix', result['selected_route']}


def test_pilot_standalone_b_never_uses_router_or_prefix_cache():
    client = fixture.Client()
    with patch.object(ex, 'run_prefix', side_effect=AssertionError('B must start from initial input')), \
         patch.object(ex, 'evaluate_all', side_effect=AssertionError('B has no prefix router')), \
         patch.object(ex, 'run_interactive', fixture.interactive):
        result = ex.run_case(fixture.ROW, client, fixture.config(), mode='pilot', arm='B', split='dev',
                             cached_prefix={'not': 'a valid prefix'}, box_factory=fixture.Box)
    assert result['status'] == 'completed' and result['submitted_patch']
    assert result['policy_cost_cny'] == .01 and 'prefix_reused' not in result


def test_pilot_shared_stop_freezes_prefix_without_continuation_cost():
    def passing(*args, **kwargs):
        prefix = fixture.prefix(*args, **kwargs)
        prefix.state.patches.candidates[0] = Candidate.build(0, fixture.DIFF, applies_cleanly=True,
                                                             validation='pass', syntax='pass')
        return prefix
    for arm in 'ACDE':
        result, client = run(arm, prefix=passing)
        assert set(result['stages']) == {'prefix'} and result['selected_route'] == 'stop'
        assert result['termination_reason'] == 'early_stop_public_pass'
        assert result['policy_cost_cny'] == .01 and len(client.requests) == 1


def test_pilot_requires_dev_split_without_calibration_bypass_before_any_request():
    for split, calibration in ((None, False), ('test', False), ('dev', True)):
        client = fixture.Client()
        with patch.object(ex, 'run_prefix', side_effect=AssertionError('must reject before generation')):
            try:
                ex.run_case(fixture.ROW, client, fixture.config(), mode='pilot', split=split,
                            calibration=calibration, box_factory=fixture.Box)
            except ValueError as exc:
                assert 'pilot requires explicit dev' in str(exc)
            else:
                raise AssertionError('pilot split or calibration escape accepted')
        assert not client.requests


def test_pilot_requires_explicit_candidate_thresholds_and_e_probability():
    for key in ('localization_disagreement_threshold', 'duplicate_rate_threshold', 'switch_probability'):
        raw = fixture.config()
        raw['router'][key] = None
        client = fixture.Client()
        try:
            ex.run_case(fixture.ROW, client, raw, mode='pilot', split='dev', box_factory=fixture.Box)
        except ValueError as exc:
            assert 'candidate D policy' in str(exc)
        else:
            raise AssertionError('pilot invented pending router values')
        assert not client.requests


def test_pilot_branch_failure_keeps_candidate_cost_and_mode():
    with patch.object(ex, 'run_prefix', fixture.prefix), \
         patch.object(ex, 'validate_candidate', side_effect=ValueError('synthetic validation failure')):
        result = ex.run_case(fixture.ROW, fixture.Client(), fixture.config(), mode='pilot', arm='A',
                             split='dev', box_factory=fixture.Box)
    assert result['mode'] == 'pilot' and result['status'] == 'generation_error'
    assert result['submitted_patch'] == fixture.DIFF and result['policy_cost_cny'] == .02


def pilot_matrix():
    result, _ = run('D')
    tag = 'pilot_dev_identity'
    result.update(repeat_index=0, run_id=tag)
    return {'tag': tag, 'config_hash': result['config_hash'], 'mode': 'pilot', 'split': 'dev',
            'seed': 0, 'repeat_index': 0, 'arm': 'D', 'designated_instances': [fixture.ROW['instance_id']],
            'cases': [result]}


def test_pilot_scoring_identity_binds_mode_and_only_actual_arm_prediction():
    matrix = pilot_matrix()
    patches = frozen_predictions(matrix, 'D')
    assert patches == {fixture.ROW['instance_id']: fixture.DIFF}
    assert frozen_predictions(matrix, 'A') == {}
    payload = ('\n'.join(json.dumps({'instance_id': iid, 'model_name_or_path': matrix['tag'] + '-D',
                                     'model_patch': diff}) for iid, diff in patches.items()) + '\n').encode()
    report = {'resolved_ids': [fixture.ROW['instance_id']]}
    provenance = build_provenance(matrix, 'D', payload, report,
                                  matrix_bytes=json.dumps(matrix).encode(), report_bytes=json.dumps(report).encode())
    assert provenance['identity']['mode'] == 'pilot'
    changed = copy.deepcopy(matrix)
    changed['mode'] = changed['cases'][0]['mode'] = 'formal'
    try: validate_provenance(changed, 'D', report, provenance)
    except ValueError: pass
    else: raise AssertionError('pilot provenance was relabeled formal')


def test_pilot_test_split_is_rejected_by_both_scoring_identity_apis():
    matrix = pilot_matrix()
    matrix['split'] = 'test'
    for action in (lambda: run_identity(matrix), lambda: frozen_predictions(matrix, 'D')):
        try: action()
        except ValueError as exc: assert 'restricted to the dev split' in str(exc)
        else: raise AssertionError('pilot test scoring accepted')


def test_pilot_cannot_enter_formal_statistics_or_single_repeat_confidence_interval():
    row = {'instance_id': fixture.ROW['instance_id'], 'mode': 'pilot', 'arm': 'D', 'repeat_index': 0}
    try: validate_formal_records([row], [row['instance_id']], repeats=1)
    except ValueError as exc: assert 'formal A-E' in str(exc)
    else: raise AssertionError('pilot row entered main statistics')
    try: paired_cluster_bootstrap([row], [row['instance_id']], 'A', 'D', repeats=1)
    except ValueError as exc: assert '>=3 repeats' in str(exc)
    else: raise AssertionError('single-repeat pilot got a formal interval')
