"""Full DEV23 posthoc rule ablations and threshold sensitivity; no live client."""
from pathlib import Path
from collections import Counter
import copy,hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from swe_repair.router import RouterConfig,route_for_arm
from swe_repair.state import RepairState
from swe_repair.cf import verdict_status,resolved_value
from swe_repair.evaluation import validate_artifact_files,sidecar_path,validate_provenance
OUT=ROOT/'runs/dev_supplement_20261112_02'
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def auc(scores,labels):
    pos=[s for s,y in zip(scores,labels) if y];neg=[s for s,y in zip(scores,labels) if not y]
    return sum(1 if p>n else .5 if p==n else 0 for p in pos for n in neg)/(len(pos)*len(neg)) if pos and neg else None
def main():
    source=ROOT/'runs/dev23_scoring_replay_20261112_02';matrix=read(source/'matrix.json')
    designated=(ROOT/'data/frozen/instances_dev.txt').read_text(encoding='utf-8').splitlines()
    assert matrix['designated_instances']==designated and len(matrix['cases'])==23
    reports={};sources=[]
    for arm in ('A','FIXED','ESC'):
        p=source/'scoring'/arm/(matrix['tag']+'-'+arm+'.'+matrix['tag']+'.json')
        report=read(p);provenance=read(sidecar_path(p))
        validate_artifact_files(source/'matrix.json',p,arm,provenance);validate_provenance(matrix,arm,report,provenance)
        reports[arm]=report;sources.append({'arm':arm,'path':str(p.relative_to(ROOT)),'sha256':sha(p)})
    reference=read(ROOT/'configs/test20_frozen_20261112_01.json')['router']
    original=RouterConfig.from_config(matrix['effective_config'])
    original.localization_disagreement_threshold=reference['localization_disagreement_threshold']
    original.duplicate_rate_threshold=reference['duplicate_rate_threshold'];original.switch_probability=reference['switch_probability']
    cases=matrix['cases'];eligible=[];pairs=[]
    for c in cases:
        state=RepairState.from_dict(c['prefix_snapshot'])
        if route_for_arm('A',copy.deepcopy(state),original).route!='stop':
            eligible.append(c['instance_id'])
            f=resolved_value(verdict_status(reports['FIXED'],c['instance_id']));i=resolved_value(verdict_status(reports['ESC'],c['instance_id']))
            if f is not None and i is not None:pairs.append((c,f,i))
    assert len(eligible)==17 and len(pairs)==13
    specs=[('reference',.75,.75),('no_localization_disagreement',1.,.75),('no_duplicate_signal',.75,1.)]
    specs += [(f'grid_loc_{l}_dup_{d}',l,d) for l in (.25,.5,.75,1.) for d in (.25,.5,.75,1.)]
    output=[]
    for name,l,d in specs:
        cfg=copy.deepcopy(original);cfg.localization_disagreement_threshold=l;cfg.duplicate_rate_threshold=d
        rows=[]
        for c in cases:
            decision=route_for_arm('D',RepairState.from_dict(c['prefix_snapshot']),cfg)
            role={'stop':'A','fixed':'FIXED','interactive':'ESC'}[decision.route]
            status=verdict_status(reports[role],c['instance_id'])
            selected='prefix' if decision.route=='stop' else decision.route
            cost=c['stages']['prefix']['cost_cny']+(c['stages'].get(selected,{}).get('cost_cny',0) if selected!='prefix' else 0)
            rows.append({'instance_id':c['instance_id'],'eligible':c['instance_id'] in eligible,
                'route':decision.route,'rule':decision.rule,'status':status,'strategy_cost_cny':cost,
                'label_role':role,'full_state_replay':True})
        decisions={r['instance_id']:r['route'] for r in rows}
        regret=sum(int((i if decisions[c['instance_id']]=='interactive' else f)!=max(f,i)) for c,f,i in pairs)
        chosen=sum(i if decisions[c['instance_id']]=='interactive' else f for c,f,i in pairs)
        output.append({'name':name,'localization_threshold':l,'duplicate_threshold':d,'designated':23,
            'eligible':17,'valid_pairs':13,'eligible_interactive':sum(r['eligible'] and r['route']=='interactive' for r in rows),
            'valid_pair_selected_resolved':chosen,'valid_pair_routing_regret':regret,
            'designated_status_counts':dict(Counter(r['status'] for r in rows)),
            'strategy_cost_recorded_cny':sum(r['strategy_cost_cny'] for r in rows),'rows':rows})
    baseline={r['instance_id']:r for r in output[0]['rows']}
    for result in output:
        result['route_changes_from_reference']=[r['instance_id'] for r in result['rows'] if r['route']!=baseline[r['instance_id']]['route']]
    quadrants=Counter('both_resolved' if f and i else 'fixed_only' if f else 'interactive_only' if i else 'neither_resolved' for c,f,i in pairs)
    loc=[];lab=[];dup=[]
    for c,f,i in pairs:
        state=RepairState.from_dict(c['prefix_snapshot'])
        if state.u_loc is not None:loc.append(state.u_loc);lab.append(i and not f)
        dup.append((state.u_dup,i and not f))
    report={'kind':'posthoc_full_DEV23_routing_ablation_and_sensitivity','not_formal_test_evidence':True,
        'reference_router_not_refit':reference,'source_matrix':str((source/'matrix.json').relative_to(ROOT)),
        'source_matrix_sha256':sha(source/'matrix.json'),'source_reports':sources,'designated':23,'eligible':17,'valid_pairs':13,
        'missing_pair_ids':sorted(set(eligible)-{c['instance_id'] for c,f,i in pairs}),
        'quadrants_complete_pairs_only':dict(quadrants),'settings':output,
        'no_duplicate_ablation_is_structural_noop':not output[2]['route_changes_from_reference'],
        'duplicate_rule_inactive_in_reference':True,
        'discrimination_posthoc':{'target':'interactive solves and fixed does not','localization_auc':auc(loc,lab),
            'localization_known_n':len(loc),'duplicate_auc':auc([v for v,y in dup],[y for v,y in dup]),
            'positive_n':sum(i and not f for c,f,i in pairs),'warning':'Tiny training/dev sample; no inference or refreeze.'},
        'interpretation':'Complete-state policy replay using actual independently scored paired branches, not fresh model executions or changed formal test results. Missing/error verdicts are never failures.'}
    with (OUT/'full_dev_router_ablation_sensitivity.json').open('x',encoding='utf-8') as f:json.dump(report,f,ensure_ascii=False,indent=2)
    print(json.dumps({'designated':23,'eligible':17,'pairs':13,'quadrants':dict(quadrants),
        'ablations':[{k:v for k,v in r.items() if k not in ('rows',)} for r in output[:3]]},ensure_ascii=False))
if __name__=='__main__':main()
