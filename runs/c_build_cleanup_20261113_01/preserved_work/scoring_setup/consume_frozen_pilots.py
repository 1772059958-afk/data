"""Sequentially consume authorized frozen pilot tags; never print verdicts."""
import importlib.util
import json
from pathlib import Path
import sys
import time

root = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('pilot_scoring', root / 'scripts/score_run.py')
score = importlib.util.module_from_spec(spec)
spec.loader.exec_module(score)
image = 'sha256:1f43c83b3d3c631d37af54a19828df269accd045a22c62c0aab5b2bfa713726f'
progress = {'controller_image_id': image, 'model_calls': 0, 'verdicts_exported': False,
            'completed': ['A'], 'reports': {}}
out = root / 'runs/dev2_acceptance_20261106/environment/scoring/pilot_scoring_progress.json'
def save():
    temp = out.with_suffix('.tmp')
    temp.write_text(json.dumps(progress, indent=2), encoding='utf-8')
    temp.replace(out)

a = root / 'runs/dev2_pilot_A_20261106_01'
assert json.loads((a / 'controller/exit_status.json').read_text())['returncode'] == 0
progress['reports']['A'] = [str(p.relative_to(root)) for p in (a / 'scoring/A').glob('*.json')
                            if not p.name.endswith('.provenance.json') and p.name != 'input_manifest.json']
save()
for arm in ('B', 'C', 'D', 'E'):
    run = root / f'runs/dev2_pilot_{arm}_20261106_01'
    print(json.dumps({'arm': arm, 'status': 'waiting_for_freeze', 'verdicts_exported': False}), flush=True)
    deadline = time.monotonic() + 3600
    while True:
        matrix_path, predictions = run / 'matrix.json', run / f'predictions_{arm}.jsonl'
        if matrix_path.exists() and predictions.exists():
            matrix = json.loads(matrix_path.read_text(encoding='utf-8'))
            lines = [line for line in predictions.read_text(encoding='utf-8').splitlines() if line.strip()]
            if (matrix.get('arm') == arm and matrix.get('mode') == 'pilot'
                    and len(matrix.get('cases', [])) == 2 and len(lines) == 2
                    and all(case.get('status') != 'running' for case in matrix['cases'])):
                _, _, jobs = score.scoring_plan(run, max_workers=1)
                assert len(jobs) == 1 and jobs[0]['arm'] == arm
                break
        if time.monotonic() >= deadline:
            raise TimeoutError('authorized pilot tag did not freeze: ' + arm)
        time.sleep(5)
    progress['running'] = arm
    save()
    print(json.dumps({'arm': arm, 'status': 'scoring_started', 'model_calls': 0}), flush=True)
    reports = score.execute_controller(run, image, max_workers=1)
    progress['completed'].append(arm)
    progress['reports'][arm] = [str(Path(path).relative_to(root)) for path in reports]
    progress.pop('running', None)
    save()
    print(json.dumps({'arm': arm, 'status': 'scoring_completed', 'reports': progress['reports'][arm],
                      'provenance_valid': True, 'verdicts_exported': False}), flush=True)
