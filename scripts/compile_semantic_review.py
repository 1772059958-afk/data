"""Bind completed qualitative notes to all 100 sealed TEST submissions."""
from pathlib import Path
from collections import Counter
import hashlib,json
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'runs/dev_supplement_20261112_02/review_only'
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    index=read(OUT/'index.json');notes={};sources=[]
    for path in sorted(OUT.glob('notes_batch*.json')):
        sources.append({'path':str(path.relative_to(ROOT)),'sha256':sha(path)})
        for case in read(path)['cases']:
            assert case['instance_id'] not in notes
            notes[case['instance_id']]=case
    rows=[];table=[];unique=0
    for item in index['packets']:
        p=ROOT/item['packet'];assert sha(p)==item['sha256'];packet=read(p);iid=packet['instance_id']
        note=notes.pop(iid);by_arm={}
        for group in note['groups']:
            for arm in group['arms']:
                assert arm not in by_arm;by_arm[arm]=group
        assert set(by_arm)==set('ABCDE')
        unique+=len(packet['unique_submitted_patches'])
        for arm,submission in packet['submissions'].items():
            group=by_arm[arm]
            rows.append({'instance_id':iid,'arm':arm,**submission,
                'packet_sha256':item['sha256'],'requirement':note['requirement'],
                'assessment':group['assessment'],'reason':group['reason'],'residual_risk':group.get('residual_risk'),
                'official_status_unchanged':True})
        table.append('| '+iid+' | '+'; '.join('/'.join(g['arms'])+': '+g['assessment'] for g in note['groups'])+' |')
    assert not notes and len(rows)==100 and len({(r['instance_id'],r['arm']) for r in rows})==100
    result={'kind':'qualitative_semantic_review_of_all_sealed_formal_submissions',
        'reviewer':'current coding agent; not external human sign-off','external_human_signoff':False,
        'formal_submissions':100,'instances':20,'unique_patch_groups_including_empty':unique,
        'assessment_counts':dict(Counter(r['assessment'] for r in rows)),
        'source_index_sha256':sha(OUT/'index.json'),'notes':sources,'rows':rows,
        'limitations':'Static analyst judgments supplement official testing and do not relabel primary results. No external human review was fabricated. Reference evidence was accessed only after formal prediction seal and is prohibited in generation.'}
    with (OUT/'semantic_review.json').open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    md='# 正式100条提交的语义复核\n\n覆盖20例、100条提交、'+str(unique)+'个实例内唯一补丁组（含空提交）。复核者为当前代码agent，不是外部真人签审。官方标签保持原样；静态合理性不替代独立测试。逐项理由、风险、原始提交哈希见 semantic_review.json 及 notes_batch1–4.json。参考答案在全部正式预测封存后才进入隔离复核目录，未用于生成。\n\n| 实例 | 各组复核结论 |\n| --- | --- |\n'+'\n'.join(table)+'\n'
    with (OUT/'semantic_review.md').open('x',encoding='utf-8') as f:f.write(md)
    print(json.dumps({k:v for k,v in result.items() if k not in ('rows','notes')},ensure_ascii=False))
if __name__=='__main__':main()
