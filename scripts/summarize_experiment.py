"""Offline primary summaries and instance-cluster bootstrap for formal repeats."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from swe_repair.statistics import primary_summary, paired_cluster_bootstrap


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--records', type=Path, nargs='+', required=True)
    p.add_argument('--instances', type=Path, required=True)
    p.add_argument('--repeats', type=int, default=3)
    p.add_argument('--left', default='A')
    p.add_argument('--right', default='D')
    p.add_argument('--bootstrap-samples', type=int, default=2000)
    p.add_argument('--seed', type=int, default=0)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    records = []
    for path in a.records:
        records.extend(json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip())
    if any(row.get('mode') != 'formal' for row in records):
        p.error('only records explicitly marked mode=formal can enter the main experiment summary')
    hashes = {row.get('config_hash') for row in records}
    if None in hashes or len(hashes) != 1:
        p.error('all records must carry the same frozen effective config hash')
    text = a.instances.read_text(encoding='utf-8')
    if a.instances.suffix == '.json':
        plan = json.loads(text)
        ids = plan.get('instance_ids', plan.get('instances'))
        if not isinstance(ids, list) or ('instances' in plan and plan['instances'] != ids):
            p.error('sampling manifest instance list is missing or inconsistent')
    else:
        ids = text.splitlines()
    report = {'repeats': a.repeats,
              'primary': {arm: primary_summary([r for r in records if r['arm'] == arm], ids, a.repeats)
                          for arm in sorted({r['arm'] for r in records})},
              'paired_difference': paired_cluster_bootstrap(records, ids, a.left, a.right,
                          repeats=a.repeats, samples=a.bootstrap_samples, seed=a.seed)}
    out = a.out.resolve()
    if not out.is_relative_to(ROOT / 'runs') or out.exists():
        p.error('output must be a new file under runs/')
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('x', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
