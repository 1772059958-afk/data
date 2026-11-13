"""Archive the already-stopped session; never starts experiments or Docker."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
TARGET=Path(r'D:\CodexExperimentCache\test20_20261111\checkpoint_20261112_01')


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024**2),b''):h.update(b)
    return h.hexdigest()


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path,obj):
    with Path(path).open('x',encoding='utf-8',newline='\n') as f:
        json.dump(obj,f,ensure_ascii=False,indent=2);f.write('\n')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state',required=True,choices=['complete','blocked'])
    args=p.parse_args()
    shutdown=read(OUT/'shutdown_audit.json')
    cost=read(OUT/'final_cost_audit.json')
    validation=read(OUT/'final_validation.json')
    outcome=read(OUT/'final_outcome.json')
    assert shutdown['docker_desktop_stopped'] and not shutdown['docker_wsl_running']
    assert shutdown['owned_containers_remaining']==[] and shutdown['owned_workers_remaining']==[]
    assert validation['preservation_ok'] and validation['offline_suite_passed']
    ledger=ROOT/'runs/test20_execution_20261111/batch_ledger.json'
    assert digest(ledger)==cost['ledger_sha256']
    assert read(ledger)['pending']==cost['pending']
    assert outcome['state']==args.state
    assert read(ROOT/outcome['inactive_config'])['execution']['live_authorized'] is False
    handoff=ROOT/'docs/恢复执行与断点交接_20261112.md'
    assert handoff.is_file()
    # Both destinations are new; the previous day's checkpoint remains untouched.
    assert not TARGET.exists() and not (OUT/'SESSION_SAVED.json').exists()
    excluded={'.git','.venv','__pycache__','.pytest_cache','node_modules'}
    self_refs={OUT/n for n in ['artifact_manifest.json','project_archive.json','SESSION_SAVED.json']}
    files=set()
    def add(path):
        if path.is_symlink() or path.name in excluded or path.name.startswith('.env'):return
        if path.is_dir():
            for child in path.iterdir():add(child)
        elif path.is_file() and path not in self_refs:files.add(path)
    for name in ['src','tests','scripts','configs','docs','docker','data','reports','dustbin']:
        add(ROOT/name)
    # Include the full current round and its actual prefix caches, not temporary checkouts.
    for directory in (ROOT/'runs').iterdir():
        if directory.is_dir() and ('20261111' in directory.name or '20261112' in directory.name or directory.name=='prefix_cache'):
            add(directory)
    for name in ['AGENTS.md','README.md','.gitattributes','.gitignore','requirements.txt','requirements-dev.txt']:
        add(ROOT/name)
    rows=[{'path':v.relative_to(ROOT).as_posix(),'size_bytes':v.stat().st_size,'sha256':digest(v)} for v in sorted(files)]
    size=sum(v['size_bytes'] for v in rows)
    assert shutil.disk_usage(TARGET.parent).free>size+1024**3,'checkpoint space reserve insufficient'
    manifest=OUT/'artifact_manifest.json'
    write(manifest,{'kind':'verified_stopped_round_inventory','files':rows,'file_count':len(rows),
                    'credentials_included':False,'excluded':['.env*','.git','.venv','bytecode','temporary checkouts'],
                    'external_docker_data_and_caches':'durable D paths recorded in shutdown audit; not included in project ZIP'})
    TARGET.mkdir(exist_ok=False)
    archive=TARGET/'project-session-20261112.zip'
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for path in sorted(files|{manifest}):z.write(path,path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for row in rows:
            assert hashlib.sha256(z.read(row['path'])).hexdigest()==row['sha256']
            assert digest(ROOT/row['path'])==row['sha256']
    info={'path':str(archive),'sha256':digest(archive),'size_bytes':archive.stat().st_size,
          'files':len(rows)+1,'zip_crc_verified':True,'every_entry_sha256_verified':True}
    write(OUT/'project_archive.json',info)
    saved={'kind':'verified_experiment_checkpoint','saved_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
           'state':args.state,'outcome':outcome,'cost':cost,'shutdown':shutdown,'validation':validation,
           'handoff':{'path':handoff.relative_to(ROOT).as_posix(),'sha256':digest(handoff)},
           'project_archive':info,'model_calls_during_save':0,'new_full_vhdx_backup_created':False,
           'credentials_included':False,'requires_explicit_resume_if_blocked':args.state=='blocked'}
    write(OUT/'SESSION_SAVED.json',saved)
    for name in ['artifact_manifest.json','project_archive.json','SESSION_SAVED.json']:
        shutil.copyfile(OUT/name,TARGET/name);assert digest(OUT/name)==digest(TARGET/name)
    assert digest(ledger)==cost['ledger_sha256']
    print(json.dumps({'state':args.state,'archive':info,'pending':cost['pending']},ensure_ascii=False))


if __name__=='__main__':main()
