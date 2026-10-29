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
from swe_repair.calibration import load_observations, select_thresholds, select_switch_probability
from swe_repair.router import RouterConfig, route_for_arm
from swe_repair.state import RepairState


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
    obs = load_observations(a.observations)
    report = select_thresholds(obs, grid=config.threshold_grid, config=config)
    payload = report.to_dict()
    payload['sensitivity'] = report.sensitivity()
    payload['status'] = 'candidate_requires_review_and_freeze'
    if report.chosen is not None:
        chosen = config.with_thresholds(report.chosen.localization_threshold, report.chosen.duplicate_threshold)
        decisions = [route_for_arm('D', RepairState.from_dict(o.prefix_snapshot), chosen) for o in obs]
        chosen.switch_probability = select_switch_probability(decisions)
        candidate = chosen.effective_config()
        candidate['status'] = 'draft-pending-calibration'
        candidate.setdefault('execution', {})['live_authorized'] = False
        payload.update(candidate_config=candidate, candidate_config_hash=RouterConfig.from_config(candidate).digest,
                       matched_switch_probability=chosen.switch_probability)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('x', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
