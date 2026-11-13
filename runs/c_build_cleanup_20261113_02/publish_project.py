"""User-authorized source/data/PPT publication with credential and size gates."""
from pathlib import Path
from datetime import datetime
import hashlib,json,os,re,subprocess,sys
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
GIT=['git','-c','safe.directory='+ROOT.as_posix(),'-c','core.excludesFile=NUL','-c','core.quotePath=false']
SAFE_ENV_TEMPLATES={'.env.example','.env.sample','.env.template'}
PREFLIGHT='publication_preflight_commit_ready.json'
CANDIDATES='publication_candidates_commit_ready.json'
FINGERPRINTS='publication_fingerprints_commit_ready.json'
def credential_file(name):return name.startswith('.env') and name not in SAFE_ENV_TEMPLATES
def git(*args,input=None):
    r=subprocess.run(GIT+list(args),cwd=ROOT,input=input,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if r.returncode:raise RuntimeError(r.stderr.decode('utf-8',errors='replace')[:1500])
    return r.stdout
def write(p,v):
    with Path(p).open('x',encoding='utf-8') as f:json.dump(v,f,ensure_ascii=False,indent=2)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def candidates():
    files=set(p.decode('utf-8') for p in git('ls-files','--cached','--others','--exclude-standard','-z').split(b'\0') if p)
    # User explicitly asked to publish experiment data; include normally ignored
    # phase events and harness logs, but never credentials or derived pyc/temp files.
    for directory,dirs,names in os.walk(ROOT/'runs',followlinks=False):
        dirs[:]=[d for d in dirs if d not in {'__pycache__','.git','.venv','node_modules'}]
        for name in names:
            p=Path(directory)/name
            if p.suffix in {'.pyc','.tmp','.lock'} or credential_file(name) or name.startswith('~$'):continue
            files.add(p.relative_to(ROOT).as_posix())
    return sorted(p for p in files if (ROOT/p).is_file())
def prepare():
    files=candidates();findings=[];sizes=[];fingerprints=[]
    assert not git('diff','--cached','--name-only'), 'Preexisting staged changes require review'
    cache_path=OUT/'publication_fingerprints_final.json'
    cached={r['path']:r for r in json.loads(cache_path.read_text(encoding='utf-8'))['files']} if cache_path.exists() else {}
    old_check=json.loads((OUT/'publication_preflight_final.json').read_text(encoding='utf-8')) if cached else {}
    old_hits={r['path']:r for r in old_check.get('credential_findings',[])+old_check.get('verified_upstream_public_fixtures',[])}
    patterns=[('provider_key',re.compile(rb'\bsk-[A-Za-z0-9_-]{24,}')),
        ('github_token',re.compile(rb'\b(?:ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{50,})')),
        ('aws_access_key',re.compile(rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b')),
        ('private_key',re.compile(rb'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----'))]
    for ordinal,relative in enumerate(files,1):
        p=ROOT/relative
        if p.is_symlink() or credential_file(p.name) or '.venv' in p.parts or 'work'==p.relative_to(ROOT).parts[0]:
            raise RuntimeError('Forbidden publication path: '+relative)
        size=p.stat().st_size;sizes.append((size,relative))
        if size>=100*1024**2:raise RuntimeError('File exceeds GitHub100MiB limit: '+relative)
        prior=cached.get(relative)
        if prior and size==prior['bytes'] and sha(p)==prior['sha256']:
            fingerprints.append(prior)
            if relative in old_hits:findings.append(old_hits[relative])
            if ordinal%1000==0:print(json.dumps({'hash_verified_files':ordinal,'total':len(files)}),flush=True)
            continue
        tail=b'';digest=hashlib.sha256();blob=hashlib.sha1(('blob '+str(size)+'\0').encode())
        with p.open('rb') as f:
            for block in iter(lambda:f.read(1024**2),b''):
                chunk=tail+block
                digest.update(block);blob.update(block)
                for kind,pattern in patterns:
                    if pattern.search(chunk):findings.append({'path':relative,'kind':kind})
                tail=chunk[-256:]
        fingerprints.append({'path':relative,'sha256':digest.hexdigest(),'git_blob_raw':blob.hexdigest(),'bytes':size})
        if ordinal%1000==0:print(json.dumps({'scanned_files':ordinal,'total':len(files)}),flush=True)
    findings=list({(r['path'],r['kind']):r for r in findings}.values())
    review=json.loads((OUT/'public_fixture_credential_review.json').read_text(encoding='utf-8'))
    approved={r['path']:r['file_sha256'] for r in review['findings'] if r['public_fixture_match']}
    current={r['path']:r['sha256'] for r in fingerprints}
    public_fixtures=[r for r in findings if r['kind']=='private_key' and current[r['path']]==approved.get(r['path'])]
    findings=[r for r in findings if r not in public_fixtures]
    result={'at_local':datetime.now().isoformat(timespec='seconds'),'candidate_count':len(files),
        'logical_bytes':sum(s for s,p in sizes),'credential_findings':findings,'verified_upstream_public_fixtures':public_fixtures,
        'largest_files':[{'path':p,'bytes':s} for s,p in sorted(sizes,reverse=True)[:8]],
        'file_over_100MiB':False,'env_excluded':'.env' not in files,
        'raw_events_and_harness_logs_included':True,'remote_ref':'refs/heads/develop',
        'head_before':git('rev-parse','HEAD').decode().strip(),'shutdown_authorized':False}
    write(OUT/PREFLIGHT,result)
    write(OUT/CANDIDATES,{'files':files})
    write(OUT/FINGERPRINTS,{'files':fingerprints})
    print(json.dumps(result,ensure_ascii=False))
    if findings:raise RuntimeError('Credential-pattern findings require local review; values were not printed')
def commit_all():
    check=json.loads((OUT/PREFLIGHT).read_text(encoding='utf-8'))
    assert not check['credential_findings'] and check['env_excluded']
    assert git('branch','--show-current').strip()==b'develop'
    assert git('rev-parse','HEAD').decode().strip()==check['head_before']
    fingerprints=json.loads((OUT/FINGERPRINTS).read_text(encoding='utf-8'))['files']
    for row in fingerprints:assert sha(ROOT/row['path'])==row['sha256'], 'Candidate changed: '+row['path']
    files=json.loads((OUT/CANDIDATES).read_text(encoding='utf-8'))['files']
    # Include the reviewed preflight records, which contain paths/counts only.
    files+=[(OUT/name).relative_to(ROOT).as_posix() for name in [PREFLIGHT,CANDIDATES,FINGERPRINTS]]
    groups=[('feat: finalize guarded repair execution and descriptive experiment tooling',
        [p for p in files if p.split('/')[0] in {'src','scripts','tests','configs','docker'} or p in {'.gitattributes','.gitignore'}]),
      ('data: preserve dev calibration formal results and cleanup audit evidence',
        [p for p in files if p.split('/')[0] in {'runs','data','reports','dustbin'}]),
      ('docs: deliver closeout slides and final experiment handoff',
        [p for p in files if p.split('/')[0] not in {'src','scripts','tests','configs','docker','runs','data','reports','dustbin'} and p not in {'.gitattributes','.gitignore'}])]
    commits=[]
    index_path=ROOT/'.git/codex_publish_paths_20261113_02.nul'
    receipt_path=ROOT/'.git/codex_publish_20261113_02.json'
    for message,paths in groups:
        if not paths:continue
        index_path.write_bytes(b'\0'.join(p.encode('utf-8') for p in paths)+b'\0')
        git('--literal-pathspecs','add','--force','--pathspec-from-file='+str(index_path),'--pathspec-file-nul')
        git('--literal-pathspecs','add','--renormalize','--pathspec-from-file='+str(index_path),'--pathspec-file-nul')
        staged=git('diff','--cached','--name-only','-z')
        if not staged:continue
        # Final guard against accidentally staging a credential or machine env.
        if any(credential_file(Path(p.decode('utf-8')).name) or '.venv' in Path(p.decode('utf-8')).parts for p in staged.split(b'\0') if p):raise RuntimeError('Forbidden staged path')
        # Confirm files with -text attributes retain their exact source/evidence bytes.
        index={}
        for entry in git('ls-files','--stage','-z').split(b'\0'):
            if entry:
                meta,name=entry.split(b'\t',1);index[name.decode('utf-8')]=meta.split()[1].decode()
        attrs=git('check-attr','--stdin','-z','text',input=b'\0'.join(p.encode('utf-8') for p in paths)+b'\0').split(b'\0')
        exact={attrs[i].decode('utf-8') for i in range(0,len(attrs)-1,3) if attrs[i+2]==b'unset'}
        exact.update(name for name in paths if name.startswith(('runs/','src/')) or name.endswith('.pptx'))
        known={r['path']:r['git_blob_raw'] for r in fingerprints}
        for name in exact:
            expected=known.get(name)
            if expected is None:
                content=(ROOT/name).read_bytes();expected=hashlib.sha1(('blob '+str(len(content))+'\0').encode()+content).hexdigest()
            assert index[name]==expected,'Index bytes differ from preserved input: '+name
        git('commit','-m',message)
        commits.append({'commit':git('rev-parse','HEAD').decode().strip(),'message':message})
        print(json.dumps(commits[-1]),flush=True)
        receipt_path.write_text(json.dumps({'commits':commits,'branch':'develop','push_status':'not_yet_pushed','shutdown':False},ensure_ascii=False,indent=2),encoding='utf-8')
    index_path.unlink(missing_ok=True)
    status=git('status','--porcelain=v1','--untracked-files=normal').decode('utf-8')
    receipt={'commits':commits,'head':git('rev-parse','HEAD').decode().strip(),'branch':'develop',
        'working_tree_status':status,'push_status':'not_yet_pushed','at_local':datetime.now().isoformat(timespec='seconds'),'shutdown':False}
    receipt_path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'commits_created':len(commits),'working_tree_clean':not status,'head':receipt['head']},ensure_ascii=False))
if __name__=='__main__':
    if sys.argv[1:] == ['--prepare']:prepare()
    elif sys.argv[1:] == ['--commit']:commit_all()
    else:raise SystemExit('--prepare or --commit required')
