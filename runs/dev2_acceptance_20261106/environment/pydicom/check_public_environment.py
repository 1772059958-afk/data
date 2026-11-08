"""Only checkout/public-dependency inspection; no evaluator data or model calls."""
from pathlib import Path
import json
import shlex
import subprocess
import uuid

ROOT = Path(__file__).resolve().parent
IMAGE = 'swebench/sweb.eval.x86_64.pydicom_1776_pydicom-1139:latest'
BASE = 'b9fb05c177b685bf683f7f57b2d57374eb7d882d'


def execute(args, timeout=90):
    result = subprocess.run(['docker', '--context', 'desktop-linux', *args],
                            capture_output=True, text=True, timeout=timeout)
    return {'command': args, 'exit_code': result.returncode,
            'stdout': result.stdout, 'stderr': result.stderr}


def save(name, record):
    with (ROOT / name).open('x', encoding='utf-8') as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)


def check(image, filename, checkout=False, collect=False):
    name = 'pydicom-public-' + uuid.uuid4().hex[:10]
    commands = ['set -e', 'cd /testbed']
    if checkout:
        commands += [f'git cat-file -e {BASE}^{{commit}}', f'git checkout --detach {BASE}', 'git clean -fdq']
    commands += ['printf "BASE_COMMIT="', 'git rev-parse HEAD', 'git status --porcelain',
                 'command -v python', 'python --version', 'python -m pytest --version',
                 'python -c ' + shlex.quote("import pydicom,numpy,pytest; print('PUBLIC_IMPORTS_OK'); print('pydicom='+pydicom.__version__); print('numpy='+numpy.__version__)"),
                 f'git cat-file -e {BASE}^{{commit}}',
                 'find . -path ./.git -prune -o -type f -name test_dataset.py -print']
    if collect:
        commands.append('python -m pytest pydicom/tests/test_dataset.py --collect-only -q --no-header -p no:cacheprovider')
    record = {'kind': 'public_environment_check', 'image': image, 'designated_base': BASE,
              'generation_requests': 0, 'container_name': name}
    try:
        record.update(execute(['run', '--rm', '--name', name, '--network', 'none',
                               '--entrypoint', '/bin/bash', image, '-lc', '\n'.join(commands)]))
    finally:
        record['cleanup'] = execute(['rm', '-f', name])
        absent = execute(['ps', '-a', '--filter', 'name=' + name, '--format', '{{.Names}}'])
        record['cleanup_confirmed_absent'] = absent['exit_code'] == 0 and not absent['stdout'].strip()
        save(filename, record)
    return record


if __name__ == '__main__':
    result = execute(['image', 'inspect', IMAGE, '--format', '{{json .}}'])
    if result['exit_code']:
        raise SystemExit(result['stderr'])
    original = json.loads(result['stdout'])
    identity = {'image': IMAGE, 'image_id': original['Id'], 'repo_digests': original.get('RepoDigests'),
                'size_bytes': original['Size'], 'os': original['Os'], 'architecture': original['Architecture']}
    save('original_image_identity.json', identity)
    initial = check(original['Id'], 'initial_environment.json')
    print(json.dumps(identity))
    print(initial['stdout'])
    print(initial['stderr'])
    prepared = check(original['Id'], 'designated_base_environment.json', checkout=True, collect=True)
    print(prepared['stdout'][-2200:])
    print(prepared['stderr'][-1400:])
    print('CHECK_EXIT=' + str(prepared['exit_code']))
