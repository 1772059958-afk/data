"""Gold environment checks: default plan, explicit --execute, new runs directory.

This never imports a model client. A gold failure is recorded, never used to
remove designated instances from a method experiment's primary denominator.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = Path(__file__).resolve().parents[1]


def plan(args):
    source = Path(args.instances_file) if args.instances_file else ROOT / f'data/frozen/instances_{args.split}.txt'
    if not source.is_absolute(): source = ROOT / source
    text = source.read_text(encoding='utf-8')
    ids = json.loads(text)['instance_ids'] if source.suffix == '.json' else text.splitlines()
    ids = [i.strip() for i in ids if i.strip()]
    full = set((ROOT / f'data/frozen/instances_{args.split}.txt').read_text(encoding='utf-8').splitlines())
    if not ids or len(set(ids)) != len(ids) or set(ids) - full:
        raise ValueError('invalid designated instance list')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,96}', args.tag):
        raise ValueError('invalid tag')
    out = ROOT / 'runs' / args.tag
    command = [sys.executable, '-m', 'swebench.harness.run_evaluation', '--dataset_name', str(ROOT / 'data/harness'),
               '--split', args.split, '--predictions_path', 'gold', '--instance_ids', *ids,
               '--run_id', args.tag, '--max_workers', str(args.max_workers), '--report_dir', str(out)]
    return {'kind': 'gold_environment_check', 'split': args.split, 'tag': args.tag,
            'designated_instances': ids, 'instance_list_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'output_directory': str(out), 'command': command, 'model_calls': 0}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--split', choices=('dev', 'test'), default='dev')
    p.add_argument('--tag', required=True)
    p.add_argument('--instances-file')
    p.add_argument('--max-workers', type=int, default=1)
    action = p.add_mutually_exclusive_group()
    action.add_argument('--dry-run', action='store_true')
    action.add_argument('--execute', action='store_true')
    args = p.parse_args(argv)
    try:
        if args.max_workers < 1: raise ValueError('max-workers must be positive')
        record = plan(args)
        if not args.execute:
            print(json.dumps(record, ensure_ascii=False, indent=2))
            return 0
        manifest = json.loads((ROOT / 'data/harness/manifest.json').read_text(encoding='utf-8'))
        data = manifest['splits'][args.split]
        if hashlib.sha256((ROOT / data['local_file']).read_bytes()).hexdigest().lower() != data['sha256'].lower():
            raise ValueError('dataset hash mismatch')
        out = Path(record['output_directory'])
        out.mkdir(parents=True, exist_ok=False)
        (out / 'gold_plan.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        return subprocess.run(record['command'], cwd=ROOT).returncode
    except (ValueError, FileExistsError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
