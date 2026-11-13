"""Score completed DEV settings after cancellation; never generates a model request."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,importlib.util,json,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'runs/dev_supplement_finish_20261112_01'
SOURCE=ROOT/'runs/dev_supplement_20261112_02'
sys.path.insert(0,str(ROOT/'src'))
from swe_repair.evaluation import validate_artifact_files,validate_provenance,sidecar_path
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,v):
    with Path(p).open('x',encoding='utf-8') as f:json.dump(v,f,ensure_ascii=False,indent=2)
def main():
    OUT.mkdir(exist_ok=False)
    assert read(SOURCE/'WORKFLOW_EXITED.json')['status']=='breakpoint'
    ledger=read(ROOT/'runs/test20_execution_20261111/batch_ledger.json');assert ledger['pending'] is None
    config=read(SOURCE/'config_manifest.json')['configs'][:2]
    sealed=[]
    for e in config:
        p=ROOT/'runs'/e['tag']/'matrix.json';m=read(p)
        assert len(m['cases'])==6 and not m.get('batch_stopped')
        sealed.append({'path':str(p.relative_to(ROOT)),'sha256':sha(p),'variant':e['variant']})
    write(OUT/'GENERATION_SEALED.json',{'completed_settings':config,'artifacts':sealed,'model_calls_in_followup':0,
        'cancelled_settings':'no_stagnation and all later unexecuted settings; partial records retained and excluded from complete-setting comparisons',
        'at':datetime.now(timezone.utc).isoformat()})
    write(OUT/'STARTED.json',{'pid':__import__('os').getpid(),'at':datetime.now(timezone.utc).isoformat(),
        'ledger_sha256':sha(ROOT/'runs/test20_execution_20261111/batch_ledger.json')})
    spec=importlib.util.spec_from_file_location('preserved_scoring_helpers',SOURCE/'orchestrate.py')
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    reports=[]
    for e in config:
        for a in sealed:assert sha(ROOT/a['path'])==a['sha256']
        view=helper.make_scoring_view(e)
        (OUT/'progress.json').write_text(json.dumps({'phase':'independent_scoring','variant':e['variant'],'tag':view.name}),encoding='utf-8')
        with (OUT/(e['variant']+'_scoring.log')).open('xb') as log:
            result=subprocess.run([sys.executable,str(ROOT/'scripts/score_run.py'),str(view),
                '--controller-image',helper.CONTROLLER,'--max-workers','1','--execute'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        write(OUT/(e['variant']+'_scoring_exit.json'),{'returncode':result.returncode})
        if result.returncode:raise RuntimeError('Scoring stopped; preserve outputs, no automatic retry')
        m=read(view/'matrix.json')
        for role in ('PREFIX','FIXED','ESC','B'):
            if not (view/('predictions_'+role+'.jsonl')).exists():continue
            p=view/'scoring'/role/(view.name+'-'+role+'.'+view.name+'.json')
            r=read(p);provenance=read(sidecar_path(p))
            validate_artifact_files(view/'matrix.json',p,role,provenance);validate_provenance(m,role,r,provenance)
            reports.append({'variant':e['variant'],'role':role,'path':str(p.relative_to(ROOT)),'sha256':sha(p),'provenance_sha256':sha(sidecar_path(p))})
    assert sha(ROOT/'runs/test20_execution_20261111/batch_ledger.json')==read(OUT/'STARTED.json')['ledger_sha256']
    write(OUT/'SCORING_COMPLETED.json',{'reports':reports,'model_calls':0,'at':datetime.now(timezone.utc).isoformat()})
    write(OUT/'WORKFLOW_EXITED.json',{'status':'complete'})
    (OUT/'progress.json').write_text(json.dumps({'phase':'ready_for_analysis_and_save','model_calls':0}),encoding='utf-8')
if __name__=='__main__':
    try:main()
    except Exception as e:
        if OUT.exists() and not (OUT/'WORKFLOW_EXITED.json').exists():write(OUT/'WORKFLOW_EXITED.json',{'status':'breakpoint','type':type(e).__name__,'detail':str(e)})
        raise
