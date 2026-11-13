"""Continue audited one-repeat formal generation, then freeze all 100 outputs."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,shutil,subprocess,sys,time,threading,os
ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
PRIOR=ROOT/'runs/test20_resume_20261112_01'
STOP=PRIOR/'WORKFLOW_STOP.json'
DONE=OUT/'GENERATION_WORKFLOW_EXITED.json'
TAGS={'A':'test20_A_20261112_01','B':'test20_B_20261112_02',
      'C':'test20_C_20261112_01','D':'test20_D_20261112_01','E':'test20_E_20261112_01'}
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def write(p,v):
    with Path(p).open('x',encoding='utf-8') as f:json.dump(v,f,ensure_ascii=False,indent=2)
def check_source():
    snapshot=read(PRIOR/'formal_source_snapshot/manifest.json')
    for r in snapshot['files']:assert sha(ROOT/r['path'])==r['sha256'],r['path']
    return snapshot['generation_code_sha256']
def guard():
    while not DONE.exists():
        free={d:shutil.disk_usage(d+':/').free for d in 'CD'}
        if min(free.values())<4*1024**3+64*1024**2:
            try:write(STOP,{'reason':'disk_reserve_breakpoint','free_bytes':free,'at':datetime.now(timezone.utc).isoformat()})
            except FileExistsError:pass
            return
        time.sleep(5)
def main():
    source=check_source();config=ROOT/'configs/test20_frozen_20261112_01.json';cfgsha=sha(config)
    raw=read(config);ids=read(ROOT/'runs/test20_preparation_20261111/instances.json')['instance_ids']
    assert len(ids)==20 and raw['execution']['allowed_instances']==ids
    audit=read(OUT/'B8_recovery_audit.json');assert audit['new_model_requests']==0
    assert not any((ROOT/'runs'/TAGS[a]).exists() for a in 'BCDE')
    oldstop=read(STOP);assert oldstop['reason']=='formal_pipeline_breakpoint'
    archive=PRIOR/'WORKFLOW_STOP_interruption_01.json';assert not archive.exists()
    stopsha=sha(STOP);STOP.rename(archive)
    write(OUT/'formal_resume_started.json',{'tags':TAGS,'pid':os.getpid(),'frozen_source_sha256':source,
        'config_sha256':cfgsha,'retired_stop_sha256':stopsha,'retired_stop_path':str(archive.relative_to(ROOT)),
        'new_user_instruction':'继续进行实验','hidden_formal_results_read':False,
        'operational_adapters':[{'path':p.name,'sha256':sha(p)} for p in (Path(__file__),OUT/'resume_B_remaining.py',OUT/'recover_interrupted_B8.py')],
        'started_at':datetime.now(timezone.utc).isoformat()})
    threading.Thread(target=guard,daemon=True).start()
    matrices={};artifacts=[]
    for arm,tag in TAGS.items():
        assert not STOP.exists() and check_source()==source and sha(config)==cfgsha
        folder=ROOT/'runs'/tag
        if arm!='A':
            cmd=([sys.executable,str(OUT/'resume_B_remaining.py')] if arm=='B' else
                [sys.executable,str(ROOT/'scripts/run_cf.py'),'--config',str(config),'--mode','formal',
                 '--arm',arm,'--split','test','--seed','20261111','--repeat-index','0',
                 '--instances-file',str(ROOT/'runs/test20_preparation_20261111/instances.json'),
                 '--tag',tag,'--execute','--allow-paid'])
            with (OUT/('formal_'+arm+'_generation.log')).open('xb') as log:
                p=subprocess.Popen(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
                write(OUT/('formal_'+arm+'_started.json'),{'pid':p.pid,'tag':tag,'at':datetime.now(timezone.utc).isoformat()})
                code=p.wait()
            matrix=read(folder/'matrix.json') if (folder/'matrix.json').exists() else {}
            write(OUT/('formal_'+arm+'_exit.json'),{'returncode':code,'cases':len(matrix.get('cases',[])),
                'batch_stopped':matrix.get('batch_stopped'),'at':datetime.now(timezone.utc).isoformat()})
            if code or matrix.get('batch_stopped'):raise RuntimeError('formal generation stopped: '+tag)
        matrix=read(folder/'matrix.json');assert [c['instance_id'] for c in matrix['cases']]==ids
        assert matrix['effective_config']['provenance']['code_sha256']==source
        pred=folder/('predictions_'+arm+'.jsonl');rows=[json.loads(s) for s in pred.read_text(encoding='utf-8').splitlines()]
        assert len(rows)==20 and [r['instance_id'] for r in rows]==ids
        for case,prediction in zip(matrix['cases'],rows):
            assert case['submitted_patch']==prediction['model_patch']
            assert case['image_digest']==raw['execution']['images'][case['instance_id']]
        if arm!='A':assert matrix['config_hash']==matrices['A']['config_hash']
        if arm in 'CDE':
            for base,case in zip(matrices['A']['cases'],matrix['cases']):
                assert case['prefix_reused'] is True
                assert canonical(base['prefix_snapshot'])==canonical(case['prefix_snapshot'])
                assert canonical(base['stages']['prefix'])==canonical(case['stages']['prefix'])
        matrices[arm]=matrix
        artifacts.extend({'path':str(p.relative_to(ROOT)),'sha256':sha(p)} for p in [folder/'matrix.json',pred])
    ledger=ROOT/'runs/test20_execution_20261111/batch_ledger.json';money=read(ledger)
    assert money['pending'] is None and sum(r['cost_cny'] for r in money['records'])<=100
    write(OUT/'formal_generation_freeze_manifest.json',{'kind':'all_five_generation_outputs_frozen_before_independent_scoring',
        'tags':TAGS,'arms':list('ABCDE'),'instances':ids,'prediction_count':100,'artifacts':artifacts,
        'config_hash':matrices['A']['config_hash'],'source_sha256':source,'shared_prefixes_exact':True,
        'all20_A_C_D_E_actual_prefix_stages_and_snapshots_equal':True,
        'B_resume_provenance_sha256':sha(OUT/'B_resume_cost_and_provenance.json'),
        'B8_recovery_audit_sha256':sha(OUT/'B8_recovery_audit.json'),'ledger_sha256':sha(ledger),
        'cumulative_estimate_cny':sum(r['cost_cny'] for r in money['records']),
        'frozen_at':datetime.now(timezone.utc).isoformat(),'hidden_formal_results_read':False})
    write(DONE,{'status':'all100_generation_frozen','at':datetime.now(timezone.utc).isoformat()})
if __name__=='__main__':
    try:main()
    except Exception as e:
        if not STOP.exists():write(STOP,{'reason':'formal_resume_breakpoint','type':type(e).__name__,
            'detail':str(e),'at':datetime.now(timezone.utc).isoformat()})
        if not DONE.exists():write(DONE,{'status':'breakpoint','detail':str(e)})
        raise
