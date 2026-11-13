"""The user-requested one-repeat report preserves audit and uncertainty limits."""
import copy
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('single_run_summary', ROOT / 'scripts/summarize_single_run.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def rows():
    ids = [f'repo__sample-{i}' for i in range(20)]
    records = [{'instance_id': iid, 'mode': 'formal', 'arm': arm, 'repeat_index': 0,
                'seed': 20261111, 'run_id': 'test20_' + arm, 'config_hash': 'same-frozen-config',
                'status': 'unresolved', 'prediction_sha256': 'a' * 64, 'patch_sha256': 'b' * 64,
                'cost_cny': .1, 'cost_complete': True,
                'resources': {'token': 100, 'model_call': 1, 'tool_call': 2, 'wallclock_seconds': 3},
                'resources_complete': True}
               for iid in ids for arm in 'ABCDE']
    return records, ids


def rejected(records, ids):
    try:
        module.summarize(records, ids)
    except ValueError:
        return
    raise AssertionError('invalid single-run input accepted')


def registration(manifest, manifest_path, manifest_bytes):
    return {'kind': 'preregistered_single_run_descriptive', 'split': 'test',
            'population_size': 300, 'sample_size': 20, 'arms': list('ABCDE'),
            'repeats': 1, 'repeat_index': 0, 'inference': False,
            'statistics': 'descriptive_single_run_no_inference',
            'sampling_seed': manifest['seed'], 'generation_seed': 20261111,
            'sample_manifest': str(manifest_path.resolve()),
            'sample_manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest(),
            'instance_ids': manifest['instance_ids']}


def test_single_run_is_descriptive_with_full_denominators_and_no_zero_solve_ratio():
    records, ids = rows()
    records[0]['status'] = 'resolved'
    report = module.summarize(records, ids)
    assert report['designated_units'] == 100 and len(report['rows']) == 100
    assert report['repeats'] == 1 and not report['inference_performed']
    assert report['confidence_interval'] is None and report['statistical_significance'] is None
    assert report['primary']['A']['resolved_rate'] == 1 / 20
    assert abs(report['primary']['A']['cost_per_resolved_cny'] - 2) < 1e-9
    assert report['primary']['B']['cost_per_resolved_cny'] is None
    assert report['primary']['A']['repository_macro_average'] == 1 / 20
    assert '>=3-repeat' in report['interpretation']


def test_preregistered_paired_comparisons_report_direction_quadrants_and_discordance():
    records, ids = rows()
    indexed = {(row['instance_id'], row['arm']): row for row in records}
    for iid, arm in [(ids[0], 'C'), (ids[0], 'D'), (ids[1], 'D'), (ids[2], 'C'),
                     (ids[3], 'D'), (ids[4], 'E')]:
        indexed[iid, arm]['status'] = 'resolved'
    report = module.summarize(records, ids)
    comparisons = report['paired_differences']
    assert set(comparisons['primary']) == {'D_minus_C', 'D_minus_E'}
    assert set(comparisons['secondary']) == {'D_minus_A', 'D_minus_B'}
    dc = comparisons['primary']['D_minus_C']
    assert dc['left'] == 'C' and dc['right'] == 'D' and dc['direction'] == 'D minus C'
    assert dc['known_pair_count'] == 20 and dc['evaluation_complete']
    assert dc['paired_resolved_quadrants'] == {
        'both_resolved': 1, 'left_only_resolved': 1, 'right_only_resolved': 2,
        'neither_resolved': 16}
    assert dc['discordant_pair_count'] == 3
    assert dc['resolved_rate_difference'] == 1 / 20 and dc['difference_percentage_points'] == 5
    assert comparisons['primary']['D_minus_E']['resolved_rate_difference'] == 2 / 20
    assert comparisons['secondary']['D_minus_A']['resolved_rate_difference'] == 3 / 20
    assert report['confidence_interval'] is None and not report['inference_performed']


def test_paired_unknowns_withhold_designated_difference_without_dropping_pairs():
    records, ids = rows()
    indexed = {(row['instance_id'], row['arm']): row for row in records}
    indexed[ids[0], 'D']['status'] = 'resolved'
    indexed[ids[1], 'C'].update(status='not_scored', prediction_sha256=None, patch_sha256=None)
    indexed[ids[2], 'C'].update(status='infra_error', generation_status='environment_error')
    report = module.summarize(records, ids)
    dc = report['paired_differences']['primary']['D_minus_C']
    assert dc['known_pair_count'] == 19 and dc['designated_pairs'] == 20
    assert dc['unknown_pair_instance_ids'] == [ids[1]] and not dc['evaluation_complete']
    assert dc['resolved_rate_difference'] is None and dc['difference_percentage_points'] is None
    assert sum(dc['paired_resolved_quadrants'].values()) == 19
    assert dc['known_pairs_with_infrastructure_status'] == [ids[2]]
    assert dc['paired_resolved_quadrants']['right_only_resolved'] == 1
    assert report['paired_differences']['primary']['D_minus_E']['resolved_rate_difference'] == 1 / 20


def test_unknown_infrastructure_and_unresolved_remain_distinct():
    records, ids = rows()
    records[0].update(status='not_scored', prediction_sha256=None, patch_sha256=None)
    records[5].update(status='infra_error', generation_status='environment_error')
    records[10]['status'] = 'resolved'
    report = module.summarize(records, ids)
    arm = report['primary']['A']
    assert arm['total'] == 20 and arm['status_counts'] == {
        'not_scored': 1, 'infra_error': 1, 'resolved': 1, 'unresolved': 17}
    assert arm['resolved_rate'] is None and arm['resolved_rate_lower_bound'] == 1 / 20
    assert not report['evaluation_complete']
    assert len(report['common_runnable']['instance_ids']) == 18
    assert set(report['common_runnable']['excluded']) == set(ids[:2])


def test_unknown_cost_and_resources_do_not_produce_precise_ratios():
    records, ids = rows()
    records[0].update(status='resolved', cost_complete=False, resources_complete=False)
    report = module.summarize(records, ids)
    item = report['primary']['A']
    assert not item['cost_complete'] and item['cost_per_resolved_cny'] is None
    assert item['resources']['token']['mean_per_task'] is None
    assert item['resources']['token']['per_resolved'] is None
    del records[0]['cost_complete']
    assert not module.summarize(records, ids)['primary']['A']['cost_complete']
    records[0]['cost_cny'] = None
    assert not module.summarize(records, ids)['primary']['A']['cost_complete']


def test_single_run_rejects_missing_duplicate_outside_population_or_extra_repeat_rows():
    records, ids = rows()
    rejected(records[:-1], ids)
    rejected(records + [copy.deepcopy(records[0])], ids)
    for field, value in [('instance_id', 'other'), ('repeat_index', 1), ('repeat_index', False)]:
        changed = copy.deepcopy(records)
        changed[0][field] = value
        rejected(changed, ids)
    rejected(records, ids[:-1])
    rejected(records, [*ids[:-1], ids[0]])


def test_single_run_reuses_formal_mode_seed_config_run_and_prediction_identity_checks():
    original, ids = rows()
    for field, value in [('mode', 'pilot'), ('seed', 8), ('config_hash', 'other'),
                         ('run_id', ''), ('prediction_sha256', 'bad'), ('patch_sha256', None)]:
        changed = copy.deepcopy(original)
        changed[0][field] = value
        rejected(changed, ids)
    changed = copy.deepcopy(original)
    changed[1]['run_id'] = changed[0]['run_id']
    rejected(changed, ids)
    changed = copy.deepcopy(original)
    changed[5]['prediction_sha256'] = 'c' * 64
    rejected(changed, ids)


def test_uniform_and_per_instance_seed_changes_cannot_escape_registration_binding():
    records, ids = rows()
    assert module.summarize(records, ids, expected_seed=20261111)['repeats'] == 1
    for changed in ([dict(row, seed=8) for row in records],
                    [dict(row, seed=8) if row['instance_id'] == ids[0] else dict(row) for row in records]):
        try:
            module.summarize(changed, ids, expected_seed=20261111)
        except ValueError:
            pass
        else:
            raise AssertionError('uniform or individually paired wrong seed escaped preregistration')


def test_single_run_rejects_invalid_costs_and_false_precision_markers():
    for value in (True, -1, float('nan'), float('inf'), '0.1'):
        records, ids = rows()
        records[0]['cost_cny'] = value
        rejected(records, ids)
    records, ids = rows()
    records[0]['cost_complete'] = 'unknown'
    rejected(records, ids)


def test_manifest_binds_all_test_population_and_selected_list_without_outcome_inputs():
    population = (ROOT / 'data/frozen/instances_test.txt').read_text(encoding='utf-8').splitlines()
    from swe_repair.statistics import stratified_sample
    manifest = stratified_sample(population, 20, 20261111)
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'instances.json'
        path.write_text(json.dumps(manifest), encoding='utf-8')
        assert module.load_instances(path) == manifest['instance_ids']
        for field, value in [('population_sha256', 'a' * 64), ('instance_list_sha256', 'b' * 64),
                             ('sample_size', 19), ('population_size', 98)]:
            changed = dict(manifest, **{field: value})
            path.write_text(json.dumps(changed), encoding='utf-8')
            try:
                module.load_instances(path)
            except ValueError:
                pass
            else:
                raise AssertionError('inconsistent manifest accepted: ' + field)


def test_self_consistent_different_list_and_wrong_algorithm_do_not_reproduce_sample():
    population = (ROOT / 'data/frozen/instances_test.txt').read_text(encoding='utf-8').splitlines()
    from swe_repair.statistics import stratified_sample
    manifest = stratified_sample(population, 20, 20261111)
    other_ids = sorted([*manifest['instance_ids'][1:], next(iid for iid in population if iid not in manifest['instance_ids'])])
    other_hash = hashlib.sha256(('\n'.join(other_ids) + '\n').encode()).hexdigest()
    variants = [dict(manifest, seed=20261112), dict(manifest, sampling='other_algorithm'),
                dict(manifest, instance_ids=other_ids, instances=other_ids, instance_list_sha256=other_hash)]
    for changed in variants:
        try:
            module.load_instances('unused.json', contents=json.dumps(changed).encode())
        except ValueError:
            pass
        else:
            raise AssertionError('self-consistent list escaped deterministic algorithm/seed replay')


def test_registration_rejects_wrong_scope_list_path_bytes_and_sampling_seed():
    population = (ROOT / 'data/frozen/instances_test.txt').read_text(encoding='utf-8').splitlines()
    from swe_repair.statistics import stratified_sample
    manifest = stratified_sample(population, 20, 20261111)
    with tempfile.TemporaryDirectory(dir=ROOT / 'runs') as folder:
        path = Path(folder) / 'instances.json'
        manifest_bytes = json.dumps(manifest).encode()
        frozen = registration(manifest, path, manifest_bytes)
        assert module.validate_preregistration(frozen, path, manifest_bytes, manifest['instance_ids']) == 20261111
        variants = [('kind', 'pilot'), ('split', 'dev'), ('sample_size', 19), ('arms', list('ABCD')),
                    ('repeats', 3), ('repeat_index', False), ('inference', True), ('generation_seed', True),
                    ('statistics', 'bootstrap'), ('sample_manifest', str(path.with_name('other.json'))),
                    ('sample_manifest_sha256', '0' * 64), ('instance_ids', list(reversed(manifest['instance_ids']))),
                    ('sampling_seed', 20261112)]
        for field, value in variants:
            try:
                module.validate_preregistration(dict(frozen, **{field: value}), path, manifest_bytes, manifest['instance_ids'])
            except ValueError:
                pass
            else:
                raise AssertionError('wrong preregistration accepted: ' + field)
        changed_bytes = json.dumps(manifest, indent=2).encode()
        try:
            module.validate_preregistration(frozen, path, changed_bytes, manifest['instance_ids'])
        except ValueError:
            pass
        else:
            raise AssertionError('same manifest data with different bytes escaped registration hash')


def test_existing_bootstrap_still_rejects_one_repeat():
    from swe_repair.statistics import paired_cluster_bootstrap
    records, ids = rows()
    try:
        paired_cluster_bootstrap(records, ids, 'A', 'D', repeats=1, samples=100)
    except ValueError:
        pass
    else:
        raise AssertionError('one-repeat exception reached inferential bootstrap')


def test_cli_binds_used_input_bytes_and_refuses_to_replace_report():
    from swe_repair.statistics import stratified_sample
    population = (ROOT / 'data/frozen/instances_test.txt').read_text(encoding='utf-8').splitlines()
    manifest = stratified_sample(population, 20, 20261111)
    records, original_ids = rows()
    mapping = dict(zip(original_ids, manifest['instance_ids']))
    records = [dict(row, instance_id=mapping[row['instance_id']]) for row in records]
    with tempfile.TemporaryDirectory(dir=ROOT / 'runs') as folder:
        directory = Path(folder)
        instances_path = directory / 'instances.json'
        registration_path = directory / 'preregistration.json'
        records_path = directory / 'evaluated_records.jsonl'
        output = directory / 'summary.json'
        instances_path.write_text(json.dumps(manifest), encoding='utf-8')
        registration_path.write_text(json.dumps(registration(manifest, instances_path, instances_path.read_bytes())), encoding='utf-8')
        records_path.write_text('\n'.join(json.dumps(row) for row in records) + '\n', encoding='utf-8')
        arguments = ['summarize_single_run.py', '--records', str(records_path), '--instances',
                     str(instances_path), '--preregistration', str(registration_path), '--out', str(output)]
        old_argv = sys.argv
        try:
            sys.argv = arguments
            with contextlib.redirect_stdout(io.StringIO()):
                assert module.main() == 0
            first_bytes = output.read_bytes()
            report = json.loads(first_bytes)
            assert report['inputs']['preregistration']['sha256'] == hashlib.sha256(registration_path.read_bytes()).hexdigest()
            assert report['inputs']['instance_manifest']['sha256'] == hashlib.sha256(instances_path.read_bytes()).hexdigest()
            assert report['inputs']['evaluated_records'][0]['sha256'] == hashlib.sha256(records_path.read_bytes()).hexdigest()
            with contextlib.redirect_stderr(io.StringIO()):
                try:
                    module.main()
                except SystemExit as exc:
                    assert exc.code == 2
                else:
                    raise AssertionError('existing single-run report replaced')
            assert output.read_bytes() == first_bytes
            records_path.write_text('\n'.join(json.dumps(dict(row, seed=8)) for row in records) + '\n', encoding='utf-8')
            sys.argv = [*arguments[:-1], str(directory / 'wrong_seed_summary.json')]
            with contextlib.redirect_stderr(io.StringIO()):
                try:
                    module.main()
                except SystemExit as exc:
                    assert exc.code == 2
                else:
                    raise AssertionError('CLI accepted all records with a different generation seed')
            assert not (directory / 'wrong_seed_summary.json').exists()
        finally:
            sys.argv = old_argv
