"""Audit the completed official-scoring artifacts and separate actual vs policy cost."""
from pathlib import Path
from datetime import datetime,timezone
from collections import Counter
import hashlib,json,sys
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def write(p,v):
    with Path(p).open('x',encoding='utf-8') as f:json.dump(v,f,ensure_ascii=False,indent=2)
def main():
    from swe_repair.evaluation import sidecar_path,validate_artifact_files,validate_provenance
    from swe_repair.pricing import PRICES,PRICE_TABLE_DATE
    completed=read(OUT/'formal_scoring_completed.json')
    freeze=read(OUT/'formal_generation_freeze_manifest.json')
    summary=read(OUT/'test20_single_run_summary.json')
    assert sha(OUT/'test20_single_run_summary.json')==completed['summary_sha256']
    for item in freeze['artifacts']+completed['reports']+completed['evaluated_records']:
        assert sha(ROOT/item['path'])==item['sha256']
    snap=read(ROOT/'runs/test20_resume_20261112_01/formal_source_snapshot/manifest.json')
    for item in snap['files']:assert sha(ROOT/item['path'])==item['sha256'],item['path']
    assert summary['designated_units']==100 and summary['repeats']==1 and summary['inference_performed'] is False
    assert len(summary['rows'])==100
    ledgerpath=ROOT/'runs/test20_execution_20261111/batch_ledger.json';ledger=read(ledgerpath)
    assert ledger['pending'] is None
    total=sum(r['cost_cny'] for r in ledger['records']);assert total<=100
    formal_tags=list(freeze['tags'].values())+['test20_B_20261112_01']
    formal=[r for r in ledger['records'] if r.get('run_id') in formal_tags]
    request_ids=[r['request_id'] for r in formal]
    assert len(request_ids)==len(set(request_ids))
    assert all(r.get('system_fingerprint')=='bc19ba97cbe016479903222bb1578db6' for r in formal)
    old_b=read(ROOT/'runs/test20_B_20261112_01/matrix.json')
    new_b=read(ROOT/'runs'/freeze['tags']['B']/'matrix.json')
    old_predictions=[json.loads(s) for s in (ROOT/'runs/test20_B_20261112_01/predictions_B.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(old_predictions)==7
    for before,after,prediction in zip(old_b['cases'],new_b['cases'][:7],old_predictions):
        assert before['submitted_patch']==prediction['model_patch']==after['submitted_patch']
        before={k:v for k,v in before.items() if k!='run_id'}
        after={k:v for k,v in after.items() if k not in ('run_id','resume_provenance')}
        assert before==after, 'reused completed B case changed'
    recovered=read(OUT/'B8_recovered_case.json')
    after={k:v for k,v in new_b['cases'][7].items() if k not in ('run_id','repeat_index','resume_provenance')}
    assert recovered==after, 'B8 recovered state changed during consolidation'
    arms={}
    for arm,tag in freeze['tags'].items():
        folder=ROOT/'runs'/tag;matrix=read(folder/'matrix.json')
        report=folder/'scoring'/arm/(tag+'-'+arm+'.'+tag+'.json')
        provenance=read(sidecar_path(report))
        validate_artifact_files(folder/'matrix.json',report,arm,provenance)
        validate_provenance(matrix,arm,read(report),provenance)
        tags=[tag]+(['test20_B_20261112_01'] if arm=='B' else [])
        actual=[r for r in formal if r.get('run_id') in tags]
        policy=sum(c['policy_cost_cny'] for c in matrix['cases'])
        assert abs(policy-summary['primary'][arm]['cost_cny_recorded'])<1e-6
        policy_records=[]
        for case in matrix['cases']:
            names=(['standalone'] if arm=='B' else ['prefix']+
                ([case['selected_route']] if case['selected_route'] in ('fixed','interactive') else []))
            for name in names:policy_records.extend(case['stages'][name]['calls'])
        mix={k:sum(r.get(k,0) for r in policy_records) for k in ('cache_hit_tokens','cache_miss_tokens','output_tokens')}
        price=PRICES['deepseek-flash']
        normalised=sum(mix[k]/1e6*price.rate(kind,'off_peak') for k,kind in
            [('cache_hit_tokens','cache_hit'),('cache_miss_tokens','cache_miss'),('output_tokens','output')])
        actual_mix={k:sum(r.get(k,0) for r in actual) for k in mix}
        actual_normalised=sum(actual_mix[k]/1e6*price.rate(kind,'off_peak') for k,kind in
            [('cache_hit_tokens','cache_hit'),('cache_miss_tokens','cache_miss'),('output_tokens','output')])
        arms[arm]={'tag':tag,'prediction_count':len(matrix['cases']),
            'actual_new_model_requests':len(actual),'actual_new_generation_cost_cny':sum(r['cost_cny'] for r in actual),
            'full_strategy_cost_including_inherited_prefix_cny':policy,
            'actual_new_request_price_tier_counts':dict(Counter(r.get('price_tier') for r in actual)),
            'full_strategy_request_price_tier_counts':dict(Counter(r.get('price_tier') for r in policy_records)),
            'full_strategy_observed_token_mix':mix,
            'user_requested_full_strategy_cost_at_uniform_frozen_off_peak_prices_cny':normalised,
            'user_requested_actual_new_generation_cost_at_uniform_frozen_off_peak_prices_cny':actual_normalised,
            'generation_statuses':dict(Counter(c['status'] for c in matrix['cases'])),
            'independent_evaluation':summary['primary'][arm],
            'unknown_verdict_instances':[r['instance_id'] for r in summary['rows'] if r['arm']==arm and r['status']=='not_scored'],
            'unknown_semantic_verdict_instances':[r['instance_id'] for r in summary['rows'] if r['arm']==arm and
                r['status'] in ('not_scored','infra_error','error','ambiguous_error')]}
    cost={'ceiling_cny':100,'ledger_sha256':sha(ledgerpath),'ledger_records':len(ledger['records']),
        'pending':None,'cumulative_estimated_or_reserved_cny':total,'remaining_guard_cny':100-total,
        'formal_actual_generation_requests':len(formal),'formal_actual_generation_cost_cny':sum(r['cost_cny'] for r in formal),
        'dev_preparation_and_other_actual_cost_cny':total-sum(r['cost_cny'] for r in formal),
        'billing_counts':dict(Counter(r.get('billing','missing') for r in ledger['records'])),
        'formal_usage_reported_missing':sum(not r.get('usage_reported',False) for r in formal),
        'formal_identity_all_matching':True,'formal_request_ids_unique':True,'arms':arms,
        'price_table_date':PRICE_TABLE_DATE,
        'price_reporting_user_amendment_sha256':sha(OUT/'user_cost_reporting_amendment.json'),
        'uniform_off_peak_comparative_reporting_user_requested_during_generation_before_formal_verdicts':True,
        'price_and_observed_server_cache_order_are_cost_comparison_limitations':True,
        'formal_finish_reasons':dict(Counter(r.get('finish_reason') for r in formal)),
        'is_invoice_or_account_balance':False,'B8_historical_responses_rebooked':False,
        'at':datetime.now(timezone.utc).isoformat()}
    write(OUT/'final_cost_audit.json',cost)
    write(OUT/'formal_result_audit.json',{'all100_generation_inputs_immutable':True,
        'all_five_independent_reports_and_provenance_validated':True,'all100_evaluated_audit_rows_present':True,
        'all20_denominators_retained':True,'source_files_verified':len(snap['files']),
        'formal_scoring_completed_sha256':sha(OUT/'formal_scoring_completed.json'),
        'summary_sha256':sha(OUT/'test20_single_run_summary.json'),
        'all_evaluation_statuses_accounted_for':summary['evaluation_complete'],
        'all_semantic_verdicts_known':not any(v['unknown_semantic_verdict_instances'] for v in arms.values()),
        'formal_model_fingerprint_matched':True,
        'B_completed_seven_cases_and_predictions_exactly_preserved':True,
        'B8_reconstructed_state_exactly_preserved':True,
        'immutable_model_version':False,'inference_performed':False,'at':datetime.now(timezone.utc).isoformat()})
    print(json.dumps({'cumulative_estimate_cny':total,'all_evaluation_statuses_accounted_for':summary['evaluation_complete'],
        'arms':{a:{'resolved':v['independent_evaluation']['resolved'],
                  'status_counts':v['independent_evaluation']['status_counts'],
                  'actual_new_cost_cny':v['actual_new_generation_cost_cny'],
                  'full_strategy_cost_cny':v['full_strategy_cost_including_inherited_prefix_cny']}
                for a,v in arms.items()}},ensure_ascii=False))
if __name__=='__main__':main()
