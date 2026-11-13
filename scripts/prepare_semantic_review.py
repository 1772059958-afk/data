"""Quarantine issue/reference evidence for review of already-sealed TEST patches."""
from pathlib import Path
import hashlib,json
import pyarrow.parquet as pq
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'runs/dev_supplement_20261112_02/review_only'
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    freeze=read(ROOT/'runs/test20_resume_20261112_02/formal_generation_freeze_manifest.json')
    assert freeze['prediction_count']==100
    for f in freeze['artifacts']:assert sha(ROOT/f['path'])==f['sha256']
    OUT.mkdir(exist_ok=False)
    source=read(ROOT/'data/harness/manifest.json')['splits']['test'];data=ROOT/source['local_file']
    assert sha(data)==source['sha256'].lower()
    rows={r['instance_id']:r for r in pq.read_table(data,columns=['instance_id','repo','base_commit','problem_statement','patch']).to_pylist()}
    matrices={a:read(ROOT/'runs'/tag/'matrix.json') for a,tag in freeze['tags'].items()}
    records={a:{r['instance_id']:r for r in map(json.loads,(ROOT/'runs'/tag/'evaluated_records.jsonl').read_text(encoding='utf-8').splitlines())} for a,tag in freeze['tags'].items()}
    index=[]
    for iid in freeze['instances']:
        groups={};submissions={}
        for arm,m in matrices.items():
            c=next(c for c in m['cases'] if c['instance_id']==iid);diff=c['submitted_patch']
            digest=hashlib.sha256(diff.encode()).hexdigest()
            groups.setdefault(digest,{'sha256':digest,'patch':diff,'arms':[]})['arms'].append(arm)
            submissions[arm]={'patch_sha256':digest,'official_status':records[arm][iid]['status'],
                'generation_status':c['status'],'route':c['selected_route'],
                'source_matrix':str((ROOT/'runs'/m['tag']/'matrix.json').relative_to(ROOT))}
        packet={'kind':'review_only_after_all_formal_predictions_sealed','instance_id':iid,'repo':rows[iid]['repo'],
            'base_commit':rows[iid]['base_commit'],'issue':rows[iid]['problem_statement'],
            'developer_reference_patch':rows[iid]['patch'],'unique_submitted_patches':list(groups.values()),
            'submissions':submissions,'generation_import_prohibited':True,'reference_is_not_a_textual_equality_oracle':True}
        p=OUT/(iid+'.json')
        with p.open('x',encoding='utf-8') as f:json.dump(packet,f,ensure_ascii=False,indent=2)
        index.append({'instance_id':iid,'packet':str(p.relative_to(ROOT)),'sha256':sha(p),
            'unique_patches':len(groups),'patch_characters':sum(len(v['patch']) for v in groups.values()),'issue_characters':len(packet['issue'])})
    with (OUT/'index.json').open('x',encoding='utf-8') as f:json.dump({'coverage':100,'instances':20,'source_freeze_sha256':sha(ROOT/'runs/test20_resume_20261112_02/formal_generation_freeze_manifest.json'),
        'dataset_sha256':sha(data),'packets':index,'human_sign_off_fabricated':False,'reviewer':'current coding agent; analyst review, not an external human signature'},f,ensure_ascii=False,indent=2)
    (OUT/'README.md').write_text('Review-only reference answers and sealed outputs. Never import these packets into generation, localization, routing, candidate selection or DEV model prompts. All formal100 predictions were sealed before this directory was created.\n',encoding='utf-8')
    print(json.dumps(index,ensure_ascii=False))
if __name__=='__main__':main()
