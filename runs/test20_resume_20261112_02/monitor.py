"""Compact read-only live status using shared-delete Windows handles."""
from pathlib import Path
import importlib.util,json,shutil
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('shared_monitor',ROOT/'runs/test20_resume_20261112_01/monitor_workflow.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
read=mod.shared_json
def main():
    tags={'A':'test20_A_20261112_01','B':'test20_B_20261112_02','C':'test20_C_20261112_01',
          'D':'test20_D_20261112_01','E':'test20_E_20261112_01'}
    ledger=read(ROOT/'runs/test20_execution_20261111/batch_ledger.json');arms={};active=None
    for arm,tag in tags.items():
        m=read(ROOT/'runs'/tag/'matrix.json')
        if m:
            n=len(m['cases']);arms[arm]={'committed':n,'active_or_next':m['designated_instances'][n] if n<20 else None,
                'batch_stopped':m.get('batch_stopped')}
            events=ROOT/'runs'/tag/'events.jsonl'
            if n<20 and events.exists():
                with events.open('rb') as f:
                    f.seek(max(0,events.stat().st_size-150000));tail=f.read().splitlines()
                for line in reversed(tail):
                    try:entry=json.loads(line)
                    except (ValueError,UnicodeError):continue
                    event=entry.get('event',{})
                    if not isinstance(event,dict):continue
                    active={'arm':arm,'instance':entry.get('instance_id'),'stage':entry.get('stage'),
                        'event':event.get('event'),'consumed':event.get('budget',{}).get('consumed')}
                    break
    print(json.dumps({'arms':arms,'requests_booked':len(ledger['records']),
        'cumulative_estimate_cny':round(sum(r['cost_cny'] for r in ledger['records']),8),
        'pending_run':(ledger.get('pending') or {}).get('run_id'),
        'active_event':active,
        'stop':read(ROOT/'runs/test20_resume_20261112_01/WORKFLOW_STOP.json'),
        'all100_frozen':(OUT/'formal_generation_freeze_manifest.json').exists(),
        'scoring_complete':(OUT/'formal_scoring_completed.json').exists(),
        'free_gib':{d:round(shutil.disk_usage(d+':/').free/1024**3,2) for d in 'CD'}},ensure_ascii=False))
if __name__=='__main__':main()
