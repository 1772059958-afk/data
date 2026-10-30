"""Join explicit independent harness reports without altering historical evidence.

New: python scripts/analyse_cf.py --matrix runs/TAG/matrix.json --report A=FILE --report ESC=FILE --out runs/TAG/analysis.json
Legacy: python scripts/analyse_cf.py --tag cf_dev7_v23 (historical diagnostics only)
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from swe_repair import cf
from swe_repair.statistics import primary_summary
from swe_repair.budget import ASPECTS
from swe_repair.evaluation import (validate_provenance, validate_artifact_files, sidecar_path,
                                   frozen_predictions, patch_hash)


def _route(value):
    return value.get('route') if isinstance(value, dict) else value


def _designated(matrix):
    for key in ('designated_instances', 'instance_ids'):
        values = matrix.get(key)
        if isinstance(values, list) and all(isinstance(x, str) for x in values):
            if len(values) != len(set(values)):
                raise ValueError('duplicate designated instance')
            return values
    legacy = 'cases' not in matrix
    if not legacy:
        raise ValueError('new matrices must persist the designated instance list')
    return sorted({x['instance_id'] for x in matrix.get('instances', [])}
                  | {x['instance_id'] for x in matrix.get('failures', [])})


def analyze(matrix: dict, reports: dict[str, dict], provenance: dict | None = None,
            *, historical: bool = False) -> dict:
    """Never use generation completed/error as an evaluator verdict."""
    legacy = 'cases' not in matrix
    if legacy != historical or (legacy and matrix.get('mode') == 'formal'):
        raise ValueError('legacy matrices require explicit historical analysis; current runs require cases')
    provenance = provenance or {}
    if not legacy:
        for arm, report in reports.items():
            validate_provenance(matrix, arm, report, provenance.get(arm))
    cases = matrix.get('cases', matrix.get('instances', []))
    indexed = {}
    for case in cases:
        iid = case['instance_id']
        if iid in indexed:
            raise ValueError('one matrix must contain one repeat per designated instance')
        indexed[iid] = case
    ids = _designated(matrix)
    if not ids:
        raise ValueError('empty designated population')
    if set(indexed) - set(ids):
        raise ValueError('case outside designated list')
    outcomes, records, observations, eligible_prefixes = [], [], [], []
    arms = tuple('ABCDE') if legacy or matrix.get('mode') == 'diagnostic' else (matrix.get('arm', 'D'),)
    prediction_patches = {arm: frozen_predictions(matrix, arm) for arm in arms} if not legacy else {}
    for iid in ids:
        case = indexed.get(iid, {})
        stages = case.get('stages', {})
        routes = case.get('decisions', matrix.get('decisions', {}).get(iid, {}))
        routes = {arm: _route(value) for arm, value in routes.items()}
        if not legacy and case.get('mode', matrix.get('mode')) == 'formal':
            routes[case.get('arm', matrix.get('arm', 'D'))] = case.get('selected_route', routes.get(case.get('arm', matrix.get('arm', 'D'))))
        outcome = cf.InstanceOutcome(iid, dict(case.get('features', {})))
        outcome.routes = routes
        outcome.paired_eligible = case.get('paired_eligible', routes.get('A') != 'stop' if legacy else False)
        def stage(name):
            return case.get(name, {}) if legacy else stages.get(name, {})
        prefix, fixed, inter, solo = (stage(n) for n in ('prefix', 'fixed', 'interactive', 'standalone'))
        outcome.prefix_cost_cny = float(prefix.get('cost_cny') or 0)
        outcome.fixed_cost_cny = float(fixed.get('cost_cny') or 0)
        outcome.interactive_cost_cny = float(inter.get('cost_cny') or 0)
        outcome.standalone_cost_cny = float(solo.get('cost_cny') or 0)
        outcome.router_rules = list(case.get('router_rules', []))
        outcome.prefix_trace = list(case.get('prefix_trace', prefix.get('trace', [])))
        def status(arm):
            return cf.verdict_status(reports.get(arm), iid) if case else 'not_scored'
        outcome.arm_statuses = {a: status(a) for a in arms}
        fixed_status = status('FIXED') if 'FIXED' in reports else status('A')
        outcome.fixed_resolved = cf.resolved_value(fixed_status)
        outcome.interactive_resolved = cf.resolved_value(status('ESC'))
        prefix_status = status('PREFIX') if 'PREFIX' in reports else (status('A') if routes.get('A') == 'stop' else 'not_scored')
        outcome.prefix_resolved = cf.resolved_value(prefix_status)
        outcome.standalone_resolved = cf.resolved_value(status('B'))
        outcomes.append(outcome)
        if (not legacy and matrix.get('split') == 'dev' and outcome.paired_eligible
                and case.get('prefix_snapshot')):
            eligible_prefixes.append({'instance_id': iid, 'prefix_snapshot': case['prefix_snapshot'], 'split': 'dev'})
        if (not legacy and matrix.get('split') == 'dev' and outcome.paired_eligible
                and outcome.quadrant is not None and case.get('prefix_snapshot')):
            observations.append({'instance_id': iid, 'fixed_resolved': outcome.fixed_resolved,
                                 'interactive_resolved': outcome.interactive_resolved,
                                 'prefix_snapshot': case['prefix_snapshot'], 'split': 'dev',
                                 'u_loc': outcome.features.get('u_loc'), 'u_dup': outcome.features.get('u_dup', 0)})
        for arm in arms:
            chosen = routes.get(arm)
            if not legacy and case.get('mode', matrix.get('mode')) == 'formal':
                cost = case.get('policy_cost_cny')
                if cost is None and case:
                    chosen = routes.get(arm)
                    cost = outcome.standalone_cost_cny if arm == 'B' else outcome.prefix_cost_cny + (outcome.interactive_cost_cny if chosen == 'interactive' else outcome.fixed_cost_cny if chosen == 'fixed' else 0)
            else:
                chosen = routes.get(arm)
                cost = (outcome.standalone_cost_cny if arm == 'B' else outcome.prefix_cost_cny +
                        (outcome.interactive_cost_cny if chosen == 'interactive' else outcome.fixed_cost_cny if chosen == 'fixed' else 0)) if case else None
            selected_name = 'standalone' if arm == 'B' else ('prefix' if chosen == 'stop' else chosen)
            selected_stage = stages.get(selected_name, {})
            policy_stages = ([selected_stage] if arm == 'B' or chosen == 'stop'
                             else [prefix, selected_stage])
            # A prefix can fail before the selected continuation starts. Keep
            # its recorded resource lower bound without claiming the absent
            # continuation budget is complete.
            resource_stage = selected_stage or (prefix if arm != 'B' else {})
            consumed = resource_stage.get('budget', {}).get('consumed', {})
            decision = case.get('decisions', {}).get(arm, {})
            stop_reason = decision.get('reason') if chosen == 'stop' and isinstance(decision, dict) else None
            reason = (stop_reason or selected_stage.get('termination_reason') or selected_stage.get('ended_by')
                      or case.get('termination_reason'))
            generation_status = selected_stage.get('status', case.get('status', 'missing_case'))
            if stop_reason in ('stop_env_failure', 'stop_budget_insufficient'):
                generation_status = {'stop_env_failure': 'environment_error',
                                     'stop_budget_insufficient': 'budget_exhausted'}[stop_reason]
            elif chosen is None and arm == 'E' and case.get('decisions'):
                # E is deliberately undefined during pending dev calibration.
                generation_status, reason = 'not_run', 'random_probability_pending'
            diff = prediction_patches.get(arm, {}).get(iid)
            unknown_usage = any(r.get('billing') == 'unknown' for item in policy_stages
                                for r in item.get('calls', []) + item.get('events', []))
            records.append({'instance_id': iid, 'repeat_index': case.get('repeat_index', matrix.get('repeat_index', 0)),
                            'seed': case.get('seed', matrix.get('seed')), 'run_id': matrix.get('tag'),
                            'mode': 'legacy_diagnostic' if legacy else case.get('mode', matrix.get('mode')),
                            'config_hash': case.get('config_hash', matrix.get('config_hash')),
                            'arm': arm, 'status': status(arm), 'cost_cny': cost,
                            'prediction_sha256': provenance.get(arm, {}).get('predictions_sha256'),
                            'patch_sha256': patch_hash(diff) if diff is not None else None,
                            'resources': {aspect: consumed.get(aspect) for aspect in ASPECTS},
                            'resources_complete': {aspect: bool(selected_stage) and consumed.get(aspect) is not None
                                                   and (aspect != 'token' or not unknown_usage)
                                                   for aspect in ASPECTS},
                            'termination_reason': reason,
                            'generation_status': generation_status,
                            'cost_complete': bool(case) and all(policy_stages) and not unknown_usage})
    # Actual groups are distinct from an unconditional use of the ESC diagnostic.
    scores = [cf.score_actual_policy(f'{a}_actual', outcomes, a).to_dict() for a in arms]
    summaries = {a: primary_summary([dict(r, repeat_index=0) for r in records if r['arm'] == a], ids) for a in arms}
    eligible = [o for o in outcomes if o.paired_eligible]
    paired = [o for o in eligible if o.quadrant is not None]
    prefix_unavailable = [iid for iid in ids if not indexed.get(iid, {}).get('prefix_snapshot')
                          or indexed[iid].get('stages', {}).get('prefix', {}).get('status') == 'generation_error'
                          or any(event.get('step') == 'prefix_error'
                                 for event in indexed[iid].get('stages', {}).get('prefix', {}).get('trace', []))]
    gap = None
    if paired:
        f = cf.score_policy('paired_fixed', paired, lambda o: False)
        d = cf.score_policy('paired_D', paired, lambda o: o.routes.get('D') == 'interactive')
        oracle = cf.score_policy('oracle_diagnostic_upper_bound', paired, cf.build_policies()['oracle'])
        if all(o.routes.get('D') in ('fixed', 'interactive') for o in paired):
            gap = cf.oracle_gap_closure(f, d, oracle)
    return {'historical_diagnostic_only': legacy, 'mode': matrix.get('mode', 'legacy_diagnostic'),
            'config_hash': matrix.get('config_hash'),
            'effective_config': matrix.get('effective_config'),
            'designated_instances': ids, 'scored_instances': len(paired),
            'split': matrix.get('split', 'legacy'), 'observations': observations,
            'eligible_prefixes': eligible_prefixes,
            'eligible_instance_ids': [o.instance_id for o in eligible],
            'eligible_population_complete': not legacy and not prefix_unavailable,
            'prefix_unavailable_instance_ids': prefix_unavailable,
            'paired_eligible': len(eligible), 'paired_complete': len(paired),
            'unscored_paired_instances': [o.instance_id for o in eligible if o.quadrant is None],
            'primary_summaries': summaries, 'policies': scores,
            'quadrants': cf.quadrant_table(eligible), 'features': cf.feature_report(paired),
            'oracle_gap_closure_paired_complete_diagnostic_only': gap,
            'diagnostic_cost_cny': float(matrix.get('spent_cny', 0)) if legacy else sum(float(c.get('diagnostic_cost_cny', 0)) for c in cases),
            'records': records,
            'arm_equivalence': {a: {'identical_to_C': (all(o.routes.get(a) == o.routes.get('C') for o in outcomes) if all(o.routes.get(a) and o.routes.get('C') for o in outcomes) else None),
                                    'escalations': sum(o.routes.get(a) == 'interactive' for o in outcomes)}
                                for a in ('C', 'D', 'E') if a in arms},
            'notes': ['Unknown verdicts remain not_scored. Final rates require complete evaluator coverage.',
                      'Paired metrics are diagnostic complete-case results; their denominator is not the primary population.',
                      'Legacy generations cannot become proposal-aligned formal evidence through reanalysis.']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument('--matrix', type=Path)
    source.add_argument('--tag')
    p.add_argument('--report', action='append', default=[], metavar='ARM=PATH')
    p.add_argument('--provenance', action='append', default=[], metavar='ARM=PATH',
                   help='scoring sidecar; defaults to REPORT.provenance.json for each current report')
    p.add_argument('--out', type=Path)
    p.add_argument('--records-out', type=Path, help='optional evaluated JSONL for formal repeat aggregation')
    args = p.parse_args()
    if args.tag and (not args.tag.replace('_', '').replace('-', '').isalnum()):
        p.error('invalid historical tag')
    matrix_path = args.matrix or ROOT / 'reports' / f'{args.tag}_matrix.json'
    reports, sources, provenances = {}, [], {}
    sidecars = {}
    for spec in args.provenance:
        arm, separator, path = spec.partition('=')
        if not separator or arm in sidecars:
            p.error('provenance must be a unique ARM=PATH')
        sidecars[arm] = Path(path)
    specs = list(args.report)
    if args.tag and not specs:
        specs = [f'{arm}={ROOT / "reports" / (args.tag + "-" + arm + "." + args.tag + ".json")}'
                 for arm in ('A', 'B', 'C', 'D', 'E', 'ESC')]
    for spec in specs:
        arm, separator, path = spec.partition('=')
        if not separator or arm not in ('A', 'B', 'C', 'D', 'E', 'FIXED', 'ESC', 'PREFIX'):
            p.error('report must be ARM=PATH with an actual arm or branch label')
        if arm in reports:
            p.error(f'duplicate report for {arm}')
        path = Path(path)
        if args.tag and not path.exists():
            continue
        payload = path.read_bytes()
        reports[arm] = json.loads(payload)
        sources.append({'arm': arm, 'path': str(path.resolve()), 'sha256': hashlib.sha256(payload).hexdigest()})
        if not args.tag:
            provenance_path = sidecars.get(arm, sidecar_path(path))
            try:
                provenance_bytes = provenance_path.read_bytes()
                provenances[arm] = json.loads(provenance_bytes)
                validate_artifact_files(matrix_path, path, arm, provenances[arm])
            except (ValueError, OSError) as exc:
                p.error(str(exc))
            sources[-1]['provenance_path'] = str(provenance_path.resolve())
            sources[-1]['provenance_sha256'] = hashlib.sha256(provenance_bytes).hexdigest()
    if set(sidecars) - set(reports):
        p.error('provenance supplied without its report')
    matrix = json.loads(matrix_path.read_text(encoding='utf-8'))
    analysis = analyze(matrix, reports, provenances, historical=bool(args.tag))
    analysis['source_reports'] = sources
    analysis['source_matrix_sha256'] = hashlib.sha256(matrix_path.read_bytes()).hexdigest()
    out = (args.out or (ROOT / 'runs/legacy_analysis' / f'{args.tag}_analysis.json' if args.tag else matrix_path.parent / 'analysis.json')).resolve()
    if not out.is_relative_to(ROOT / 'runs'):
        p.error('analysis output must be under runs/, never overwrite original reports/data')
    if out.exists():
        p.error('refusing to replace an existing analysis')
    records_out = args.records_out.resolve() if args.records_out else None
    if records_out and (not records_out.is_relative_to(ROOT / 'runs') or records_out.exists() or records_out == out):
        p.error('records output must be a distinct new file under runs/')
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('x', encoding='utf-8') as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)
    if records_out:
        records_out.parent.mkdir(parents=True, exist_ok=True)
        with records_out.open('x', encoding='utf-8') as f:
            for row in analysis['records']:
                f.write(json.dumps(row, ensure_ascii=False) + '\n')
    print(f'primary instances: {len(analysis["designated_instances"])}; eligible pairs: {analysis["paired_eligible"]}; complete pairs: {analysis["paired_complete"]}')
    print(out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
