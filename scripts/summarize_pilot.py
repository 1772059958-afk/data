"""Describe a complete single-repeat DEV A-E pilot, without formal inference."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from swe_repair.statistics import primary_summary


def summarize(records, instance_ids):
    ids = list(instance_ids)
    if not ids or len(set(ids)) != len(ids):
        raise ValueError('pilot needs a unique designated list')
    indexed, hashes, seeds = {}, set(), {}
    for row in records:
        iid, arm = row.get('instance_id'), row.get('arm')
        if row.get('mode') != 'pilot' or row.get('repeat_index') != 0 or arm not in tuple('ABCDE') or iid not in ids:
            raise ValueError('only designated single-repeat pilot A-E records are accepted')
        if (iid, arm) in indexed:
            raise ValueError('duplicate pilot record')
        seed = row.get('seed')
        if not isinstance(seed, int) or isinstance(seed, bool) or (iid in seeds and seeds[iid] != seed):
            raise ValueError('pilot arms must have the same integer seed')
        seeds[iid] = seed
        if not row.get('run_id') or not row.get('config_hash'):
            raise ValueError('missing pilot run/config identity')
        if row.get('status') != 'not_scored':
            for field in ('prediction_sha256', 'patch_sha256'):
                if not re.fullmatch(r'[0-9a-f]{64}', row.get(field, '')):
                    raise ValueError('known verdict requires prediction and patch identity')
        hashes.add(row['config_hash'])
        indexed[iid, arm] = row
    if len(hashes) != 1 or set(indexed) != {(iid, arm) for iid in ids for arm in 'ABCDE'}:
        raise ValueError('pilot grid must be complete and share one configuration')
    return {'kind': 'dev_pilot_descriptive', 'mode': 'pilot', 'instances': ids, 'repeats': 1,
            'config_hash': next(iter(hashes)),
            'primary': {arm: primary_summary([indexed[iid, arm] for iid in ids], ids, 1) for arm in 'ABCDE'},
            'rows': [indexed[iid, arm] for iid in ids for arm in 'ABCDE'],
            'confidence_interval': None,
            'interpretation': 'Two-case DEV interface acceptance. Calibration and pilot use the same cases; report descriptive outcomes only.'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--records', nargs='+', type=Path, required=True)
    p.add_argument('--instances', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    ids = json.loads(a.instances.read_text(encoding='utf-8'))['instance_ids']
    records = [json.loads(line) for path in a.records for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    out = a.out.resolve()
    if not out.is_relative_to(ROOT / 'runs') or out.exists():
        p.error('output must be a new file under runs/')
    report = summarize(records, ids)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(out)


if __name__ == '__main__':
    main()
