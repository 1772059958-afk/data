"""Freeze the limited DEV-only remaining-work design before new paid responses."""
from pathlib import Path
from datetime import datetime,timezone
import copy,hashlib,json
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,v):
    with Path(p).open('x',encoding='utf-8') as f:json.dump(v,f,ensure_ascii=False,indent=2)
def main():
    formal=read(ROOT/'configs/test20_frozen_20261112_01.json')
    dev=read(ROOT/'configs/dev23_calibration_20261112_01.json')
    ledger=ROOT/'runs/test20_execution_20261111/batch_ledger.json';money=read(ledger)
    assert money['pending'] is None and len(money['records'])==1008
    ids=(ROOT/'data/frozen/instances_dev.txt').read_text(encoding='utf-8').splitlines()
    repos=sorted({iid.rsplit('-',1)[0] for iid in ids})
    panel=[min([iid for iid in ids if iid.rsplit('-',1)[0]==repo],
        key=lambda iid:hashlib.sha256(('20261112:'+iid).encode()).hexdigest()) for repo in repos]
    assert len(panel)==6
    base={'prefix_fraction':0.2,'interaction_calls':6,'stagnation_patience':3,
        'omit_failure_ledger':False,'resource_ceiling':{'token':512000,'model_call':12,'tool_call':80,'wallclock_seconds':1200}}
    changes=[('baseline',{}),('no_failure_ledger',{'omit_failure_ledger':True}),
        ('no_stagnation',{'stagnation_patience':0}),('interaction4',{'interaction_calls':4}),
        ('interaction8',{'interaction_calls':8}),('prefix30',{'prefix_fraction':0.3}),
        ('prefix40',{'prefix_fraction':0.4}),
        ('budget_half',{'resource_ceiling':{'token':256000,'model_call':6,'tool_call':40,'wallclock_seconds':600}}),
        ('budget_onehalf',{'resource_ceiling':{'token':768000,'model_call':18,'tool_call':120,'wallclock_seconds':1800}})]
    variants=[]
    for name,patch in changes:
        v=copy.deepcopy(base);v.update(patch);v['name']=name
        v['reuse_baseline_prefix']=name in ('no_failure_ledger','no_stagnation','interaction4','interaction8')
        variants.append(v)
    protocol={'kind':'posthoc_DEV_remaining_work_protocol','authorization':'完成剩余所有工作',
        'authorization_interpretation':'Complete the disclosed ablation/sensitivity and semantic-review work within the original100CNY, without extra formal test cases or repetitions.',
        'formal_test_scope_unchanged':'20 instances x A-E x repeat0; no new formal generation',
        'seed':20261112,'dev_population':ids,'panel_instance_ids':panel,
        'panel_selection':'One per each of six DEV repositories, minimum SHA256 of 20261112:instance_id; no labels, gold or image availability used.',
        'panel_size':6,'variants':variants,'diagnostic_branches':'same actual baseline prefix for continuation-only interventions; fresh prefix for ratio/resource changes; eligible fixed and interactive plus independent B',
        'baseline_tag':'devsupp_baseline_20261112_02',
        'prefix_reuse_contract':'DEV diagnostic only; preserve source task/hash, exact stage and serialized snapshot; model/prefix/global budgets/environment/code must match; never relax formal cache identity.',
        'offline_full_dev_work':{'population':23,'router_ablations':['no_localization_disagreement','no_duplicate_signal'],
            'threshold_grid':[0.25,0.5,0.75,1.0]},
        'feedback_ablation_definition':'Omit only the structured failure-ledger summary from seed/fixed-continuation messages. Keep source, bug report, candidate history and raw tool observations. Do not claim a no-feedback agent.',
        'semantic_review':'Every formal submission mapped to reviewed unique patches, issue requirements, boundary risks and independent evidence. Agent-assisted review is not a fabricated human sign-off.',
        'posthoc_exploratory_not_recalibration':True,'formal_test_labels_already_seen':True,
        'no_test_label_inputs_to_model_prompts':True,'shared_ledger':'runs/test20_execution_20261111/batch_ledger.json',
        'ceiling_cny':100,'starting_spend_cny':sum(r['cost_cny'] for r in money['records']),
        'starting_ledger_sha256':sha(ledger),'per_strategy_instance_cny':2,
        'model_reference':formal['model'],'model_identity_protocol_unchanged':True,
        'reference_frozen_config':'configs/test20_frozen_20261112_01.json','reference_frozen_config_sha256':sha(ROOT/'configs/test20_frozen_20261112_01.json'),
        'adapter':'scripts/run_dev_supplement.py','adapter_sha256':sha(ROOT/'scripts/run_dev_supplement.py'),
        'stop_on_missing_or_changed_fingerprint_or_api_quota':True,'breakpoint_policy':'Save, document and verify, then shut down; no user question or bypass.',
        'inference':False,'confidence_intervals':False,'created_at':datetime.now(timezone.utc).isoformat()}
    write(OUT/'protocol.json',protocol)
    (OUT/'ledger_at_start.json').write_bytes(ledger.read_bytes())
    write(OUT/'panel.json',{'instance_ids':panel,'seed':20261112,'population_size':23,'sample_size':6,'selection':protocol['panel_selection']})
    configs=[]
    for variant in variants:
        raw=copy.deepcopy(formal)
        raw['status']='posthoc_dev_supplement_not_formal_frozen'
        raw['note']='DEV-only predefined remaining-work experiment. No formal test generation or recalibration. Original formal configuration and grades remain immutable.'
        raw['prompt_version']=formal['prompt_version']
        raw['prefix']['prefix_fraction']=variant['prefix_fraction'];raw['prefix']['calibration']='posthoc_reference_or_sensitivity'
        raw['interaction'].update(model_calls=variant['interaction_calls'],stagnation_patience=variant['stagnation_patience'],calibration='posthoc_reference_or_sensitivity')
        raw['fixed_continuation']['calibration']='posthoc_reference'
        raw['router']['calibration']='frozen_reference_not_refit'
        raw['budget_tiers']=[dict(tier='development',**variant['resource_ceiling'])]
        raw['active_tier']='development'
        raw['evaluation']={'design':'posthoc_dev_supplement','repeats':1,'inference':False,'statistics':'descriptive_only'}
        for key in ('freeze_review','formal_environment_evidence'):raw.pop(key,None)
        raw['execution'].update(live_authorized=True,allowed_modes=['diagnostic'],allowed_splits=['dev'],
            allowed_instances=panel,max_instances=6,total_cny=100,per_instance_cny=2,
            batch_ledger=protocol['shared_ledger'],credential_source='project_dotenv',model_probe_authorized=False,
            images={iid:dev['execution']['images'][iid] for iid in panel},
            workflow_stop_file=str((OUT/'WORKFLOW_STOP.json').relative_to(ROOT)).replace('\\','/'),
            authorization_scope=protocol['authorization_interpretation'],budget_status='authorized_remaining_work_same_100_cny',stop_on_api_breakpoint=True)
        raw['supplement']={'protocol':str((OUT/'protocol.json').relative_to(ROOT)).replace('\\','/'),
            'protocol_sha256':sha(OUT/'protocol.json'),'adapter_sha256':protocol['adapter_sha256'],
            'variant':variant['name'],'omit_failure_ledger':variant['omit_failure_ledger'],
            'reuse_baseline_prefix':variant['reuse_baseline_prefix']}
        path=ROOT/'configs'/('devsupp_'+variant['name']+'_20261112_02.json');write(path,raw)
        configs.append({'variant':variant['name'],'path':path.relative_to(ROOT).as_posix(),'sha256':sha(path),
            'tag':'devsupp_'+variant['name']+'_20261112_02'})
    write(OUT/'config_manifest.json',{'protocol_sha256':sha(OUT/'protocol.json'),'configs':configs})
    print(json.dumps({'panel':panel,'variants':len(variants),'starting_spend_cny':protocol['starting_spend_cny']},ensure_ascii=False))
if __name__=='__main__':main()
