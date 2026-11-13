"""Read live checkpoints without blocking Windows atomic rename writers."""
from pathlib import Path
import ctypes,json,os,shutil
from ctypes import wintypes

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent

def shared_json(path):
    path=Path(path)
    if os.name!='nt':
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
    import msvcrt
    dll=ctypes.WinDLL('kernel32',use_last_error=True)
    create=dll.CreateFileW
    create.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,wintypes.LPVOID,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    create.restype=wintypes.HANDLE
    handle=create(str(path.resolve()),0x80000000,7,None,3,0x80,None)
    if handle==ctypes.c_void_p(-1).value:
        err=ctypes.get_last_error()
        if err in (2,3):return None
        raise ctypes.WinError(err)
    fd=msvcrt.open_osfhandle(int(handle),os.O_RDONLY|os.O_BINARY)
    with os.fdopen(fd,'rb') as stream:return json.loads(stream.read().decode('utf-8'))

def main():
    ledger=shared_json(ROOT/'runs/test20_execution_20261111/batch_ledger.json')
    arms={}
    for arm in 'ABCDE':
        tag='test20_'+arm+'_20261112_01';m=shared_json(ROOT/'runs'/tag/'matrix.json')
        if m:
            n=len(m['cases']);ids=m['designated_instances']
            arms[arm]={'complete':n,'designated':len(ids),'active_or_next':ids[n] if n<len(ids) else None,
                       'batch_stopped':m.get('batch_stopped'),'config_hash':m['config_hash']}
    print(json.dumps({'arms':arms,'requests_booked':len(ledger['records']),
         'cumulative_estimate_cny':round(sum(v['cost_cny'] for v in ledger['records']),8),
         'pending_run':(ledger.get('pending') or {}).get('run_id'),
         'stop':shared_json(OUT/'WORKFLOW_STOP.json'),
         'all_predictions_frozen':(OUT/'formal_generation_freeze_manifest.json').exists(),
         'scoring_complete':(OUT/'formal_scoring_completed.json').exists(),
         'free_gib':{v:round(shutil.disk_usage(v+':/').free/1024**3,2) for v in ('C','D')}},ensure_ascii=False))

if __name__=='__main__':main()
