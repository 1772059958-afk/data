"""Install an isolated, loopback-only historical HTTPbin public fixture."""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import re
import shlex

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('exact_public_prep', HERE / 'prepare_official_test20_03.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

STARTUP = '''export HTTPBIN_URL=http://127.0.0.1:8765/
if ! /opt/public-httpbin/bin/python -c "import socket;s=socket.create_connection(('127.0.0.1',8765),0.2);s.close()" >/dev/null 2>&1; then
 (
  flock -w 10 9 || exit 1
  if ! /opt/public-httpbin/bin/python -c "import socket;s=socket.create_connection(('127.0.0.1',8765),0.2);s.close()" >/dev/null 2>&1; then
   nohup /opt/public-httpbin/bin/gunicorn --bind 127.0.0.1:8765 --workers 1 --threads 2 httpbin:app </dev/null >/tmp/public-httpbin.log 2>&1 9>&- &
  fi
  /opt/public-httpbin/bin/python -c "import socket,time;exec('for i in range(40):\\n try:\\n  s=socket.create_connection((\\\"127.0.0.1\\\",8765),0.2);s.close();break\\n except OSError:time.sleep(.1)\\nelse:raise RuntimeError(\\\"public HTTPbin startup failed\\\")')"
 ) 9>/tmp/public-httpbin.lock || return 1
fi
'''


def main():
    args = argparse.Namespace(tag='requestsfixture_20261112_01', context='desktop-linux',
       docker_data_host_path=Path(r'D:\DockerData\swe-repair-20261111\DockerDesktopWSL'))
    output = HERE / 'environment/test20_preparation_runs' / args.tag
    output.mkdir(parents=True, exist_ok=False)
    runner = base.Preparation(args, {'wheel_cache': r'D:\CodexExperimentCache\test20_20261111'}, output)
    case = next(c for c in json.loads((HERE / 'test20_exact_git_tree_manifest_01.json').read_text(encoding='utf-8'))['instances'] if c['instance_id']=='psf__requests-1963')
    parent = 'sha256:6716c827839feec2259b5eadb66a16813a9ad9bca78993702d901b1c6a80de78'
    deps = json.loads((HERE / 'requests_fixture_dependencies_01.json').read_text(encoding='utf-8'))
    for p in deps['packages']:
        assert base.io.digest(p['path']) == p['sha256']
    profile = deps['profiles'][case['instance_id']]
    assert base.io.digest(profile['lock']) == profile['lock_sha256']
    startup = output/'public-httpbin-start.sh'
    startup.write_text(STARTUP, encoding='utf-8', newline='\n')
    probe = output/'public_identity.py'
    probe.write_text(base.program(case),encoding='utf-8',newline='\n')
    result={'kind':'isolated_public_httpbin_fixture','instance_id':case['instance_id'],
            'parent_image':parent,'dependencies':deps,'startup_sha256':base.io.digest(startup),
            'source_or_tests_modified':False,'model_calls':0,'network':'none; service loopback only'}
    name = runner.start('fixture_install',parent)
    try:
        result['before'] = base.identity(runner,name,case,probe,'after')
        runner.docker('copy_fixed_fixture_wheels','cp',deps['cache'],name+':/tmp/public-fixture-wheels')
        runner.shell(name,'install_isolated_fixture','python -m venv /opt/public-httpbin && /opt/public-httpbin/bin/python -m pip install --no-index --no-deps --no-cache-dir --require-hashes --find-links /tmp/public-fixture-wheels -r /tmp/public-fixture-wheels/'+Path(profile['lock']).name)
        runner.docker('copy_fixture_startup','cp',str(startup),name+':/opt/public-httpbin-start.sh')
        result['import_probe'],_=runner.shell(name,'fixture_import',"cd /tmp && /opt/public-httpbin/bin/python -c 'import httpbin;print(httpbin.__version__)'")
        result['after'] = base.identity(runner,name,case,probe,'after')
        runner.shell(name,'remove_own_probe','rm -f /tmp/public-tree-check.py')
        tag='test20-prepared/requests-httpbin:'+args.tag
        runner.docker('commit_fixture_image','commit','--change','ENV BASH_ENV=/opt/public-httpbin-start.sh','--change','ENV HTTPBIN_URL=http://127.0.0.1:8765/',name,tag)
        _,text=runner.docker('fixture_image_id','image','inspect',tag,'--format','{{.Id}}')
        image=text.strip();assert re.fullmatch(r'sha256:[0-9a-f]{64}',image)
        result['candidate_image_id']=image
    finally:
        runner.clean(name)
    name=runner.start('fixture_fresh',image)
    try:
        result['fresh_identity']=base.identity(runner,name,case,probe,'after')
        result['service_probe'],_=runner.shell(name,'fixture_service_probe',"python -c \"import requests;u='http://127.0.0.1:8765';assert requests.get(u+'/get').status_code==200;assert len(requests.get(u+'/redirect/2').history)==2;print('public HTTPbin ready')\"")
        result['public_smoke'],_=runner.shell(name,'public_smoke','cd /testbed && '+case['public_smoke_command'])
        result['public_file_probe'],_=runner.shell(name,'public_file_probe','cd /testbed && python -m pytest test_requests.py -q -p no:cacheprovider',check=False,timeout=360)
        result['fresh_after']=base.identity(runner,name,case,probe,'after')
        result.update(status='public_smoke_ready',image_id=image,
            full_public_file_passed=result['public_file_probe']['exit_code']==0)
    finally:
        runner.clean(name)
        runner.log.close()
        result['owned_containers_remaining']=runner.owned
        with (output/'result.json').open('x',encoding='utf-8') as f:json.dump(result,f,indent=2)
    print(output/'result.json')


if __name__=='__main__':
    main()
