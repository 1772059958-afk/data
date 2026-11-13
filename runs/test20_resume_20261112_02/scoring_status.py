"""Read controller progress and completed analysis markers, without mutations."""
from pathlib import Path
import json,re,time
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def main():
    tags=read(OUT/'formal_generation_freeze_manifest.json')['tags'];arms={}
    for arm,tag in tags.items():
        finish=OUT/('formal_'+arm+'_analysis_exit.json')
        started=OUT/('formal_'+arm+'_independent_scoring.log')
        console=ROOT/'runs'/tag/'controller/console.log'
        item={'status':'complete' if finish.exists() and read(finish)['returncode']==0 else 'running' if started.exists() else 'pending'}
        if console.exists():
            with console.open('rb') as f:
                f.seek(max(0,console.stat().st_size-150000));tail=f.read().decode('utf-8',errors='replace')
            progress=re.findall(r'(\d+)/(\d+)\s*\[',tail)
            if progress:item['nonempty_progress']=progress[-1][0]+'/'+progress[-1][1]
        if item['status']=='running':
            logs=ROOT/'runs'/tag/'controller/logs/run_evaluation'/tag/(tag+'-'+arm)
            activity=list(logs.glob('*/run_instance.log')) if logs.exists() else []
            if activity:
                latest=max(activity,key=lambda p:p.stat().st_mtime)
                item['last_case_log']=latest.parent.name
                item['seconds_since_last_case_log_update']=round(max(0,time.time()-latest.stat().st_mtime))
        arms[arm]=item
    stop=ROOT/'runs/test20_resume_20261112_01/WORKFLOW_STOP.json'
    print(json.dumps({'arms':arms,'scoring_complete':(OUT/'formal_scoring_completed.json').exists(),
        'stop':read(stop) if stop.exists() else None},ensure_ascii=False))
if __name__=='__main__':main()
