"""Plan independent scoring; --execute runs the harness and binds its reports.

No model is imported or called. Execution still requires authorized container
work. Each scoring directory is new, so stale harness reports cannot be reused.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from swe_repair.evaluation import (ARMS, run_identity, prediction_manifest, build_provenance,
                                   sha256_bytes, sidecar_path, validate_artifact_files)


def scoring_plan(run_dir: Path, *, max_workers: int = 3) -> tuple[dict, bytes, list[dict]]:
    run_dir = run_dir.resolve()
    if not run_dir.is_relative_to(ROOT / 'runs') or max_workers < 1:
        raise ValueError('scoring needs a run directory under runs/ and positive workers')
    matrix_path = run_dir / 'matrix.json'
    matrix_bytes = matrix_path.read_bytes()
    matrix = json.loads(matrix_bytes)
    identity = run_identity(matrix)
    if 'cases' not in matrix:
        raise ValueError('historical runs cannot enter current scoring')
    jobs = []
    for path in sorted(run_dir.glob('predictions_*.jsonl')):
        arm = path.stem.removeprefix('predictions_')
        if arm not in ARMS:
            raise ValueError('unknown prediction file: ' + path.name)
        predictions = path.read_bytes()
        manifest = prediction_manifest(matrix, arm, predictions)
        directory = run_dir / 'scoring' / arm
        report_path = directory / f"{identity['tag']}-{arm}.{identity['tag']}.json"
        command = [sys.executable, '-m', 'swebench.harness.run_evaluation',
                   '--dataset_name', str(ROOT / 'data/harness'), '--split', matrix['split'],
                   '--predictions_path', str(path), '--instance_ids', *matrix['designated_instances'],
                   '--run_id', identity['tag'], '--max_workers', str(max_workers),
                   '--report_dir', str(directory)]
        jobs.append({'arm': arm, **manifest, 'report_path': str(report_path),
                     'command': command, 'directory': str(directory)})
    if not jobs:
        raise ValueError('no frozen predictions files in run directory')
    return matrix, matrix_bytes, jobs


def execute_scoring(run_dir: Path, *, max_workers: int = 3, runner=None) -> list[str]:
    """Freeze inputs BEFORE dispatch and emit sidecars only for successful jobs."""
    runner = runner or subprocess.run
    matrix, matrix_bytes, jobs = scoring_plan(run_dir, max_workers=max_workers)
    run_dir = run_dir.resolve()
    scoring_dir = run_dir / 'scoring'
    scoring_dir.mkdir(exist_ok=False)
    plan = {'kind': 'independent_scoring', 'identity': run_identity(matrix),
            'matrix_sha256': sha256_bytes(matrix_bytes), 'jobs': jobs}
    (scoring_dir / 'scoring_plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
    reports = []
    for job in jobs:
        directory, report_path = Path(job['directory']), Path(job['report_path'])
        directory.mkdir(exist_ok=False)
        predictions_path = run_dir / job['predictions_file']
        predictions = predictions_path.read_bytes()
        if (sha256_bytes((run_dir / 'matrix.json').read_bytes()) != plan['matrix_sha256']
                or sha256_bytes(predictions) != job['predictions_sha256']):
            raise ValueError('scoring inputs changed before dispatch')
        (directory / 'input_manifest.json').write_text(
            json.dumps({'identity': plan['identity'], 'matrix_sha256': plan['matrix_sha256'], **job},
                       ensure_ascii=False, indent=2), encoding='utf-8')
        completed = runner(job['command'], cwd=ROOT)
        if completed.returncode:
            raise RuntimeError(f"{job['arm']}: harness failed with exit {completed.returncode}; no verdict sidecar emitted")
        if ((run_dir / 'matrix.json').read_bytes() != matrix_bytes
                or predictions_path.read_bytes() != predictions):
            raise ValueError('frozen matrix/predictions changed during scoring')
        report_bytes = report_path.read_bytes()  # Never guess among unrelated JSONs.
        report = json.loads(report_bytes)
        provenance = build_provenance(matrix, job['arm'], predictions, report,
                                      matrix_bytes=matrix_bytes, report_bytes=report_bytes)
        try:
            harness_version = importlib.metadata.version('swebench')
        except importlib.metadata.PackageNotFoundError:
            harness_version = None
        provenance['harness_environment'] = {'python': platform.python_version(), 'swebench': harness_version}
        provenance['harness_command'] = job['command']
        with sidecar_path(report_path).open('x', encoding='utf-8') as stream:
            json.dump(provenance, stream, ensure_ascii=False, indent=2)
        validate_artifact_files(run_dir / 'matrix.json', report_path, job['arm'], provenance)
        reports.append(str(report_path))
    return reports


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_dir', type=Path)
    parser.add_argument('--max-workers', type=int, default=3)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.execute:
            output = execute_scoring(args.run_dir, max_workers=args.max_workers)
        else:
            matrix, matrix_bytes, jobs = scoring_plan(args.run_dir, max_workers=args.max_workers)
            output = {'execute': False, 'model_calls': 0, 'identity': run_identity(matrix),
                      'matrix_sha256': sha256_bytes(matrix_bytes), 'jobs': jobs}
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    raise SystemExit(main())
