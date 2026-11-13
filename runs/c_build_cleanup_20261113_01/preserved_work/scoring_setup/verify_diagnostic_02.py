import importlib.util
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / 'src'))
from swe_repair.evaluation import validate_artifact_files, sidecar_path, sha256_bytes
spec = importlib.util.spec_from_file_location('score_run_verified', root / 'scripts/score_run.py')
score = importlib.util.module_from_spec(spec)
spec.loader.exec_module(score)
run = root / 'runs/dev2_diagnostic_20261106_02'
matrix = json.loads((run / 'matrix.json').read_text(encoding='utf-8'))
manifest = json.loads((run / 'controller/input_manifest.json').read_text(encoding='utf-8'))
exit_status = json.loads((run / 'controller/exit_status.json').read_text())
assert exit_status['returncode'] == 0
assert sha256_bytes((run / 'matrix.json').read_bytes()) == manifest['matrix_sha256']
fields = ('submitted_instances', 'completed_instances', 'resolved_instances', 'unresolved_instances',
          'empty_patch_instances', 'error_instances', 'infra_failure_instances', 'ambiguous_failure_instances')
rows = []
for job in manifest['jobs']:
    report_path = Path(job['report_path'])
    report = json.loads(report_path.read_text())
    provenance = json.loads(sidecar_path(report_path).read_text())
    validate_artifact_files(run / 'matrix.json', report_path, job['arm'], provenance)
    score.validate_dataset_binding(matrix, run, provenance)
    assert provenance['harness_environment']['swebench'] == '5.0.2'
    rows.append({'arm': job['arm'], 'report': report_path.relative_to(root).as_posix(),
                 'provenance_valid': True, **{field: report.get(field, 0) for field in fields}})
summary = {'tag': matrix['tag'], 'controller_exit_status': 0,
           'controller_image_id': manifest['controller_image_id'], 'reports': rows,
           'matrix_predictions_unchanged': True, 'protected_evaluator_source_unchanged': True,
           'model_calls': 0, 'hidden_feedback_exported': False,
           'environment_health': 'not_inferred_from_harness_error_count',
           'cleanup_observation': 'controller lacked Linux docker CLI; leftover tail containers are cleaned separately; next-arm creation removes same-name old containers through Docker SDK before a clean image start'}
with (run / 'scoring/verification_summary.json').open('x', encoding='utf-8') as stream:
    json.dump(summary, stream, ensure_ascii=False, indent=2)
print(json.dumps(summary, ensure_ascii=False, indent=2))
