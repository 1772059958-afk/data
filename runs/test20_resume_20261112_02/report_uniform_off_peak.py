"""Apply the user's reporting amendment; preserve original ledger and raw summary."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    audit=read(OUT/'final_cost_audit.json');summary=read(OUT/'test20_single_run_summary.json')
    amendment=read(OUT/'user_cost_reporting_amendment.json')
    assert amendment['actual_100_cny_guard_not_reduced_by_normalisation'] is True
    arms={}
    for arm,v in audit['arms'].items():
        item=summary['primary'][arm]
        policy=v['user_requested_full_strategy_cost_at_uniform_frozen_off_peak_prices_cny']
        actual=v['user_requested_actual_new_generation_cost_at_uniform_frozen_off_peak_prices_cny']
        if arm!='E':
            assert set(v['actual_new_request_price_tier_counts'])=={'off_peak'}
            assert abs(policy-v['full_strategy_cost_including_inherited_prefix_cny'])<1e-6
        arms[arm]={'designated_instances':20,'resolved':item['resolved'],'status_counts':item['status_counts'],
            'all_evaluation_statuses_accounted_for':item['complete'],
            'unknown_semantic_verdict_instances':v['unknown_semantic_verdict_instances'],
            'all_semantic_verdicts_known':not v['unknown_semantic_verdict_instances'],
            'observed_resolved_share_of_designated_population':item['resolved_rate'],
            'resolved_rate_lower_bound':item['resolved_rate_lower_bound'],
            'comparative_full_strategy_cost_off_peak_cny':policy,
            'comparative_actual_new_generation_cost_off_peak_cny':actual,
            'comparative_cost_per_resolved_off_peak_cny':policy/item['resolved'] if item['complete'] and item['cost_complete'] and item['resolved'] else None,
            'original_full_strategy_time_tier_estimate_cny':v['full_strategy_cost_including_inherited_prefix_cny'],
            'original_actual_new_generation_time_tier_estimate_cny':v['actual_new_generation_cost_cny'],
            'actual_new_request_price_tier_counts':v['actual_new_request_price_tier_counts'],
            'observed_cache_token_mix_retained':True,'cost_complete':item['cost_complete']}
    output={'kind':'user_amended_single_run_uniform_off_peak_cost_comparison',
        'amendment_sha256':sha(OUT/'user_cost_reporting_amendment.json'),
        'original_summary_sha256':sha(OUT/'test20_single_run_summary.json'),
        'original_cost_audit_sha256':sha(OUT/'final_cost_audit.json'),'price_source':amendment['price_source'],
        'cny_per_million_tokens':amendment['cny_per_million_tokens'],'arms':arms,
        'actual_cumulative_budget_estimate_cny':audit['cumulative_estimated_or_reserved_cny'],
        'actual_remaining_guard_cny':audit['remaining_guard_cny'],
        'original_ledger_rewritten':False,'inference_performed':False,
        'interpretation':'Uniform-price descriptive comparison. This does not change billing, grant a discount, reset the monetary guard or remove observed server cache/order effects.',
        'generated_at':datetime.now(timezone.utc).isoformat()}
    with (OUT/'test20_uniform_off_peak_comparison.json').open('x',encoding='utf-8') as f:json.dump(output,f,ensure_ascii=False,indent=2)
    print(json.dumps({a:{'resolved':v['resolved'],'full_strategy_cost_off_peak_cny':v['comparative_full_strategy_cost_off_peak_cny'],
        'actual_new_cost_off_peak_cny':v['comparative_actual_new_generation_cost_off_peak_cny']} for a,v in arms.items()},ensure_ascii=False))
if __name__=='__main__':main()
