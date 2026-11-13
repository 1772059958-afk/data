import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[2]
base = ['docker', '--context', 'desktop-linux']
parent = subprocess.check_output(base + ['image', 'inspect', 'swe-repair/scoring-controller:20261106',
                                       '--format', '{{.Id}}'], text=True).strip()
assert parent == 'sha256:123849a78746d803a2b646170562856056621673f02d9f4ab11c6f150b732aef'
image = subprocess.check_output(base + ['image', 'inspect', 'swe-repair/scoring-controller:20261106-cli',
                                      '--format', '{{.Id}}'], text=True).strip()
assert image == 'sha256:1f43c83b3d3c631d37af54a19828df269accd045a22c62c0aab5b2bfa713726f'
cmd = base + ['run', '--rm', '--network', 'none', '--env', 'DOCKER_HOST=unix:///var/run/docker.sock',
              '--mount', 'type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock',
              '--mount', f'type=bind,src={root / "work/scoring_setup/check_official_cleanup.py"},dst=/opt/check.py,readonly',
              image, '/opt/check.py']
result = subprocess.run(cmd, capture_output=True, text=True)
out = root / 'runs/dev2_acceptance_20261106/environment/scoring'
with (out / 'cleanup_smoke_console.log').open('x', encoding='utf-8') as stream:
    stream.write(result.stdout + result.stderr)
if result.returncode:
    raise RuntimeError('official cleanup smoke failed; see environment audit log')
data = json.loads(result.stdout)
data.update(controller_image_id=image, parent_controller_image_id=parent,
            command=cmd, network='none', dataset_mounted=False)
with (out / 'cleanup_smoke.json').open('x', encoding='utf-8') as stream:
    json.dump(data, stream, ensure_ascii=False, indent=2)
print(json.dumps(data))
