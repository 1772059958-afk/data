"""Finish publication after nested third-party attributes normalize archived CRLF."""
from pathlib import Path
from datetime import datetime
import hashlib,json,re
from publish_project import ROOT,OUT,GIT,git,sha,PREFLIGHT,CANDIDATES,FINGERPRINTS,credential_file

def index_entries():
    out={}
    for entry in git('ls-files','--stage','-z').split(b'\0'):
        if entry:
            meta,name=entry.split(b'\t',1);mode,blob,stage=meta.split();assert stage==b'0'
            out[name.decode('utf-8')]=(mode.decode(),blob.decode())
    return out

def raw_blob(name):
    content=(ROOT/name).read_bytes()
    return hashlib.sha1(('blob '+str(len(content))+'\0').encode()+content).hexdigest()

def main():
    assert git('branch','--show-current').strip()==b'develop'
    assert git('rev-parse','HEAD').decode().strip()=='84ad2f26af0faca0d75f3acec70834aa369a5d21'
    check=json.loads((OUT/PREFLIGHT).read_text(encoding='utf-8'))
    assert not check['credential_findings'] and check['env_excluded']
    fingerprints=json.loads((OUT/FINGERPRINTS).read_text(encoding='utf-8'))['files']
    known={r['path']:r['git_blob_raw'] for r in fingerprints}
    for row in fingerprints:assert sha(ROOT/row['path'])==row['sha256'],row['path']
    files=json.loads((OUT/CANDIDATES).read_text(encoding='utf-8'))['files']
    files.extend((OUT/name).relative_to(ROOT).as_posix() for name in [PREFLIGHT,CANDIDATES,FINGERPRINTS])
    files.append(Path(__file__).relative_to(ROOT).as_posix())
    files=sorted(set(files))
    patterns=[rb'\bsk-[A-Za-z0-9_-]{24,}',rb'\b(?:ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{50,})',rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b',rb'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----']
    for name in files:
        assert not credential_file(Path(name).name) and '.venv' not in Path(name).parts
        if name not in known:
            content=(ROOT/name).read_bytes()
            assert not any(re.search(pattern,content) for pattern in patterns),name
            known[name]=raw_blob(name)
    groups=[('data: preserve dev calibration formal results and cleanup audit evidence',
        [p for p in files if p.split('/')[0] in {'runs','data','reports','dustbin'}]),
      ('docs: deliver closeout slides and final experiment handoff',
        [p for p in files if p.split('/')[0] not in {'src','scripts','tests','configs','docker','runs','data','reports','dustbin'} and p not in {'.gitattributes','.gitignore'}])]
    receipt_path=ROOT/'.git/codex_publish_20261113_02.json'
    receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
    spec=ROOT/'.git/codex_publish_paths_20261113_02.nul'
    fixes=[]
    for message,paths in groups:
        spec.write_bytes(b'\0'.join(p.encode('utf-8') for p in paths)+b'\0')
        git('--literal-pathspecs','add','--force','--pathspec-from-file='+str(spec),'--pathspec-file-nul')
        staged={p.decode('utf-8') for p in git('diff','--cached','--name-only','-z').split(b'\0') if p}
        assert staged.issubset(set(paths)),'Unexpected staged path'
        index=index_entries()
        attr=git('check-attr','--stdin','-z','text',input=b'\0'.join(p.encode('utf-8') for p in paths)+b'\0').split(b'\0')
        exact={attr[i].decode('utf-8') for i in range(0,len(attr)-1,3) if attr[i+2]==b'unset'}
        exact.update(p for p in paths if p.startswith(('runs/','src/')) or p.endswith('.pptx'))
        changed=[p for p in sorted(exact) if index[p][1]!=known[p]]
        if changed:
            assert not any('\n' in p or '\r' in p for p in changed)
            blobs=git('hash-object','-w','--no-filters','--stdin-paths',input=('\n'.join(changed)+'\n').encode()).decode().splitlines()
            assert len(blobs)==len(changed)
            rows=[]
            for name,blob in zip(changed,blobs):
                assert blob==known[name],name
                rows.append((index[name][0]+' '+blob+'\t'+name).encode()+b'\0')
            git('update-index','-z','--index-info',input=b''.join(rows))
            fixes.extend(changed)
        index=index_entries()
        for name in exact:assert index[name][1]==known[name],name
        git('commit','-m',message)
        receipt['commits'].append({'commit':git('rev-parse','HEAD').decode().strip(),'message':message})
        receipt['head']=receipt['commits'][-1]['commit']
        receipt['raw_index_preserved_files']=len(fixes)
        receipt['raw_index_reason']='Nested upstream .gitattributes uses text=auto; object/index records preserve original archived bytes.'
        receipt['push_status']='not_yet_pushed';receipt['shutdown']=False
        receipt_path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(receipt['commits'][-1]),flush=True)
    spec.unlink(missing_ok=True)
    receipt['working_tree_status']=git('status','--porcelain=v1','--untracked-files=normal').decode('utf-8')
    receipt['at_local']=datetime.now().isoformat(timespec='seconds')
    receipt['final_ppt_sha256']=sha(ROOT/'docs/deliverables/结题汇报_深入分析版_20261113_定稿.pptx')
    receipt['ledger_sha256']=sha(ROOT/'runs/test20_execution_20261111/batch_ledger.json')
    receipt_path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'commits':len(receipt['commits']),'clean':not receipt['working_tree_status'],'head':receipt['head'],'raw_index_preserved_files':len(fixes)}))

if __name__=='__main__':main()
