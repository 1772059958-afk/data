"""Replay the full router on evaluated DEV prefix snapshots, entirely offline.

Input is a JSON object with observations (or analyse_cf.py's dev analysis JSON).
Output is a reviewable candidate, never an automatically frozen live config.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from swe_repair.calibration import load_calibration_inputs, select_thresholds
from swe_repair.router import RouterConfig


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--observations', type=Path, required=True)
    p.add_argument('--config', type=Path, default=ROOT / 'configs/proposal_v1.json')
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    out = a.out.resolve()
    if not out.is_relative_to(ROOT / 'runs') or out.exists():
        p.error('calibration output must be a new file under runs/')
    config = RouterConfig.from_file(a.config)
    inputs = load_calibration_inputs(a.observations, config,
               allowed_ids=(ROOT / 'data/frozen/instances_dev.txt').read_text(encoding='utf-8').splitlines())
    obs = inputs.observations
    report = select_thresholds(obs, grid=config.threshold_grid, config=config)
    payload = report.to_dict()
    payload['sensitivity'] = report.sensitivity()
    payload['status'] = 'candidate_requires_review_and_freeze'
    import hashlib
    payload['calibration_source'] = {
        'path': str(a.observations.resolve()),
        'sha256': hashlib.sha256(a.observations.read_bytes()).hexdigest(),
        'config_hash': inputs.config_hash,
        'eligible_count': len(inputs.eligible_prefixes),
        'complete_pair_count': len(obs),
        'missing_pair_ids': list(inputs.missing_pair_ids),
    }
    if inputs.missing_pair_ids:
        payload['warnings'].append(
            'threshold selection uses complete pairs only; E trigger matching uses all eligible dev prefixes')
    if report.chosen is not None:
        chosen = config.with_thresholds(report.chosen.localization_threshold, report.chosen.duplicate_threshold)
        matching = inputs.trigger_rate(chosen)
        chosen.switch_probability = matching['probability']
        candidate = chosen.effective_config()
        candidate['status'] = 'draft-pending-calibration'
        candidate.setdefault('execution', {})['live_authorized'] = False
        payload.update(candidate_config=candidate, candidate_config_hash=RouterConfig.from_config(candidate).digest,
                       matched_switch_probability=chosen.switch_probability,
                       trigger_rate_matching=matching)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('x', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
