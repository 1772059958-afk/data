"""Describe the preregistered 20-instance TEST A-E run, without inference.

Only independently evaluated formal records enter this single-repeat report.
The separate summarize_experiment.py entry still requires >=3 repeats for
cluster bootstrap. Missing verdicts must have explicit not_scored audit rows.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from swe_repair.statistics import (common_runnable_summary, primary_summary, stratified_sample,
                                   validate_formal_records)

ARMS = tuple('ABCDE')
INSTANCE_COUNT = 20


def _paired_difference(indexed, ids, left, right):
    """Resolved-indicator difference on the designated sample, right minus left.

    Quadrants describe only pairs with known evaluation statuses. Infrastructure
    statuses remain explicit non-resolved designated outcomes; neither-resolved
    must not be interpreted as proof that both patches were logically wrong.
    """
    quadrants = dict(both_resolved=0, left_only_resolved=0,
                     right_only_resolved=0, neither_resolved=0)
    unknown_pairs, infrastructure_pairs = [], []
    for iid in ids:
        left_status, right_status = indexed[iid, left]['status'], indexed[iid, right]['status']
        if 'not_scored' in (left_status, right_status):
            unknown_pairs.append(iid)
            continue
        if left_status in ('infra_error', 'error') or right_status in ('infra_error', 'error'):
            infrastructure_pairs.append(iid)
        left_resolved, right_resolved = left_status == 'resolved', right_status == 'resolved'
        key = ('both_resolved' if left_resolved and right_resolved else
               'left_only_resolved' if left_resolved else
               'right_only_resolved' if right_resolved else 'neither_resolved')
        quadrants[key] += 1
    known = len(ids) - len(unknown_pairs)
    difference = (quadrants['right_only_resolved'] - quadrants['left_only_resolved']) / len(ids)
    return {
        'left': left, 'right': right, 'direction': f'{right} minus {left}',
        'designated_pairs': len(ids), 'known_pair_count': known,
        'evaluation_complete': not unknown_pairs,
        'resolved_rate_difference': difference if not unknown_pairs else None,
        'difference_percentage_points': 100 * difference if not unknown_pairs else None,
        'paired_resolved_quadrants': quadrants,
        'discordant_pair_count': quadrants['right_only_resolved'] + quadrants['left_only_resolved'],
        'unknown_pair_instance_ids': unknown_pairs,
        'known_pairs_with_infrastructure_status': infrastructure_pairs,
        'quadrant_population': 'known-status pairs only; designated-sample difference withheld if any pair is not_scored',
    }


def _normalise_cost(row):
    """A missing completeness marker never asserts exact cost measurement."""
    result = dict(row)
    value = result.get('cost_cny')
    if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                              or not math.isfinite(value) or value < 0):
        raise ValueError('cost_cny must be a non-negative finite number or unknown')
    known = result.get('cost_complete', False)
    if not isinstance(known, bool):
        raise ValueError('cost_complete must be boolean')
    result['cost_complete'] = known and value is not None
    return result


def summarize(records, instance_ids, *, expected_seed=None):
    """Keep all 100 designated units; unknown evaluation is not a failure."""
    ids = list(instance_ids)
    if len(ids) != INSTANCE_COUNT:
        raise ValueError('this preregistered single run requires exactly 20 designated instances')
    records = [_normalise_cost(row) for row in records]
    validate_formal_records(records, ids, repeats=1)
    if expected_seed is not None:
        if (not isinstance(expected_seed, int) or isinstance(expected_seed, bool)
                or any(row['seed'] != expected_seed for row in records)):
            raise ValueError('all generation seeds must match the preregistration')
    indexed = {(row['instance_id'], row['arm']): row for row in records}
    expected = {(iid, arm) for iid in ids for arm in ARMS}
    if set(indexed) != expected:
        raise ValueError('all 20 x A-E audit rows are required; retain unknown verdicts as not_scored')
    primary = {arm: primary_summary([indexed[iid, arm] for iid in ids], ids, repeats=1)
               for arm in ARMS}
    return {
        'kind': 'test20_single_run_descriptive',
        'design': 'preregistered_single_run_descriptive',
        'mode': 'formal', 'split': 'test',
        'instances': ids, 'arms': list(ARMS), 'repeats': 1,
        'designated_units': INSTANCE_COUNT * len(ARMS),
        'config_hash': records[0]['config_hash'],
        'evaluation_complete': all(item['complete'] for item in primary.values()),
        'primary': primary,
        'paired_differences': {
            'primary': {f'D_minus_{arm}': _paired_difference(indexed, ids, arm, 'D')
                        for arm in ('C', 'E')},
            'secondary': {f'D_minus_{arm}': _paired_difference(indexed, ids, arm, 'D')
                          for arm in ('A', 'B')},
        },
        'common_runnable': common_runnable_summary(records, ids, repeats=1, arms=ARMS),
        'quality_cost_points': [dict(arm=arm,
            resolved_rate=item['resolved_rate'],
            resolved_rate_lower_bound=item['resolved_rate_lower_bound'],
            cost_cny_recorded=item['cost_cny_recorded'], cost_complete=item['cost_complete'],
            cost_per_resolved_cny=item['cost_per_resolved_cny'], resources=item['resources'])
            for arm, item in primary.items()],
        'rows': [indexed[iid, arm] for iid in ids for arm in ARMS],
        'inference_performed': False,
        'confidence_interval': None,
        'statistical_significance': None,
        'interpretation': (
            'Descriptive results for this preregistered 20-instance TEST sample and one repeat. '
            'This does not complete the original >=3-repeat inferential protocol or establish '
            'method superiority or robustness to generation randomness.'),
        'notes': [
            'The primary denominator is all 20 designated instances in each arm, including infrastructure errors.',
            'Unweighted micro rates describe this 20-instance sample; repository-stratified minimum-one sampling does not make them estimates of the full 300-instance rate.',
            'A not_scored verdict is unknown, not an unresolved label; only a lower bound is reported when labels are missing.',
            'Common runnable results are secondary and do not replace the designated population.',
            'Recorded strategy costs include inherited prefix costs; they are estimates/reservations, not an invoice or new-generation spend.',
            'Unknown costs/resources remain incomplete; cost per resolved is undefined when no instance is resolved.',
            'One budget setting supplies quality-cost points, not a multi-budget curve.',
            'The preregistered 5-percentage-point quality tolerance is one of 20 cases and is operational descriptive guidance; it is not an equivalence or noninferiority conclusion.',
        ],
    }


def load_instances(path, *, contents=None):
    """Bind the report to a size-20 manifest sampled from the complete TEST list."""
    plan = json.loads(contents if contents is not None else Path(path).read_bytes())
    if not isinstance(plan, dict):
        raise ValueError('sampling manifest must be a JSON object')
    ids = plan.get('instance_ids')
    if (not isinstance(ids, list) or any(not isinstance(iid, str) or not iid.strip() for iid in ids)
            or len(ids) != INSTANCE_COUNT or len(set(ids)) != len(ids)
            or plan.get('sample_size') != INSTANCE_COUNT or plan.get('population_size') != 300
            or ('instances' in plan and plan['instances'] != ids)):
        raise ValueError('expected a preregistered 20-of-300 test sampling manifest')
    digest = lambda rows: hashlib.sha256(('\n'.join(sorted(rows)) + '\n').encode()).hexdigest()
    population = (ROOT / 'data/frozen/instances_test.txt').read_text(encoding='utf-8').splitlines()
    if (len(population) != 300 or not set(ids).issubset(population)
            or plan.get('population_sha256') != digest(population)
            or plan.get('instance_list_sha256') != digest(ids)):
        raise ValueError('sampling manifest list/population identity mismatch')
    seed = plan.get('seed')
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError('sampling manifest requires an integer seed')
    expected = stratified_sample(population, INSTANCE_COUNT, seed)
    if any(plan.get(field) != value for field, value in expected.items()):
        raise ValueError('sampling manifest does not reproduce its registered stratified algorithm and seed')
    return ids


def validate_preregistration(registration, manifest_path, manifest_bytes, ids):
    """Bind scope, list bytes, sampling seed and generation seed before summary."""
    if not isinstance(registration, dict):
        raise ValueError('preregistration must be a JSON object')
    expected_scope = {
        'kind': 'preregistered_single_run_descriptive', 'split': 'test',
        'population_size': 300, 'sample_size': INSTANCE_COUNT,
        'arms': list(ARMS), 'repeats': 1, 'repeat_index': 0,
        'inference': False, 'statistics': 'descriptive_single_run_no_inference',
    }
    for field, expected in expected_scope.items():
        value = registration.get(field)
        if value != expected or type(value) is not type(expected):
            raise ValueError('preregistration scope mismatch: ' + field)
    for field in ('sampling_seed', 'generation_seed'):
        value = registration.get(field)
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError('preregistration requires an integer ' + field)
    manifest = registration.get('sample_manifest')
    if not isinstance(manifest, str) or not manifest.strip():
        raise ValueError('preregistration requires a sample manifest path')
    registered_path = (ROOT / manifest).resolve()
    if not registered_path.is_relative_to(ROOT / 'runs') or registered_path != Path(manifest_path).resolve():
        raise ValueError('instance manifest path differs from the preregistration')
    plan = json.loads(manifest_bytes)
    if (registration.get('sample_manifest_sha256') != hashlib.sha256(manifest_bytes).hexdigest()
            or registration.get('instance_ids') != ids
            or registration['sampling_seed'] != plan['seed']):
        raise ValueError('instance manifest bytes/list/sampling seed differ from the preregistration')
    return registration['generation_seed']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--records', type=Path, nargs='+', required=True)
    parser.add_argument('--instances', type=Path, required=True)
    parser.add_argument('--preregistration', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    if not out.is_relative_to(ROOT / 'runs') or out.exists():
        parser.error('output must be a new file under runs/')
    try:
        manifest_bytes = args.instances.read_bytes()
        ids = load_instances(args.instances, contents=manifest_bytes)
        registration_bytes = args.preregistration.read_bytes()
        generation_seed = validate_preregistration(json.loads(registration_bytes), args.instances, manifest_bytes, ids)
        record_inputs = [(path, path.read_bytes()) for path in args.records]
        records = [json.loads(line) for path, content in record_inputs
                   for line in content.decode('utf-8').splitlines() if line.strip()]
        report = summarize(records, ids, expected_seed=generation_seed)
    except (ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))
    report['inputs'] = {
        'preregistration': {'path': str(args.preregistration.resolve()),
                            'sha256': hashlib.sha256(registration_bytes).hexdigest()},
        'instance_manifest': {'path': str(args.instances.resolve()),
                              'sha256': hashlib.sha256(manifest_bytes).hexdigest()},
        'evaluated_records': [{'path': str(path.resolve()),
                               'sha256': hashlib.sha256(content).hexdigest()}
                              for path, content in record_inputs],
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
