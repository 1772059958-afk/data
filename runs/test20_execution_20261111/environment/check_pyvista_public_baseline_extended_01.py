"""Run the exact generated public test command on the untouched image baseline."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import time

HERE = Path(__file__).resolve().parent
OUT = HERE / 'pyvista_public_baseline_extended_01.json'
IMAGE = 'sha256:c3d02ef66da989070d532ea6993104f9d4b76e3d5f86fea85d7e4da1fba2e230'
BASE = 'db6ee8dd4a747b8864caae36c5d05883976a3ae5'
NAME = 'test20-pyvista-public-baseline-extended-20261111-01'
DOCKER = ['docker', '--context', 'desktop-linux']
TEST = 'python -m pytest tests/test_grid.py tests/test_demos.py tests/test_cells.py -q --no-header -p no:cacheprovider'


def call(args, timeout=30):
    result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8',
                            errors='replace', timeout=timeout)
    return {'command': args, 'returncode': result.returncode,
            'stdout': result.stdout, 'stderr': result.stderr}


def checked(args, timeout=30):
    result = call(args, timeout)
    if result['returncode']:
        raise RuntimeError(json.dumps(result))
    return result


def main():
    if OUT.exists():
        raise FileExistsError('refusing to replace public baseline evidence')
    prior = call(DOCKER + ['container', 'inspect', NAME])
    if prior['returncode'] == 0:
        raise FileExistsError('named baseline container already exists')
    image = checked(DOCKER + ['image', 'inspect', IMAGE, '--format', '{{.Id}}'])
    assert image['stdout'].strip() == IMAGE
    started = False
    report = {'kind': 'extended_public_baseline_validation', 'date': '2026-11-11',
              'instance_id': 'pyvista__pyvista-4315', 'expected_image_id': IMAGE,
              'base_commit': BASE, 'network': 'none', 'mounts': [],
              'official_or_hidden_tests': False, 'patch_applied': False,
              'test_command': TEST, 'probe_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    try:
        report['start'] = checked(DOCKER + ['run', '-d', '--pull=never', '--network', 'none',
            '--name', NAME, '--entrypoint', '/bin/bash', IMAGE, '-lc', 'sleep infinity'])
        started = True
        report['container_image'] = checked(DOCKER + ['inspect', NAME, '--format', '{{.Image}}'])
        assert report['container_image']['stdout'].strip() == IMAGE
        report['head_before'] = checked(DOCKER + ['exec', NAME, 'bash', '-lc', 'cd /testbed && git rev-parse HEAD'])
        report['clean_before'] = checked(DOCKER + ['exec', NAME, 'bash', '-lc', 'cd /testbed && git status --porcelain'])
        assert report['head_before']['stdout'].strip() == BASE
        assert not report['clean_before']['stdout'].strip()
        start = time.monotonic()
        report['public_test'] = call(DOCKER + ['exec', NAME, 'bash', '-lc',
            'cd /testbed && timeout --signal=KILL 180s bash -lc ' + shlex.quote(TEST)], timeout=190)
        report['public_test']['elapsed_seconds'] = round(time.monotonic() - start, 3)
        report['head_after'] = checked(DOCKER + ['exec', NAME, 'bash', '-lc', 'cd /testbed && git rev-parse HEAD'])
        report['clean_after'] = checked(DOCKER + ['exec', NAME, 'bash', '-lc', 'cd /testbed && git status --porcelain'])
        report['head_unchanged'] = report['head_after']['stdout'].strip() == BASE
        report['tracked_and_untracked_checkout_clean'] = not report['clean_after']['stdout'].strip()
    except Exception as exc:
        report['probe_error'] = f'{type(exc).__name__}: {exc}'
    finally:
        if started:
            report['cleanup'] = call(DOCKER + ['rm', '-f', NAME])
        absent = call(DOCKER + ['container', 'inspect', NAME])
        report['container_absence_verified'] = absent['returncode'] != 0 and 'No such container' in absent['stderr']
        report['active_container_names_after'] = checked(DOCKER + ['ps', '--format', '{{.Names}}'])['stdout'].splitlines()
        with OUT.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
    print(json.dumps({'output': str(OUT), 'test_returncode': report.get('public_test', {}).get('returncode'),
        'public_stdout': report.get('public_test', {}).get('stdout'),
        'public_stderr': report.get('public_test', {}).get('stderr'),
        'head_unchanged': report.get('head_unchanged'),
        'checkout_clean': report.get('tracked_and_untracked_checkout_clean'),
        'container_absence_verified': report.get('container_absence_verified'),
        'active_container_names_after': report.get('active_container_names_after'),
        'probe_error': report.get('probe_error')}, ensure_ascii=False))
    if report.get('probe_error') or not report['container_absence_verified']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
