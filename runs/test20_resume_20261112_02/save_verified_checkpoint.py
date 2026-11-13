"""Save quiescent project evidence to E, without credentials or starting Docker."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,shutil,zipfile
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
TARGET=Path(r'E:\DockerBackups\project-session-20261112-02')
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024**2),b''):h.update(b)
    return h.hexdigest()
def write(p,v):
    with Path(p).open('x',encoding='utf-8') as f:json.dump(v,f,ensure_ascii=False,indent=2)
def main():
    shutdown=read(OUT/'shutdown_audit.json');cost=read(OUT/'final_cost_audit.json')
    validation=read(OUT/'final_validation.json');outcome=read(OUT/'final_outcome.json')
    assert shutdown['docker_desktop_stopped'] and not shutdown['docker_wsl_running']
    assert shutdown['owned_containers_remaining']==[] and shutdown['owned_workers_remaining']==[]
    assert validation['preservation_ok'] and validation['offline_suite_passed']
    assert sha(ROOT/'runs/test20_execution_20261111/batch_ledger.json')==cost['ledger_sha256']
    assert read(ROOT/outcome['inactive_config'])['execution']['live_authorized'] is False
    assert not TARGET.exists()
    excluded={'.git','.venv','__pycache__','.pytest_cache','node_modules'}
    self_refs={OUT/x for x in ('artifact_manifest.json','project_archive.json','SESSION_SAVED.json','checkpoint.log')}
    files=set()
    def add(p):
        if p.is_symlink() or p.name in excluded or p.name.startswith('.env'):return
        if p.is_dir():
            for q in p.iterdir():add(q)
        elif p.is_file() and p not in self_refs:files.add(p)
    for name in ('src','tests','scripts','configs','docs','docker','data','reports','dustbin'):add(ROOT/name)
    for p in (ROOT/'runs').iterdir():
        if p.is_dir() and ('20261111' in p.name or '20261112' in p.name or p.name=='prefix_cache'):add(p)
    for name in ('AGENTS.md','README.md','.gitattributes','.gitignore','requirements.txt','requirements-dev.txt'):add(ROOT/name)
    rows=[{'path':p.relative_to(ROOT).as_posix(),'size_bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(files)]
    assert shutil.disk_usage(TARGET.parent).free>sum(r['size_bytes'] for r in rows)+1024**3
    write(OUT/'artifact_manifest.json',{'kind':'quiescent_project_evidence_inventory','files':rows,
        'file_count':len(rows),'credentials_included':False,
        'external_docker_volume_not_in_archive':True,'old_cold_backups_location':'E:/DockerBackups/'})
    TARGET.mkdir(exist_ok=False);archive=TARGET/'project-session-20261112-02.zip'
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(files|{OUT/'artifact_manifest.json'}):z.write(p,p.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for row in rows:
            assert hashlib.sha256(z.read(row['path'])).hexdigest()==row['sha256']
            assert sha(ROOT/row['path'])==row['sha256']
    info={'path':str(archive),'sha256':sha(archive),'size_bytes':archive.stat().st_size,'files':len(rows)+1,
        'zip_crc_verified':True,'every_entry_sha256_verified':True}
    write(OUT/'project_archive.json',info)
    write(OUT/'SESSION_SAVED.json',{'kind':'verified_stopped_experiment_checkpoint',
        'saved_at':datetime.now(timezone.utc).isoformat(),'outcome':outcome,'cost':cost,
        'shutdown':shutdown,'validation':validation,'project_archive':info,'credentials_included':False,
        'model_calls_during_save':0,'new_full_vhdx_backup_created':False})
    for name in ('artifact_manifest.json','project_archive.json','SESSION_SAVED.json'):
        shutil.copyfile(OUT/name,TARGET/name);assert sha(OUT/name)==sha(TARGET/name)
    print(json.dumps({'saved':True,'archive':info,'pending':cost['pending']},ensure_ascii=False))
if __name__=='__main__':main()
