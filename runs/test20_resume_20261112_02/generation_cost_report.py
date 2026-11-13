"""Cost-only report from sealed predictions; no evaluator verdicts required."""
from pathlib import Path
from datetime import datetime,timezone
from collections import Counter
import hashlib,json,sys
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))
from swe_repair.pricing import PRICES,PRICE_TABLE_DATE
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def cost(records,tier='off_peak'):
    price=PRICES['deepseek-flash'];total=0
    for r in records:
        assert r.get('usage_reported') is True
        total+=sum(r[k]/1e6*price.rate(kind,tier) for k,kind in
            [('cache_hit_tokens','cache_hit'),('cache_miss_tokens','cache_miss'),('output_tokens','output')])
    return total
def main():
    freeze=read(OUT/'formal_generation_freeze_manifest.json')
    for f in freeze['artifacts']:assert sha(ROOT/f['path'])==f['sha256']
    path=ROOT/'runs/test20_execution_20261111/batch_ledger.json';ledger=read(path)
    assert ledger['pending'] is None
    arms={}
    for arm,tag in freeze['tags'].items():
        tags=[tag]+(['test20_B_20261112_01'] if arm=='B' else [])
        actual=[r for r in ledger['records'] if r.get('run_id') in tags]
        for r in actual:assert abs(cost([r],r['price_tier'])-r['cost_cny'])<1e-7
        matrix=read(ROOT/'runs'/tag/'matrix.json');policy=[]
        for case in matrix['cases']:
            names=['standalone'] if arm=='B' else ['prefix']+([case['selected_route']] if case['selected_route'] in ('fixed','interactive') else [])
            for name in names:policy.extend(case['stages'][name]['calls'])
        arms[arm]={'actual_new_requests':len(actual),'actual_request_price_tiers':dict(Counter(r['price_tier'] for r in actual)),
            'actual_new_generation_time_tier_estimate_cny':sum(r['cost_cny'] for r in actual),
            'actual_new_generation_uniform_off_peak_cny':cost(actual),
            'full_strategy_time_tier_estimate_cny':sum(c['policy_cost_cny'] for c in matrix['cases']),
            'full_strategy_uniform_off_peak_cny':cost(policy),'full_strategy_price_tiers':dict(Counter(r['price_tier'] for r in policy)),
            'actual_finish_reasons':dict(Counter(r['finish_reason'] for r in actual))}
    data={'kind':'sealed_generation_cost_audit_with_user_off_peak_amendment','arms':arms,
        'ledger_sha256':sha(path),'cumulative_time_tier_estimate_cny':sum(r['cost_cny'] for r in ledger['records']),
        'ledger_records':len(ledger['records']),'pending':None,'price_table_date':PRICE_TABLE_DATE,
        'amendment_sha256':sha(OUT/'user_cost_reporting_amendment.json'),
        'all_recorded_request_costs_match_frozen_price_table':True,'is_invoice_or_refund':False,
        'at':datetime.now(timezone.utc).isoformat()}
    with (OUT/'generation_cost_audit.json').open('x',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2)
    print(json.dumps(data,ensure_ascii=False))
if __name__=='__main__':main()
