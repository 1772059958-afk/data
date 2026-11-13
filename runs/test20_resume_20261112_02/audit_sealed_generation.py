"""Audit actual sealed selections/routing and scope; never read gold/test labels."""
from pathlib import Path
from collections import Counter
from datetime import datetime,timezone
import hashlib,json,random,sys
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))
from swe_repair.state import RepairState
from swe_repair.router import RouterConfig,route_for_arm
from swe_repair.patchutil import patch_scope_valid
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    freeze=read(OUT/'formal_generation_freeze_manifest.json');rows=[]
    for f in freeze['artifacts']:assert sha(ROOT/f['path'])==f['sha256']
    for arm,tag in freeze['tags'].items():
        matrix=read(ROOT/'runs'/tag/'matrix.json');cfg=RouterConfig.from_config(matrix['effective_config'])
        assert cfg.digest==freeze['config_hash']
        for c in matrix['cases']:
            route=c['selected_route'];stage_name='standalone' if arm=='B' else 'prefix' if route=='stop' else route
            expected={'standalone'} if arm=='B' else {'prefix'}|({route} if route!='stop' else set())
            assert set(c['stages'])==expected, 'unselected formal branch ran'
            stage=c['stages'][stage_name];state=RepairState.from_dict(stage['state'])
            best=state.patches.best_candidate();patch=best.diff if best else ''
            assert patch==c['submitted_patch']==stage['patch'], 'submission differs from common candidate selection'
            assert not patch or (patch_scope_valid(patch) and best.applies_cleanly and best.syntax=='pass')
            if arm!='B':
                prefix=RepairState.from_dict(c['prefix_snapshot'])
                decision=route_for_arm(arm,prefix,cfg,rng=random.Random(f"{matrix['seed']}:{c['instance_id']}"))
                assert decision.to_dict()==c['decisions'][arm], 'decision does not reproduce frozen rule/seed'
            consumed=stage['budget']['consumed'];ceil=stage['budget']['ceiling']
            rows.append({'arm':arm,'instance_id':c['instance_id'],'route':route,'generation_status':c['status'],
                'submitted_nonempty':bool(patch),'selected_candidate_public_validation':best.validation if best else None,
                'reproduced_selection':True,'reproduced_router':arm!='B','selected_branch_only':True,
                'selected_patch_scope_valid':True,'budget_overrun_recorded':stage['budget']['overrun'],
                'resource_over_ceiling':{k:consumed[k]-ceil[k] for k in consumed if consumed[k]>ceil[k]},
                'model_request_count_including_prefix':consumed['model_call']})
    assert len(rows)==100
    report={'kind':'post_generation_public_state_selection_and_route_audit','units':100,
        'selections_reproduced':100,'A_C_D_E_router_decisions_reproduced':80,'all_nonempty_submissions_within_frozen_scope':True,
        'unselected_branches_run':0,'official_gold_or_hidden_test_labels_read_by_this_audit':False,
        'rows':rows,'per_arm':{a:{'generation_statuses':dict(Counter(r['generation_status'] for r in rows if r['arm']==a)),
            'nonempty_submissions':sum(r['submitted_nonempty'] for r in rows if r['arm']==a),
            'selected_public_validation':dict(Counter(r['selected_candidate_public_validation'] for r in rows if r['arm']==a))}
            for a in 'ABCDE'},'at':datetime.now(timezone.utc).isoformat()}
    with (OUT/'sealed_generation_selection_audit.json').open('x',encoding='utf-8') as f:json.dump(report,f,ensure_ascii=False,indent=2)
    print(json.dumps({k:v for k,v in report.items() if k!='rows'},ensure_ascii=False))
if __name__=='__main__':main()
