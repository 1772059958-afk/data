import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[2]
out = root / 'runs/dev2_acceptance_20261106/environment/scoring'
image_id = json.loads((out / 'preflight.json').read_text(encoding='utf-8'))['controller_image_id']
cmd = ['docker', '--context', 'desktop-linux', 'run', '--rm', '--network', 'none',
       '--mount', f'type=bind,src={root / "work/scoring_setup/check_harness_semantics.py"},dst=/opt/check.py,readonly',
       image_id, '/opt/check.py']
result = subprocess.run(cmd, capture_output=True, text=True)
if result.returncode:
    raise RuntimeError(result.stderr)
data = json.loads(result.stdout)
data['controller_image_id'] = image_id
with (out / 'synthetic_semantics.json').open('x', encoding='utf-8') as stream:
    json.dump(data, stream, ensure_ascii=False, indent=2)
print(json.dumps(data))
