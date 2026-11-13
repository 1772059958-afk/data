"""Read-only analysis of completed formal results for the concise closeout deck."""
from pathlib import Path
from collections import Counter,defaultdict
import hashlib,json,statistics
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'runs/ppt_analysis_20261113_01'
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    OUT.mkdir(exist_ok=False)
    base=ROOT/'runs/test20_resume_20261112_02';freeze=read(base/'formal_generation_freeze_manifest.json')
    for f in freeze['artifacts']:assert sha(ROOT/f['path'])==f['sha256']
    cost=read(base/'test20_uniform_off_peak_comparison.json');old=read(base/'test20_single_run_summary.json')
    cases={};records={};sources=[]
    for arm,tag in freeze['tags'].items():
        p=ROOT/'runs'/tag/'matrix.json';m=read(p);cases[arm]={c['instance_id']:c for c in m['cases']}
        rp=ROOT/'runs'/tag/'evaluated_records.jsonl';records[arm]={r['instance_id']:r for r in map(json.loads,rp.read_text(encoding='utf-8').splitlines())}
        sources.extend([{'path':str(p.relative_to(ROOT)),'sha256':sha(p)},{'path':str(rp.relative_to(ROOT)),'sha256':sha(rp)}])
    ids=freeze['instances'];assert len(ids)==20
    arms={};prefix_cost=sum(c['stages']['prefix']['cost_cny'] for c in cases['A'].values())
    for arm in 'ABCDE':
        cs=cases[arm];rs=records[arm];calls=[x for c in cs.values() for s in c['stages'].values() for x in s.get('calls',[])]
        counts=dict(Counter(r['status'] for r in rs.values()));assert counts==cost['arms'][arm]['status_counts']
        full=cost['arms'][arm]['comparative_full_strategy_cost_off_peak_cny'];solved=counts.get('resolved',0)
        arms[arm]={'status_counts':counts,'resolved':solved,'full_cost':full,
            'prefix_cost':0 if arm=='B' else prefix_cost,'continuation_cost':full-(0 if arm=='B' else prefix_cost),
            'new_actual_off_peak_cost':cost['arms'][arm]['comparative_actual_new_generation_cost_off_peak_cny'],
            'cost_per_observed_resolved':full/solved,'routes':dict(Counter(c['selected_route'] for c in cs.values())),
            'full_strategy_requests':len(calls),'output_tokens':sum(x['output_tokens'] for x in calls),
            'average_output_per_request':sum(x['output_tokens'] for x in calls)/len(calls),
            'length_responses_full_strategy':sum(x['finish_reason']=='length' for x in calls),
            'termination_reasons':dict(Counter(r['termination_reason'] for r in rs.values())),
            'generation_env_error_but_official_resolved':sum(r['generation_status']=='environment_error' and r['status']=='resolved' for r in rs.values()),
            'route_status_counts':{route:dict(Counter(rs[i]['status'] for i,c in cs.items() if c['selected_route']==route)) for route in sorted({c['selected_route'] for c in cs.values()})}}
    difference=[]
    for iid in ids:
        c=cases['C'][iid];d=cases['D'][iid];cr=records['C'][iid];dr=records['D'][iid]
        if cr['status']!=dr['status']:
            difference.append({'instance_id':iid,'C_status':cr['status'],'D_status':dr['status'],'C_route':c['selected_route'],'D_route':d['selected_route'],
                'D_rule':d['decisions']['D']['rule'],'D_features':d.get('features',{})})
    extra=[r for r in difference if r['C_status']=='resolved' and r['D_status']!='resolved'];assert len(extra)==3
    repo={}
    for iid in ids:
        name=iid.rsplit('-',1)[0];repo.setdefault(name,{'n':0,**{a:0 for a in 'ABCDE'}});repo[name]['n']+=1
        for arm in 'ABCDE':repo[name][arm]+=records[arm][iid]['status']=='resolved'
    per_case=[{'instance_id':i,'status':{a:records[a][i]['status'] for a in 'ABCDE'},
        'route':{a:cases[a][i]['selected_route'] for a in 'ABCDE'}} for i in ids]
    dev=read(ROOT/'runs/dev23_scoring_replay_20261112_02/analysis.json')
    review=read(ROOT/'runs/test20_resume_20261112_01/formal_freeze_review_01.json')
    config=read(ROOT/'configs/test20_frozen_20261112_01.json')
    audit=read(ROOT/'runs/dev_supplement_20261112_02/formal_scoped_log_audit.json')
    result={'kind':'additional_descriptive_analysis_of_completed_formal_experiment_for_presentation',
        'new_experiments':0,'cancelled_supplement_settings_used':False,'original_primary_results_unchanged':True,
        'designated_n':20,'arms':arms,'prefix_cost':prefix_cost,'C_extra_observed_resolved_vs_D':extra,
        'C_D_all_status_differences':difference,'per_repository':repo,'per_case':per_case,
        'dev_quadrants':dev['quadrants']['counts'],'dev_designated':23,'dev_eligible':17,'dev_complete_pairs':13,
        'frozen_router':review['chosen'],'E_probability':review['E_matching']['probability'],
        'global_budget':config['budget_tiers'][0],'interaction_limits':config['interaction'],
        'common_runnable_ids':old['common_runnable']['instance_ids'],
        'common_runnable_resolved':{a:old['common_runnable']['primary'][a]['resolved'] for a in 'ABCDE'},
        'repository_macro_observed_share':{a:old['primary'][a]['repository_macro_average'] for a in 'ABCDE'},
        'scoped_log_audit_counts':audit['scoped_counts'],'sources':sources,
        'formal_scope_note':'20 cases, one run. Empty patches and evaluation errors remain separate. No new calibration, intervention or repeated inference.'}
    (OUT/'analysis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'resolved':{a:v['resolved'] for a,v in arms.items()},'C_D_extra':extra,
        'route_status_D':arms['D']['route_status_counts'],'B_A_output_ratio':arms['B']['output_tokens']/arms['A']['output_tokens'],
        'dev_quadrants':result['dev_quadrants']},ensure_ascii=False))
if __name__=='__main__':main()
