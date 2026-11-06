"""Offline pilot provenance gates; fixtures contain public IDs and fake states."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile

from swe_repair.budget import Budget, BudgetState
from swe_repair.calibration import calibration_inputs, select_thresholds
from swe_repair.router import RouterConfig
from swe_repair.state import Localization, RepairState, TaskManifest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('pilot_cli_runner', ROOT / 'scripts/run_cf.py')
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)
IDS = ['pvlib__pvlib-python-1707', 'pydicom__pydicom-1139']


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@contextmanager
def fixture():
    with tempfile.TemporaryDirectory(prefix='offline_pilot_cli_', dir=ROOT / 'runs') as folder:
        folder = Path(folder)
        raw = json.loads((ROOT / 'configs/proposal_v1.json').read_text(encoding='utf-8'))
        raw['model']['model_version'] = 'offline-served-model'
        raw['execution'].update(live_authorized=True, allowed_modes=['diagnostic', 'pilot', 'formal'],
                                allowed_splits=['dev'], allowed_instances=IDS, max_instances=2,
                                total_cny=100, batch_ledger='runs/offline_fake_ledger.json',
                                docker_context='offline-fake', credential_source='project_dotenv',
                                images={iid: 'sha256:offline-fake-image' for iid in IDS})
        other = deepcopy(raw['budget_tiers'][0])
        other['tier'] = 'alternate'
        other['token'] *= 2
        raw['budget_tiers'].append(other)
        cfg = RouterConfig.from_config(raw)
        rows = []
        for index, iid in enumerate(IDS):
            state = RepairState(TaskManifest(iid, 'public/repo', 'offline-base', cfg.config_version, cfg.digest))
            state.budget = BudgetState('development', Budget(512000, 12, 80, 1200))
            state.localization = Localization.from_file_sets({'one': ['pkg/a.py'],
                'two': ['pkg/b.py'] if index == 0 else ['pkg/a.py']})
            rows.append({'instance_id': iid, 'split': 'dev', 'prefix_snapshot': state.to_dict()})
        analysis = {'mode': 'diagnostic', 'split': 'dev', 'historical_diagnostic_only': False,
            'config_hash': cfg.digest, 'effective_config': cfg.effective_config(),
            'designated_instances': IDS, 'eligible_instance_ids': IDS,
            'eligible_prefixes': rows, 'eligible_population_complete': True,
            'prefix_unavailable_instance_ids': [], 'paired_eligible': 2, 'paired_complete': 1,
            'unscored_paired_instances': [IDS[1]],
            'observations': [dict(deepcopy(rows[0]), fixed_resolved=False, interactive_resolved=True)]}
        source = folder / 'analysis.json'
        write_json(source, analysis)
        inputs = calibration_inputs(analysis, cfg, allowed_ids=IDS)
        report = select_thresholds(inputs.observations, grid=cfg.threshold_grid, config=cfg)
        chosen = cfg.with_thresholds(report.chosen.localization_threshold, report.chosen.duplicate_threshold)
        matching = inputs.trigger_rate(chosen)
        chosen.switch_probability = matching['probability']
        proposed = chosen.effective_config()
        proposed['status'] = 'draft-pending-calibration'
        proposed['execution']['live_authorized'] = False
        candidate = report.to_dict()
        candidate.update(status='candidate_requires_review_and_freeze', candidate_config=proposed,
            candidate_config_hash=RouterConfig.from_config(proposed).digest,
            matched_switch_probability=matching['probability'], trigger_rate_matching=matching,
            calibration_source={'path': str(source), 'sha256': sha(source), 'config_hash': cfg.digest,
                'eligible_count': 2, 'complete_pair_count': 1, 'missing_pair_ids': [IDS[1]]})
        runtime = deepcopy(proposed)
        runtime['execution']['live_authorized'] = True
        runtime['pilot'] = {'calibration_candidate': str(folder / 'candidate.json')}
        case = {'root': folder, 'analysis': analysis, 'candidate': candidate, 'runtime': runtime}
        refresh(case)
        yield case


def refresh(case, *, source=False, config_hash=False):
    if source:
        write_json(case['root'] / 'analysis.json', case['analysis'])
        case['candidate']['calibration_source']['sha256'] = sha(case['root'] / 'analysis.json')
    if config_hash:
        case['candidate']['candidate_config_hash'] = RouterConfig.from_config(case['candidate']['candidate_config']).digest
    path = case['root'] / 'candidate.json'
    write_json(path, case['candidate'])
    case['runtime']['pilot']['candidate_sha256'] = sha(path)


def rejected(case):
    try:
        RUNNER.validate_pilot_candidate(case['runtime'], IDS)
    except (ValueError, KeyError):
        return
    raise AssertionError('unreviewed or changed pilot execution was accepted')


def test_pilot_accepts_real_candidate_schema_with_all_eligible_e_denominator():
    with fixture() as case:
        RUNNER.validate_pilot_candidate(case['runtime'], IDS)
        matching = case['candidate']['trigger_rate_matching']
        assert matching['denominator'] == 2 and matching['complete_pair_count'] == 1
        assert matching['probability'] == .5
        assert case['runtime']['status'] == 'draft-pending-calibration'


def test_pilot_rejects_changed_candidate_and_analysis_bytes():
    for name in ('candidate.json', 'analysis.json'):
        with fixture() as case:
            path = case['root'] / name
            path.write_text(path.read_text(encoding='utf-8') + '\n', encoding='utf-8')
            rejected(case)


def test_pilot_binds_both_candidate_and_source_configuration_hashes():
    for source in (False, True):
        with fixture() as case:
            if source:
                case['candidate']['calibration_source']['config_hash'] = 'other-source-config'
            else:
                case['candidate']['candidate_config_hash'] = 'other-candidate-config'
            refresh(case)
            rejected(case)
    with fixture() as case:
        case['analysis']['effective_config']['model']['max_tokens'] += 1
        refresh(case, source=True)
        rejected(case)


def test_pilot_rejects_incomplete_dev_population_even_when_file_hashes_match():
    for mutate in (lambda a: a.update(eligible_population_complete=False),
                   lambda a: a['eligible_prefixes'].pop(),
                   lambda a: a.update(prefix_unavailable_instance_ids=[IDS[1]])):
        with fixture() as case:
            mutate(case['analysis'])
            refresh(case, source=True)
            rejected(case)


def test_pilot_rejects_threshold_and_e_probability_changes():
    for key in ('localization_disagreement_threshold', 'duplicate_rate_threshold', 'switch_probability'):
        with fixture() as case:
            case['runtime']['router'][key] = .123
            rejected(case)
    with fixture() as case:
        case['candidate']['candidate_config']['router']['switch_probability'] = .123
        case['runtime']['router']['switch_probability'] = .123
        refresh(case, config_hash=True)
        rejected(case)


def test_pilot_rejects_changed_generation_settings_and_active_budget_tier():
    changes = [('model', 'max_tokens', 99), ('prefix', 'n_candidates', 3),
               ('interaction', 'model_calls', 2), ('fixed_continuation', 'max_candidates', 2),
               ('execution', 'images', {}), ('execution', 'total_cny', 101),
               ('execution', 'per_instance_cny', 3), ('execution', 'batch_ledger', 'runs/other.json')]
    for section, key, value in changes:
        with fixture() as case:
            case['runtime'][section][key] = value
            rejected(case)
    for key, value in (('active_tier', 'alternate'), ('prompt_version', 'other-prompt')):
        with fixture() as case:
            case['runtime'][key] = value
            rejected(case)
    with fixture() as case:
        # Updating both hashes is insufficient when execution diverges from the source diagnostic.
        case['runtime']['active_tier'] = 'alternate'
        case['candidate']['candidate_config']['active_tier'] = 'alternate'
        refresh(case, config_hash=True)
        rejected(case)


def test_pending_pilot_candidate_cannot_bypass_formal_freeze_gate():
    with fixture() as case:
        config_path, instances_path = case['root'] / 'config.json', case['root'] / 'instances.json'
        write_json(config_path, case['runtime'])
        write_json(instances_path, {'instance_ids': IDS})
        argv = ['--config', str(config_path), '--instances-file', str(instances_path),
                '--split', 'dev', '--execute', '--allow-paid', '--tag', 'offline_pilot_gate']
        _, plan = RUNNER.load_plan(RUNNER.parser().parse_args(argv + ['--mode', 'pilot']))
        assert plan['mode'] == 'pilot' and plan['formal_readiness_errors']
        try:
            RUNNER.load_plan(RUNNER.parser().parse_args(argv + ['--mode', 'formal']))
        except ValueError as exc:
            assert 'not consistently frozen' in str(exc)
        else:
            raise AssertionError('pending pilot configuration bypassed the formal freeze gate')
