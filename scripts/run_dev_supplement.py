"""Scoped posthoc DEV experiments through the original paid runner gates.

Only the no-failure-ledger variant adapts the seed-message renderer. Raw tool
observations, retained candidates, budgets and independent scoring stay intact.
"""
from contextlib import contextmanager
import copy,hashlib,importlib.util,json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))

def file_hash(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def omit_failure_ledger(original):
    def render(problem,prefix):
        # Copy state, not just the list: an ablation cannot erase the source
        # failures used by routing, validation, selection or the other branch.
        shadow=copy.copy(prefix)
        shadow.state=copy.deepcopy(prefix.state)
        shadow.state.failures.records=[]
        return original(problem,shadow)
    return render

@contextmanager
def renderer_adapter(enabled):
    from swe_repair import experiment
    original=experiment.seed_messages
    if enabled:experiment.seed_messages=omit_failure_ledger(original)
    try:yield
    finally:experiment.seed_messages=original

def validate_supplement(raw,plan,args):
    s=raw.get('supplement',{})
    path=(ROOT/s.get('protocol','')).resolve()
    if not path.is_relative_to(ROOT/'runs') or not path.is_file() or file_hash(path)!=s.get('protocol_sha256'):
        raise ValueError('supplement requires an unchanged preregistered DEV protocol')
    protocol=json.loads(path.read_text(encoding='utf-8'))
    if s.get('adapter_sha256')!=file_hash(__file__):raise ValueError('supplement adapter changed')
    if (args.mode!='diagnostic' or args.split!='dev' or not args.calibration or args.repeat_index!=0
            or plan['designated_instances']!=protocol['panel_instance_ids'] or args.seed!=protocol['seed']):
        raise ValueError('supplement is restricted to its complete DEV panel and diagnostic repeat zero')
    variants={v['name']:v for v in protocol['variants']}
    if s.get('variant') not in variants:raise ValueError('unknown supplemental variant')
    expected=variants[s['variant']]
    if (raw['prefix']['prefix_fraction']!=expected['prefix_fraction']
            or raw['interaction']['model_calls']!=expected['interaction_calls']
            or raw['interaction']['stagnation_patience']!=expected['stagnation_patience']
            or s.get('omit_failure_ledger')!=expected['omit_failure_ledger']):
        raise ValueError('variant differs from the registered one-factor setting')
    tier=next(t for t in raw['budget_tiers'] if t['tier']==raw['active_tier'])
    if any(tier[k]!=v for k,v in expected['resource_ceiling'].items()):
        raise ValueError('supplement resource tier changed')
    execution=raw['execution']
    if (execution['batch_ledger']!=protocol['shared_ledger'] or execution['total_cny']!=100
            or execution['per_instance_cny']!=2 or execution['credential_source']!='project_dotenv'
            or execution.get('stop_on_api_breakpoint') is not True):
        raise ValueError('supplement must keep the original cumulative and instance guards')
    if raw['model']!=protocol['model_reference']:raise ValueError('supplement model/identity changed')
    if s['variant']!='no_failure_ledger' and s['omit_failure_ledger']:
        raise ValueError('feedback adaptation outside its declared variant')
    return protocol

def bind_baseline_prefixes(raw,plan,protocol):
    """Create source-labelled cache references; never rewrite the source state."""
    from swe_repair import experiment
    baseline=protocol['baseline_tag']
    matrix_path=ROOT/'runs'/baseline/'matrix.json'
    source=json.loads(matrix_path.read_text(encoding='utf-8'))
    if source['designated_instances']!=plan['designated_instances'] or len(source['cases'])!=len(plan['designated_instances']):
        raise ValueError('baseline prefix population incomplete')
    experiment.validate_diagnostic_prefix_contract(raw,{'effective_config':source['effective_config'],
        'config_hash':source['config_hash']},mode=plan['mode'],split=plan['split'],calibration=plan['calibration'])
    cache=ROOT/'runs/prefix_cache'/plan['config_hash'];cache.mkdir(parents=True,exist_ok=False)
    for case in source['cases']:
        stage=case['stages']['prefix']
        if stage['status']!='completed' or any(t.get('step')=='prefix_error' for t in stage['trace']):
            raise ValueError('cannot substitute a failed baseline prefix')
        payload={'config_hash':source['config_hash'],'image_digest':case['image_digest'],'stage':stage,
            'source_matrix':str(matrix_path.relative_to(ROOT)),'source_matrix_sha256':file_hash(matrix_path),
            'reference_for_continuation_config_hash':plan['config_hash']}
        p=cache/f"{plan['seed']}_r{plan['repeat_index']}_{case['instance_id']}.json"
        with p.open('x',encoding='utf-8') as f:json.dump(payload,f,ensure_ascii=False)
    return {'effective_config':source['effective_config'],'config_hash':source['config_hash']}

def main():
    spec=importlib.util.spec_from_file_location('supplement_original_runner',ROOT/'scripts/run_cf.py')
    runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    args=runner.parser().parse_args();raw,plan=runner.load_plan(args)
    protocol=validate_supplement(raw,plan,args)
    if not args.execute:
        print(json.dumps(plan,ensure_ascii=False,indent=2));return 0
    from swe_repair import experiment
    original=experiment.run_case
    source=(bind_baseline_prefixes(raw,plan,protocol) if raw['supplement']['reuse_baseline_prefix'] else None)
    def execute_case(*a,**kw):
        if source is not None:kw['cached_prefix_contract']=source
        return original(*a,**kw)
    experiment.run_case=execute_case
    try:
        with renderer_adapter(raw['supplement']['omit_failure_ledger']):return runner.execute(raw,plan)
    finally:experiment.run_case=original
if __name__=='__main__':raise SystemExit(main())
