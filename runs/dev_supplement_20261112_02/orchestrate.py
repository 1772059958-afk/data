"""Execute the frozen DEV panel, seal outputs, then independently grade branches."""
from pathlib import Path
from datetime import datetime,timezone
import copy,hashlib,json,os,shutil,subprocess,sys,threading,time
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))
from swe_repair.evaluation import frozen_predictions
STOP=OUT/'WORKFLOW_STOP.json';DONE=OUT/'WORKFLOW_EXITED.json'
CONTROLLER='sha256:1f43c83b3d3c631d37af54a19828df269accd045a22c62c0aab5b2bfa713726f'
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,v):
    with Path(p).open('x',encoding='utf-8') as f:json.dump(v,f,ensure_ascii=False,indent=2)
def core_hash():
    files=sorted((ROOT/'src/swe_repair').glob('*.py'))+[ROOT/'scripts/run_cf.py']
    return hashlib.sha256(''.join(sha(p) for p in files).encode()).hexdigest()
def progress(**v):
    p=OUT/'progress.json';tmp=p.with_suffix('.tmp')
    tmp.write_text(json.dumps(dict(v,at=datetime.now(timezone.utc).isoformat()),ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(p)
def disk_guard():
    while not DONE.exists():
        free={d:shutil.disk_usage(d+':/').free for d in 'CD'}
        if min(free.values())<4*1024**3+64*1024**2:
            try:write(STOP,{'reason':'disk_reserve_breakpoint','free_bytes':free})
            except FileExistsError:pass
            return
        time.sleep(5)
def run(label,args):
    if STOP.exists():raise RuntimeError('cooperative stop present')
    with (OUT/(label+'.log')).open('xb') as log:
        p=subprocess.Popen([sys.executable,*map(str,args)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        write(OUT/(label+'_started.json'),{'pid':p.pid,'at':datetime.now(timezone.utc).isoformat()})
        code=p.wait()
    write(OUT/(label+'_exit.json'),{'returncode':code,'at':datetime.now(timezone.utc).isoformat()})
    if code:raise RuntimeError(label+' stopped; inspect preserved outputs, never automatically retry')
def make_scoring_view(entry):
    source=ROOT/'runs'/entry['tag'];m=read(source/'matrix.json')
    tag=entry['tag']+'_eval';dest=ROOT/'runs'/tag;dest.mkdir(exist_ok=False)
    m=copy.deepcopy(m);m['tag']=tag;m['output_directory']=str(dest)
    m['source_generation']={'matrix':str((source/'matrix.json').relative_to(ROOT)),'sha256':sha(source/'matrix.json'),
        'model_calls_in_scoring_view':0,'kind':'identical_case_patches_and_states_with_new_evaluation_run_identity'}
    for case in m['cases']:case['source_generation_run_id']=case['run_id'];case['run_id']=tag
    write(dest/'matrix.json',m)
    # Grade unique branch roles, not duplicate A/C/D/E selections. Policy
    # descriptions are derived afterwards from these independently scored roles.
    for arm in ('PREFIX','FIXED','ESC','B'):
        patches=frozen_predictions(m,arm)
        if not patches:continue
        with (dest/('predictions_'+arm+'.jsonl')).open('x',encoding='utf-8') as f:
            for iid,diff in patches.items():f.write(json.dumps({'instance_id':iid,'model_name_or_path':tag+'-'+arm,'model_patch':diff},ensure_ascii=False)+'\n')
    return dest
def main():
    manifest=read(OUT/'config_manifest.json');protocol=read(OUT/'protocol.json');code=core_hash()
    assert sha(OUT/'protocol.json')==manifest['protocol_sha256']
    assert sha(ROOT/protocol['adapter'])==protocol['adapter_sha256']
    money=read(ROOT/protocol['shared_ledger']);assert money['pending'] is None
    assert sha(ROOT/protocol['shared_ledger'])==protocol['starting_ledger_sha256']
    assert not STOP.exists() and not any((ROOT/'runs'/e['tag']).exists() for e in manifest['configs'])
    write(OUT/'STARTED.json',{'pid':os.getpid(),'protocol_sha256':manifest['protocol_sha256'],
        'generation_code_sha256':code,'orchestrator_sha256':sha(__file__),'at':datetime.now(timezone.utc).isoformat()})
    threading.Thread(target=disk_guard,daemon=True).start()
    sealed=[]
    for index,e in enumerate(manifest['configs']):
        assert core_hash()==code and sha(ROOT/e['path'])==e['sha256']
        progress(phase='generation',variant=e['variant'],variant_index=index+1,variant_count=len(manifest['configs']),tag=e['tag'])
        run(e['variant']+'_generation',[ROOT/'scripts/run_dev_supplement.py','--config',ROOT/e['path'],
            '--mode','diagnostic','--split','dev','--calibration','--arm','D','--seed',str(protocol['seed']),
            '--repeat-index','0','--instances-file',OUT/'panel.json','--tag',e['tag'],'--execute','--allow-paid'])
        folder=ROOT/'runs'/e['tag'];m=read(folder/'matrix.json')
        assert len(m['cases'])==6 and [c['instance_id'] for c in m['cases']]==protocol['panel_instance_ids']
        assert not m.get('batch_stopped')
        if next(v for v in protocol['variants'] if v['name']==e['variant'])['reuse_baseline_prefix']:
            baseline=read(ROOT/'runs'/protocol['baseline_tag']/'matrix.json')
            for a,b in zip(baseline['cases'],m['cases']):
                assert b['prefix_reused'] and a['prefix_snapshot']==b['prefix_snapshot'] and a['stages']['prefix']==b['stages']['prefix']
        for p in [folder/'matrix.json',*sorted(folder.glob('predictions_*.jsonl'))]:
            sealed.append({'path':str(p.relative_to(ROOT)),'sha256':sha(p)})
        money=read(ROOT/protocol['shared_ledger']);assert money['pending'] is None
        if sum(r['cost_cny'] for r in money['records'])>=100:raise RuntimeError('cumulative100CNY exhausted')
    write(OUT/'GENERATION_SEALED.json',{'all_nine_variants_complete':True,'artifacts':sealed,
        'independent_new_supplement_labels_not_read_before_seal':True,'at':datetime.now(timezone.utc).isoformat()})
    reports=[]
    for index,e in enumerate(manifest['configs']):
        for item in sealed:assert sha(ROOT/item['path'])==item['sha256']
        folder=make_scoring_view(e)
        progress(phase='independent_scoring',variant=e['variant'],variant_index=index+1,variant_count=len(manifest['configs']),tag=folder.name)
        run(e['variant']+'_scoring',[ROOT/'scripts/score_run.py',folder,'--controller-image',CONTROLLER,'--max-workers','1','--execute'])
        for report in sorted((folder/'scoring').glob('*/*.json')):
            if not report.name.endswith('.'+folder.name+'.json'):continue
            reports.append({'path':str(report.relative_to(ROOT)),'sha256':sha(report)})
    write(OUT/'SCORING_COMPLETED.json',{'reports':reports,'model_calls_during_scoring':0,'at':datetime.now(timezone.utc).isoformat()})
    write(DONE,{'status':'generation_and_independent_scoring_complete'})
    progress(phase='ready_for_final_analysis',variant_count=len(manifest['configs']))
if __name__=='__main__':
    try:main()
    except Exception as e:
        if not STOP.exists():write(STOP,{'reason':'supplement_breakpoint','type':type(e).__name__,'detail':str(e),'at':datetime.now(timezone.utc).isoformat()})
        if not DONE.exists():write(DONE,{'status':'breakpoint','detail':str(e)})
        raise
