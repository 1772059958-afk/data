"""Write the scoped cooperative stop flag before the saved disk reserve is lost."""
from pathlib import Path
from datetime import datetime, timezone
import json,os,shutil,time

HERE=Path(__file__).resolve().parent
STOP=HERE/'WORKFLOW_STOP.json'
DONE=HERE/'WORKFLOW_FINISHED.json'

def main():
    start=datetime.now(timezone.utc).isoformat()
    minimum=4*1024**3+64*1024**2
    while not STOP.exists() and not DONE.exists():
        free={drive:shutil.disk_usage(drive+':/').free for drive in ('C','D')}
        if min(free.values())<minimum:
            try:
                with STOP.open('x',encoding='utf-8') as f:
                    json.dump({'reason':'disk_reserve_breakpoint','minimum_bytes':minimum,'free_bytes':free,
                               'at':datetime.now(timezone.utc).isoformat()},f,indent=2)
            except FileExistsError:pass
            break
        time.sleep(5)
    with (HERE/'disk_guard_exit.json').open('x',encoding='utf-8') as f:
        json.dump({'pid':os.getpid(),'started_at':start,'ended_at':datetime.now(timezone.utc).isoformat(),
                   'stop_present':STOP.exists(),'workflow_finished':DONE.exists()},f,indent=2)

if __name__=='__main__':main()
