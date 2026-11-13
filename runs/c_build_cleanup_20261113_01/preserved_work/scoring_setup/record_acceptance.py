import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[2]
run = root / 'runs/prefix_dev1_20261106_01'
report = run / 'scoring/PREFIX/prefix_dev1_20261106_01-PREFIX.prefix_dev1_20261106_01.json'
sidecar = report.with_name(report.name + '.provenance.json')
manifest = json.loads((run / 'controller/input_manifest.json').read_text(encoding='utf-8'))
scored = json.loads(report.read_text(encoding='utf-8'))
frozen = {'matrix.json': manifest['matrix_sha256'],
          **{job['predictions_file']: job['predictions_sha256'] for job in manifest['jobs']}}
unchanged = all(hashlib.sha256((run / name).read_bytes()).hexdigest() == value
                for name, value in frozen.items())
assert unchanged and sidecar.is_file()
data = {'run': 'prefix_dev1_20261106_01', 'model_calls': 0,
        'controller_image_id': manifest['controller_image_id'],
        'harness': 'swebench==5.0.2', 'frozen_inputs_unchanged': unchanged,
        'verdict': 'unresolved' if scored['unresolved_instances'] == 1 else 'other',
        'completed_instances': scored['completed_instances'],
        'error_instances': scored['error_instances'],
        'infrastructure_error': False,
        'report': report.relative_to(root).as_posix(),
        'report_sha256': hashlib.sha256(report.read_bytes()).hexdigest(),
        'provenance': sidecar.relative_to(root).as_posix(),
        'hidden_feedback_exported': False}
with (root / 'runs/dev2_acceptance_20261106/environment/scoring/frozen_prefix_acceptance.json').open('x', encoding='utf-8') as stream:
    json.dump(data, stream, ensure_ascii=False, indent=2)
print(json.dumps(data))
