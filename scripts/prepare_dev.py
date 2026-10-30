"""Prepare a small DEV integration plan, offline, without reading outcome data.

No model client, credentials, package installation or container commands run.
The complete 23-instance dev population remains in the coverage ledger.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import random
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from run_cf import load_plan, parser as run_parser
from scan_gold import plan as gold_plan


def select_dev(ids, size, seed):
    if len(ids) != len(set(ids)) or not 1 <= size <= len(ids):
        raise ValueError('invalid dev population or sample size')
    groups = {}
    for iid in sorted(ids):
        groups.setdefault(iid.rsplit('-', 1)[0], []).append(iid)
    rng = random.Random(seed)
    repos = sorted(groups)
    chosen_repos = sorted(rng.sample(repos, min(size, len(repos))))
    chosen = [rng.choice(groups[repo]) for repo in chosen_repos]
    if len(chosen) < size:
        chosen += rng.sample(sorted(set(ids) - set(chosen)), size - len(chosen))
    return sorted(chosen)


def write_json(path, payload):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def prepare(out, *, size=3, seed=20261030, config='configs/proposal_v1.json'):
    out = Path(out).resolve()
    if not out.is_relative_to(ROOT / 'runs') or out.exists():
        raise ValueError('preparation must use a new directory under runs/')
    population = (ROOT / 'data/frozen/instances_dev.txt').read_text(encoding='utf-8').splitlines()
    selected = select_dev(population, size, seed)
    if len(population) != 23:
        raise ValueError('complete dev population must retain all 23 designated cases')
    # Validate the active draft before creating any preparation artifacts.
    raw, _ = load_plan(run_parser().parse_args(['--config', str(config), '--calibration', '--dry-run']))
    if raw['execution'].get('live_authorized') is not False:
        raise ValueError('offline preparation requires live_authorized=false')
    out.mkdir(parents=True, exist_ok=False)
    manifest = {'kind': 'dev_integration_selection_only', 'split': 'dev', 'seed': seed,
                'sampling': 'repository_spread_then_uniform_without_outcome_fields',
                'population_size': len(population), 'sample_size': size,
                'population_sha256': hashlib.sha256(('\n'.join(sorted(population)) + '\n').encode()).hexdigest(),
                'instance_ids': selected, 'intended_use': 'integration_acceptance_not_method_effectiveness'}
    write_json(out / 'instances.json', manifest)
    first = dict(manifest, instance_ids=selected[:1], sample_size=1, parent_selection='instances.json')
    write_json(out / 'first_instance.json', first)
    if size > 1:
        write_json(out / 'remaining_instances.json', dict(manifest, instance_ids=selected[1:], sample_size=size - 1,
                                                        parent_selection='instances.json'))
    ledger = {'split': 'dev', 'designated_total': 23, 'integration_selection': selected,
              'instances': [{'instance_id': iid, 'selected_for_integration': iid in selected,
                             'generation_status': 'not_run', 'environment_status': 'not_verified',
                             'evaluation_status': 'not_scored'} for iid in population]}
    write_json(out / 'full_dev_coverage.json', ledger)
    plans = {}
    selections = [('first_instance', 'first_instance.json'), ('diagnostic', 'instances.json')]
    if size > 1:
        selections.append(('remaining', 'remaining_instances.json'))
    for label, filename in selections:
        args = run_parser().parse_args(['--config', str(config), '--mode', 'diagnostic', '--split', 'dev',
                '--calibration', '--seed', str(seed), '--instances-file', str(out / filename),
                '--tag', f'dev_{label}_{seed}', '--dry-run'])
        _, plans[label] = load_plan(args)
        write_json(out / f'{label}_plan.json', plans[label])
    args = argparse.Namespace(instances_file=str(out / 'instances.json'), split='dev', tag=f'dev_gold_{seed}', max_workers=1)
    write_json(out / 'gold_plan.json', dict(gold_plan(args), execute=False))
    gates = ['explicit authorization for real containers and paid generation',
             'pin and verify the served model version; keep router calibration pending',
             'validate WSL/Linux dependencies and local image digest/base commit',
             'approve instance/batch ceilings and reserve termination budget',
             'accept the first instance interface/tool/patch/public-test behavior before widening',
             'retain environment errors and resource exhaustion; never silently replace a case',
             'score frozen predictions independently with provenance sidecars',
             'use complete eligible dev prefixes for E matching after full-dev calibration']
    record = {'kind': 'offline_dev_preparation', 'execute': False, 'live_authorized': False,
              'seed': seed, 'selected_instances': selected, 'first_instance': selected[0],
              'full_dev_denominator': 23, 'python': platform.python_version(),
              'local_import_availability': {name: importlib.util.find_spec(name) is not None
                                            for name in ('requests', 'pyarrow', 'swebench')},
              'executable_paths_only': {name: shutil.which(name) for name in ('docker', 'wsl')},
              'config_hash': plans['diagnostic']['config_hash'],
              'formal_readiness_errors': plans['diagnostic']['formal_readiness_errors'],
              'review_gates_before_live': gates,
              'budget': {'batch_ceiling_cny': raw['execution']['total_cny'],
                         'per_policy_instance_ceiling_cny': raw['execution']['per_instance_cny'],
                         'diagnostic_upper_bound_cny': size * 3 * raw['execution']['per_instance_cny'],
                         'note': 'A diagnostic collects alternative policies. The batch guard may stop before all plans finish; no automatic ceiling increase.'}}
    write_json(out / 'preparation.json', record)
    (out / 'README.md').write_text(
        '# 小范围 dev 集成准备（未执行）\n\n'
        f'从完整 dev 23 按种子 {seed}、仅依据实例 ID 与仓库分布选择 {size} 个实例。'
        '未读取旧方法成绩或 gold 通过名单，不是主实验子集或校准结论。\n\n'
        f'先验收 `{selected[0]}`，通过接口、工具调用、完整补丁、公开测试和预算审计后再扩至其余实例。'
        '全部 23 个 dev 的未运行/环境状态保存在 full_dev_coverage.json。\n\n'
        '当前仅有离线计划，配置仍 pending、live_authorized=false；没有读取密钥、启动容器、拉镜像或调用模型。'
        '本目录是准备材料，实际运行必须写另一个新 tag，不能把计划目录当作已运行矩阵。\n\n'
        'first_instance_plan.json / remaining_plan.json / diagnostic_plan.json / gold_plan.json 均为 execute=false。'
        '分阶段时使用 first_instance 与 remaining，避免再跑 diagnostic 整批而重复生成。'
        'preparation.json 列出真实运行前的验收门槛、依赖可发现性和金额上限；可发现路径不表示服务可用。'
        '双分支诊断上界可能超过批次守卫，守卫不能自动提高。\n\n'
        '真实运行仍需新的明确授权及已固定的服务端模型版本；不要通过改 pending 或授权布尔值绕过。'
        '小范围集成不能替代完整 dev 校准、正式三次重复、独立判分或消融。\n', encoding='utf-8')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--size', type=int, default=3)
    parser.add_argument('--seed', type=int, default=20261030)
    parser.add_argument('--config', default='configs/proposal_v1.json')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare(args.out, size=args.size, seed=args.seed, config=args.config)
    except (ValueError, FileExistsError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
