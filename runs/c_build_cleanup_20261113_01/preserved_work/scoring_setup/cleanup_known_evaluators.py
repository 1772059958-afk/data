import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[2]
base = ['docker', '--context', 'desktop-linux']
names = ['sweb.eval.pvlib__pvlib-python-1707.prefix_dev1_20261106_01',
         'sweb.eval.pvlib__pvlib-python-1707.dev2_diagnostic_20261106_02',
         'sweb.eval.pydicom__pydicom-1139.dev2_diagnostic_20261106_02']
rows = []
for name in names:
    inspected = subprocess.run(base + ['container', 'inspect', name, '--format', '{{json .}}'],
                               capture_output=True, text=True)
    if inspected.returncode:
        rows.append({'name': name, 'already_absent': True})
        continue
    data = json.loads(inspected.stdout)
    assert data['Name'] == '/' + name
    ident = data['Id']
    removed = subprocess.run(base + ['container', 'rm', '--force', ident], capture_output=True, text=True)
    assert removed.returncode == 0
    after = subprocess.run(base + ['container', 'inspect', ident], capture_output=True, text=True)
    assert after.returncode != 0 and 'No such' in after.stderr
    rows.append({'name': name, 'id': ident, 'removed': True, 'absence_verified': True})
with (root / 'runs/dev2_diagnostic_20261106_02/scoring/controller_cleanup_addendum.json').open('x', encoding='utf-8') as stream:
    json.dump({'scope': 'three explicitly named completed evaluator containers only', 'containers': rows}, stream, indent=2)
print(json.dumps(rows))
