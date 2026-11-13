"""Preserve PPT metadata and fingerprint project evidence before cache deletion."""
from pathlib import Path
import hashlib,json,os,shutil
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
TARGETS=['work','.chart-data-9ms2WV','.chart-data-uYclH4','.chart-data-wWZuBa','.chart-data-yKvtsO']
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda:f.read(1024**2),b''):h.update(block)
    return h.hexdigest()
def save(name,data):
    with (OUT/name).open('x',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2)
def protected():
    for parent,dirs,names in os.walk(ROOT,followlinks=False):
        dirs[:]=[n for n in dirs if n not in {'.git','.venv','__pycache__','.pytest_cache'} and not (Path(parent)==ROOT and n in TARGETS) and Path(parent,n)!=OUT]
        for name in names:
            p=Path(parent)/name
            if name.startswith(('.env','~$')) or p.suffix in {'.pyc','.tmp','.lock'}:continue
            assert not p.is_symlink(),str(p)
            yield {'path':p.relative_to(ROOT).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)}
if __name__=='__main__':
    items=[];preserved=[]
    for name in TARGETS:
        target=ROOT/name;assert target.is_dir() and not target.is_symlink()
        files=[]
        for p in sorted(target.rglob('*')):
            assert not p.is_symlink(),str(p)
            if not p.is_file():continue
            row={'path':p.relative_to(ROOT).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)};files.append(row)
            if p.suffix in {'.json','.ndjson'}:
                dest=OUT/'preserved_build_metadata'/p.relative_to(ROOT)
                dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dest)
                assert sha(dest)==row['sha256']
                preserved.append({**row,'preserved_path':dest.relative_to(ROOT).as_posix()})
        items.append({'absolute':str(target),'relative':name,'files':files,'bytes':sum(r['bytes'] for r in files)})
    rows=list(protected())
    save('protected_files_before.json',rows)
    save('cleanup_plan.json',{'targets':items,'preserved':preserved,'protected_files':len(rows),'shutdown_authorized':False})
    print(json.dumps({'targets':len(items),'deletable_bytes':sum(r['bytes'] for r in items),'protected_files':len(rows),'preserved_metadata':len(preserved)}))
