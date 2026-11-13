"""Fix the observed removed pytest.raises string API, without changing tests."""
from pathlib import Path
import json,importlib.util,argparse,re
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('public_prep',HERE/'prepare_official_test20_03.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)

def main():
    args=argparse.Namespace(tag='requestsfixture_20261112_08',context='desktop-linux',docker_data_host_path=Path(r'D:\DockerData\swe-repair-20261111\DockerDesktopWSL'))
    out=HERE/'environment/test20_preparation_runs'/args.tag;out.mkdir(exist_ok=False)
    runner=base.Preparation(args,{'wheel_cache':r'D:\CodexExperimentCache\test20_20261111'},out)
    case=next(c for c in json.loads((HERE/'test20_exact_git_tree_manifest_01.json').read_text(encoding='utf-8'))['instances'] if c['instance_id']=='psf__requests-1963')
    probe=out/'public_identity.py';probe.write_text(base.program(case),encoding='utf-8',newline='\n')
    compat=json.loads((HERE/'formal_compat_dependencies_01.json').read_text(encoding='utf-8'))
    py=json.loads((HERE/'formal_compat_dependencies_05.json').read_text(encoding='utf-8'))
    packages=compat['profiles']['scikit-learn__scikit-learn-11281']['packages']+[v for v in py['packages'] if v['name']=='py']
    fixture=json.loads((HERE/'requests_fixture_dependencies_01.json').read_text(encoding='utf-8'))
    transitives=json.loads((HERE/'requests_pytest_dependencies_07.json').read_text(encoding='utf-8'))
    packages += [p for p in fixture['packages'] if p['name']=='six'] + transitives['packages']
    packages += [p for p in compat['packages'] if p['name']=='setuptools' and p['version']=='68.0.0']
    assert len(packages)==8
    for p in packages:assert base.io.digest(p['path'])==p['sha256']
    lock=out/'legacy-pytest.lock.txt';lock.write_text('\n'.join(p['name']+'=='+p['version']+' --hash=sha256:'+p['sha256'] for p in packages)+'\n',encoding='utf-8')
    parent='sha256:eea7f334b1e55167bacfe1aa58d3ce200f75f9c079ea540e516938aeccedd6f9'
    result={'instance_id':case['instance_id'],'parent':parent,'pins':packages,'lock_sha256':base.io.digest(lock),
            'reason':'Observed pytest7 removed string-form raises API; pytest3.10 with plain assertions preserves Python3.9 test semantics.',
            'assertions_disabled':False,'assertion_introspection':'plain (no rewriting)',
            'source_or_tests_modified':False,'model_calls':0}
    name=runner.start('install_legacy_pytest',parent)
    try:
        result['before']=base.identity(runner,name,case,probe,'after')
        runner.shell(name,'create_wheel_directory','mkdir /tmp/legacy-pytest-wheels')
        for p in packages:runner.docker('copy_pinned_wheel','cp',p['path'],name+':/tmp/legacy-pytest-wheels/'+p['filename'])
        runner.docker('copy_lock','cp',str(lock),name+':/tmp/legacy-pytest.lock.txt')
        runner.shell(name,'install_legacy_pytest','python -m pip install --no-index --no-deps --no-cache-dir --require-hashes --find-links /tmp/legacy-pytest-wheels -r /tmp/legacy-pytest.lock.txt')
        result['after']=base.identity(runner,name,case,probe,'after')
        runner.shell(name,'remove_own_probe','rm -f /tmp/public-tree-check.py')
        tag='test20-prepared/requests-legacy-pytest:'+args.tag
        runner.docker('commit_legacy_runner','commit','--change','ENV PYTEST_ADDOPTS=--assert=plain',name,tag)
        _,text=runner.docker('prepared_image_id','image','inspect',tag,'--format','{{.Id}}');image=text.strip();assert re.fullmatch(r'sha256:[0-9a-f]{64}',image)
        result['candidate_image_id']=image
    finally:runner.clean(name)
    name=runner.start('fresh_legacy_runner',image)
    try:
        result['fresh_before']=base.identity(runner,name,case,probe,'after')
        result['public_smoke'],_=runner.shell(name,'fixed_public_smoke','cd /testbed && '+case['public_smoke_command'])
        result['original_public_first_failure'],_=runner.shell(name,'original_public_first_failure','cd /testbed && timeout 60 python -m pytest test_requests.py -x -q -p no:cacheprovider',check=False,timeout=90)
        result['fresh_after']=base.identity(runner,name,case,probe,'after')
        result.update(status='public_smoke_ready',image_id=image,full_public_file_passed=result['original_public_first_failure']['exit_code']==0)
    finally:
        runner.clean(name);runner.log.close();result['owned_containers_remaining']=runner.owned
        with (out/'result.json').open('x',encoding='utf-8') as f:json.dump(result,f,indent=2)
    print(out/'result.json')

if __name__=='__main__':main()
