"""Offline fixed-denominator summaries, clustered intervals and stratified sampling."""
from __future__ import annotations

import hashlib
import math
import random
from collections import Counter, defaultdict
from typing import Any, Iterable, Mapping, Sequence

from .cf import SCORED_STATUSES


def repo_of(instance_id: str) -> str:
    """SWE-bench's full owner/repository slug, not just the owner."""
    return instance_id.rsplit('-', 1)[0]


def _ids(designated_ids: Sequence[str]) -> list[str]:
    ids = list(designated_ids)
    if not ids or any(not isinstance(i, str) or not i.strip() for i in ids) or len(ids) != len(set(ids)):
        raise ValueError('designated instance list must be non-empty and unique')
    return ids


def primary_summary(records: Sequence[Mapping[str, Any]], designated_ids: Sequence[str],
                    repeats: int = 1) -> dict[str, Any]:
    """One arm, all predesignated instances and repeats, including missing/error rows.

    Unknown evaluations produce a lower bound, NOT a final resolved rate.
    Error/infra_error/empty_patch/unresolved are retained in the denominator.
    """
    ids = _ids(designated_ids)
    if repeats < 1:
        raise ValueError('repeats must be positive')
    indexed = {}
    for row in records:
        iid, repeat = row['instance_id'], row.get('repeat_index', 0)
        if iid not in ids or not isinstance(repeat, int) or not 0 <= repeat < repeats:
            raise ValueError('record is outside the designated population/repeats')
        key = (iid, repeat)
        if key in indexed:
            raise ValueError(f'duplicate instance/repeat record: {key}')
        if row.get('status', 'not_scored') not in SCORED_STATUSES | {'not_scored'}:
            raise ValueError('generation status cannot be used as an evaluation verdict')
        indexed[key] = row
    counts, per_repo = Counter(), defaultdict(lambda: Counter())
    total_cost, cost_complete = 0.0, True
    for iid in ids:
        for repeat in range(repeats):
            row = indexed.get((iid, repeat))
            status = row.get('status', 'not_scored') if row else 'not_scored'
            counts[status] += 1
            per_repo[repo_of(iid)][status] += 1
            if row is None or row.get('cost_cny') is None:
                cost_complete = False
            else:
                value = float(row['cost_cny'])
                if not math.isfinite(value) or value < 0:
                    raise ValueError('invalid cost')
                total_cost += value
                cost_complete = cost_complete and row.get('cost_complete', True)
    total = len(ids) * repeats
    complete = counts['not_scored'] == 0
    resolved = counts['resolved']
    rows = {repo: {'total': sum(c.values()), 'resolved': c['resolved'],
                   'status_counts': dict(c),
                   'resolved_rate': c['resolved'] / sum(c.values()) if not c['not_scored'] else None}
            for repo, c in sorted(per_repo.items())}
    return {
        'designated_instances': len(ids), 'repeats': repeats, 'total': total,
        'resolved': resolved, 'complete': complete, 'status_counts': dict(counts),
        'resolved_rate': resolved / total if complete else None,
        'resolved_rate_lower_bound': resolved / total,
        'cost_cny_recorded': total_cost, 'cost_complete': cost_complete,
        'cost_per_resolved_cny': total_cost / resolved if complete and cost_complete and resolved else None,
        'per_repo': rows,
        'repository_macro_average': (sum(r['resolved_rate'] for r in rows.values()) / len(rows))
        if complete else None,
    }


def paired_cluster_bootstrap(records: Sequence[Mapping[str, Any]], designated_ids: Sequence[str],
                             left: str, right: str, *, repeats: int = 3,
                             samples: int = 2000, seed: int = 0) -> dict[str, Any]:
    """Difference right-left. Resample INSTANCES, preserving every arm/repeat.

    A complete designated grid with >=3 repeats is required. No pseudo-
    replication, silent complete-case selection, or intervals from a smoke run.
    """
    ids = _ids(designated_ids)
    if repeats < 3 or samples < 100:
        raise ValueError('formal interval needs >=3 repeats and >=100 resamples')
    if left == right:
        raise ValueError('compare distinct arms')
    indexed = {}
    hashes = {row['config_hash'] for row in records if row.get('config_hash') and row.get('arm') in (left, right)}
    if len(hashes) > 1:
        raise ValueError('paired repeats must share one frozen configuration hash')
    for row in records:
        if row['arm'] not in (left, right):
            continue
        key = (row['instance_id'], row.get('repeat_index', 0), row['arm'])
        if key in indexed:
            raise ValueError(f'duplicate paired record {key}')
        if key[0] not in ids or not isinstance(key[1], int) or not 0 <= key[1] < repeats:
            raise ValueError('record outside designated grid')
        if row.get('status') not in SCORED_STATUSES:
            raise ValueError('all designated evaluations must be known before computing an interval')
        indexed[key] = row['status'] == 'resolved'
    differences = []
    for iid in ids:
        pairs = [(iid, repeat, arm) for repeat in range(repeats) for arm in (left, right)]
        if any(key not in indexed for key in pairs):
            raise ValueError('incomplete designated paired repeat grid')
        differences.append(sum(int(indexed[iid, r, right]) - int(indexed[iid, r, left])
                               for r in range(repeats)) / repeats)
    rng = random.Random(seed)
    draws = sorted(sum(rng.choice(differences) for _ in ids) / len(ids) for _ in range(samples))
    def quantile(p):
        x = (len(draws) - 1) * p
        lo, hi = math.floor(x), math.ceil(x)
        return draws[lo] + (draws[hi] - draws[lo]) * (x - lo)
    return {'left': left, 'right': right, 'difference': sum(differences) / len(ids),
            'confidence_level': 0.95, 'ci': [quantile(0.025), quantile(0.975)],
            'resampling_unit': 'instance', 'instances': len(ids), 'repeats': repeats,
            'bootstrap_samples': samples, 'seed': seed}


def stratified_sample(designated_ids: Sequence[str], size: int, seed: int) -> dict[str, Any]:
    """Proportional largest-remainder repository allocation, at least one/stratum.

    The full list and a seed are the only inputs; image/gold/model outcomes
    cannot influence selection. Freeze this manifest before any main results.
    """
    ids = sorted(_ids(designated_ids))
    groups = defaultdict(list)
    for iid in ids:
        groups[repo_of(iid)].append(iid)
    if not len(groups) <= size <= len(ids):
        raise ValueError('sample must cover every repository and not exceed the population')
    quotas = {repo: 1 for repo in groups}
    remaining = size - len(groups)
    # Reserve one per repository, distribute remaining slots proportionally to
    # remaining capacity; this rule is explicit and deterministic at ties.
    capacity = len(ids) - len(groups)
    shares = {repo: remaining * (len(rows) - 1) / capacity if capacity else 0.0
              for repo, rows in groups.items()}
    for repo in groups:
        quotas[repo] += math.floor(shares[repo])
    slots = size - sum(quotas.values())
    priority = sorted(groups, key=lambda repo: (-(shares[repo] % 1), repo))
    for repo in priority[:slots]:
        quotas[repo] += 1
    rng = random.Random(seed)
    selected = sorted(iid for repo in sorted(groups) for iid in rng.sample(groups[repo], quotas[repo]))
    digest = lambda rows: hashlib.sha256(('\n'.join(rows) + '\n').encode()).hexdigest()
    return {'sampling': 'repository_stratified_capacity_proportional_minimum_one',
            'seed': seed, 'population_size': len(ids), 'sample_size': size,
            'population_sha256': digest(ids), 'instance_list_sha256': digest(selected),
            'instance_ids': selected,
            'per_repository': {repo: {'population': len(groups[repo]), 'sample': quotas[repo]}
                               for repo in sorted(groups)}, 'instances': selected}
