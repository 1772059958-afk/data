"""Proposal runner. Default is an offline plan; explicit authorization gates live work."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import math
import subprocess
import platform
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from swe_repair.router import RouterConfig


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


SINGLE_RUN_DESIGN = 'preregistered_single_run_descriptive'


def single_run_design_errors(raw):
    """Bind the user-requested 20 x A-E x 1 design to its offline registration.

    This changes the repetition design only. Calibration, freeze declarations,
    credentials and paid authorization retain their independent checks.
    """
    evaluation, scope = raw.get('evaluation', {}), raw.get('execution', {})
    errors = []
    if (evaluation.get('design') != SINGLE_RUN_DESIGN or type(evaluation.get('repeats')) is not int
            or evaluation.get('repeats') != 1
            or evaluation.get('inference') is not False
            or evaluation.get('statistics') != 'descriptive_single_run_no_inference'):
        errors.append('single-run design requires one descriptive repetition without inference')
    try:
        def registered_file(key, hash_key):
            path = Path(evaluation.get(key, ''))
            if not path.is_absolute():
                path = ROOT / path
            path = path.resolve()
            if (not path.is_relative_to(ROOT / 'runs') or not path.is_file()
                    or file_hash(path) != evaluation.get(hash_key)):
                raise ValueError(key + ' is missing, outside runs, or has changed')
            return json.loads(path.read_text(encoding='utf-8'))
        sample = registered_file('sample_manifest', 'sample_manifest_sha256')
        registration = registered_file('preregistration', 'preregistration_sha256')
        from swe_repair.statistics import stratified_sample
        population = (ROOT / 'data/frozen/instances_test.txt').read_text(encoding='utf-8').splitlines()
        seed = registration.get('sampling_seed')
        if not isinstance(seed, int) or isinstance(seed, bool):
            raise ValueError('registration needs an integer sampling seed')
        expected = stratified_sample(population, 20, seed)
        if any(sample.get(key) != value for key, value in expected.items()):
            raise ValueError('single-run sample differs from full-test stratified registration')
        if (registration.get('kind') != SINGLE_RUN_DESIGN or registration.get('split') != 'test'
                or registration.get('arms') != list('ABCDE') or type(registration.get('repeats')) is not int
                or registration.get('repeats') != 1 or type(registration.get('repeat_index')) is not int
                or registration.get('repeat_index') != 0 or registration.get('sample_size') != 20
                or registration.get('inference') is not False
                or registration.get('sample_manifest') != evaluation.get('sample_manifest')
                or registration.get('sample_manifest_sha256') != evaluation.get('sample_manifest_sha256')
                or registration.get('instance_ids') != sample['instance_ids']
                or registration.get('generation_seed') != evaluation.get('generation_seed')
                or not isinstance(evaluation.get('generation_seed'), int)
                or isinstance(evaluation.get('generation_seed'), bool)):
            raise ValueError('single-run registration identity or scope differs')
        if (evaluation.get('instance_list') != evaluation.get('sample_manifest')
                or scope.get('allowed_modes') != ['formal'] or scope.get('allowed_splits') != ['test']
                or scope.get('allowed_instances') != sample['instance_ids']
                or scope.get('max_instances') != 20):
            raise ValueError('single-run configuration must be restricted to the registered 20 test cases')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append('single-run preregistration invalid: ' + str(exc))
    return errors


def frozen_config_errors(raw):
    """All formal freeze declarations must agree; numeric defaults are not evidence."""
    errors = []
    if raw.get('status') != 'frozen':
        errors.append('overall status is not frozen')
    for section in ('model', 'prefix', 'router', 'fixed_continuation'):
        if raw.get(section, {}).get('calibration') != 'frozen':
            errors.append(f'{section}.calibration is not frozen')
    for section in ('candidate_selection', 'evaluation'):
        if raw.get(section, {}).get('frozen') is not True:
            errors.append(f'{section}.frozen is not true')
    if not raw.get('model', {}).get('model_version'):
        errors.append('served model version is not pinned')
    router = raw.get('router', {})
    if any(router.get(k) is None for k in ('localization_disagreement_threshold', 'duplicate_rate_threshold', 'switch_probability')):
        errors.append('router thresholds or matched switch probability are pending')
    if raw.get('evaluation', {}).get('design') == SINGLE_RUN_DESIGN:
        errors.extend(single_run_design_errors(raw))
    elif raw.get('evaluation', {}).get('repeats', 0) < 3:
        errors.append('formal evaluation requires at least three repeats')
    if not raw.get('prompt_version'):
        errors.append('prompt version is missing')
    return errors


def validate_development_contract(raw):
    fixed = raw.get('fixed_continuation', {})
    if (not isinstance(fixed.get('max_candidates'), int) or isinstance(fixed['max_candidates'], bool)
            or fixed['max_candidates'] < 1 or fixed.get('feedback') != 'structured'
            or fixed.get('stop_on_public_pass') is not True):
        raise ValueError('fixed continuation must have a positive candidate limit, structured feedback and public-pass early stop')
    for key in ('model_calls', 'tool_calls', 'wallclock_seconds'):
        value = raw['interaction'].get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'interaction.{key} must be positive and finite')
    for key in ('total_cny', 'per_instance_cny'):
        value = raw['execution'].get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'execution.{key} must be positive and finite')


def validate_pilot_candidate(raw, ids):
    """Bind provisional routing to its audited DEV population and execution setup.

    The candidate remains provisional. This validates the existing calibration
    artifact schema rather than converting a small pilot into a formal freeze.
    """
    from swe_repair.calibration import calibration_inputs
    review = raw.get('pilot', {})
    candidate_path = ROOT / review.get('calibration_candidate', '')
    if (not candidate_path.resolve().is_relative_to(ROOT / 'runs') or not candidate_path.is_file()
            or file_hash(candidate_path) != review.get('candidate_sha256')):
        raise ValueError('pilot needs an audited independent DEV calibration candidate')
    candidate = json.loads(candidate_path.read_text(encoding='utf-8'))
    proposed_config = candidate.get('candidate_config')
    if (candidate.get('status') != 'candidate_requires_review_and_freeze'
            or not isinstance(proposed_config, dict)):
        raise ValueError('pilot needs an actual DEV candidate configuration')
    proposed = RouterConfig.from_config(proposed_config)
    if proposed.digest != candidate.get('candidate_config_hash'):
        raise ValueError('pilot candidate configuration hash differs')
    source = candidate.get('calibration_source', {})
    source_path = Path(source.get('path', ''))
    if not source_path.is_absolute(): source_path = ROOT / source_path
    if (not source_path.resolve().is_relative_to(ROOT / 'runs') or not source_path.is_file()
            or file_hash(source_path) != source.get('sha256')):
        raise ValueError('pilot calibration source is missing or changed')
    analysis = json.loads(source_path.read_text(encoding='utf-8'))
    source_config = analysis.get('effective_config')
    if not isinstance(source_config, dict) or source.get('config_hash') != analysis.get('config_hash'):
        raise ValueError('pilot calibration source configuration identity differs')
    original = RouterConfig.from_config(source_config)
    inputs = calibration_inputs(analysis, original,
        allowed_ids=(ROOT / 'data/frozen/instances_dev.txt').read_text(encoding='utf-8').splitlines())
    if set(ids) - set(analysis.get('designated_instances', [])):
        raise ValueError('pilot instances lie outside the complete designated DEV diagnostic')
    if (len(inputs.observations) < 1
            or source.get('complete_pair_count') != len(inputs.observations)
            or source.get('eligible_count') != len(inputs.eligible_prefixes)
            or source.get('missing_pair_ids') != list(inputs.missing_pair_ids)):
        raise ValueError('pilot calibration source counts differ from its full DEV population')
    chosen = candidate.get('chosen', {})
    if (chosen.get('localization_threshold') != proposed.localization_disagreement_threshold
            or chosen.get('duplicate_threshold') != proposed.duplicate_rate_threshold):
        raise ValueError('pilot thresholds differ from the selected DEV grid candidate')
    matching = inputs.trigger_rate(proposed)
    if (candidate.get('trigger_rate_matching') != matching
            or candidate.get('matched_switch_probability') != matching['probability']
            or proposed.switch_probability != matching['probability']):
        raise ValueError('pilot E probability differs from the full eligible DEV trigger rate')
    for section in ('model', 'prefix', 'interaction', 'fixed_continuation', 'budget_tiers',
                    'prompt_version', 'active_tier', 'candidate_selection'):
        if (proposed_config.get(section) != raw.get(section)
                or proposed_config.get(section) != source_config.get(section)):
            raise ValueError('pilot changed calibrated execution setting: ' + section)
    calibrated = {'localization_disagreement_threshold', 'duplicate_rate_threshold', 'switch_probability'}
    router_setup = lambda config: {key: value for key, value in config.get('router', {}).items()
                                  if key not in calibrated}
    if router_setup(raw) != router_setup(proposed_config) or router_setup(proposed_config) != router_setup(source_config):
        raise ValueError('pilot changed the DEV routing rule order or continuation setup')
    for key in calibrated:
        if proposed_config['router'].get(key) != raw['router'].get(key):
            raise ValueError('pilot routing differs from the actual DEV candidate')
    for key in ('total_cny', 'per_instance_cny', 'tool_call_unit', 'environment_retries',
                'environment_recovery', 'modify_scope', 'prompt_estimator', 'docker_context',
                'images', 'credential_source', 'batch_ledger'):
        values = [config.get('execution', {}).get(key) for config in (raw, proposed_config, source_config)]
        if values[0] != values[1] or values[1] != values[2]:
            raise ValueError('pilot changed calibrated execution setting: execution.' + key)


def load_plan(args):
    cfgpath = Path(args.config)
    if not cfgpath.is_absolute(): cfgpath = ROOT / cfgpath
    raw = json.loads(cfgpath.read_text(encoding='utf-8'))
    validate_development_contract(raw)
    listing = Path(args.instances_file) if args.instances_file else ROOT / f'data/frozen/instances_{args.split}.txt'
    if not listing.is_absolute(): listing = ROOT / listing
    text = listing.read_text(encoding='utf-8')
    ids = json.loads(text)['instance_ids'] if listing.suffix == '.json' else [s.strip() for s in text.splitlines() if s.strip()]
    full = set((ROOT / f'data/frozen/instances_{args.split}.txt').read_text(encoding='utf-8').splitlines())
    if not ids or len(ids) != len(set(ids)) or set(ids) - full:
        raise ValueError('empty, duplicate or out-of-split instance selection')
    if args.repeat_index < 0: raise ValueError('repeat-index must be nonnegative')
    if args.calibration and (args.split != 'dev' or args.mode != 'diagnostic'):
        raise ValueError('calibration is allowed only for dev diagnostics')
    if args.mode == 'pilot' and args.split != 'dev':
        raise ValueError('pilot interface runs are restricted to dev')
    if raw.get('evaluation', {}).get('design') == SINGLE_RUN_DESIGN:
        problems = single_run_design_errors(raw)
        if problems:
            raise ValueError('; '.join(problems))
        if (args.mode != 'formal' or args.split != 'test' or args.repeat_index != 0
                or args.seed != raw['evaluation']['generation_seed']
                or ids != raw['execution']['allowed_instances']):
            raise ValueError('single-run plan must use the exact registered test20 list, seed and repeat zero')
    files = sorted((ROOT / 'src/swe_repair').glob('*.py')) + [Path(__file__)]
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    raw['provenance'] = {'code_sha256': hashlib.sha256(''.join(file_hash(p) for p in files).encode()).hexdigest(),
                         'git_commit': revision,
                         'dataset_manifest_sha256': file_hash(ROOT / 'data/harness/manifest.json'),
                         'instance_list_sha256': file_hash(listing)}
    cfg = RouterConfig.from_config(raw)
    tier = cfg.budget_tiers()[raw['active_tier']]
    if any(not math.isfinite(float(x)) or float(x) <= 0 for x in tier.values()):
        raise ValueError('resource ceilings must be positive finite values')
    if not 0 < cfg.prefix_fraction <= 1:
        raise ValueError('prefix fraction must be in (0, 1]')
    if (raw['execution']['tool_call_unit'] != 'container_exec'
            or raw['execution']['environment_retries'] != 1
            or raw['execution']['modify_scope'] != 'python_source_excluding_tests'):
        raise ValueError('unsupported execution contract; update protocol and implementation together')
    tag = args.tag or f'proposal_{args.mode}_{args.split}_{args.arm}_r{args.repeat_index}_{args.seed}'
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,96}', tag):
        raise ValueError('invalid tag: letters, digits, underscore and hyphen only')
    if args.execute:
        if not args.allow_paid or not raw['execution'].get('live_authorized', False):
            raise ValueError('paid execution disabled: user authorization, config live_authorized and --allow-paid required')
        scope = raw['execution']
        if scope.get('allowed_modes') is not None and args.mode not in scope['allowed_modes']:
            raise ValueError('run mode is outside the authorized scope')
        if scope.get('allowed_splits') is not None and args.split not in scope['allowed_splits']:
            raise ValueError('split is outside the authorized scope')
        if scope.get('allowed_instances') is not None and set(ids) - set(scope['allowed_instances']):
            raise ValueError('instance selection is outside the authorized scope')
        if scope.get('max_instances') is not None and len(ids) > scope['max_instances']:
            raise ValueError('instance count exceeds the authorized scope')
        if args.mode == 'prefix' and args.split != 'dev':
            raise ValueError('prefix integration is restricted to dev')
        if not raw['model'].get('model_version'):
            raise ValueError('pin served model version first')
        if args.mode != 'prefix' and not args.calibration and (not cfg.calibrated or cfg.switch_probability is None):
            raise ValueError('freeze thresholds and matched random probability on dev first')
        if args.mode == 'pilot':
            validate_pilot_candidate(raw, ids)
        if args.mode not in ('prefix', 'pilot') and not args.calibration and frozen_config_errors(raw):
            raise ValueError('formal configuration is not consistently frozen: ' + '; '.join(frozen_config_errors(raw)))
        if args.split == 'test' and len(ids) < len(full):
            sample = raw['evaluation'].get('sample_manifest')
            if not sample: raise ValueError('test subset requires a preregistered sampling manifest')
            samplepath = Path(sample)
            if not samplepath.is_absolute(): samplepath = ROOT / samplepath
            manifest = json.loads(samplepath.read_text(encoding='utf-8'))
            if manifest.get('instance_ids') != ids or manifest.get('seed') is None:
                raise ValueError('sampling manifest does not match selected instances')
    return raw, {'tag': tag, 'mode': args.mode, 'arm': 'PREFIX' if args.mode == 'prefix' else args.arm, 'split': args.split,
                 'seed': args.seed, 'repeat_index': args.repeat_index, 'calibration': args.calibration,
                 'designated_instances': ids, 'instance_list_sha256': file_hash(listing),
                 'config_hash': cfg.digest, 'effective_config': cfg.effective_config(),
                 'formal_readiness_errors': frozen_config_errors(raw),
                 'live_authorized': raw['execution']['live_authorized'],
                 'execute': args.execute, 'output_directory': str(ROOT / 'runs' / tag)}


def predictions(case, mode, arm):
    stages = case['stages']
    if mode == 'prefix':
        return {'PREFIX': case.get('submitted_patch', stages.get('prefix', {}).get('patch', ''))}
    if mode in ('formal', 'pilot'): return {arm: case.get('submitted_patch', '')}
    result = {}
    for a in ('A', 'C', 'D', 'E'):
        decision = case.get('decisions', {}).get(a)
        if decision:
            stage = 'prefix' if decision['route'] == 'stop' else decision['route']
            result[a] = stages.get(stage, {}).get('patch', '')
    for name, stage in (('B', 'standalone'), ('FIXED', 'fixed'), ('ESC', 'interactive')):
        if stage in stages: result[name] = stages[stage]['patch']
    return result


def execute(raw, plan):
    from swe_repair.experiment import run_case
    from swe_repair.llm import DeepSeekClient, ModelConfig, load_scoped_api_key
    from swe_repair.spend import SpendGuard, SpendPolicy
    from swe_repair.state import generation_view
    import pyarrow.parquet as pq
    if raw['execution'].get('docker_context'):
        os.environ['DOCKER_CONTEXT'] = raw['execution']['docker_context']
    out = Path(plan['output_directory'])
    out.mkdir(parents=True, exist_ok=False)
    matrixpath = out / 'matrix.json'
    from importlib.metadata import version, PackageNotFoundError
    dependencies = {}
    for package in ('requests', 'pyarrow', 'swebench'):
        try: dependencies[package] = version(package)
        except PackageNotFoundError: dependencies[package] = None
    matrix = dict(plan, cases=[], schema_version='proposal-v1', historical=False,
                  environment={'python': platform.python_version(), 'platform': platform.platform(),
                               'dependencies': dependencies})
    def save():
        tmp = out / 'matrix.tmp'
        tmp.write_text(json.dumps(matrix, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        tmp.replace(matrixpath)
    save()
    ledger = raw['execution'].get('batch_ledger')
    if ledger:
        from swe_repair.batch_ledger import LedgerSpendGuard
        ledgerpath = (ROOT / ledger).resolve()
        if not ledgerpath.is_relative_to(ROOT / 'runs'):
            raise ValueError('cumulative ledger must stay under runs/')
        guard = LedgerSpendGuard(ledgerpath, raw['execution']['total_cny'], plan['tag'])
    else:
        guard = SpendGuard(SpendPolicy(ceiling_cny=raw['execution']['total_cny']))
    starting_spend = guard.spent_cny
    m = raw['model']
    stop_file = raw['execution'].get('workflow_stop_file')
    if stop_file:
        stop_file = (ROOT / stop_file).resolve()
        if not stop_file.is_relative_to(ROOT / 'runs'):
            raise ValueError('workflow stop file must stay under runs/')
    client = DeepSeekClient(ModelConfig(model=m['model'], thinking=m['thinking'], effort=m['effort'],
                                       max_tokens=m['max_tokens'], max_retries=m.get('max_retries', 0),
                                       temperature=m.get('temperature'), top_p=m.get('top_p'),
                                       stop_on_api_breakpoint=raw['execution'].get('stop_on_api_breakpoint', False),
                                       workflow_stop_file=str(stop_file) if stop_file else None),
                            api_key=load_scoped_api_key(raw['execution'], str(ROOT)), guard=guard, allow_live=True)
    manifest = json.loads((ROOT / 'data/harness/manifest.json').read_text(encoding='utf-8'))
    parquet = ROOT / manifest['splits'][plan['split']]['local_file']
    if file_hash(parquet).lower() != manifest['splits'][plan['split']]['sha256'].lower():
        raise ValueError('dataset bytes differ from frozen manifest')
    rows = {r['instance_id']: generation_view(r) for r in pq.read_table(parquet).to_pylist()}
    cache = ROOT / 'runs/prefix_cache' / plan['config_hash']
    cache.mkdir(parents=True, exist_ok=True)
    with (out / 'events.jsonl').open('x', encoding='utf-8', newline='\n') as log:
        def checkpoint(event):
            log.write(json.dumps(event, ensure_ascii=False) + '\n')
            log.flush()
            os.fsync(log.fileno())
        for iid in plan['designated_instances']:
            getattr(client, 'check_workflow_stop', lambda: None)()
            if getattr(client, '_api_breakpoint', None):
                matrix['batch_stopped'] = 'api_access_or_quota_breakpoint'
                matrix['api_breakpoint'] = client._api_breakpoint
                save()
                break
            cachepath = cache / f"{plan['seed']}_r{plan['repeat_index']}_{iid}.json"
            cached = json.loads(cachepath.read_text(encoding='utf-8')) if cachepath.exists() else None
            case = run_case(rows[iid], client, raw, mode=plan['mode'], arm=plan['arm'], seed=plan['seed'],
                            split=plan['split'], calibration=plan['calibration'], checkpoint=checkpoint, cached_prefix=cached)
            case['repeat_index'] = plan['repeat_index']
            case['seed'] = plan['seed']
            case['run_id'] = plan['tag']
            matrix['cases'].append(case)
            matrix['new_generation_cost_cny'] = guard.spent_cny - starting_spend
            matrix['cumulative_batch_cost_cny'] = guard.spent_cny
            save()
            prefix = case['stages'].get('prefix')
            if (prefix and prefix['status'] == 'completed' and not cachepath.exists()
                    and not any(x.get('step') == 'prefix_error' for x in prefix.get('trace', []))):
                with cachepath.open('x', encoding='utf-8') as fh:
                    json.dump({'config_hash': plan['config_hash'], 'image_digest': case['image_digest'],
                               'stage': prefix}, fh, ensure_ascii=False)
            for a, diff in predictions(case, plan['mode'], plan['arm']).items():
                with (out / f'predictions_{a}.jsonl').open('a', encoding='utf-8', newline='\n') as fh:
                    fh.write(json.dumps({'instance_id': iid, 'model_name_or_path': f"{plan['tag']}-{a}",
                                         'model_patch': diff}, ensure_ascii=False) + '\n')
            if getattr(client, '_identity_violation', None):
                matrix['batch_stopped'] = 'served_model_identity_violation'
                matrix['identity_violation'] = client._identity_violation
                save()
                break
            if getattr(client, '_api_breakpoint', None):
                matrix['batch_stopped'] = 'api_access_or_quota_breakpoint'
                matrix['api_breakpoint'] = client._api_breakpoint
                save()
                break
            if (plan['mode'] == 'formal' and plan['arm'] in 'ACDE'
                    and (not prefix or prefix['status'] != 'completed'
                         or any(x.get('step') == 'prefix_error' for x in prefix.get('trace', [])))):
                # An interrupted prefix cannot be regenerated independently in
                # subsequent A/C/D/E runs while claiming a shared actual prefix.
                matrix['batch_stopped'] = 'formal_prefix_failed_no_cross_arm_regeneration'
                save()
                break
    print(matrixpath)
    return 2 if matrix.get('batch_stopped') else 0


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', default='configs/proposal_v1.json')
    p.add_argument('--mode', choices=('formal', 'diagnostic', 'prefix', 'pilot'), default='diagnostic')
    p.add_argument('--arm', choices=tuple('ABCDE'), default='D')
    p.add_argument('--split', choices=('dev', 'test'), default='dev')
    p.add_argument('--instances-file')
    p.add_argument('--seed', type=int, default=20261029)
    p.add_argument('--repeat-index', type=int, default=0)
    p.add_argument('--tag')
    p.add_argument('--calibration', action='store_true')
    action = p.add_mutually_exclusive_group()
    action.add_argument('--dry-run', action='store_true')
    action.add_argument('--execute', action='store_true')
    p.add_argument('--allow-paid', action='store_true')
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        raw, plan = load_plan(args)
        if not args.execute:
            print(json.dumps(plan, ensure_ascii=False, indent=2))
            return 0
        return execute(raw, plan)
    except (ValueError, FileExistsError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
