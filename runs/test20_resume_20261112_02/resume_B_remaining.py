"""Full registered B plan; reuse 8 audited cases and run untouched cases once.

Only scheduling is adapted. The original load_plan/execute gates, client,
ledger, generator, budgets, config hash and exact 20-case list stay in effect.
"""
from pathlib import Path
import copy, hashlib, importlib.util, json, sys

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    from swe_repair import experiment
    olddir=ROOT/'runs/test20_B_20261112_01'
    old=read(olddir/'matrix.json')
    audit=read(OUT/'B8_recovery_audit.json')
    assert audit['new_model_requests']==0 and audit['replayed_events']==audit['original_event_count']
    assert sha(OUT/'B8_recovered_case.json')==audit['case_sha256']
    assert audit['ledger_before_sha256']==audit['ledger_after_sha256']
    ids=old['designated_instances'];assert len(old['cases'])==7
    saved={c['instance_id']:copy.deepcopy(c) for c in old['cases']}
    recovered=read(OUT/'B8_recovered_case.json');saved[recovered['instance_id']]=recovered
    assert list(saved)==ids[:8]
    for c in saved.values():
        assert c['config_hash']==old['config_hash'] and c['arm']=='B'
    source_hash=sha(olddir/'matrix.json');calls=[]
    original=experiment.run_case
    def case_adapter(row,client,raw,**kwargs):
        iid=row['instance_id'];assert iid==ids[len(calls)]
        assert kwargs['mode']=='formal' and kwargs['arm']=='B' and kwargs['seed']==20261111
        calls.append(iid)
        if iid in saved:
            case=copy.deepcopy(saved[iid])
            assert case['image_digest']==raw['execution']['images'][iid]
            case['resume_provenance']={'kind':'completed_strategy_unit_reused_without_new_model_or_container_calls',
                'source_tag':olddir.name,'source_matrix_sha256':source_hash,
                'source_case_index':ids.index(iid),'recovered_case':iid==ids[7],
                'B8_recovery_audit_sha256':sha(OUT/'B8_recovery_audit.json') if iid==ids[7] else None,
                'adapter_sha256':sha(__file__),'new_model_requests':0}
            kwargs['checkpoint']({'instance_id':iid,'stage':'case_reused','outcome':case})
            return case
        return original(row,client,raw,**kwargs)
    spec=importlib.util.spec_from_file_location('frozen_run_cf',ROOT/'scripts/run_cf.py')
    runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    args=runner.parser().parse_args(['--config','configs/test20_frozen_20261112_01.json','--mode','formal',
        '--arm','B','--split','test','--seed','20261111','--repeat-index','0',
        '--instances-file','runs/test20_preparation_20261111/instances.json',
        '--tag','test20_B_20261112_02','--execute','--allow-paid'])
    raw,plan=runner.load_plan(args)
    assert plan['designated_instances']==ids and plan['config_hash']==old['config_hash']
    experiment.run_case=case_adapter
    try:code=runner.execute(raw,plan)
    finally:experiment.run_case=original
    matrixpath=ROOT/'runs/test20_B_20261112_02/matrix.json'
    matrix=read(matrixpath)
    if code==0:assert calls==ids and len(matrix['cases'])==20
    # Keep process delta separate from full B study cost, including billed B8.
    ledger=read(ROOT/'runs/test20_execution_20261111/batch_ledger.json')
    tagged={tag:sum(r['cost_cny'] for r in ledger['records'] if r.get('run_id')==tag)
            for tag in (olddir.name,plan['tag'])}
    with (OUT/'B_resume_cost_and_provenance.json').open('x',encoding='utf-8') as f:
        json.dump({'registered_units':20,'reused_units':8,'newly_scheduled_units':len(calls)-8,
            'actual_new_model_cost_cny_by_ledger_tag':tagged,'full_B_actual_generation_cost_cny':sum(tagged.values()),
            'matrix_process_delta_cny':matrix.get('new_generation_cost_cny'),
            'historical_incomplete_B8_cost_already_in_old_tag':0.02955332,
            'model_usage_rebooked':False,'frozen_generator_source_changed':False},f,indent=2)
    return code
if __name__=='__main__':sys.exit(main())
