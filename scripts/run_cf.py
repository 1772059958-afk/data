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
    if raw.get('evaluation', {}).get('repeats', 0) < 3:
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
        if not raw['model'].get('model_version'):
            raise ValueError('pin served model version first')
        if not args.calibration and (not cfg.calibrated or cfg.switch_probability is None):
            raise ValueError('freeze thresholds and matched random probability on dev first')
        if not args.calibration and frozen_config_errors(raw):
            raise ValueError('formal configuration is not consistently frozen: ' + '; '.join(frozen_config_errors(raw)))
        if args.split == 'test' and len(ids) < len(full):
            sample = raw['evaluation'].get('sample_manifest')
            if not sample: raise ValueError('test subset requires a preregistered sampling manifest')
            samplepath = Path(sample)
            if not samplepath.is_absolute(): samplepath = ROOT / samplepath
            manifest = json.loads(samplepath.read_text(encoding='utf-8'))
            if manifest.get('instance_ids') != ids or manifest.get('seed') is None:
                raise ValueError('sampling manifest does not match selected instances')
    return raw, {'tag': tag, 'mode': args.mode, 'arm': args.arm, 'split': args.split,
                 'seed': args.seed, 'repeat_index': args.repeat_index, 'calibration': args.calibration,
                 'designated_instances': ids, 'instance_list_sha256': file_hash(listing),
                 'config_hash': cfg.digest, 'effective_config': cfg.effective_config(),
                 'formal_readiness_errors': frozen_config_errors(raw),
                 'live_authorized': raw['execution']['live_authorized'],
                 'execute': args.execute, 'output_directory': str(ROOT / 'runs' / tag)}


def predictions(case, mode, arm):
    stages = case['stages']
    if mode == 'formal': return {arm: case.get('submitted_patch', '')}
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
    from swe_repair.llm import DeepSeekClient, ModelConfig
    from swe_repair.spend import SpendGuard, SpendPolicy
    from swe_repair.state import generation_view
    import pyarrow.parquet as pq
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
    guard = SpendGuard(SpendPolicy(ceiling_cny=raw['execution']['total_cny']))
    m = raw['model']
    client = DeepSeekClient(ModelConfig(model=m['model'], thinking=m['thinking'], effort=m['effort'],
                                       max_tokens=m['max_tokens'], max_retries=m.get('max_retries', 0),
                                       temperature=m.get('temperature'), top_p=m.get('top_p')),
                            guard=guard, allow_live=True)
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
            cachepath = cache / f"{plan['seed']}_r{plan['repeat_index']}_{iid}.json"
            cached = json.loads(cachepath.read_text(encoding='utf-8')) if cachepath.exists() else None
            case = run_case(rows[iid], client, raw, mode=plan['mode'], arm=plan['arm'], seed=plan['seed'],
                            calibration=plan['calibration'], checkpoint=checkpoint, cached_prefix=cached)
            case['repeat_index'] = plan['repeat_index']
            case['seed'] = plan['seed']
            case['run_id'] = plan['tag']
            matrix['cases'].append(case)
            matrix['new_generation_cost_cny'] = guard.spent_cny
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
    print(matrixpath)
    return 0


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', default='configs/proposal_v1.json')
    p.add_argument('--mode', choices=('formal', 'diagnostic'), default='diagnostic')
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
