"""Read generation artifacts only; write audit after all five pilot arms finish."""
from __future__ import annotations
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from swe_repair.router import RouterConfig

IDS = ['pvlib__pvlib-python-1707', 'pydicom__pydicom-1139']
IDENTITIES = {
    IDS[0]: {'image_id': 'sha256:6bddca9c6360684b088cba4a502969e84c3a2f125550983e48e38e2e252b660c',
             'base_commit': '40e9e978c170bdde4eeee1547729417665dbc34c'},
    IDS[1]: {'image_id': 'sha256:bd5edf8694cde12aaf99beb18b3935b15e076e81ac7e52aef46b1ca3d9071428',
             'base_commit': 'b9fb05c177b685bf683f7f57b2d57374eb7d882d'},
}
ASPECTS = ('token', 'model_call', 'tool_call', 'wallclock_seconds')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    out = ROOT / 'runs/dev2_acceptance_20261106/pilot_execution_audit.json'
    if out.exists():
        raise ValueError('refusing to replace existing final audit')
    sources, matrices, predictions = {}, {}, {}
    for arm in 'ABCDE':
        run = ROOT / f'runs/dev2_pilot_{arm}_20261106_01'
        matrix_path, prediction_path = run / 'matrix.json', run / f'predictions_{arm}.jsonl'
        if not matrix_path.is_file() or not prediction_path.is_file():
            print(f'WAIT: {arm} matrix/predictions unavailable')
            return 3
        matrix = json.loads(matrix_path.read_text(encoding='utf-8'))
        rows = [json.loads(line) for line in prediction_path.read_text(encoding='utf-8').splitlines() if line.strip()]
        if (len(matrix.get('cases', [])) != 2 or len(rows) != 2
                or any(case.get('status') == 'running' for case in matrix['cases'])):
            print(f'WAIT: {arm} has not completed its two cells')
            return 3
        matrices[arm], predictions[arm] = matrix, rows
        sources[str(matrix_path.relative_to(ROOT))] = file_sha(matrix_path)
        sources[str(prediction_path.relative_to(ROOT))] = file_sha(prediction_path)
    ledger_path = ROOT / 'runs/dev2_acceptance_20261106/batch_ledger.json'
    ledger = json.loads(ledger_path.read_text(encoding='utf-8'))
    if ledger.get('pending') is not None:
        print('WAIT: batch ledger still has an unreconciled request')
        return 3
    sources[str(ledger_path.relative_to(ROOT))] = file_sha(ledger_path)
    findings = []

    def check(condition, code, **details):
        if not condition:
            findings.append({'code': code, **details})
        return bool(condition)

    first = matrices['A']
    cfg = first['effective_config']
    tiers = {tier['tier']: {aspect: tier[aspect] for aspect in ASPECTS} for tier in cfg['budget_tiers']}
    ceiling = tiers[cfg['active_tier']]
    interaction = cfg['interaction']
    money_cap = cfg['execution']['per_instance_cny']
    check(money_cap == 2, 'unexpected_single_instance_money_cap', actual=money_cap)
    check(cfg['execution']['total_cny'] == 100, 'unexpected_batch_money_cap')
    check(cfg['status'] == 'draft-pending-calibration', 'pilot_promoted_to_formal_status')
    cells, indexed = [], {}
    for arm, matrix in matrices.items():
        check(matrix['mode'] == 'pilot' and matrix['arm'] == arm and matrix['split'] == 'dev',
              'wrong_pilot_identity', arm=arm)
        check(matrix['designated_instances'] == IDS, 'designated_population_differs', arm=arm)
        check(matrix['config_hash'] == first['config_hash'], 'configuration_hash_differs', arm=arm)
        check(RouterConfig.from_config(matrix['effective_config']).digest == matrix['config_hash'],
              'effective_configuration_hash_invalid', arm=arm)
        check(matrix['effective_config'] == cfg, 'effective_configuration_differs', arm=arm)
        check(matrix['seed'] == first['seed'] and matrix['repeat_index'] == first['repeat_index'],
              'seed_or_repeat_differs', arm=arm)
        check(bool(matrix.get('formal_readiness_errors')), 'formal_freeze_errors_erased', arm=arm)
        cases = {case['instance_id']: case for case in matrix['cases']}
        check(len(cases) == 2 and set(cases) == set(IDS), 'case_population_differs', arm=arm)
        predicted = {row['instance_id']: row['model_patch'] for row in predictions[arm]}
        check(len(predicted) == 2 and set(predicted) == set(IDS), 'prediction_population_differs', arm=arm)
        for iid, case in cases.items():
            indexed[arm, iid] = case
            loc = {'arm': arm, 'instance_id': iid}
            stages, selected = case['stages'], case['selected_route']
            prefix = stages.get('prefix')
            selected_stage = stages.get('prefix' if selected == 'stop' else selected, {})
            expected_stages = {'standalone'} if arm == 'B' else ({'prefix'} if selected == 'stop' else {'prefix', selected})
            check(set(stages) == expected_stages, 'unselected_branch_executed', **loc, actual=list(stages), selected=selected)
            check(case['config_hash'] == matrix['config_hash'] and case['seed'] == matrix['seed']
                  and case['repeat_index'] == matrix['repeat_index'] and case['arm'] == arm,
                  'case_identity_differs', **loc)
            check(case['image_digest'] == IDENTITIES[iid]['image_id'], 'image_differs', **loc)
            check(cfg['execution']['images'].get(iid) == IDENTITIES[iid]['image_id'],
                  'configured_image_differs', **loc)
            starts = [event for event in case['lifecycle'] if event['event'] == 'start']
            closes = [event for event in case['lifecycle'] if event['event'] == 'close']
            started_names = {event['container'] for event in starts}
            closed_names = {event['container'] for event in closes if event.get('error') is None}
            cleanup_ok = started_names == closed_names and not case.get('cleanup_errors')
            check(cleanup_ok, 'container_cleanup_not_confirmed_by_lifecycle', **loc)
            for event in starts:
                check(event['image_digest'] == IDENTITIES[iid]['image_id']
                      and event['base_commit'] == IDENTITIES[iid]['base_commit'],
                      'lifecycle_image_or_base_differs', **loc, stage=event['stage'])
            check(len(started_names) == len(starts) and len(starts) == len(expected_stages)
                  and {event['stage'] for event in starts} == expected_stages,
                  'fresh_container_per_executed_stage_not_proven', **loc)
            for stage_name, stage in stages.items():
                task = stage['state']['task_manifest']
                check(task['instance_id'] == iid and task['base_commit'] == IDENTITIES[iid]['base_commit']
                      and task['config_hash'] == matrix['config_hash'], 'stage_task_identity_differs', **loc, stage=stage_name)
                budget = stage['budget']
                check(budget['ceiling'] == ceiling, 'global_resource_ceiling_differs', **loc, stage=stage_name)
                for aspect in ASPECTS:
                    check(0 <= budget['consumed'][aspect] <= ceiling[aspect] + 1e-8,
                          'global_resource_ceiling_exceeded', **loc, stage=stage_name, aspect=aspect,
                          consumed=budget['consumed'][aspect], ceiling=ceiling[aspect])
                check(not budget.get('overrun'), 'global_resource_overrun_marked', **loc, stage=stage_name)
                check(math.isclose(sum(float(call['cost_cny']) for call in stage['calls']),
                                   stage['cost_cny'], abs_tol=1e-9), 'stage_cost_does_not_match_booked_calls', **loc, stage=stage_name)
            prefix_cost = float(prefix['cost_cny']) if prefix else 0.0
            branch_cost = float(stages[selected]['cost_cny']) if selected != 'stop' else 0.0
            expected_cost = prefix_cost + branch_cost
            check(math.isclose(case['policy_cost_cny'], expected_cost, abs_tol=1e-9),
                  'policy_did_not_inherit_full_prefix_cost', **loc, actual=case['policy_cost_cny'], expected=expected_cost)
            check(0 <= case['policy_cost_cny'] <= money_cap + 1e-9, 'single_instance_money_ceiling_exceeded', **loc)
            expected_new = expected_cost - (prefix_cost if case.get('prefix_reused') else 0)
            check(math.isclose(case['new_generation_cost_cny'], expected_new, abs_tol=1e-9),
                  'new_generation_cost_incorrect', **loc)
            check(case['submitted_patch'] == selected_stage.get('patch') == predicted.get(iid),
                  'submitted_prediction_differs_from_selected_candidate', **loc)
            session = None
            if selected in ('interactive', 'standalone'):
                used = selected_stage['budget']['consumed']
                inherited = prefix['budget']['consumed'] if selected == 'interactive' else {a: 0 for a in ASPECTS}
                session = {aspect: used[aspect] - inherited[aspect] for aspect in ASPECTS}
                session['named_tool_calls'] = selected_stage.get('named_tool_calls')
                check(session['model_call'] <= interaction['model_calls'], 'interaction_model_call_ceiling_exceeded', **loc)
                check(session['named_tool_calls'] is not None and session['named_tool_calls'] <= interaction['tool_calls'],
                      'interaction_named_tool_ceiling_exceeded', **loc)
                check(session['wallclock_seconds'] <= interaction['wallclock_seconds'] + 1e-8,
                      'interaction_wallclock_ceiling_exceeded', **loc)
            if arm == 'B':
                check(prefix is None and case.get('prefix_snapshot') is None and not case.get('prefix_reused')
                      and selected == 'standalone' and not case.get('decisions'), 'B_did_not_start_independently', **loc)
            else:
                check(case.get('prefix_snapshot') == prefix['state'], 'snapshot_does_not_equal_real_prefix_state', **loc)
                check(case['decisions'][arm]['route'] == selected, 'selected_route_differs_from_policy_decision', **loc)
                if arm in 'CDE':
                    check(case.get('prefix_reused') is True, 'shared_prefix_cache_was_not_reused', **loc)
            cells.append({**loc, 'status': case['status'], 'termination_reason': case['termination_reason'],
                'selected_route': selected, 'executed_stages': list(stages), 'image_id': case['image_digest'],
                'base_commit': IDENTITIES[iid]['base_commit'], 'prefix_reused': case.get('prefix_reused', False),
                'policy_cost_cny': case['policy_cost_cny'], 'inherited_prefix_cost_cny': prefix_cost,
                'new_generation_cost_cny': case['new_generation_cost_cny'],
                'global_resource_consumed': selected_stage['budget']['consumed'],
                'interaction_session_consumed': session, 'cleanup_lifecycle_ok': cleanup_ok,
                'container_names': sorted(started_names), 'prediction_patch_sha256': hashlib.sha256(case['submitted_patch'].encode()).hexdigest()})
        booked = sum(float(row['cost_cny']) for row in ledger['records'] if row.get('run_id') == matrix['tag'])
        check(math.isclose(matrix['new_generation_cost_cny'], booked, abs_tol=1e-9),
              'matrix_new_spend_differs_from_cumulative_ledger', arm=arm,
              matrix_new=matrix['new_generation_cost_cny'], ledger_booked=booked)
    shared = {}
    for iid in IDS:
        stage_hashes = {arm: digest(indexed[arm, iid]['stages']['prefix']) for arm in 'ACDE'}
        snapshot_hashes = {arm: digest(indexed[arm, iid]['prefix_snapshot']) for arm in 'ACDE'}
        check(len(set(stage_hashes.values())) == 1, 'shared_complete_prefix_stage_hash_differs', instance_id=iid)
        check(len(set(snapshot_hashes.values())) == 1, 'shared_prefix_snapshot_hash_differs', instance_id=iid)
        shared[iid] = {'complete_stage_hashes': stage_hashes, 'snapshot_hashes': snapshot_hashes,
                       'hash_scheme': 'SHA256 of UTF-8 canonical JSON: sorted keys, compact separators, ensure_ascii=false'}
    spent = sum(float(row['cost_cny']) for row in ledger['records'])
    check(ledger['ceiling_cny'] == 100 and spent <= 100, 'cumulative_money_ceiling_exceeded_or_changed')
    check(ledger.get('pending') is None, 'unreconciled_batch_reservation')
    for relative, expected in sources.items():
        if file_sha(ROOT / relative) != expected:
            raise RuntimeError('generation artifact changed during audit: ' + relative)
    result = {'kind': 'generation_only_pilot_execution_audit', 'date': '2026-11-06',
        'scope': '2 designated dev instances x 5 actual pilot arms x 1 repeat; no scoring artifacts read',
        'passed': not findings, 'findings': findings, 'cell_count': len(cells),
        'expected_cell_count': 10, 'config_hash': first['config_hash'], 'seed': first['seed'],
        'repeat_index': first['repeat_index'], 'formal_status': cfg['status'],
        'global_resource_ceiling': ceiling, 'interaction_session_ceiling': {k: interaction[k] for k in ('model_calls','tool_calls','wallclock_seconds','final_call')},
        'per_instance_cny': money_cap, 'shared_prefix': shared, 'cells': cells,
        'policy_cost_cny_by_arm': {arm: sum(c['policy_cost_cny'] for c in matrices[arm]['cases']) for arm in 'ABCDE'},
        'pilot_new_generation_cost_cny': sum(m['new_generation_cost_cny'] for m in matrices.values()),
        'cumulative_ledger': {'path': str(ledger_path.relative_to(ROOT)), 'sha256': file_sha(ledger_path),
            'ceiling_cny': ledger['ceiling_cny'], 'booked_cny': spent, 'pending': ledger.get('pending'),
            'record_count': len(ledger['records']), 'billing_counts': dict(Counter(row.get('billing') for row in ledger['records'])),
            'cost_interpretation': 'usage-based estimates and retained conservative unknown reservations; not invoiced payment'},
        'source_file_sha256': sources, 'audit_script_sha256': file_sha(Path(__file__)),
        'limitations': ['Cleanup is verified from generation lifecycle records, not an additional Docker inspection.',
            'The entire audit uses generation matrices, predictions and the cumulative ledger; no scoring reports, hidden patches, logs, credentials or model calls.',
            'This is a small provisional dev pilot, not formal calibration or a three-repeat statistical experiment.']}
    check(len(cells) == 10, 'wrong_cell_count')
    # Ensure the late cell-count check is reflected in the final flag.
    result['passed'] = not findings
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(out), 'passed': result['passed'], 'cells': len(cells),
                      'findings': findings, 'pilot_new_generation_cost_cny': result['pilot_new_generation_cost_cny'],
                      'cumulative_booked_cny': spent}, ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
