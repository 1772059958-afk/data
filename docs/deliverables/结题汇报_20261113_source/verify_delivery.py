"""Verify completed PPT inputs and preserve its slide notes without altering results."""
from pathlib import Path
from datetime import datetime
import hashlib,json,re,subprocess,zipfile,xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'runs/ppt_analysis_20261113_01'
SOURCE=Path(__file__).resolve().parent
FINAL=ROOT/'docs/deliverables/结题汇报_深入分析版_20261113_定稿.pptx'
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,data):
    with p.open('x',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2)
data=read(OUT/'analysis.json')
for row in data['sources']:assert sha(ROOT/row['path'])==row['sha256'],row['path']
freeze=read(ROOT/'runs/test20_resume_20261112_02/formal_generation_freeze_manifest.json')
for row in freeze['artifacts']:assert sha(ROOT/row['path'])==row['sha256'],row['path']
assert [data['arms'][a]['resolved'] for a in 'ABCDE']==[7,7,10,7,8]
assert sum(sum(data['arms'][a]['status_counts'].values()) for a in 'ABCDE')==100
ledger=ROOT/'runs/test20_execution_20261111/batch_ledger.json'
assert sha(ledger)=='339bf28d4e5ee0153083d983003db05ef0ab7f77569cc78ac6731816949b6105'
receipt=read(OUT/'validation_receipt_final.json')
assert sha(FINAL)==receipt['finalSha256']
assert receipt['packageIntegrity']['status']=='pass'
assert receipt['presentationLayout']['finding_count']==0
before=read(OUT/'final_render_manifest.json');after=read(OUT/'final_render_manifest_v2.json')
changed=[a['slide'] for a,b in zip(before['slides'],after['slides']) if a['sha256']!=b['sha256']]
assert changed==[10] and len(after['slides'])==21
assert after['source_sha256']==sha(FINAL)
original=ROOT/'docs/deliverables/结题汇报_自适应混合架构程序修复_20261112.pptx'
assert sha(original)=='1cca57db829394390902f297d8cc96b3272fea889f44433b2057b8563bd1e826'
ns={'a':'http://schemas.openxmlformats.org/drawingml/2006/main','p':'http://schemas.openxmlformats.org/presentationml/2006/main'}
sections=['# 逐页讲稿与来源\n\n对应21页深入分析定稿。\n']
with zipfile.ZipFile(FINAL) as z:
    slides=[n for n in z.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml',n)]
    assert len(slides)==21
    for i in range(1,22):
        slide=ET.fromstring(z.read(f'ppt/slides/slide{i}.xml'))
        notes=ET.fromstring(z.read(f'ppt/notesSlides/notesSlide{i}.xml'))
        visible=[''.join(p.itertext()) for p in slide.findall('.//a:t',ns)]
        body=[]
        for shape in notes.findall('.//p:sp',ns):
            ph=shape.find('.//p:ph',ns)
            if ph is not None and ph.attrib.get('type')=='sldNum':continue
            body.extend(''.join(p.itertext()) for p in shape.findall('.//a:t',ns))
        sections.append(f'\n## 第{i}页\n\n'+ '\n'.join(visible)+'\n\n讲稿与来源：\n\n'+'\n'.join(body)+'\n')
(SOURCE/'讲稿与来源.md').write_text(''.join(sections),encoding='utf-8')
protection=subprocess.run(['python','scripts/verify_preservation.py','--archive'],cwd=ROOT,check=True,stdout=subprocess.PIPE,text=True,encoding='utf-8')
protected=json.loads(protection.stdout)
assert protected['experiments']['ok'] and protected['archive']['ok']
result={'at_local':datetime.now().isoformat(timespec='seconds'),'status':'completed',
    'final_path':str(FINAL.relative_to(ROOT)),'sha256':sha(FINAL),'slides':21,
    'visual_review':'All 21 exported slides inspected individually; final revision slide 10 reinspected and other 20 PNG hashes unchanged.',
    'source_inputs_unchanged':True,'formal_prediction_seal_verified':True,'ledger_sha256':sha(ledger),
    'original_assets':protected,'native_tables_and_charts':'validated by validation_receipt_final.json',
    'user_deferred_followups':['cleanup','commit','push','shutdown'],'new_model_requests':0,
    'source_files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p)} for p in SOURCE.iterdir() if p.is_file()]}
save(OUT/'COMPLETED.json',result)
print(json.dumps({'slides':21,'sha256':sha(FINAL),'source_inputs_unchanged':True,'followups':'deferred'},ensure_ascii=False))
