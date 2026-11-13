"""Preserve project sources/evidence before deleting only the work build tree."""
from pathlib import Path
from datetime import datetime
from collections import Counter
import hashlib,json,os,shutil
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent;WORK=ROOT/'work'
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024**2),b''):h.update(b)
    return h.hexdigest()
def write(p,v):
    with Path(p).open('x',encoding='utf-8') as f:json.dump(v,f,ensure_ascii=False,indent=2)
def main():
    keep=OUT/'preserved_work';keep.mkdir(exist_ok=False)
    excluded_parts={'__pycache__','.git','linux_site','uv_cache','docker_cli','wheels','system_debs'}
    source_extensions={'.py','.mjs','.js','.ts','.ps1','.sh','.md','.toml','.yml','.yaml'}
    rows=[];copied=[];categories=Counter()
    for directory,dirs,files in os.walk(WORK,followlinks=False):
        if any((Path(directory)/d).is_symlink() for d in dirs):raise RuntimeError('Path link in work tree')
        for name in files:
            p=Path(directory)/name
            if p.is_symlink():raise RuntimeError('Linked file in work tree')
            r=p.relative_to(WORK);parts=r.parts;size=p.stat().st_size
            if p.name.startswith('.env'):raise RuntimeError('Unexpected credential file in work, preserve in place')
            preserve=True;reason='source_or_original_record'
            if any(part in excluded_parts for part in parts) or p.suffix=='.pyc':preserve=False;reason='rebuildable_dependency_cache_or_git_objects'
            elif parts[0].startswith('ppt_'):
                preserve=(p.suffix.lower() in source_extensions or 'validation' in p.name.lower() or
                    (len(parts)==2 and p.suffix.lower() in {'.json','.txt','.log'} and p.name!='authored-proto.json') or
                    p.name=='reference_asset.png')
                reason='ppt_source_data_or_validation' if preserve else 'ppt_draft_render_or_import_inspection'
            info={'path':r.as_posix(),'bytes':size,'preserve':preserve,'category':reason}
            rows.append(info);categories[reason]+=size
            if preserve:
                dest=keep/r;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
                digest=sha(p);assert sha(dest)==digest
                copied.append({'original_path':str(p.relative_to(ROOT)),'preserved_path':str(dest.relative_to(ROOT)),
                    'bytes':size,'sha256':digest})
    write(OUT/'work_retention_manifest.json',{'at_local':datetime.now().isoformat(timespec='seconds'),
        'original_work_files':len(rows),'original_work_logical_bytes':sum(r['bytes'] for r in rows),
        'preserved_files':copied,'preserved_logical_bytes':sum(r['bytes'] for r in copied),
        'classification_bytes':dict(categories),'all_work_files':rows})
    # Preserve the final PPT receipt beside the delivery, keeping old manifest bytes unchanged.
    receipt=ROOT/'docs/deliverables/结题汇报_20261112_source/validation_receipt.json'
    assert not receipt.exists();shutil.copy2(WORK/'ppt_closeout_20261112/validation.json',receipt)
    assert sha(receipt)==sha(WORK/'ppt_closeout_20261112/validation.json')
    write(ROOT/'docs/deliverables/结题汇报_20261112_source/validation_location_after_cleanup.json',{
        'historical_validation_path':'work/ppt_closeout_20261112/validation.json',
        'current_validation_path':str(receipt.relative_to(ROOT)),'sha256':sha(receipt),
        'reason':'Build/previews cleaned at user request; final deck and all source code remain.'})
    (keep/'PRESERVED_WORK_README.md').write_text('Historical build helpers, source checkouts and original validation/data records, preserved byte-for-byte before work cleanup. This directory is a cold source/evidence copy, not a new experiment entry point. Installed dependency copies, package caches, git object caches and generated PPT drafts/previews were removed. No credentials were copied.\n',encoding='utf-8')
    protected=[]
    for group in ('src','scripts','tests','configs','data','reports','dustbin','docs/deliverables','runs'):
        base=ROOT/group
        for directory,dirs,files in os.walk(base,followlinks=False):
            dirs[:]=[d for d in dirs if d!='__pycache__' and not (Path(directory)/d).is_symlink()]
            for name in files:
                p=Path(directory)/name
                if p.is_relative_to(OUT) or p.is_symlink() or p.suffix=='.pyc' or name.startswith('.env') or name=='debug.log':continue
                protected.append({'path':str(p.relative_to(ROOT)),'bytes':p.stat().st_size,'sha256':sha(p)})
    write(OUT/'protected_files_before.json',{'files':protected,'file_count':len(protected),
        'ppt_and_source_records_preserved':True,'free_C_before_bytes':shutil.disk_usage('C:/').free})
    print(json.dumps({'work_logical_gib':sum(r['bytes'] for r in rows)/1024**3,
        'preserved_source_and_records_gib':sum(r['bytes'] for r in copied)/1024**3,'preserved_files':len(copied),
        'protected_file_count':len(protected)},ensure_ascii=False))
if __name__=='__main__':main()
