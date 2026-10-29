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


def analyze(matrix: dict, reports: dict[str, dict]) -> dict:
    """Never use generation completed/error as an evaluator verdict."""
    legacy = 'cases' not in matrix
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
    outcomes, records, observations = [], [], []
    arms = tuple('ABCDE') if legacy or matrix.get('mode') == 'diagnostic' else tuple(sorted({c.get('arm', matrix.get('arm', 'D')) for c in cases}))
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
                and outcome.quadrant is not None and case.get('prefix_snapshot')):
            observations.append({'instance_id': iid, 'fixed_resolved': outcome.fixed_resolved,
                                 'interactive_resolved': outcome.interactive_resolved,
                                 'prefix_snapshot': case['prefix_snapshot'], 'split': 'dev',
                                 'u_loc': outcome.features.get('u_loc'), 'u_dup': outcome.features.get('u_dup', 0)})
        for arm in arms:
            if not legacy and case.get('mode', matrix.get('mode')) == 'formal':
                cost = case.get('policy_cost_cny')
                if cost is None and case:
                    chosen = routes.get(arm)
                    cost = outcome.standalone_cost_cny if arm == 'B' else outcome.prefix_cost_cny + (outcome.interactive_cost_cny if chosen == 'interactive' else outcome.fixed_cost_cny if chosen == 'fixed' else 0)
            else:
                chosen = routes.get(arm)
                cost = (outcome.standalone_cost_cny if arm == 'B' else outcome.prefix_cost_cny +
                        (outcome.interactive_cost_cny if chosen == 'interactive' else outcome.fixed_cost_cny if chosen == 'fixed' else 0)) if case else None
            records.append({'instance_id': iid, 'repeat_index': case.get('repeat_index', matrix.get('repeat_index', 0)),
                            'mode': case.get('mode', matrix.get('mode', 'legacy_diagnostic')),
                            'config_hash': case.get('config_hash', matrix.get('config_hash')),
                            'arm': arm, 'status': status(arm), 'cost_cny': cost,
                            'generation_status': case.get('status', 'missing_case'),
                            'cost_complete': bool(case) and not any(
                                r.get('billing') == 'unknown'
                                for stage in stages.values()
                                for r in stage.get('calls', []) + stage.get('events', []))})
    # Actual groups are distinct from an unconditional use of the ESC diagnostic.
    scores = [cf.score_actual_policy(f'{a}_actual', outcomes, a).to_dict() for a in arms]
    summaries = {a: primary_summary([dict(r, repeat_index=0) for r in records if r['arm'] == a], ids) for a in arms}
    eligible = [o for o in outcomes if o.paired_eligible]
    paired = [o for o in eligible if o.quadrant is not None]
    gap = None
    if paired:
        f = cf.score_policy('paired_fixed', paired, lambda o: False)
        d = cf.score_policy('paired_D', paired, lambda o: o.routes.get('D') == 'interactive')
        oracle = cf.score_policy('oracle_diagnostic_upper_bound', paired, cf.build_policies()['oracle'])
        if all(o.routes.get('D') in ('fixed', 'interactive') for o in paired):
            gap = cf.oracle_gap_closure(f, d, oracle)
    return {'historical_diagnostic_only': legacy, 'mode': matrix.get('mode', 'legacy_diagnostic'),
            'designated_instances': ids, 'scored_instances': len(paired),
            'split': matrix.get('split', 'legacy'), 'observations': observations,
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
    p.add_argument('--out', type=Path)
    p.add_argument('--records-out', type=Path, help='optional evaluated JSONL for formal repeat aggregation')
    args = p.parse_args()
    if args.tag and (not args.tag.replace('_', '').replace('-', '').isalnum()):
        p.error('invalid historical tag')
    matrix_path = args.matrix or ROOT / 'reports' / f'{args.tag}_matrix.json'
    reports, sources = {}, []
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
    matrix = json.loads(matrix_path.read_text(encoding='utf-8'))
    analysis = analyze(matrix, reports)
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
