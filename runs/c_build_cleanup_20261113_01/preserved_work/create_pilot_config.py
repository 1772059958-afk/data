from pathlib import Path
import json,hashlib
candidate_path=Path('runs/dev2_acceptance_20261106/calibration_candidate.json')
if not candidate_path.is_file():
 print('awaiting evaluated candidate; no config written')
else:
 candidate=json.loads(candidate_path.read_text(encoding='utf-8'))
 raw=candidate['candidate_config']
 raw['execution']['live_authorized']=True
 raw['pilot']={'kind':'actual_single_policy_dev_acceptance','calibration_candidate':candidate_path.as_posix(),'candidate_sha256':hashlib.sha256(candidate_path.read_bytes()).hexdigest(),'analysis_kind':'descriptive_same_dev_cases_one_repeat'}
 out=Path('configs/dev2_pilot_20261106.json')
 with out.open('x',encoding='utf-8') as f:json.dump(raw,f,ensure_ascii=False,indent=2);f.write('\n')
 print(out)
