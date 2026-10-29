"""Tests of estimands and sampling, not generated performance claims."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from swe_repair.statistics import primary_summary, paired_cluster_bootstrap, stratified_sample, repo_of


def test_primary_denominator_preserves_infra_missing_and_failure_costs():
    rows = [{'instance_id': 'a__repo-1', 'status': 'resolved', 'cost_cny': 1},
            {'instance_id': 'b__repo-2', 'status': 'infra_error', 'cost_cny': 2}]
    report = primary_summary(rows, ['a__repo-1', 'b__repo-2', 'b__repo-3'])
    assert report['total'] == 3
    assert report['status_counts'] == {'resolved': 1, 'infra_error': 1, 'not_scored': 1}
    assert report['resolved_rate'] is None
    assert report['resolved_rate_lower_bound'] == 1 / 3
    assert report['cost_cny_recorded'] == 3
    assert not report['cost_complete'] and report['cost_per_resolved_cny'] is None


def test_repository_macro_is_not_instance_micro():
    rows = [{'instance_id': 'a__repo-1', 'status': 'resolved', 'cost_cny': 1},
            {'instance_id': 'b__repo-1', 'status': 'unresolved', 'cost_cny': 1},
            {'instance_id': 'b__repo-2', 'status': 'unresolved', 'cost_cny': 1}]
    report = primary_summary(rows, [r['instance_id'] for r in rows])
    assert report['resolved_rate'] == 1 / 3
    assert report['repository_macro_average'] == 0.5
    assert report['cost_per_resolved_cny'] == 3


def test_primary_rejects_generation_status_and_duplicate_rows():
    for rows in [[{'instance_id': 'x', 'status': 'completed', 'cost_cny': 0}],
                 [{'instance_id': 'x', 'status': 'resolved'}] * 2]:
        try:
            primary_summary(rows, ['x'])
        except ValueError:
            pass
        else:
            raise AssertionError('invalid primary data accepted')


def paired_rows():
    return [{'instance_id': iid, 'repeat_index': repeat, 'arm': arm,
             'status': 'resolved' if ((iid == 'one' and arm == 'D') or (iid == 'two' and arm == 'A')) else 'unresolved'}
            for iid in ('one', 'two') for repeat in range(3) for arm in ('A', 'D')]


def test_bootstrap_resamples_whole_instances_not_repeats():
    result = paired_cluster_bootstrap(paired_rows(), ['one', 'two'], 'A', 'D', samples=500, seed=7)
    assert result['difference'] == 0
    assert result['ci'] == [-1, 1]
    assert result['resampling_unit'] == 'instance'
    assert result['instances'] == 2 and result['repeats'] == 3
    assert result == paired_cluster_bootstrap(list(reversed(paired_rows())), ['one', 'two'], 'A', 'D', samples=500, seed=7)


def test_bootstrap_refuses_smoke_runs_unknowns_and_incomplete_grids():
    for rows, repeats in [(paired_rows(), 1), (paired_rows()[:-1], 3),
                          ([dict(r, status='not_scored') for r in paired_rows()], 3)]:
        try:
            paired_cluster_bootstrap(rows, ['one', 'two'], 'A', 'D', repeats=repeats, samples=100)
        except ValueError:
            pass
        else:
            raise AssertionError('incomplete/invalid experiment produced a confidence interval')


def test_sampling_covers_repositories_and_is_order_independent():
    ids = [f'owner__a-{i}' for i in range(10)] + [f'owner__b-{i}' for i in range(3)]
    sample = stratified_sample(ids, 6, 12)
    assert sample == stratified_sample(list(reversed(ids)), 6, 12)
    assert len(set(sample['instances'])) == 6
    assert sample['instance_ids'] == sample['instances']
    assert {repo_of(i) for i in sample['instances']} == {'owner__a', 'owner__b'}
    assert sample['per_repository']['owner__b']['sample'] >= 1
    assert stratified_sample(ids, len(ids), 12)['instances'] == sorted(ids)


def test_sampling_rejects_impossible_or_duplicate_population():
    for ids, n in [(['a__x-1', 'b__x-1'], 1), (['x', 'x'], 2)]:
        try:
            stratified_sample(ids, n, 0)
        except ValueError:
            pass
        else:
            raise AssertionError('invalid sampling plan accepted')
