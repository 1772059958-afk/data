"""Grade immutable 100-prediction inputs, including audited composite B tag."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,shutil,subprocess,sys,threading,time
ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
STOP=ROOT/'runs/test20_resume_20261112_01/WORKFLOW_STOP.json'
CONTROLLER='sha256:1f43c83b3d3c631d37af54a19828df269accd045a22c62c0aab5b2bfa713726f'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def write(p,v):
    with Path(p).open('x',encoding='utf-8') as f:json.dump(v,f,ensure_ascii=False,indent=2)
def check_inputs(freeze):
    assert freeze['prediction_count']==100 and freeze['shared_prefixes_exact'] is True
    for f in freeze['artifacts']:assert sha(ROOT/f['path'])==f['sha256']
    snap=read(ROOT/'runs/test20_resume_20261112_01/formal_source_snapshot/manifest.json')
    for f in snap['files']:assert sha(ROOT/f['path'])==f['sha256'],f['path']
def run(label,args):
    if STOP.exists():raise RuntimeError('workflow stop present')
    with (OUT/(label+'.log')).open('xb') as log:
        p=subprocess.run([sys.executable,*map(str,args)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    write(OUT/(label+'_exit.json'),{'returncode':p.returncode,'at':datetime.now(timezone.utc).isoformat()})
    if p.returncode:raise RuntimeError(label+' failed; outputs preserved')
def disk_guard():
    while not (OUT/'SCORING_WORKFLOW_EXITED.json').exists():
        free={d:shutil.disk_usage(d+':/').free for d in 'CD'}
        if min(free.values())<4*1024**3+64*1024**2:
            if not STOP.exists():write(STOP,{'reason':'scoring_disk_reserve_breakpoint','free_bytes':free})
            return
        time.sleep(5)
def main():
    if '--wait-generation' in sys.argv:
        while not (OUT/'formal_generation_freeze_manifest.json').exists():
            if STOP.exists() or (OUT/'GENERATION_WORKFLOW_EXITED.json').exists():
                raise RuntimeError('generation exited without 100 frozen predictions; scoring not started')
            time.sleep(5)
    freeze=read(OUT/'formal_generation_freeze_manifest.json');check_inputs(freeze)
    write(OUT/'formal_scoring_started.json',{'generation_freeze_sha256':sha(OUT/'formal_generation_freeze_manifest.json'),
        'script_sha256':sha(__file__),'tags':freeze['tags'],'controller':CONTROLLER,
        'model_calls':0,'started_at':datetime.now(timezone.utc).isoformat()})
    threading.Thread(target=disk_guard,daemon=True).start()
    records=[];reports=[]
    for arm,tag in freeze['tags'].items():
        check_inputs(freeze);folder=ROOT/'runs'/tag
        run('formal_'+arm+'_independent_scoring',[ROOT/'scripts/score_run.py',folder,
            '--controller-image',CONTROLLER,'--max-workers','1','--execute'])
        report=folder/'scoring'/arm/(tag+'-'+arm+'.'+tag+'.json');record=folder/'evaluated_records.jsonl'
        run('formal_'+arm+'_analysis',[ROOT/'scripts/analyse_cf.py','--matrix',folder/'matrix.json',
            '--report',arm+'='+str(report),'--out',folder/'analysis.json','--records-out',record])
        records.append(record);reports.append(report)
    run('formal_single_run_summary',[ROOT/'scripts/summarize_single_run.py','--records',*records,
        '--instances',ROOT/'runs/test20_preparation_20261111/instances.json',
        '--preregistration',ROOT/'runs/test20_preparation_20261111/preregistration.json',
        '--out',OUT/'test20_single_run_summary.json'])
    check_inputs(freeze)
    write(OUT/'formal_scoring_completed.json',{'reports':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p)} for p in reports],
        'evaluated_records':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p)} for p in records],
        'summary_sha256':sha(OUT/'test20_single_run_summary.json'),'model_calls':0,
        'ended_at':datetime.now(timezone.utc).isoformat()})
    write(OUT/'SCORING_WORKFLOW_EXITED.json',{'status':'independent_scoring_and_descriptive_analysis_complete'})
if __name__=='__main__':
    try:main()
    except Exception as e:
        if not STOP.exists():write(STOP,{'reason':'formal_independent_scoring_breakpoint','type':type(e).__name__,
            'detail':str(e),'at':datetime.now(timezone.utc).isoformat()})
        if not (OUT/'SCORING_WORKFLOW_EXITED.json').exists():write(OUT/'SCORING_WORKFLOW_EXITED.json',{'status':'breakpoint','detail':str(e)})
        raise
