"""Apply the audited pre-generation libXrender runtime fix, then verify/commit.

The first import-failure logs and original preparation script remain unchanged.
This is environment preparation before any model generation, not a run retry.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

OUT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('original_pyvista_preparation', OUT / 'prepare_pyvista4315.py')
prep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prep)


def main():
    if (OUT / 'pyvista4315_validation.json').exists():
        raise RuntimeError('refusing to overwrite a completed validation')
    prior = json.loads((OUT / 'pyvista4315_preparation_progress.json').read_text(encoding='utf-8'))
    prep.COMMANDS.extend(prior['commands'])
    amendment = json.loads((OUT / 'pyvista4315_xrender_amendment.json').read_text(encoding='utf-8'))
    dep = prep.CONTEXT / 'system_debs' / amendment['filename']
    if hashlib.sha256(dep.read_bytes()).hexdigest() != amendment['sha256']:
        raise RuntimeError('amendment package bytes changed')
    prep.execute('install_xrender', 'DEBIAN_FRONTEND=noninteractive dpkg -i /public-system-debs/libxrender1_0.9.10-1build4_amd64.deb')
    identity = prep.execute('identity_02', 'cd /testbed && git rev-parse HEAD && git status --porcelain '
        '&& python -c "import ipykernel.ipkernel,pyvista,vtk,numpy,matplotlib,PIL,pytest; '
        'print(pyvista.__version__,vtk.vtkVersion.GetVTKVersion(),numpy.__version__,matplotlib.__version__,PIL.__version__,pytest.__version__)"')
    public = prep.execute('public_ndarray', 'cd /testbed && python -m pytest -q tests/test_pyvista_ndarray.py')
    prep.run('commit', ['docker', '--context', 'desktop-linux', 'commit', prep.NAME, prep.TAG], 180)
    image = json.loads(prep.run('inspect_image', ['docker', '--context', 'desktop-linux', 'image', 'inspect', prep.TAG]))[0]['Id']
    prep.run('cleanup_preparation', ['docker', '--context', 'desktop-linux', 'rm', '-f', prep.NAME])
    name = 'test20-env-pyvista4315-20261111'
    prep.run('fresh_start', ['docker', '--context', 'desktop-linux', 'run', '-d', '--pull=never',
        '--network', 'none', '--name', name, '--entrypoint', '/bin/bash', image, '-lc', 'sleep infinity'])
    try:
        actual = prep.run('fresh_image_id', ['docker', '--context', 'desktop-linux', 'inspect', '--format', '{{.Image}}', name]).strip()
        fresh = prep.run('fresh_verify', ['docker', '--context', 'desktop-linux', 'exec', name, 'bash', '-lc',
            'cd /testbed && git rev-parse HEAD && test -z "$(git status --porcelain)" '
            '&& python -c "import pyvista,vtk; print(pyvista.__version__,vtk.vtkVersion.GetVTKVersion())"'])
        if actual != image:
            raise RuntimeError('fresh container image differs from the prepared image')
    finally:
        prep.run('fresh_cleanup', ['docker', '--context', 'desktop-linux', 'rm', '-f', name])
    record = {'instance_id': 'pyvista__pyvista-4315', 'tag': prep.TAG,
        'image_id': image, 'actual_container_image_id': actual,
        'base_commit': 'db6ee8dd4a747b8864caae36c5d05883976a3ae5', 'network': 'none',
        'method': 'offline_owned_container_then_commit', 'identity_stdout': identity,
        'public_test_command': 'python -m pytest -q tests/test_pyvista_ndarray.py',
        'public_test_stdout': public, 'fresh_container_stdout': fresh, 'commands': prep.COMMANDS,
        'preparation_scripts': {name: hashlib.sha256((OUT / name).read_bytes()).hexdigest()
            for name in ('prepare_pyvista4315.py', 'resume_pyvista4315.py')},
        'environment_amendment': 'pyvista4315_xrender_amendment.json',
        'apt_signature_input': 'ubuntu_inrelease_verification_01.json',
        'apt_signature_input_sha256': hashlib.sha256((OUT / 'ubuntu_inrelease_verification_01.json').read_bytes()).hexdigest(),
        'limitations': ['Only non-rendering public ndarray tests and imports were validated.',
            'VTK 9.2.6 uses GLX; no DISPLAY/Xvfb or rendering acceptance is claimed.',
            'Initial missing-libXrender import failure is preserved; fix occurred before generation.',
            'No test or source assertion was changed; pytest plugin autoload remained enabled.'],
        'C_free_bytes': shutil.disk_usage('C:/').free}
    with (OUT / 'pyvista4315_validation.json').open('x', encoding='utf-8', newline='\n') as f:
        json.dump(record, f, indent=2)
        f.write('\n')
    print(json.dumps({'image_id': image, 'actual_image_matches': actual == image,
                      'public_test_tail': public[-800:], 'C_free_bytes': record['C_free_bytes']}))


if __name__ == '__main__':
    main()
