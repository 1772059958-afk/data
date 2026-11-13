"""Independent scoring only after all 100 generated predictions are frozen."""
from pathlib import Path
import hashlib,json,subprocess,sys
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
CONTROLLER='sha256:1f43c83b3d3c631d37af54a19828df269accd045a22c62c0aab5b2bfa713726f'

def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def write(p,obj):
    with Path(p).open('x',encoding='utf-8') as f:json.dump(obj,f,ensure_ascii=False,indent=2)
def run(label,arguments):
    if (OUT/'WORKFLOW_STOP.json').exists():raise RuntimeError('cooperative workflow stop present')
    with (OUT/(label+'.log')).open('xb') as log:
        p=subprocess.run([sys.executable,*map(str,arguments)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    write(OUT/(label+'_exit.json'),{'returncode':p.returncode})
    if p.returncode:raise RuntimeError(label+' failed; preserved log and incomplete outputs')

def main():
    freeze=read(OUT/'formal_generation_freeze_manifest.json')
    assert freeze['prediction_count']==100 and freeze['shared_prefixes_exact'] is True
    for item in freeze['artifacts']:assert digest(ROOT/item['path'])==item['sha256']
    write(OUT/'formal_scoring_started.json',{'generation_freeze_sha256':digest(OUT/'formal_generation_freeze_manifest.json'),
          'script_sha256':digest(Path(__file__)),'controller':CONTROLLER,'model_calls':0,
          'started_at':datetime.now(timezone.utc).isoformat()})
    records=[];reports=[]
    for arm in 'ABCDE':
        tag='test20_'+arm+'_20261112_01';folder=ROOT/'runs'/tag
        for item in freeze['artifacts']:assert digest(ROOT/item['path'])==item['sha256']
        run('formal_'+arm+'_independent_scoring',[ROOT/'scripts/score_run.py',folder,
             '--controller-image',CONTROLLER,'--max-workers','1','--execute'])
        report=folder/'scoring'/arm/(tag+'-'+arm+'.'+tag+'.json')
        record=folder/'evaluated_records.jsonl'
        run('formal_'+arm+'_analysis',[ROOT/'scripts/analyse_cf.py','--matrix',folder/'matrix.json',
              '--report',arm+'='+str(report),'--out',folder/'analysis.json','--records-out',record])
        records.append(record);reports.append(report)
    run('formal_single_run_summary',[ROOT/'scripts/summarize_single_run.py','--records',*records,
          '--instances',ROOT/'runs/test20_preparation_20261111/instances.json',
          '--preregistration',ROOT/'runs/test20_preparation_20261111/preregistration.json',
          '--out',OUT/'test20_single_run_summary.json'])
    write(OUT/'formal_scoring_completed.json',{'reports':[{'path':str(p.relative_to(ROOT)),'sha256':digest(p)} for p in reports],
          'evaluated_records':[{'path':str(p.relative_to(ROOT)),'sha256':digest(p)} for p in records],
          'summary_sha256':digest(OUT/'test20_single_run_summary.json'),'model_calls':0,
          'ended_at':datetime.now(timezone.utc).isoformat()})
    print(OUT/'test20_single_run_summary.json')

if __name__=='__main__':
    try:main()
    except Exception as exc:
        if not (OUT/'WORKFLOW_STOP.json').exists():
            write(OUT/'WORKFLOW_STOP.json',{'reason':'formal_independent_scoring_breakpoint',
                  'error_type':type(exc).__name__,'detail':str(exc)})
        raise
