"""Wait for the complete independent DEV replay, then calibrate offline only."""
from pathlib import Path
import json,subprocess,sys,time,hashlib

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
RUN=ROOT/'runs/dev23_scoring_replay_20261112_02'
TAG='dev23_calibration_20261112_01'

def main():
    exitfile=RUN/'controller/exit_status.json'
    while not exitfile.exists():
        if (OUT/'WORKFLOW_STOP.json').exists():raise RuntimeError('cooperative stop requested')
        time.sleep(2)
    assert json.loads(exitfile.read_text(encoding='utf-8'))['returncode']==0
    reports=[]
    for arm in ['A','B','C','D','ESC','FIXED']:
        path=RUN/'scoring'/arm/(TAG+'-'+arm+'.'+TAG+'.json')
        assert path.exists()
        reports+=['--report',arm+'='+str(path)]
    matrix=json.loads((RUN/'matrix.json').read_text(encoding='utf-8'))
    effective=RUN/'effective_config_for_calibration.json'
    with effective.open('x',encoding='utf-8') as f:json.dump(matrix['effective_config'],f,ensure_ascii=False,indent=2)
    cmd=[sys.executable,str(ROOT/'scripts/analyse_cf.py'),'--matrix',str(RUN/'matrix.json'),
         *reports,'--out',str(RUN/'analysis.json'),'--records-out',str(RUN/'evaluated_records.jsonl')]
    with (OUT/'dev23_final_analysis_01.log').open('xb') as f:subprocess.run(cmd,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=True)
    candidate=RUN/'calibration_candidate.json'
    cmd=[sys.executable,str(ROOT/'scripts/calibrate_router.py'),'--observations',str(RUN/'analysis.json'),
         '--config',str(effective),'--out',str(candidate)]
    with (OUT/'dev23_final_calibration_01.log').open('xb') as f:subprocess.run(cmd,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=True)
    proposed=json.loads(candidate.read_text(encoding='utf-8'))
    with (OUT/'dev23_calibration_phase_completed.json').open('x',encoding='utf-8') as f:
        json.dump({'candidate':str(candidate.relative_to(ROOT)),
                   'candidate_sha256':hashlib.sha256(candidate.read_bytes()).hexdigest(),
                   'source':proposed['calibration_source'],'chosen':proposed.get('chosen'),
                   'status':'candidate_requires_review_and_freeze','model_calls':0},f,indent=2)
    print(candidate)

if __name__=='__main__':main()
