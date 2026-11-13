import sys,json
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from swe_repair.router import RouterConfig,route_for_arm
from swe_repair.state import RepairState
m=json.loads(Path('runs/dev23_calibration_20261112_01/matrix.json').read_text(encoding='utf-8'))
rows=[]
for c in m['cases']:
 if not c.get('prefix_snapshot'):continue
 for loc in [.25,.5,.75]:
  for dup in [.25,.5,.75]:
   cfg=RouterConfig.from_config(m['effective_config']).with_thresholds(loc,dup)
   d=route_for_arm('D',RepairState.from_dict(c['prefix_snapshot']),cfg)
   rows.append({'iid':c['instance_id'],'loc':loc,'dup':dup,'route':d.route,'rule':d.rule})
print(json.dumps(rows,sort_keys=True))
