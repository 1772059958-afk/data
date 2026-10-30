"""Calibration keeps missing labels out of fitting, but in E's denominator."""
from copy import deepcopy
from pathlib import Path
import importlib.util
import json
import sys
import tempfile
from unittest.mock import patch

from swe_repair.budget import Budget, BudgetState
from swe_repair.calibration import (calibration_inputs, PairedObservation,
                                    select_thresholds)
from swe_repair.router import RouterConfig
from swe_repair.state import Localization, RepairState, TaskManifest

ROOT = Path(__file__).resolve().parents[1]


def config():
    return RouterConfig.from_file(ROOT / 'configs/proposal_v1.json')


def population():
    cfg = config()
    rows = []
    for iid, high in (('demo__repo-1', True), ('demo__repo-2', False)):
        state = RepairState(TaskManifest(iid, 'demo/repo', 'base', cfg.config_version, cfg.digest))
        state.budget = BudgetState('test', Budget(200000, 12, 80, 1200))
        state.localization = Localization.from_file_sets({'one': ['pkg/a.py'],
            'two': ['pkg/b.py'] if high else ['pkg/a.py']})
        rows.append({'instance_id': iid, 'split': 'dev', 'prefix_snapshot': state.to_dict()})
    first = rows[0]
    return {'mode': 'diagnostic', 'split': 'dev', 'historical_diagnostic_only': False,
            'config_hash': cfg.digest, 'effective_config': cfg.effective_config(),
            'designated_instances': [r['instance_id'] for r in rows],
            'eligible_instance_ids': [r['instance_id'] for r in rows],
            'eligible_prefixes': rows, 'eligible_population_complete': True,
            'prefix_unavailable_instance_ids': [], 'paired_eligible': 2, 'paired_complete': 1,
            'unscored_paired_instances': ['demo__repo-2'],
            'observations': [dict(deepcopy(first), fixed_resolved=False, interactive_resolved=True)]}


def rejected(payload):
    try:
        calibration_inputs(payload, config())
    except (ValueError, KeyError):
        return
    raise AssertionError('incomplete or inconsistent calibration population accepted')


def test_e_probability_uses_all_eligible_prefixes_despite_missing_pair_labels():
    data = population()
    inputs = calibration_inputs(data, config())
    candidate = config().with_thresholds(.5, .5)
    matching = inputs.trigger_rate(candidate)
    assert matching['denominator'] == 2 and matching['complete_pair_count'] == 1
    assert matching['interactive'] == 1 and matching['probability'] == .5
    assert matching['missing_pair_ids'] == ['demo__repo-2']
    assert matching['source'] == 'all_eligible_dev_prefixes'


def test_calibration_refuses_complete_case_inputs_without_the_eligible_population():
    data = population()
    for key in ('eligible_prefixes', 'eligible_instance_ids', 'eligible_population_complete'):
        changed = deepcopy(data)
        changed.pop(key)
        rejected(changed)
    changed = deepcopy(data)
    changed['eligible_population_complete'] = False
    rejected(changed)
    changed = deepcopy(data)
    changed['eligible_prefixes'].pop()
    rejected(changed)


def test_calibration_refuses_wrong_split_duplicates_mixed_config_and_snapshot_mismatch():
    data = population()
    for mutate in (
        lambda p: p.update(split='test'),
        lambda p: p['eligible_prefixes'][1].update(split='test'),
        lambda p: p['eligible_instance_ids'].append('demo__repo-2'),
        lambda p: p['eligible_prefixes'].append(deepcopy(p['eligible_prefixes'][0])),
        lambda p: p['eligible_prefixes'][1]['prefix_snapshot']['task_manifest'].update(config_hash='OTHER'),
        lambda p: p['observations'][0]['prefix_snapshot']['task_manifest'].update(base_commit='OTHER'),
        lambda p: p.update(unscored_paired_instances=[]),
    ):
        changed = deepcopy(data)
        mutate(changed)
        # The input intentionally keeps separate copies of each snapshot.
        rejected(changed)


def test_dev_membership_and_incomplete_designated_prefixes_are_enforced():
    data = population()
    try:
        calibration_inputs(data, config(), allowed_ids=['other__repo-1'])
    except ValueError:
        pass
    else:
        raise AssertionError('test instances could be relabelled as dev')
    data['prefix_unavailable_instance_ids'] = ['demo__repo-3']
    rejected(data)


def test_threshold_fitting_refuses_duplicate_or_mixed_config_observations():
    data = population()
    first = PairedObservation.from_dict(data['observations'][0])
    try:
        select_thresholds([first, first])
    except ValueError:
        pass
    else:
        raise AssertionError('duplicate paired labels were counted twice')
    second = deepcopy(data['eligible_prefixes'][1])
    second['prefix_snapshot']['task_manifest']['config_hash'] = 'OTHER'
    second.update(fixed_resolved=True, interactive_resolved=False)
    try:
        select_thresholds([first, PairedObservation.from_dict(second)])
    except ValueError:
        pass
    else:
        raise AssertionError('mixed source configurations could calibrate one router')


def test_dormant_duplicate_thresholds_are_reported_for_two_candidate_prefix():
    data = population()
    report = select_thresholds([PairedObservation.from_dict(data['observations'][0])], config=config())
    warning = next(w for w in report.warnings if 'duplicate-rate rule is unreachable' in w)
    assert '0.5' in warning and '0.75' in warning and 'strict greater-than' in warning


def test_real_runner_provenance_is_compatible_with_original_config_for_calibration_cli():
    spec = importlib.util.spec_from_file_location('population_runner', ROOT / 'scripts/run_cf.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    _, plan = runner.load_plan(runner.parser().parse_args(['--calibration', '--dry-run']))
    data = population()
    data.update(config_hash=plan['config_hash'], effective_config=plan['effective_config'])
    for row in data['eligible_prefixes'] + data['observations']:
        row['prefix_snapshot']['task_manifest']['config_hash'] = plan['config_hash']
    assert plan['config_hash'] != config().digest  # provenance is part of the generation identity
    inputs = calibration_inputs(data, config())
    assert inputs.config_hash == plan['config_hash']
    spec = importlib.util.spec_from_file_location('population_calibrator', ROOT / 'scripts/calibrate_router.py')
    calibrator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(calibrator)
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        listing = root / 'data/frozen/instances_dev.txt'
        listing.parent.mkdir(parents=True)
        listing.write_text('\n'.join(data['designated_instances']) + '\n', encoding='utf-8')
        source, output = root / 'analysis.json', root / 'runs/calibration.json'
        source.write_text(json.dumps(data), encoding='utf-8')
        with patch.object(calibrator, 'ROOT', root), patch.object(sys, 'argv',
             ['calibrate_router.py', '--observations', str(source), '--config',
              str(ROOT / 'configs/proposal_v1.json'), '--out', str(output)]):
            assert calibrator.main() == 0
        result = json.loads(output.read_text(encoding='utf-8'))
        assert result['matched_switch_probability'] == .5
        assert result['trigger_rate_matching']['denominator'] == 2
        assert result['calibration_source']['config_hash'] == plan['config_hash']
        assert result['candidate_config']['execution']['live_authorized'] is False
        assert result['candidate_config']['status'] == 'draft-pending-calibration'


def test_calibration_rejects_changed_generation_settings_even_with_matching_version():
    data = population()
    raw = config().effective_config()
    raw['prefix']['prefix_fraction'] = .4
    try:
        calibration_inputs(data, RouterConfig.from_config(raw))
    except ValueError as exc:
        assert 'configuration differs' in str(exc)
    else:
        raise AssertionError('old prefixes were recalibrated under a different budget split')
