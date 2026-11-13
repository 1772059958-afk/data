"""Emit a bounded, credential-free live heartbeat using shared-delete reads."""
import contextlib,datetime,importlib.util,io,json,os,time
from pathlib import Path
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('workflow_monitor',HERE/'monitor_workflow.py')
monitor=importlib.util.module_from_spec(spec);spec.loader.exec_module(monitor)
with (HERE/'workflow_follow_started.json').open('x',encoding='utf-8') as f:
    json.dump({'pid':os.getpid(),'source':'follow_workflow.py','model_calls':0},f)
while True:
    try:
        buffer=io.StringIO()
        with contextlib.redirect_stdout(buffer):monitor.main()
        row=json.loads(buffer.getvalue());row['at']=datetime.datetime.now(datetime.timezone.utc).isoformat()
        print(json.dumps(row,ensure_ascii=False),flush=True)
    except (FileNotFoundError,json.JSONDecodeError):
        time.sleep(1)
        continue
    if row['stop'] or row['scoring_complete'] or (HERE/'WORKFLOW_FINISHED.json').exists():break
    time.sleep(45)
