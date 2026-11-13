"""Analyse sealed DEV panel roles with independently bound official verdicts."""
from pathlib import Path
from collections import Counter
import hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from swe_repair.evaluation import validate_artifact_files,validate_provenance,sidecar_path,frozen_predictions
from swe_repair.cf import verdict_status,resolved_value
OUT=ROOT/'runs/dev_supplement_20261112_02'
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def off_peak(calls):
    if any(not c.get('usage_reported') or c.get('billing')=='unknown' for c in calls):return None
    return sum((c['cache_hit_tokens']*.02+c['cache_miss_tokens']+c['output_tokens']*4)/1e6 for c in calls)
def policy_row(case,arm,reports):
    route='standalone' if arm=='B' else case['decisions'][arm]['route']
    stage='prefix' if route=='stop' else route
    role={'prefix':'PREFIX','fixed':'FIXED','interactive':'ESC','standalone':'B'}[stage]
    stages=case['stages'];selected=stages.get(stage,{})
    used=[selected] if stage in ('prefix','standalone') else [stages['prefix'],selected]
    calls=[c for s in used for c in s.get('calls',[])]
    status=verdict_status(reports.get(role),case['instance_id'])
    return {'instance_id':case['instance_id'],'arm':arm,'route':route,'label_role':role,'status':status,
        'resolved':resolved_value(status),'generation_status':selected.get('status','not_run'),
        'full_strategy_cost_raw_cny':sum(s.get('cost_cny',0) for s in used),
        'full_strategy_cost_off_peak_cny':off_peak(calls),'model_calls_counted_with_shared_prefix':len(calls),
        'resource_consumed':selected.get('budget',{}).get('consumed'),
        'shared_prefix_not_free':arm!='B','counterfactual_DEV_role_selection_not_formal_test':True}
def main():
    manifest=read(OUT/'config_manifest.json');protocol=read(OUT/'protocol.json')
    assert sha(OUT/'protocol.json')==manifest['protocol_sha256']
    seal=read(OUT/'GENERATION_SEALED.json');assert seal['all_nine_variants_complete']
    for f in seal['artifacts']:assert sha(ROOT/f['path'].replace('\\','/'))==f['sha256']
    completed=read(OUT/'SCORING_COMPLETED.json')
    for f in completed['reports']:assert sha(ROOT/f['path'].replace('\\','/'))==f['sha256']
    baseline=read(ROOT/'runs'/protocol['baseline_tag']/'matrix.json');settings=[];report_sources=[]
    for entry in manifest['configs']:
        gen=ROOT/'runs'/entry['tag'];view=ROOT/'runs'/(entry['tag']+'_eval')
        m=read(view/'matrix.json');original=read(gen/'matrix.json')
        assert m['source_generation']['sha256']==sha(gen/'matrix.json')
        assert m['designated_instances']==protocol['panel_instance_ids'] and len(m['cases'])==6
        variant=next(v for v in protocol['variants'] if v['name']==entry['variant'])
        assert sha(ROOT/entry['path'])==entry['sha256']
        if variant['reuse_baseline_prefix']:
            for a,b in zip(baseline['cases'],original['cases']):
                assert b['prefix_reused'] and a['prefix_snapshot']==b['prefix_snapshot'] and a['stages']['prefix']==b['stages']['prefix']
        reports={}
        for role in ('PREFIX','FIXED','ESC','B'):
            expected=frozen_predictions(m,role)
            if not expected:continue
            p=view/'scoring'/role/(m['tag']+'-'+role+'.'+m['tag']+'.json')
            report=read(p);provenance=read(sidecar_path(p))
            validate_artifact_files(view/'matrix.json',p,role,provenance);validate_provenance(m,role,report,provenance)
            reports[role]=report;report_sources.append({'variant':entry['variant'],'role':role,'path':str(p.relative_to(ROOT)),
                'sha256':sha(p),'provenance_sha256':sha(sidecar_path(p)),'submitted_predictions':len(expected)})
        rows=[policy_row(c,a,reports) for c in m['cases'] for a in 'ABCDE']
        summaries={}
        for arm in 'ABCDE':
            ar=[r for r in rows if r['arm']==arm];cost=sum(r['full_strategy_cost_off_peak_cny'] for r in ar) if all(r['full_strategy_cost_off_peak_cny'] is not None for r in ar) else None
            solved=sum(r['status']=='resolved' for r in ar)
            summaries[arm]={'designated':6,'status_counts':dict(Counter(r['status'] for r in ar)),
                'observed_resolved':solved,'unknown_semantic':sum(r['resolved'] is None for r in ar),
                'complete_strategy_cost_off_peak_cny':cost,'complete_strategy_cost_raw_cny':sum(r['full_strategy_cost_raw_cny'] for r in ar),
                'cost_per_observed_resolved_off_peak_cny':cost/solved if solved and cost is not None else None,
                'model_calls_full_strategy':sum(r['model_calls_counted_with_shared_prefix'] for r in ar),
                'interactive_selected':sum(r['route']=='interactive' for r in ar)}
        settings.append({'variant':entry['variant'],'design':variant,'generation_matrix_sha256':sha(gen/'matrix.json'),
            'evaluation_matrix_sha256':sha(view/'matrix.json'),'config_hash':m['config_hash'],
            'eligible':sum(c['paired_eligible'] for c in m['cases']),'rows':rows,'summaries':summaries,
            'prefix_equivalence_verified':bool(variant['reuse_baseline_prefix'])})
    ledger=read(ROOT/protocol['shared_ledger']);assert ledger['pending'] is None
    start=read(OUT/'ledger_at_start.json');assert ledger['records'][:len(start['records'])]==start['records']
    new=ledger['records'][len(start['records']):];tags={e['tag'] for e in manifest['configs']}
    assert all(r['run_id'] in tags for r in new)
    assert all(r['system_fingerprint']=='bc19ba97cbe016479903222bb1578db6' for r in new)
    cost=sum(r['cost_cny'] for r in ledger['records']);assert cost<=100
    result={'kind':'posthoc_exploratory_DEV_supplement','formal_test_not_rerun':True,'designated_panel':protocol['panel_instance_ids'],
        'seed':protocol['seed'],'settings_count':len(settings),'model_identity_immutable':False,
        'reports_validated':report_sources,'settings':settings,
        'new_actual_requests':len(new),'new_actual_estimate_cny':sum(r['cost_cny'] for r in new),
        'cumulative_actual_estimate_cny':cost,'remaining_cumulative_guard_cny':100-cost,
        'ledger_sha256':sha(ROOT/protocol['shared_ledger']),'ledger_records':len(ledger['records']),'pending':None,
        'physical_new_cost_by_variant':{e['variant']:sum(r['cost_cny'] for r in new if r['run_id']==e['tag']) for e in manifest['configs']},
        'limitations':['Six DEV cases, one per repository, posthoc exploratory panel; not complete DEV23 live sensitivity.',
            'Continuation settings share actual prefix, but generation randomness and fixed execution order remain.',
            'Changing prefix/resources regenerates prefix and may change eligible populations.',
            'Single-run descriptive results only; no confidence intervals, significance or stability claims.',
            'Unknown/error labels never become failures; normalized costs are not supplier actual payment.',
            'Counterfactual DEV policy costs count the complete shared prefix; research branch costs are reported separately.']}
    with (OUT/'supplement_analysis.json').open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k not in ('settings','reports_validated')},ensure_ascii=False))
if __name__=='__main__':main()
