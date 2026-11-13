"""Verify the retained fixture candidate after the bounded full-file timeout."""
from pathlib import Path
import json
import importlib.util
import argparse

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('public_prep',HERE/'prepare_official_test20_03.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)

def main():
    old=HERE/'environment/test20_preparation_runs/requestsfixture_20261112_02/result.json'
    prior=json.loads(old.read_text(encoding='utf-8'))
    assert not prior['owned_containers_remaining']
    image=prior['candidate_image_id']
    args=argparse.Namespace(tag='requestsfixture_20261112_03',context='desktop-linux',docker_data_host_path=Path(r'D:\DockerData\swe-repair-20261111\DockerDesktopWSL'))
    output=HERE/'environment/test20_preparation_runs'/args.tag;output.mkdir(exist_ok=False)
    runner=base.Preparation(args,{'wheel_cache':r'D:\CodexExperimentCache\test20_20261111'},output)
    case=next(c for c in json.loads((HERE/'test20_exact_git_tree_manifest_01.json').read_text(encoding='utf-8'))['instances'] if c['instance_id']=='psf__requests-1963')
    probe=output/'public_identity.py';probe.write_text(base.program(case),encoding='utf-8',newline='\n')
    result={'instance_id':case['instance_id'],'image_id':image,'fixture_origin':str(old),'fixture_origin_sha256':base.io.digest(old),
            'full_public_file_passed':False,'full_public_file_status':'one failure observed then 360-second timeout; preserved, not counted as passed',
            'source_or_tests_modified':False,'model_calls':0}
    name=runner.start('fresh_bounded_probe',image)
    try:
        result['before']=base.identity(runner,name,case,probe,'after')
        result['public_smoke'],_=runner.shell(name,'fixed_public_smoke','cd /testbed && '+case['public_smoke_command'])
        # Additional operational check of the documented HTTPBIN_URL interface.
        result['fixture_operational_probe'],_=runner.shell(name,'httpbin_get_redirect_probe',
            "cd /testbed && timeout 45 python -m pytest test_requests.py -q -p no:cacheprovider -k 'test_HTTP_200_OK_GET_ALTERNATIVE or test_HTTP_302_ALLOW_REDIRECT_GET'")
        result['after']=base.identity(runner,name,case,probe,'after')
        result['status']='public_smoke_ready'
    finally:
        runner.clean(name);runner.log.close()
        result['owned_containers_remaining']=runner.owned
        with (output/'result.json').open('x',encoding='utf-8') as f:json.dump(result,f,indent=2)
    print(output/'result.json')

if __name__=='__main__':main()
