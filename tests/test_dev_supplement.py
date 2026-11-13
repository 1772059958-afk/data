"""Ablation must remove only the failure ledger, without hiding source evidence."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('dev_supplement',ROOT/'scripts/run_dev_supplement.py')
supp=importlib.util.module_from_spec(spec);spec.loader.exec_module(supp)

def test_ledger_ablation_keeps_source_and_candidates_without_mutation():
    from swe_repair.state import RepairState,TaskManifest,FailureRecord
    from swe_repair.experiment import seed_messages
    state=RepairState(TaskManifest('x','base','cfg','version','hash'))
    state.failures.add(FailureRecord.from_output('python public_check.py',1,stage='public_test',stdout='AssertionError: sentinel_failure'))
    prefix=SimpleNamespace(state=state,context_text='sentinel_source')
    before=state.to_json()
    ordinary=seed_messages('sentinel_bug',prefix)
    ablated=supp.omit_failure_ledger(seed_messages)('sentinel_bug',prefix)
    assert 'sentinel_failure' in ordinary[1]['content']
    assert 'sentinel_failure' not in ablated[1]['content']
    assert 'sentinel_source' in ablated[1]['content'] and 'sentinel_bug' in ablated[1]['content']
    assert 'Prefix candidates:' in ablated[1]['content']
    assert state.to_json()==before

def test_renderer_is_restored_after_failed_variant():
    from swe_repair import experiment
    before=experiment.seed_messages
    try:
        with supp.renderer_adapter(True):
            assert experiment.seed_messages is not before
            raise RuntimeError('simulated interruption')
    except RuntimeError:pass
    assert experiment.seed_messages is before

def test_disabled_adapter_preserves_the_exact_renderer():
    from swe_repair import experiment
    before=experiment.seed_messages
    with supp.renderer_adapter(False):assert experiment.seed_messages is before

def test_cross_config_prefix_contract_rejects_formal_without_opening_container():
    import json
    from swe_repair.experiment import validate_diagnostic_prefix_contract
    raw=json.loads((ROOT/'configs/proposal_v1.json').read_text(encoding='utf-8'))
    try:validate_diagnostic_prefix_contract(raw,{},mode='formal',split='test',calibration=False)
    except ValueError as e:assert 'DEV diagnostics' in str(e)
    else:raise AssertionError('formal reuse contract accepted')

def test_cross_config_prefix_contract_rejects_changed_resource_or_model():
    import copy,json
    from swe_repair.experiment import validate_diagnostic_prefix_contract
    from swe_repair.router import RouterConfig
    raw=json.loads((ROOT/'configs/proposal_v1.json').read_text(encoding='utf-8'))
    source={'effective_config':raw,'config_hash':RouterConfig.from_config(raw).digest}
    for section,key,value in [('prefix','prefix_fraction',.4),('model','max_tokens',123)]:
        changed=copy.deepcopy(raw);changed[section][key]=value
        try:validate_diagnostic_prefix_contract(changed,source,mode='diagnostic',split='dev',calibration=True)
        except ValueError:pass
        else:raise AssertionError('changed prefix settings accepted')

def test_cross_config_prefix_contract_allows_only_continuation_change():
    import copy,json
    from swe_repair.experiment import validate_diagnostic_prefix_contract
    from swe_repair.router import RouterConfig
    raw=json.loads((ROOT/'configs/proposal_v1.json').read_text(encoding='utf-8'))
    source={'effective_config':raw,'config_hash':RouterConfig.from_config(raw).digest}
    changed=copy.deepcopy(raw);changed['interaction']['model_calls']=8
    assert validate_diagnostic_prefix_contract(changed,source,mode='diagnostic',split='dev',calibration=True)==source['config_hash']
