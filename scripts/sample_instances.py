"""Freeze a repository-stratified sample from the FULL test list, offline.

Example: python scripts/sample_instances.py --size 60 --seed 20261029 --out runs/plans/test60.json
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from swe_repair.statistics import stratified_sample


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--population', type=Path, default=ROOT / 'data/frozen/instances_test.txt')
    p.add_argument('--size', type=int, required=True)
    p.add_argument('--seed', type=int, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    out = a.out.resolve()
    if not out.is_relative_to(ROOT / 'runs'):
        p.error('new plans must be written under runs/, never over frozen historical data')
    if out.exists():
        p.error('refusing to replace an existing sampling plan')
    population = a.population.read_text(encoding='utf-8').splitlines()
    frozen = (ROOT / 'data/frozen/instances_test.txt').read_text(encoding='utf-8').splitlines()
    if sorted(population) != sorted(frozen):
        p.error('population must be the complete frozen test list, not a gold/image-available subset')
    plan = stratified_sample(population, a.size, a.seed)
    plan['source_list'] = str(a.population.resolve())
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('x', encoding='utf-8') as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    print(out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
