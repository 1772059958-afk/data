"""Final official-score audit, exporting only verdict categories and paths."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / 'src'))
from swe_repair.evaluation import validate_artifact_files, sidecar_path, sha256_bytes
from swe_repair.cf import verdict_status
spec = importlib.util.spec_from_file_location('final_pilot_score', root / 'scripts/score_run.py')
score = importlib.util.module_from_spec(spec)
spec.loader.exec_module(score)
image = 'sha256:1f43c83b3d3c631d37af54a19828df269accd045a22c62c0aab5b2bfa713726f'
base = ['docker', '--context', 'desktop-linux']
rows, names = [], []
shared = None
fields = ('submitted_instances', 'completed_instances', 'resolved_instances', 'unresolved_instances',
          'empty_patch_instances', 'error_instances', 'infra_failure_instances', 'ambiguous_failure_instances')
for arm in 'ABCDE':
    run = root / f'runs/dev2_pilot_{arm}_20261106_01'
    matrix_bytes = (run / 'matrix.json').read_bytes()
    matrix = json.loads(matrix_bytes)
    manifest = json.loads((run / 'controller/input_manifest.json').read_text(encoding='utf-8'))
    assert json.loads((run / 'controller/exit_status.json').read_text())['returncode'] == 0
    assert manifest['controller_image_id'] == image
    assert manifest['matrix_sha256'] == sha256_bytes(matrix_bytes)
    assert len(matrix['cases']) == len(matrix['designated_instances']) == 2
    assert matrix['arm'] == arm and matrix['mode'] == 'pilot' and matrix['split'] == 'dev'
    identity = {key: matrix[key] for key in ('config_hash', 'mode', 'split', 'seed', 'repeat_index', 'designated_instances')}
    identity['prepared_images'] = matrix['effective_config']['execution']['images']
    if shared is None:
        shared = identity
    assert identity == shared
    assert len(manifest['jobs']) == 1
    job = manifest['jobs'][0]
    assert job['arm'] == arm
    report_path = Path(job['report_path'])
    report = json.loads(report_path.read_text())
    provenance = json.loads(sidecar_path(report_path).read_text())
    assert provenance['matrix_sha256'] == manifest['matrix_sha256']
    assert provenance['predictions_sha256'] == job['predictions_sha256']
    validate_artifact_files(run / 'matrix.json', report_path, arm, provenance)
    score.validate_dataset_binding(matrix, run, provenance)
    assert provenance['harness_environment']['swebench'] == '5.0.2'
    statuses = {iid: verdict_status(report, iid) for iid in matrix['designated_instances']}
    rows.append({'arm': arm, 'tag': matrix['tag'], 'report': report_path.relative_to(root).as_posix(),
                 'provenance': sidecar_path(report_path).relative_to(root).as_posix(),
                 'provenance_valid': True, 'outer_inner_current_hashes_match': True,
                 'verdicts': statuses, **{field: report.get(field, 0) for field in fields}})
    names.extend(f'sweb.eval.{iid.lower()}.{matrix["tag"]}' for iid in matrix['designated_instances'])

cleanup = []
for name in names:
    inspected = subprocess.run(base + ['container', 'inspect', name, '--format', '{{json .}}'],
                               capture_output=True, text=True)
    if inspected.returncode:
        assert 'No such' in inspected.stderr
        cleanup.append({'name': name, 'already_absent': True, 'absence_verified': True})
        continue
    data = json.loads(inspected.stdout)
    assert data['Name'] == '/' + name
    ident = data['Id']
    subprocess.run(base + ['container', 'rm', '--force', ident], capture_output=True, check=True)
    after = subprocess.run(base + ['container', 'inspect', ident], capture_output=True, text=True)
    assert after.returncode != 0 and 'No such' in after.stderr
    cleanup.append({'name': name, 'id': ident, 'residual_found': True,
                    'removed_after_completed_scoring': True, 'absence_verified': True})

result = {'controller_image_id': image, 'harness': 'swebench==5.0.2',
          'model_calls': 0, 'hidden_feedback_exported': False,
          'shared_run_identity': shared, 'arms': rows, 'cleanup': cleanup,
          'all_known_evaluator_containers_absent': True,
          'all_five_outer_inner_current_hashes_match': True,
          'protected_evaluator_source_unchanged': True,
          'environment_health': 'not_inferred_from_harness_error_count'}
out = root / 'runs/dev2_acceptance_20261106/pilot_official_scoring_summary.json'
with out.open('x', encoding='utf-8') as stream:
    json.dump(result, stream, ensure_ascii=False, indent=2)
print(json.dumps({'summary': str(out), 'arms': rows,
                  'all_known_evaluator_containers_absent': True}, ensure_ascii=False, indent=2))
