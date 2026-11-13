"""Apply the pre-generation public dependency amendment to a NEW PyVista image."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

HERE = Path(__file__).resolve().parent
OUT = HERE / 'pyvista_public_test_fix_01'
PARENT = 'sha256:c3d02ef66da989070d532ea6993104f9d4b76e3d5f86fea85d7e4da1fba2e230'
TAG = 'prefix-env/pyvista-4315:base-db6ee8dd-public-tests-20261111'
BASE = 'db6ee8dd4a747b8864caae36c5d05883976a3ae5'
COMMAND = 'python -m pytest tests/test_grid.py tests/test_demos.py tests/test_cells.py -q --no-header -p no:cacheprovider'
STORAGE = Path('D:/DockerData/swe-repair-20261111/DockerDesktopWSL')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if OUT.exists() or (HERE / 'screen_images_corrected_01.json').exists():
        raise RuntimeError('refusing to overwrite an existing correction or screen map')
    plan = json.loads((HERE / 'pyvista_public_test_environment_amendment_plan_01.json').read_text(encoding='utf-8'))
    cache = json.loads((HERE / 'pyvista_public_test_dependency_fix_cache_01.json').read_text(encoding='utf-8'))
    assert plan['derive_from_image'] == PARENT and plan['acceptance_command'] == COMMAND
    lock = Path(plan['candidate_lock']['path'])
    assert sha(lock) == plan['candidate_lock']['sha256']
    for row in cache['wheels']:
        assert sha(Path(row['cache_path'])) == row['sha256']
    OUT.mkdir()
    events = []
    owned = {}

    def run(label, args, *, check=True, cleanup=False, timeout=180):
        if not cleanup:
            assert STORAGE.exists(), 'migration destination missing'
            assert min(shutil.disk_usage(p).free for p in ('C:/', STORAGE)) > 4*1024**3, 'disk reserve reached'
        began = time.monotonic()
        process = subprocess.run(['docker', '--context', 'desktop-linux', *args], capture_output=True,
                                 text=True, timeout=timeout, encoding='utf-8', errors='replace')
        path = OUT / (f'{len(events):03d}_' + label + '.log')
        with path.open('x', encoding='utf-8', newline='\n') as f:
            f.write(process.stdout + process.stderr)
        row = {'label': label, 'args': args, 'exit_code': process.returncode, 'log': path.name,
               'log_sha256': sha(path), 'seconds': round(time.monotonic()-began, 3)}
        events.append(row)
        if check and process.returncode:
            raise RuntimeError(label + ' failed: ' + path.name)
        return process.stdout.strip(), row

    def start(name, image, mounts=False):
        _, exists = run('existing_name_check', ['inspect', '--type', 'container', name], check=False)
        if exists['exit_code'] == 0:
            raise RuntimeError('container already exists; refusing to remove/reuse it')
        args = ['run', '-d', '--pull=never', '--network', 'none', '--name', name,
                '--label', 'codex.public-environment=pyvista-fix-01']
        if mounts:
            args += ['--mount', f'type=bind,source={plan["wheel_cache"]},target=/public-wheels,readonly',
                     '--mount', f'type=bind,source={lock},target=/public-fix.lock,readonly']
        args += ['--entrypoint', '/bin/bash', image, '-lc', 'sleep infinity']
        text, _ = run('start', args)
        owned[name] = text.splitlines()[-1]

    def clean(name):
        expected = owned.get(name)
        if not expected:
            return
        actual, status = run('cleanup_identity', ['inspect', '--format', '{{.Id}}', name], check=False, cleanup=True)
        if status['exit_code'] == 0:
            if actual != expected:
                raise RuntimeError('container name changed identity; refusing deletion')
            run('remove_owned_container', ['rm', '-f', name], cleanup=True)
        _, absence = run('absence', ['inspect', '--type', 'container', name], check=False, cleanup=True)
        assert absence['exit_code'] != 0, 'owned container remains'
        del owned[name]

    def shell(name, label, script, check=True):
        return run(label, ['exec', name, 'bash', '-lc', script], check=check)

    def identity(name, label, expected_image):
        actual, _ = run(label + '_actual_image', ['inspect', '--format', '{{.Image}}', name])
        assert actual == expected_image
        output, _ = shell(name, label + '_head_clean',
            f'cd /testbed && test "$(git rev-parse HEAD)" = {BASE} '
            '&& test -z "$(git status --porcelain)" && git rev-parse HEAD')
        assert output == BASE
        return {'image_id': actual, 'base_commit': output, 'clean': True}

    prepared_name = 'test20-pyvista-public-fix-20261111-01'
    fresh_name = 'test20-pyvista-public-fix-verify-20261111-01'
    success = False
    report = {'kind': 'public_pyvista_dependency_environment_correction', 'patch_applied': False,
              'source_or_tests_modified': False, 'hidden_fields_read': False,
              'model_calls': 0, 'project_dotenv_read': False, 'original_image_id': PARENT,
              'base_commit': BASE, 'test_command': COMMAND, 'cache_audit_sha256': sha(HERE / 'pyvista_public_test_dependency_fix_cache_01.json'),
              'correction_plan_sha256': sha(HERE / 'pyvista_public_test_environment_amendment_plan_01.json'),
              'script_sha256': sha(Path(__file__)), 'events': events}
    try:
        _, previous = run('existing_new_tag_check', ['image', 'inspect', TAG], check=False)
        assert previous['exit_code'] != 0, 'new tag already exists'
        start(prepared_name, PARENT, mounts=True)
        report['before'] = identity(prepared_name, 'before', PARENT)
        shell(prepared_name, 'install_fixed_additions', 'python -m pip install --no-index --no-deps '
              '--no-cache-dir --require-hashes --find-links /public-wheels -r /public-fix.lock')
        versions, _ = shell(prepared_name, 'installed_versions', 'python -c "import importlib.metadata,json; '
            'print(json.dumps({p:importlib.metadata.version(p) for p in [\'meshio\',\'tqdm\',\'rich\',\'markdown-it-py\',\'mdurl\',\'typing-extensions\',\'Pygments\',\'numpy\']}))"')
        report['installed_versions'] = json.loads(versions)
        _, test = shell(prepared_name, 'original_three_file_public_baseline', 'cd /testbed && ' + COMMAND, check=False)
        report['public_test'] = test
        report['after'] = identity(prepared_name, 'after', PARENT)
        assert test['exit_code'] == 0, 'public baseline did not pass; preserve failure and do not accept image'
        run('commit_new_image', ['commit', prepared_name, TAG])
        image, _ = run('committed_actual_image', ['image', 'inspect', '--format', '{{.Id}}', TAG])
        report['image_id'] = image
        clean(prepared_name)
        start(fresh_name, image)
        report['fresh_before'] = identity(fresh_name, 'fresh_before', image)
        _, test = shell(fresh_name, 'fresh_three_file_public_baseline', 'cd /testbed && ' + COMMAND, check=False)
        report['fresh_public_test'] = test
        report['fresh_after'] = identity(fresh_name, 'fresh_after', image)
        assert test['exit_code'] == 0
        success = True
    finally:
        failures = []
        for name in list(owned):
            try:
                clean(name)
            except Exception as exc:
                failures.append({'name': name, 'error': str(exc)})
        report.update(success=success and not failures, cleanup_failures=failures,
                      remaining_owned_containers=owned, C_free_bytes=shutil.disk_usage('C:/').free,
                      D_free_bytes=shutil.disk_usage(STORAGE).free)
        with (OUT / 'validation.json').open('x', encoding='utf-8', newline='\n') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
            f.write('\n')
    assert report['success']
    corrected = json.loads((HERE / 'screen_images.json').read_text(encoding='utf-8'))
    corrected['pyvista__pyvista-4315'] = report['image_id']
    with (HERE / 'screen_images_corrected_01.json').open('x', encoding='utf-8', newline='\n') as f:
        json.dump(corrected, f, indent=2)
        f.write('\n')
    print(json.dumps({'image_id': report['image_id'], 'success': True,
                      'new_map': 'screen_images_corrected_01.json',
                      'C_free_bytes': report['C_free_bytes'], 'D_free_bytes': report['D_free_bytes']}))


if __name__ == '__main__':
    main()
