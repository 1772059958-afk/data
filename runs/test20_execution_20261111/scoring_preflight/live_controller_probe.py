"""One bounded offline controller probe. No evaluator data/credentials mounted."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent / 'readiness_live.json'
IMAGE = 'sha256:1f43c83b3d3c631d37af54a19828df269accd045a22c62c0aab5b2bfa713726f'
NAME = 'swe_scoring_preflight_20261111_01'
DOCKER = ['docker', '--context', 'desktop-linux']
CODE = r'''
import importlib.metadata, json, platform, subprocess, sys
import docker
client = docker.from_env()
server = client.version()
cli = subprocess.run(['docker', '--version'], check=True, capture_output=True, text=True).stdout.strip()
data = {'python': platform.python_version(), 'python_executable': sys.executable,
        'swebench': importlib.metadata.version('swebench'),
        'docker_sdk': importlib.metadata.version('docker'),
        'linux_docker_cli': cli, 'docker_socket_ping': client.ping(),
        'docker_server_version': server.get('Version'),
        'docker_server_os': server.get('Os'), 'docker_server_arch': server.get('Arch'),
        'container_system': platform.system(), 'network_mode': 'none',
        'evaluator_rows_read': 0, 'hidden_logs_read': 0, 'model_calls': 0}
assert data['swebench'] == '5.0.2'
assert sys.executable == '/opt/scoring/bin/python'
assert data['container_system'] == 'Linux'
assert data['docker_socket_ping'] is True
assert cli.startswith('Docker version ')
print(json.dumps(data))
'''


def call(args, **kwargs):
    return subprocess.run(args, capture_output=True, text=True, encoding='utf-8',
                          errors='replace', timeout=60, **kwargs)


def main():
    if OUT.exists():
        raise FileExistsError('live readiness output already exists')
    inspect = call(DOCKER + ['image', 'inspect', IMAGE, '--format', '{{.Id}}'])
    if inspect.returncode or inspect.stdout.strip() != IMAGE:
        raise RuntimeError('expected immutable local controller image is unavailable')
    prior = call(DOCKER + ['container', 'inspect', NAME])
    if prior.returncode == 0:
        raise FileExistsError('preflight container name already exists; do not reuse')
    command = DOCKER + ['run', '--rm', '--pull=never', '--name', NAME,
                       '--network', 'none', '--env', 'DOCKER_HOST=unix:///var/run/docker.sock',
                       '--mount', 'type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock',
                       IMAGE, '-c', CODE]
    start = time.monotonic()
    completed = call(command)
    cleanup = call(DOCKER + ['container', 'inspect', NAME])
    disappeared = cleanup.returncode != 0 and 'No such container' in cleanup.stderr
    result = {'kind': 'live_offline_scoring_controller_health', 'date': '2026-11-11',
              'image_id': IMAGE, 'container_name': NAME, 'command': command,
              'elapsed_seconds': round(time.monotonic() - start, 3),
              'returncode': completed.returncode,
              'controller': json.loads(completed.stdout) if completed.returncode == 0 else None,
              'stderr': completed.stderr, 'container_absence_verified': disappeared,
              'mounts': ['docker socket only'], 'credentials_read': False,
              'project_or_evaluator_data_mounted': False, 'scoring_performed': False,
              'probe_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    with OUT.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    if completed.returncode or not disappeared:
        raise RuntimeError('controller health or cleanup failed; preserved readiness report')
    print(json.dumps({'output': str(OUT), 'controller': result['controller'],
                      'container_absence_verified': disappeared}, ensure_ascii=False))


if __name__ == '__main__':
    main()
