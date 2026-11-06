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
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from swe_repair.evaluation import (ARMS, run_identity, prediction_manifest, build_provenance,
                                   sha256_bytes, sidecar_path, validate_artifact_files)


def dataset_descriptor(matrix: dict, run_dir: Path) -> dict:
    """Describe evaluator input without reading hidden rows while only planning."""
    split = matrix['split']
    manifest_path = ROOT / 'data/harness/manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    source = ROOT / manifest['splits'][split]['local_file']
    payload = source.read_bytes()
    expected = manifest['splits'][split]['sha256'].lower()
    if sha256_bytes(payload) != expected:
        raise ValueError('protected evaluator parquet differs from its manifest')
    configured = matrix.get('effective_config', {}).get('execution', {}).get('images', {})
    images = {iid: configured[iid] for iid in matrix['designated_instances'] if iid in configured}
    if any(not isinstance(ref, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', ref) for ref in images.values()):
        raise ValueError('prepared scoring images must be immutable local image IDs')
    return {'source': str(source), 'source_sha256': expected,
            'source_manifest_sha256': sha256_bytes(manifest_path.read_bytes()),
            'prepared_images': images,
            'dataset_path': str(run_dir / 'scoring/evaluation_dataset.json') if images else str(ROOT / 'data/harness')}


def prepare_evaluator_dataset(matrix: dict, descriptor: dict) -> dict:
    """Evaluation-only projection after patch freeze, never returned to generation.

    Original parquet stays untouched. Only its image reference is replaced with
    the image fixed in the generation config; hidden evaluator fields stay on
    this side of the boundary.
    """
    result = dict(descriptor)
    if descriptor['prepared_images']:
        import pyarrow.parquet as pq
        wanted = set(matrix['designated_instances'])
        rows = pq.read_table(descriptor['source'],
                             filters=[('instance_id', 'in', sorted(wanted))]).to_pylist()
        if len(rows) != len(wanted) or {r['instance_id'] for r in rows} != wanted:
            raise ValueError('independent evaluator dataset is missing designated instances')
        for row in rows:
            if row['instance_id'] in descriptor['prepared_images']:
                row['image'] = descriptor['prepared_images'][row['instance_id']]
        payload = (json.dumps(rows, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        with Path(descriptor['dataset_path']).open('xb') as stream:
            stream.write(payload)
        result['effective_dataset_sha256'] = sha256_bytes(payload)
    else:
        result['effective_dataset_sha256'] = descriptor['source_sha256']
    return result


def validate_evaluator_dataset(descriptor: dict) -> None:
    if sha256_bytes(Path(descriptor['source']).read_bytes()) != descriptor['source_sha256']:
        raise ValueError('protected evaluator source changed during scoring')
    if descriptor['prepared_images']:
        if sha256_bytes(Path(descriptor['dataset_path']).read_bytes()) != descriptor['effective_dataset_sha256']:
            raise ValueError('independent evaluator input changed during scoring')


def validate_dataset_binding(matrix: dict, run_dir: Path, provenance: dict) -> None:
    """Portable host check: Linux/Windows path strings may differ, hashes may not."""
    expected = dataset_descriptor(matrix, run_dir)
    supplied = provenance.get('evaluation_dataset')
    if not isinstance(supplied, dict):
        raise ValueError('controller report is missing its evaluator dataset identity')
    for key in ('source_sha256', 'source_manifest_sha256', 'prepared_images'):
        if supplied.get(key) != expected[key]:
            raise ValueError('controller evaluator dataset identity mismatch: ' + key)
    if expected['prepared_images']:
        actual = sha256_bytes(Path(expected['dataset_path']).read_bytes())
    else:
        actual = expected['source_sha256']
    if supplied.get('effective_dataset_sha256') != actual:
        raise ValueError('controller evaluator dataset bytes changed')


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
    cases = matrix['cases']
    if (len(cases) != len(matrix['designated_instances'])
            or {case['instance_id'] for case in cases} != set(matrix['designated_instances'])
            or any(case.get('status') == 'running' for case in cases)):
        raise ValueError('generation has not frozen every designated instance')
    dataset = dataset_descriptor(matrix, run_dir)
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
                   '--dataset_name', dataset['dataset_path'], '--split', matrix['split'],
                   '--predictions_path', str(path), '--instance_ids', *matrix['designated_instances'],
                   '--run_id', identity['tag'], '--max_workers', str(max_workers),
                   '--report_dir', str(directory)]
        jobs.append({'arm': arm, **manifest, 'report_path': str(report_path),
                     'command': command, 'directory': str(directory), 'evaluation_dataset': dataset})
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
    dataset = prepare_evaluator_dataset(matrix, jobs[0]['evaluation_dataset'])
    plan = {'kind': 'independent_scoring', 'identity': run_identity(matrix),
            'matrix_sha256': sha256_bytes(matrix_bytes), 'jobs': jobs, 'evaluation_dataset': dataset}
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
            json.dumps({'identity': plan['identity'], 'matrix_sha256': plan['matrix_sha256'], **job,
                        'evaluation_dataset': dataset},
                       ensure_ascii=False, indent=2), encoding='utf-8')
        validate_evaluator_dataset(dataset)
        completed = runner(job['command'], cwd=ROOT)
        if completed.returncode:
            raise RuntimeError(f"{job['arm']}: harness failed with exit {completed.returncode}; no verdict sidecar emitted")
        if ((run_dir / 'matrix.json').read_bytes() != matrix_bytes
                or predictions_path.read_bytes() != predictions):
            raise ValueError('frozen matrix/predictions changed during scoring')
        validate_evaluator_dataset(dataset)
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
        provenance['evaluation_dataset'] = dataset
        with sidecar_path(report_path).open('x', encoding='utf-8') as stream:
            json.dump(provenance, stream, ensure_ascii=False, indent=2)
        validate_artifact_files(run_dir / 'matrix.json', report_path, job['arm'], provenance)
        reports.append(str(report_path))
    return reports


def _bind_mount(source: Path | str, destination: str, readonly: bool = False) -> list[str]:
    if ',' in str(source) or ',' in destination:
        raise ValueError('comma in Docker bind path is unsupported')
    value = f'type=bind,src={source},dst={destination}' + (',readonly' if readonly else '')
    return ['--mount', value]


def controller_plan(run_dir: Path, image: str, *, docker_context='desktop-linux', max_workers=1) -> dict:
    """Host wrapper plan: no socket access or evaluator row reads here."""
    matrix, matrix_bytes, jobs = scoring_plan(run_dir, max_workers=max_workers)
    run_dir = run_dir.resolve()
    container_dir = '/workspace/runs/' + run_dir.relative_to(ROOT / 'runs').as_posix()
    log_dir = run_dir / 'controller/logs'
    command = ['docker', '--context', docker_context, 'run', '--rm', '--network', 'none', '--workdir', '/workspace',
               '--env', 'DOCKER_HOST=unix:///var/run/docker.sock',
               '--env', 'HF_HUB_OFFLINE=1', '--env', 'HF_DATASETS_OFFLINE=1']
    for source, target in ((ROOT / 'src', '/workspace/src'), (ROOT / 'scripts', '/workspace/scripts'),
                           (ROOT / 'data/harness', '/workspace/data/harness')):
        command += _bind_mount(source, target, readonly=True)
    command += _bind_mount('/var/run/docker.sock', '/var/run/docker.sock')
    command += _bind_mount(run_dir, container_dir)
    command += _bind_mount(log_dir, '/workspace/logs')
    # Generation artifacts remain read-only even though the output run is writable.
    command += _bind_mount(run_dir / 'matrix.json', container_dir + '/matrix.json', readonly=True)
    for job in jobs:
        command += _bind_mount(run_dir / job['predictions_file'], container_dir + '/' + job['predictions_file'], readonly=True)
    image_argument = len(command)
    command += [image, '/workspace/scripts/score_run.py', container_dir, '--max-workers', str(max_workers), '--execute']
    return {'kind': 'linux_scoring_controller', 'model_calls': 0, 'execute': False,
            'identity': run_identity(matrix), 'matrix_sha256': sha256_bytes(matrix_bytes),
            'requested_controller_image': image, 'docker_context': docker_context,
            'command': command, 'container_image_argument': image_argument,
            'jobs': jobs, 'log_directory': str(log_dir)}


def execute_controller(run_dir: Path, image: str, *, docker_context='desktop-linux', max_workers=1, runner=None) -> list[str]:
    runner = runner or subprocess.run
    plan = controller_plan(run_dir, image, docker_context=docker_context, max_workers=max_workers)
    run_dir = run_dir.resolve()
    if (run_dir / 'scoring').exists():
        raise FileExistsError('scoring directory already exists; do not reuse evaluator caches')
    controller_dir = run_dir / 'controller'
    controller_dir.mkdir(exist_ok=False)
    Path(plan['log_directory']).mkdir()
    inspected = runner(['docker', '--context', docker_context, 'image', 'inspect', image, '--format', '{{.Id}}'],
                       capture_output=True, text=True, check=True)
    actual_image = inspected.stdout.strip()
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', actual_image):
        raise ValueError('controller actual image identity unavailable')
    plan.update(execute=True, controller_image_id=actual_image)
    plan['command'][plan['container_image_argument']] = actual_image
    (controller_dir / 'input_manifest.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
    # Keep hidden-test diagnostics on the evaluator side of the boundary. The
    # calling generation process receives paths/status, never harness stdout.
    with (controller_dir / 'console.log').open('xb') as console:
        result = runner(plan['command'], cwd=ROOT, stdout=console, stderr=subprocess.STDOUT)
    (controller_dir / 'exit_status.json').write_text(json.dumps({'returncode': result.returncode}), encoding='utf-8')
    if result.returncode:
        raise RuntimeError('Linux scoring controller failed; inspect its preserved logs')
    reports = []
    for job in plan['jobs']:
        report_path = Path(job['report_path'])
        provenance_path = sidecar_path(report_path)
        provenance = json.loads(provenance_path.read_text(encoding='utf-8'))
        if provenance.get('harness_environment', {}).get('swebench') != '5.0.2':
            raise ValueError('controller returned an unexpected official harness version')
        validate_artifact_files(run_dir / 'matrix.json', report_path, job['arm'], provenance)
        matrix = json.loads((run_dir / 'matrix.json').read_bytes())
        validate_dataset_binding(matrix, run_dir, provenance)
        reports.append(str(report_path))
    return reports


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_dir', type=Path)
    parser.add_argument('--max-workers', type=int, default=3)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--controller-image', help='run the official harness in an isolated Linux controller')
    parser.add_argument('--docker-context', default='desktop-linux')
    args = parser.parse_args(argv)
    try:
        if args.controller_image and args.execute:
            output = execute_controller(args.run_dir, args.controller_image,
                                        docker_context=args.docker_context, max_workers=args.max_workers)
        elif args.controller_image:
            output = controller_plan(args.run_dir, args.controller_image,
                                     docker_context=args.docker_context, max_workers=args.max_workers)
        elif args.execute:
            output = execute_scoring(args.run_dir, max_workers=args.max_workers)
        else:
            matrix, matrix_bytes, jobs = scoring_plan(args.run_dir, max_workers=args.max_workers)
            output = {'execute': False, 'model_calls': 0, 'identity': run_identity(matrix),
                      'matrix_sha256': sha256_bytes(matrix_bytes), 'jobs': jobs}
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    raise SystemExit(main())
