import importlib.util
from pathlib import Path
import copy

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('pilot_summary', ROOT / 'scripts/summarize_pilot.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def rows():
    return [{'instance_id': iid, 'mode': 'pilot', 'arm': arm, 'repeat_index': 0, 'seed': 7,
             'run_id': 'pilot_' + arm, 'config_hash': 'same', 'status': 'unresolved',
             'prediction_sha256': 'a'*64, 'patch_sha256': 'b'*64, 'cost_cny': .1,
             'cost_complete': True, 'resources': {}} for iid in ('repo-1', 'repo-2') for arm in 'ABCDE']


def test_complete_pilot_reports_descriptive_rates_and_all_failed_costs():
    records = rows()
    records[0]['status'] = 'resolved'
    report = module.summarize(records, ['repo-1','repo-2'])
    assert report['primary']['A']['resolved_rate'] == .5
    assert report['primary']['A']['cost_per_resolved_cny'] == .2
    assert report['confidence_interval'] is None and len(report['rows']) == 10


def test_pilot_unknown_verdict_keeps_denominator_without_inventing_a_failure():
    records = rows()
    records[0]['status'] = 'not_scored'
    report = module.summarize(records, ['repo-1','repo-2'])
    assert report['primary']['A']['total'] == 2 and report['primary']['A']['resolved_rate'] is None


def test_pilot_rejects_missing_rows_mixed_modes_and_unpaired_seeds():
    for variation in ('missing', 'formal', 'seed', 'hash'):
        records = rows()
        if variation == 'missing': records.pop()
        if variation == 'formal': records[0]['mode'] = 'formal'
        if variation == 'seed': records[0]['seed'] = 9
        if variation == 'hash': records[0]['config_hash'] = 'other'
        try: module.summarize(records, ['repo-1','repo-2'])
        except ValueError: pass
        else: raise AssertionError(variation + ' was accepted')
