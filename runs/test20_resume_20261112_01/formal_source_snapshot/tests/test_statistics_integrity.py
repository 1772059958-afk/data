"""Formal identity, secondary environment coverage and measured resource totals."""
from copy import deepcopy

from swe_repair.statistics import (common_runnable_summary, paired_cluster_bootstrap,
                                    primary_summary, validate_formal_records)


def records():
    return [{'instance_id': iid, 'repeat_index': repeat, 'arm': arm,
             'mode': 'formal', 'config_hash': 'frozen-config', 'seed': 100 + repeat,
             'run_id': f'run_{arm}_r{repeat}', 'prediction_sha256': 'a' * 64, 'patch_sha256': 'b' * 64,
             'status': 'resolved' if iid == 'demo__repo-1' else 'empty_patch',
             'cost_cny': 1, 'cost_complete': True, 'generation_status': 'completed',
             'termination_reason': 'step_limit',
             'resources': {'token': 20, 'model_call': 2, 'tool_call': 4, 'wallclock_seconds': 10},
             'resources_complete': {'token': True, 'model_call': True, 'tool_call': True, 'wallclock_seconds': True}}
            for iid in ('demo__repo-1', 'demo__repo-2') for repeat in range(3) for arm in ('A', 'D')]


IDS = ['demo__repo-1', 'demo__repo-2']


def test_formal_seed_pairing_and_run_identity_cannot_be_silently_changed():
    validate_formal_records(records(), IDS, 3)
    for mutate in (
        lambda rows: rows[1].update(seed=999),
        lambda rows: rows[1].update(run_id=rows[0]['run_id']),
        lambda rows: rows[0].pop('seed'),
        lambda rows: rows[0].pop('run_id'),
        lambda rows: rows[0].update(patch_sha256='wrong'),
        lambda rows: rows[0].update(prediction_sha256=None),
        lambda rows: rows[0].update(config_hash='OTHER'),
        lambda rows: rows[-2].update(prediction_sha256='c' * 64),
    ):
        changed = records()
        mutate(changed)
        try:
            paired_cluster_bootstrap(changed, IDS, 'A', 'D', samples=100)
        except ValueError:
            pass
        else:
            raise AssertionError('invalid formal run identity reached the bootstrap')


def test_resource_totals_include_failed_tasks_and_keep_unknown_usage_incomplete():
    rows = [row for row in records() if row['arm'] == 'A']
    rows[0]['resources_complete']['token'] = False
    result = primary_summary(rows, IDS, repeats=3)
    assert result['total'] == 6 and result['resolved'] == 3
    assert result['cost_per_resolved_cny'] == 2
    tokens = result['resources']['token']
    assert tokens['recorded_total'] == 120 and not tokens['complete']
    assert tokens['mean_per_task'] is None and tokens['per_resolved'] is None
    tools = result['resources']['tool_call']
    assert tools == {'recorded_total': 24, 'complete': True, 'mean_per_task': 4, 'per_resolved': 8}


def test_missing_resource_values_are_unknown_and_invalid_values_rejected():
    rows = [row for row in records() if row['arm'] == 'A']
    rows[0]['resources']['wallclock_seconds'] = None
    result = primary_summary(rows, IDS, repeats=3)
    assert not result['resources']['wallclock_seconds']['complete']
    for bad in (-1, float('nan'), True):
        changed = deepcopy(rows)
        changed[0]['resources']['token'] = bad
        try:
            primary_summary(changed, IDS, repeats=3)
        except ValueError:
            pass
        else:
            raise AssertionError('invalid usage entered resource totals')


def test_missing_or_text_resource_completeness_never_means_exact_usage():
    rows = [row for row in records() if row['arm'] == 'A']
    rows[0].pop('resources_complete')
    result = primary_summary(rows, IDS, repeats=3)
    assert all(not value['complete'] for value in result['resources'].values())
    rows[0]['resources_complete'] = {'token': 'false'}
    try:
        primary_summary(rows, IDS, repeats=3)
    except ValueError:
        pass
    else:
        raise AssertionError('a string completeness marker was treated as measured usage')


def test_common_runnable_subset_preserves_primary_population_and_excludes_one_bad_repeat():
    rows = records()
    # One environment error excludes the instance across every arm/repeat,
    # without removing it from the designated primary denominator.
    rows[1]['status'] = 'infra_error'
    result = common_runnable_summary(rows, IDS, repeats=3)
    assert result['designated_instances'] == 2
    assert result['instance_ids'] == ['demo__repo-2']
    assert result['excluded']['demo__repo-1'][0]['status'] == 'infra_error'
    assert result['primary']['D']['total'] == 3
    main = primary_summary([row for row in rows if row['arm'] == 'D'], IDS, repeats=3)
    assert main['total'] == 6 and main['status_counts']['infra_error'] == 1


def test_empty_patch_and_model_failure_are_retained_but_environment_stop_is_excluded():
    rows = records()
    for row in rows:
        if row['instance_id'] == 'demo__repo-2':
            row['generation_status'] = 'generation_error'
            row['termination_reason'] = 'model_error'
    result = common_runnable_summary(rows, IDS, repeats=3)
    assert result['instance_ids'] == IDS
    rows[-1]['termination_reason'] = 'stop_env_failure'
    result = common_runnable_summary(rows, IDS, repeats=3)
    assert result['instance_ids'] == ['demo__repo-1']


def test_unknown_eval_can_be_retained_for_primary_but_not_interval_or_common_subset():
    rows = records()
    rows[-1].update(status='not_scored', prediction_sha256=None, patch_sha256=None)
    validate_formal_records(rows, IDS, 3)
    assert common_runnable_summary(rows, IDS, repeats=3)['instance_ids'] == ['demo__repo-1']
    result = primary_summary([row for row in rows if row['arm'] == 'D'], IDS, repeats=3)
    assert result['resolved_rate'] is None and result['total'] == 6
    try:
        paired_cluster_bootstrap(rows, IDS, 'A', 'D', samples=100)
    except ValueError:
        pass
    else:
        raise AssertionError('unknown verdict entered a confidence interval')
