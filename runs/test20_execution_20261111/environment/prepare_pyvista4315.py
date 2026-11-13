"""Prepare one public PyVista baseline offline with a host disk reserve.

Uses an owned temporary container and commit to avoid duplicating the large
source/wheel build context in BuildKit cache. Existing images/cache are untouched.
All dependencies were fetched separately with verified upstream hashes.
"""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
CONTEXT = ROOT / 'work/test20_environment_20261111/pyvista__pyvista-4315'
NAME = 'test20-prepare-pyvista4315-20261111'
BASE = 'sha256:bd5edf8694cde12aaf99beb18b3935b15e076e81ac7e52aef46b1ca3d9071428'
TAG = 'prefix-env/pyvista-4315:base-db6ee8dd-20261111'
RESERVE = 4 * 1024**3
COMMANDS = []


def run(label, arguments, timeout=180):
    free = shutil.disk_usage('C:/').free
    if free < RESERVE + 64 * 1024**2:
        raise RuntimeError('C drive approaching 4 GiB preparation reserve')
    path = OUT / ('pyvista4315_' + label + '.log')
    started = time.monotonic()
    with path.open('x', encoding='utf-8', newline='\n') as log:
        process = subprocess.Popen(arguments, stdout=log, stderr=subprocess.STDOUT,
                                   text=True, encoding='utf-8', errors='replace')
        low = free
        try:
            while process.poll() is None:
                now = shutil.disk_usage('C:/').free
                low = min(low, now)
                if now < RESERVE + 64 * 1024**2:
                    subprocess.run(['docker', '--context', 'desktop-linux', 'rm', '-f', NAME],
                                   capture_output=True, timeout=30)
                    process.terminate()
                    raise RuntimeError('Stopped own preparation container at the disk reserve')
                if time.monotonic() - started > timeout:
                    process.terminate()
                    raise TimeoutError(label + ' exceeded its preparation timeout')
                time.sleep(0.5)
            code = process.returncode
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
    row = {'label': label, 'arguments': arguments, 'exit_code': code,
           'log': path.name, 'log_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
           'seconds': round(time.monotonic()-started, 3), 'C_min_free_bytes': low,
           'C_end_free_bytes': shutil.disk_usage('C:/').free}
    COMMANDS.append(row)
    with (OUT / 'pyvista4315_preparation_progress.json').open('w', encoding='utf-8', newline='\n') as f:
        json.dump({'method': 'offline_owned_container_then_commit', 'base_image': BASE,
                   'commands': COMMANDS, 'not_generation': True}, f, indent=2)
        f.write('\n')
    if code:
        raise RuntimeError(label + ' failed; preserve logs and inspect the preparation container')
    return path.read_text(encoding='utf-8')


def execute(label, script, timeout=180):
    return run(label, ['docker', '--context', 'desktop-linux', 'exec', NAME, 'bash', '-lc', script], timeout)


def main():
    if (OUT / 'pyvista4315_validation.json').exists():
        raise RuntimeError('refusing to overwrite an existing environment validation')
    signature = json.loads((OUT / 'ubuntu_inrelease_verification_01.json').read_text(encoding='utf-8'))
    # The signature evidence is retained as an input, never replaced by a status string.
    if (signature.get('returncode') != 0 or signature.get('all_signatures_valid') is not True
            or signature.get('all_cleartext_matches_previous_release') is not True
            or any(row['returncode'] != 0 for row in signature['verification']['results'])):
        raise RuntimeError('Official Ubuntu metadata signature chain was not verified')
    for manifest, directory, key in [('pyvista4315_wheels.json', 'wheels', 'wheels'),
                                     ('pyvista4315_system_debs.json', 'system_debs', 'debs')]:
        for row in json.loads((OUT / manifest).read_text(encoding='utf-8'))[key]:
            if hashlib.sha256((CONTEXT / directory / row['filename']).read_bytes()).hexdigest() != row['sha256']:
                raise RuntimeError('Offline dependency bytes changed')
    vtk = json.loads((OUT / 'pyvista4315_vtk_wheel.json').read_text(encoding='utf-8'))
    if hashlib.sha256((CONTEXT / 'wheels' / vtk['filename']).read_bytes()).hexdigest() != vtk['sha256']:
        raise RuntimeError('Offline VTK wheel bytes changed')
    run('start', ['docker', '--context', 'desktop-linux', 'run', '-d', '--pull=never',
        '--network', 'none', '--name', NAME,
        '--mount', f'type=bind,source={CONTEXT / "wheels"},target=/public-wheels,readonly',
        '--mount', f'type=bind,source={CONTEXT / "system_debs"},target=/public-system-debs,readonly',
        '-e', 'PYVISTA_OFF_SCREEN=true', '-e', 'MPLBACKEND=Agg',
        '--entrypoint', '/bin/bash', BASE, '-lc', 'sleep infinity'])
    execute('empty_testbed', 'rm -rf /testbed && mkdir /testbed')
    run('copy_git', ['docker', '--context', 'desktop-linux', 'cp',
                    str(CONTEXT / 'testbed/.git'), NAME + ':/testbed/.git'])
    execute('checkout', 'cd /testbed && git config core.autocrlf false '
        '&& git config core.filemode true && git config core.symlinks true '
        '&& git reset --hard HEAD && git config remote.origin.url https://github.com/pyvista/pyvista.git '
        '&& test "$(git rev-parse HEAD)" = db6ee8dd4a747b8864caae36c5d05883976a3ae5 '
        '&& test -z "$(git status --porcelain)"')
    execute('install_gl', 'DEBIAN_FRONTEND=noninteractive dpkg -i /public-system-debs/*.deb', 180)
    execute('install_wheels', 'python -m pip install --no-index --no-deps --no-cache-dir /public-wheels/*.whl', 180)
    execute('install_project', 'python -m pip install --no-index --no-deps --no-build-isolation --no-cache-dir -e /testbed', 180)
    identity = execute('identity', 'cd /testbed && git rev-parse HEAD && git status --porcelain '
        '&& python -c "import ipykernel.ipkernel,pyvista,vtk,numpy,matplotlib,PIL,pytest; '
        'print(pyvista.__version__,vtk.vtkVersion.GetVTKVersion(),numpy.__version__,matplotlib.__version__,PIL.__version__,pytest.__version__)"')
    public = execute('public_ndarray', 'cd /testbed && python -m pytest -q tests/test_pyvista_ndarray.py', 180)
    run('commit', ['docker', '--context', 'desktop-linux', 'commit', NAME, TAG], 180)
    inspected = json.loads(run('inspect_image', ['docker', '--context', 'desktop-linux', 'image', 'inspect', TAG]))[0]
    actual = run('inspect_container', ['docker', '--context', 'desktop-linux', 'inspect', '--format', '{{.Image}}', NAME]).strip()
    # Preparation container uses the parent image; a NEW container below verifies
    # the committed image's actual identity and clean checkout independently.
    run('cleanup_preparation', ['docker', '--context', 'desktop-linux', 'rm', '-f', NAME])
    verify_name = 'test20-env-pyvista4315-20261111'
    new_image = inspected['Id']
    fresh = run('fresh_verify', ['docker', '--context', 'desktop-linux', 'run', '--rm', '--pull=never',
        '--network', 'none', '--name', verify_name, '--entrypoint', '/bin/bash', new_image, '-lc',
        'cd /testbed && git rev-parse HEAD && test -z "$(git status --porcelain)" '
        '&& python -c "import pyvista,vtk; print(pyvista.__version__,vtk.vtkVersion.GetVTKVersion())"'])
    record = {'instance_id': 'pyvista__pyvista-4315', 'tag': TAG, 'image_id': new_image,
        'base_commit': 'db6ee8dd4a747b8864caae36c5d05883976a3ae5', 'network': 'none',
        'method': 'offline_owned_container_then_commit', 'parent_container_image_id': actual,
        'identity_stdout': identity, 'public_test_command': 'python -m pytest -q tests/test_pyvista_ndarray.py',
        'public_test_stdout': public, 'fresh_container_stdout': fresh, 'commands': COMMANDS,
        'apt_signature_input': 'ubuntu_inrelease_verification_01.json',
        'apt_signature_input_sha256': hashlib.sha256((OUT / 'ubuntu_inrelease_verification_01.json').read_bytes()).hexdigest(),
        'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'limitations': ['Only non-rendering public ndarray tests and imports were validated.',
                        'VTK 9.2.6 uses GLX; no DISPLAY/Xvfb or rendering acceptance is claimed.',
                        'No tests or source assertions were changed.'],
        'C_free_bytes': shutil.disk_usage('C:/').free}
    with (OUT / 'pyvista4315_validation.json').open('x', encoding='utf-8', newline='\n') as f:
        json.dump(record, f, indent=2)
        f.write('\n')
    print(json.dumps({'image_id': new_image, 'public_test_tail': public[-600:],
                      'C_free_bytes': record['C_free_bytes']}))


if __name__ == '__main__':
    main()
