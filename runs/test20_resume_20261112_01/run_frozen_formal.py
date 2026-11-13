"""Execute exactly the registered five arms, freeze all predictions before scoring."""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
STOP=OUT/'WORKFLOW_STOP.json'
spec=importlib.util.spec_from_file_location('registered_runner',ROOT/'scripts/run_cf.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def canonical(obj):return json.dumps(obj,sort_keys=True,ensure_ascii=False,separators=(',',':'))
def write(path,obj):
    with Path(path).open('x',encoding='utf-8') as f:json.dump(obj,f,ensure_ascii=False,indent=2)

def check_source():
    manifest=read(OUT/'formal_source_snapshot/manifest.json')
    for row in manifest['files']:
        if digest(ROOT/row['path'])!=row['sha256']:
            raise ValueError('frozen source file changed: '+row['path'])
    return manifest['generation_code_sha256']

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    args=parser.parse_args()
    config=args.config.resolve();raw=read(config)
    if runner.frozen_config_errors(raw):raise ValueError('configuration freeze is incomplete')
    if not raw['execution']['live_authorized']:raise ValueError('execution is inactive')
    source_hash=check_source()
    ids=read(ROOT/'runs/test20_preparation_20261111/instances.json')['instance_ids']
    assert len(ids)==20 and raw['execution']['allowed_instances']==ids
    tags={arm:'test20_'+arm+'_20261112_01' for arm in 'ABCDE'}
    assert all(not (ROOT/'runs'/tag).exists() for tag in tags.values()),'do not overwrite or repeat a formal arm'
    assert not STOP.exists()
    write(OUT/'formal_pipeline_started.json',{'config':str(config),'config_sha256':digest(config),
          'source_sha256':source_hash,'script_sha256':digest(Path(__file__)),
          'tags':tags,'started_at':datetime.now(timezone.utc).isoformat(),'hidden_formal_results_read':False})
    matrices={};artifacts=[]
    for arm,tag in tags.items():
        if STOP.exists():raise RuntimeError('workflow stop requested')
        assert digest(config)==read(OUT/'formal_pipeline_started.json')['config_sha256']
        assert check_source()==source_hash
        cmd=[sys.executable,str(ROOT/'scripts/run_cf.py'),'--config',str(config),'--mode','formal',
             '--arm',arm,'--split','test','--seed','20261111','--repeat-index','0',
             '--instances-file',str(ROOT/'runs/test20_preparation_20261111/instances.json'),
             '--tag',tag,'--execute','--allow-paid']
        with (OUT/('formal_'+arm+'_generation.log')).open('xb') as log:
            result=subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        folder=ROOT/'runs'/tag
        matrix=read(folder/'matrix.json') if (folder/'matrix.json').exists() else {}
        write(OUT/('formal_'+arm+'_process_exit.json'),{'arm':arm,'tag':tag,'returncode':result.returncode,
              'case_count':len(matrix.get('cases',[])),'batch_stopped':matrix.get('batch_stopped')})
        if result.returncode or matrix.get('batch_stopped'):
            raise RuntimeError('formal arm stopped; inspect preserved matrix: '+tag)
        assert len(matrix['cases'])==20 and [c['instance_id'] for c in matrix['cases']]==ids
        assert matrix['effective_config']['provenance']['code_sha256']==source_hash
        predictions=folder/('predictions_'+arm+'.jsonl')
        rows=[json.loads(s) for s in predictions.read_text(encoding='utf-8').splitlines()]
        assert len(rows)==20 and [v['instance_id'] for v in rows]==ids
        assert all(c['image_digest']==raw['execution']['images'][c['instance_id']] for c in matrix['cases'])
        if matrices:assert matrix['config_hash']==matrices['A']['config_hash']
        if arm in 'CDE':
            for base,case in zip(matrices['A']['cases'],matrix['cases']):
                assert case.get('prefix_reused') is True
                assert canonical(base['prefix_snapshot'])==canonical(case['prefix_snapshot'])
                assert canonical(base['stages']['prefix'])==canonical(case['stages']['prefix'])
        matrices[arm]=matrix
        artifacts.extend({'path':str(p.relative_to(ROOT)),'sha256':digest(p)} for p in [folder/'matrix.json',predictions])
    ledger=ROOT/'runs/test20_execution_20261111/batch_ledger.json';money=read(ledger)
    assert money['pending'] is None and sum(v['cost_cny'] for v in money['records'])<=100
    write(OUT/'formal_generation_freeze_manifest.json',{'kind':'all_five_generation_outputs_frozen_before_independent_scoring',
          'arms':list('ABCDE'),'instances':ids,'prediction_count':100,'artifacts':artifacts,
          'config_hash':matrices['A']['config_hash'],'source_sha256':source_hash,
          'shared_prefixes_exact':True,'all20_A_C_D_E_actual_prefix_stages_and_snapshots_equal':True,
          'ledger_sha256':digest(ledger),'cumulative_estimate_cny':sum(v['cost_cny'] for v in money['records']),
          'frozen_at':datetime.now(timezone.utc).isoformat(),'hidden_formal_results_read':False})
    print(OUT/'formal_generation_freeze_manifest.json')

if __name__=='__main__':
    try:main()
    except Exception as exc:
        if not STOP.exists():
            write(STOP,{'reason':'formal_pipeline_breakpoint','error_type':type(exc).__name__,
                        'detail':str(exc),'at':datetime.now(timezone.utc).isoformat()})
        raise
