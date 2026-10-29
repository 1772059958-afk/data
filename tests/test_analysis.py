"""Read-only evaluation joins: stop cost, missing labels and legacy provenance."""
from pathlib import Path
import importlib.util
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('proposal_analysis', ROOT / 'scripts/analyse_cf.py')
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


def matrix():
    return {'mode': 'diagnostic', 'split': 'dev', 'repeat_index': 0,
            'designated_instances': ['a', 'b', 'missing'], 'cases': [
                {'instance_id': 'a', 'mode': 'diagnostic', 'paired_eligible': False,
                 'decisions': {a: {'route': 'stop'} for a in ('A', 'C', 'D', 'E')},
                 'stages': {'prefix': {'cost_cny': .1}}},
                {'instance_id': 'b', 'mode': 'diagnostic', 'paired_eligible': True,
                 'decisions': {'A': {'route': 'fixed'}, 'C': {'route': 'interactive'},
                               'D': {'route': 'interactive'}, 'E': {'route': 'fixed'}},
                 'stages': {'prefix': {'cost_cny': .1}, 'fixed': {'cost_cny': .2},
                            'interactive': {'cost_cny': .3}}},
            ]}


def reports():
    return {'A': {'resolved_ids': ['a'], 'unresolved_ids': ['b']},
            'ESC': {'resolved_ids': ['b'], 'empty_patch_ids': []},
            'C': {'resolved_ids': ['a', 'b']}, 'D': {'resolved_ids': ['a', 'b']}}


def test_new_analysis_keeps_designated_unknowns_and_actual_shared_stops():
    result = analysis.analyze(matrix(), reports())
    c, d = ({s['policy']: s for s in result['policies']}[name] for name in ('C_actual', 'D_actual'))
    assert c['total'] == d['total'] == 3
    assert c['resolved'] == d['resolved'] == 2
    assert c['cost_cny'] == d['cost_cny'] == .5
    assert c['stops'] == d['stops'] == 1
    assert c['not_scored'] == 1 and c['resolved_rate'] is None
    assert result['primary_summaries']['D']['status_counts']['not_scored'] == 1
    assert result['paired_eligible'] == result['paired_complete'] == 1
    assert result['quadrants']['counts']['Q3_interactive_only'] == 1


def test_generation_completed_is_not_a_resolved_verdict():
    m = {'mode': 'formal', 'arm': 'D', 'repeat_index': 2, 'config_hash': 'frozen',
         'designated_instances': ['a'], 'cases': [
             {'instance_id': 'a', 'mode': 'formal', 'arm': 'D', 'status': 'completed',
              'selected_route': 'stop', 'policy_cost_cny': .2, 'stages': {}}]}
    result = analysis.analyze(m, {})
    assert result['primary_summaries']['D']['resolved_rate'] is None
    assert result['paired_eligible'] == 0
    assert result['records'][0]['status'] == 'not_scored'
    assert result['records'][0]['repeat_index'] == 2
    assert result['records'][0]['mode'] == 'formal'
    assert result['records'][0]['config_hash'] == 'frozen'


def test_legacy_analysis_cannot_become_formal_evidence():
    m = {'instances': [{'instance_id': 'a', 'features': {}, 'prefix': {'cost_cny': .1},
                        'fixed': {'cost_cny': 0}, 'interactive': {'cost_cny': .3}}],
         'decisions': {'a': {a: 'stop' for a in ('A', 'C', 'D', 'E')}}}
    result = analysis.analyze(m, {'A': {'resolved_ids': ['a']}})
    assert result['historical_diagnostic_only']
    assert result['records'][0]['mode'] == 'legacy_diagnostic'
    assert result['paired_eligible'] == 0


def test_new_matrix_without_frozen_population_is_rejected():
    try:
        analysis.analyze({'cases': []}, {})
    except ValueError:
        pass
    else:
        raise AssertionError('analysis invented its own population from completed cases')
