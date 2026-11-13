from pathlib import Path
import json,subprocess
from prepare_cleanup import ROOT,OUT,sha,save
plan=json.loads((OUT/'cleanup_plan.json').read_text(encoding='utf-8'))
rows=json.loads((OUT/'protected_files_before.json').read_text(encoding='utf-8'))
for row in rows:assert sha(ROOT/row['path'])==row['sha256'],row['path']
for row in plan['preserved']:assert sha(ROOT/row['preserved_path'])==row['sha256']
for row in plan['targets']:assert not (ROOT/row['relative']).exists()
assert sha(ROOT/'docs/deliverables/结题汇报_深入分析版_20261113_定稿.pptx')=='4e78fdb55408554d17e84619f45fc19fdbb3cfca66253123b0d3d53ff5846155'
assert sha(ROOT/'runs/test20_execution_20261111/batch_ledger.json')=='339bf28d4e5ee0153083d983003db05ef0ab7f77569cc78ac6731816949b6105'
r=subprocess.run(['python','scripts/verify_preservation.py','--archive'],cwd=ROOT,stdout=subprocess.PIPE,check=True,text=True,encoding='utf-8')
protected=json.loads(r.stdout);assert protected['experiments']['ok'] and protected['archive']['ok']
save('COMPLETED_VERIFIED.json',{'status':'completed_verified','protected_file_count':len(rows),'all_sha256_unchanged':True,'preserved_metadata_files':len(plan['preserved']),'original_assets':protected,'final_ppt_and_ledger_unchanged':True,'new_model_requests':0,'shutdown':False})
print(json.dumps({'verified_files':len(rows),'metadata_preserved':len(plan['preserved']),'original_assets':'93/93 + 131/131','shutdown':False}))
