import contextlib
import io
import json
import shutil
import subprocess
import docker
from swebench.harness.docker_utils import cleanup_container

client = docker.from_env()
name = 'swe-repair-scoring-cli-cleanup-20261106'
try:
    client.containers.get(name)
except docker.errors.NotFound:
    pass
else:
    raise RuntimeError('refusing to reuse an existing cleanup-smoke container')
container = client.containers.create(
    image='sha256:6bddca9c6360684b088cba4a502969e84c3a2f125550983e48e38e2e252b660c',
    name=name, command='tail -f /dev/null', detach=True)
ident = container.id
container.start()
console = io.StringIO()
try:
    with contextlib.redirect_stdout(console):
        cleanup_container(client, container, None)
    try:
        client.containers.get(ident)
    except docker.errors.NotFound:
        absent = True
    else:
        absent = False
    assert absent
except BaseException:
    try:
        client.containers.get(ident).remove(force=True)
    except docker.errors.NotFound:
        pass
    raise
print(json.dumps({'official_cleanup_function': cleanup_container.__module__ + '.cleanup_container',
                  'docker_cli': shutil.which('docker'),
                  'docker_cli_version': subprocess.check_output(['docker', '--version'], text=True).strip(),
                  'smoke_container_name': name, 'smoke_container_id': ident,
                  'official_cleanup_completed': True, 'absence_verified_by_sdk': absent,
                  'cleanup_console': console.getvalue(), 'model_calls': 0, 'hidden_rows_read': 0}))
