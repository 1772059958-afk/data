"""Freeze the reviewed, weak-evidence preregistered DEV heuristic; no API call."""
from pathlib import Path
import copy,datetime,hashlib,importlib.util,json,sys
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
DEV=ROOT/'runs/dev23_scoring_replay_20261112_02'
sys.path.insert(0,str(ROOT/'src'))
from swe_repair.router import RouterConfig
from swe_repair.calibration import load_calibration_inputs
from swe_repair.evaluation import validate_artifact_files,sidecar_path

def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def bind(p):return {'path':str(Path(p).relative_to(ROOT)),'sha256':digest(p)}
def write(p,v):
    with Path(p).open('x',encoding='utf-8') as f:json.dump(v,f,ensure_ascii=False,indent=2);f.write('\n')
def norm(v):
    v=copy.deepcopy(v)
    if isinstance(v,dict):v.pop('calibration',None);v.pop('frozen',None)
    return v

def main():
    a=read(DEV/'analysis.json');c=read(DEV/'calibration_candidate.json')
    old=RouterConfig.from_config(a['effective_config'])
    inputs=load_calibration_inputs(DEV/'analysis.json',old,allowed_ids=(ROOT/'data/frozen/instances_dev.txt').read_text(encoding='utf-8').splitlines())
    chosen=c['chosen'];assert chosen and len(inputs.observations)==13 and len(inputs.eligible_prefixes)==17
    match=inputs.trigger_rate(old.with_thresholds(chosen['localization_threshold'],chosen['duplicate_threshold']))
    assert match==c['trigger_rate_matching'] and match['probability']==8/17
    reports=[]
    for arm in ['A','B','C','D','ESC','FIXED']:
        p=DEV/'scoring'/arm/f'dev23_calibration_20261112_01-{arm}.dev23_calibration_20261112_01.json'
        side=sidecar_path(p);validate_artifact_files(DEV/'matrix.json',p,arm,read(side))
        reports.append({'arm':arm,'report':bind(p),'provenance':bind(side)})
    ledger=read(ROOT/'runs/test20_execution_20261111/batch_ledger.json');assert ledger['pending'] is None
    calls=[v for v in ledger['records'] if v['run_id']=='dev23_calibration_20261112_01']
    assert len(calls)==370 and all(v['system_fingerprint']=='bc19ba97cbe016479903222bb1578db6' for v in calls)
    source=read(OUT/'formal_source_snapshot/manifest.json')
    assert all(digest(ROOT/v['path'])==v['sha256'] for v in source['files'])
    sourcefiles={'candidate':DEV/'calibration_candidate.json','analysis':DEV/'analysis.json',
      'effective_dev_config':DEV/'effective_config_for_calibration.json','formal_source':OUT/'formal_source_snapshot/manifest.json',
      'router_portability':OUT/'router_portability_review_01.json','environment':OUT/'test20_public_environment_review_03.json',
      'resource_screen':OUT/'resource_setting_review_01.json','prefix_screen':OUT/'prefix_setting_review_01.json',
      'model_probe':OUT/'model_probe_01/result.json','identity_approval':ROOT/'runs/test20_execution_20261111/model_identity_amendment_approved.json',
      'sample':ROOT/'runs/test20_preparation_20261111/instances.json','registration':ROOT/'runs/test20_preparation_20261111/preregistration.json',
      'protocol':ROOT/'docs/实验协议_开题对齐.md','offline':OUT/'offline_formal_safety_03.log','preservation':OUT/'preservation_after_adapters_01.log'}
    review={'kind':'reviewed_formal_configuration_freeze','reviewed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
      'decision':'Proceed with the preregistered descriptive heuristic comparison; routing efficacy is not established. No grid/objective/budget/sample changes based on outcomes.',
      'dev_designated':23,'eligible':17,'complete_pairs':13,'missing_pairs':list(inputs.missing_pair_ids),
      'chosen':chosen,'E_matching':match,'full_nine_rule_replay':True,'grid':c['grid'],'sensitivity':c['sensitivity'],
      'evidence_limit':'All9 points have regret1/resolved5 on13 complete pairs;11 ties, one fixed-only and one interactive-only. Lower interaction then higher threshold is the existing tie rule, not proof of an optimal effective router.',
      'duplicate_rule':{'n_candidates':2,'maximum_repeat_rate':0.5,'strict_comparison':'>','selected_threshold':0.75,'closed':True,'active_threshold_optimized':False,
        'documentation_note':'D3 configuration fixed two candidates and the existing grid before execution. The separate D2 review did not explicitly restate reachability. This omission and the closed interval are disclosed here; earlier records are not rewritten.'},
      'sources':{k:bind(v) for k,v in sourcefiles.items()},'independent_reports':reports,
      'dev_and_formal_source_difference_disclosed':True,'immutable_model_version':False,
      'actual_alias':'deepseek-flash','backend_fingerprint':'bc19ba97cbe016479903222bb1578db6','matching_full_dev_requests':370,
      'environment_limit':'All20 fixed public smoke commands pass. Requests whole original public file still requires unavailable HTTPS in the fixed isolated fixture; preserve its designated denominator and distinguish infra/ambiguous verdicts from unresolved.',
      'budget':{'ceiling_cny':100,'per_strategy_instance_cny':2,'booked_estimate_before_formal':sum(v['cost_cny'] for v in ledger['records']),'not_invoice':True},
      'scope':'Exact registered20 x A-E x repeat0, seed20261111; freeze all five generation outputs before formal scoring.',
      'remaining_research':'No repeated-run inference/test300 generalization/complete ablation/human semantic audit; no demonstrated duplicate-signal value.'}
    reviewpath=OUT/'formal_freeze_review_01.json';write(reviewpath,review)
    raw=read(ROOT/'configs/test20_resume_pending_20261112_02.json')
    for section in ['model','prefix','fixed_continuation','interaction','budget_tiers','active_tier','candidate_selection','prompt_version']:
        assert norm(raw[section])==norm(a['effective_config'][section]),section
    raw['router'].update(localization_disagreement_threshold=chosen['localization_threshold'],duplicate_rate_threshold=chosen['duplicate_threshold'],switch_probability=match['probability'])
    raw['status']='frozen'
    for section in ['model','prefix','fixed_continuation','router']:raw[section]['calibration']='frozen'
    raw['candidate_selection']['frozen']=True;raw['evaluation']['frozen']=True;raw['execution']['live_authorized']=True
    raw['freeze_review']=bind(reviewpath);raw['model']['immutable_version']=False
    raw['note']='Reviewed preregistered DEV heuristic, not established routing efficacy:13 complete pairs,11 ties. Two0.75 thresholds selected by existing regret/resolved/share/higher-threshold tie rule; duplicate rule explicitly closed for two candidates. E=8/17 all eligible prefixes. Source differences disclosed. Approved variable alias/fingerprint protocol, immutable_version=false. Exact test20 A-E once, shared100CNY ledger, project dotenv. Requests HTTPS environment limitation retained; no sample substitution. All five predictions freeze before formal scoring.'
    config=ROOT/'configs/test20_frozen_20261112_01.json';write(config,raw)
    spec=importlib.util.spec_from_file_location('freeze_runner',ROOT/'scripts/run_cf.py');runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    assert runner.frozen_config_errors(raw)==[]
    plans=[]
    for arm in 'ABCDE':
        args=runner.parser().parse_args(['--config',str(config),'--mode','formal','--arm',arm,'--split','test','--seed','20261111','--repeat-index','0','--instances-file','runs/test20_preparation_20261111/instances.json','--tag',f'test20_{arm}_20261112_01','--execute','--allow-paid'])
        actual,plan=runner.load_plan(args);assert plan['effective_config']['provenance']['code_sha256']==source['generation_code_sha256'];plans.append(plan)
    assert len({v['config_hash'] for v in plans})==1
    write(OUT/'formal_freeze_manifest_01.json',{'config':bind(config),'review':bind(reviewpath),'effective_config_hash':plans[0]['config_hash'],
      'generation_code_sha256':source['generation_code_sha256'],'validation_only_no_client_constructed':True,'model_calls':0,
      'all_five_paid_gates_validated_offline':True,'plans':plans})
    print(json.dumps({'config':str(config),'effective_config_hash':plans[0]['config_hash'],'complete_pairs':13,'E':match['probability'],'model_calls':0}))

if __name__=='__main__':main()
