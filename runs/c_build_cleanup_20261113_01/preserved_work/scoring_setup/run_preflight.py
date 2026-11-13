import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[2]
image = 'swe-repair/scoring-controller:20261106'
base = ['docker', '--context', 'desktop-linux']
image_id = subprocess.check_output(base + ['image', 'inspect', image, '--format', '{{.Id}}'], text=True).strip()
cmd = base + ['run', '--rm', '--network', 'none', '--env', 'DOCKER_HOST=unix:///var/run/docker.sock',
    '--mount', 'type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock',
    '--mount', f'type=bind,src={root / "data/harness"},dst=/input,readonly',
    '--mount', f'type=bind,src={root / "work/scoring_setup/preflight.py"},dst=/opt/preflight.py,readonly',
    image_id, '/opt/preflight.py']
result = subprocess.run(cmd, capture_output=True, text=True)
out = root / 'runs/dev2_acceptance_20261106/environment/scoring'
with (out / 'preflight_console.log').open('x', encoding='utf-8') as stream:
    stream.write(result.stdout + result.stderr)
if result.returncode:
    raise SystemExit('preflight failed; see isolated environment log')
data = json.loads(result.stdout)
data.update(controller_image_id=image_id, command=cmd)
with (out / 'preflight.json').open('x', encoding='utf-8') as stream:
    json.dump(data, stream, ensure_ascii=False, indent=2)
print(json.dumps(data))
