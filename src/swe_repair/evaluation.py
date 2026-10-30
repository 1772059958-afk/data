"""Bind independent verdicts to the exact frozen run and prediction artifacts.

This module is offline. A sidecar is produced around a harness invocation; it
is not an assertion that the harness or a model was run by this module.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from .cf import VERDICT_FIELDS

SCHEMA = 'swe-repair-evaluation-v1'
ARMS = frozenset(('A', 'B', 'C', 'D', 'E', 'FIXED', 'ESC', 'PREFIX'))
IDENTITY_FIELDS = ('tag', 'config_hash', 'mode', 'split', 'seed', 'repeat_index')


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def content_hash(payload: Any) -> str:
    return sha256_bytes(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                  separators=(',', ':'), allow_nan=False).encode('utf-8'))


def patch_hash(diff: str) -> str:
    """Exact UTF-8 patch bytes, without normalizing candidate identity."""
    if not isinstance(diff, str):
        raise ValueError('frozen prediction patch must be a string')
    return sha256_bytes(diff.encode('utf-8'))


def run_identity(matrix: Mapping[str, Any]) -> dict[str, Any]:
    missing = [field for field in IDENTITY_FIELDS if matrix.get(field) is None]
    if missing:
        raise ValueError('evaluation requires persisted run identity: ' + ', '.join(missing))
    if matrix['mode'] not in ('formal', 'diagnostic') or matrix['split'] not in ('dev', 'test'):
        raise ValueError('invalid evaluated run mode/split')
    if (not isinstance(matrix['seed'], int) or isinstance(matrix['seed'], bool)
            or not isinstance(matrix['repeat_index'], int) or isinstance(matrix['repeat_index'], bool)
            or matrix['repeat_index'] < 0):
        raise ValueError('evaluation requires integer seed and nonnegative repeat index')
    if not all(isinstance(matrix[x], str) and matrix[x] for x in ('tag', 'config_hash')):
        raise ValueError('evaluation requires nonempty tag and config hash')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,96}', matrix['tag']):
        raise ValueError('invalid scoring run tag')
    return {field: matrix[field] for field in IDENTITY_FIELDS}


def frozen_predictions(matrix: Mapping[str, Any], arm: str) -> dict[str, str]:
    """Recover only frozen output patches; never reconstruct generation inputs."""
    if arm not in ARMS:
        raise ValueError('unknown evaluation arm')
    designated = matrix.get('designated_instances')
    if (not isinstance(designated, list) or not designated
            or len(set(designated)) != len(designated)):
        raise ValueError('evaluation requires a unique designated instance list')
    result, seen = {}, set()
    for case in matrix.get('cases', []):
        iid = case['instance_id']
        if iid not in designated or iid in seen:
            raise ValueError('duplicate or out-of-population frozen prediction')
        seen.add(iid)
        for field in ('mode', 'config_hash', 'seed', 'repeat_index'):
            if field in case and case[field] != matrix.get(field):
                raise ValueError('case and run identity differ: ' + field)
        if 'run_id' in case and case['run_id'] != matrix.get('tag'):
            raise ValueError('case and run identity differ: run_id')
        stages = case.get('stages', {})
        mode = case.get('mode', matrix.get('mode'))
        if mode == 'formal':
            if case.get('arm', matrix.get('arm')) != matrix.get('arm'):
                raise ValueError('formal case and run arm differ')
            if arm != case.get('arm', matrix.get('arm')):
                continue
            diff = case.get('submitted_patch', '')
        elif mode == 'diagnostic':
            if arm in ('A', 'C', 'D', 'E'):
                decision = case.get('decisions', {}).get(arm)
                if not decision:
                    continue
                route = decision.get('route') if isinstance(decision, Mapping) else decision
                if route not in ('stop', 'fixed', 'interactive'):
                    raise ValueError('invalid frozen prediction route')
                stage = 'prefix' if route == 'stop' else route
            else:
                stage = {'B': 'standalone', 'FIXED': 'fixed', 'ESC': 'interactive', 'PREFIX': 'prefix'}[arm]
                if stage not in stages:
                    continue
            diff = stages.get(stage, {}).get('patch', '')
        else:
            raise ValueError('only current formal/diagnostic matrices can be evaluated')
        if not isinstance(diff, str):
            raise ValueError('invalid frozen patch')
        result[iid] = diff
    return result


def prediction_manifest(matrix: Mapping[str, Any], arm: str, payload: bytes) -> dict[str, Any]:
    identity = run_identity(matrix)
    expected = frozen_predictions(matrix, arm)
    model_name = f"{identity['tag']}-{arm}"
    actual = {}
    for line in payload.decode('utf-8').splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        iid = row['instance_id']
        if iid in actual or row.get('model_name_or_path') != model_name:
            raise ValueError('duplicate prediction or wrong model/arm label')
        actual[iid] = row.get('model_patch')
    if not actual or actual != expected:
        raise ValueError('predictions differ from the frozen matrix patches')
    return {'predictions_file': f'predictions_{arm}.jsonl',
            'predictions_sha256': sha256_bytes(payload),
            'model_name_or_path': model_name,
            'prediction_patch_sha256': {iid: patch_hash(diff) for iid, diff in sorted(actual.items())}}


def build_provenance(matrix: Mapping[str, Any], arm: str, predictions: bytes,
                     report: Mapping[str, Any], *, matrix_bytes: bytes,
                     report_bytes: bytes) -> dict[str, Any]:
    """Called after the harness returns, using bytes frozen before it started."""
    if json.loads(matrix_bytes) != matrix or json.loads(report_bytes) != report:
        raise ValueError('artifact bytes do not match parsed matrix/report')
    result = {'schema_version': SCHEMA, 'identity': run_identity(matrix), 'arm': arm,
              'matrix_sha256': sha256_bytes(matrix_bytes), 'matrix_content_sha256': content_hash(matrix),
              'report_sha256': sha256_bytes(report_bytes), 'report_content_sha256': content_hash(report),
              **prediction_manifest(matrix, arm, predictions)}
    validate_provenance(matrix, arm, report, result)
    return result


def validate_provenance(matrix: Mapping[str, Any], arm: str, report: Mapping[str, Any],
                        provenance: Mapping[str, Any] | None) -> None:
    """Mandatory even for in-memory analysis; raw verdict dictionaries are unsafe."""
    if not isinstance(provenance, Mapping) or provenance.get('schema_version') != SCHEMA:
        raise ValueError(f'{arm}: independent report requires a scoring provenance sidecar')
    identity = run_identity(matrix)
    if provenance.get('identity') != identity or provenance.get('arm') != arm:
        raise ValueError(f'{arm}: scoring run identity mismatch')
    if (provenance.get('matrix_content_sha256') != content_hash(matrix)
            or provenance.get('report_content_sha256') != content_hash(report)):
        raise ValueError(f'{arm}: matrix/report content changed after scoring')
    expected = {iid: patch_hash(diff) for iid, diff in frozen_predictions(matrix, arm).items()}
    if not expected or provenance.get('prediction_patch_sha256') != expected:
        raise ValueError(f'{arm}: evaluated patches do not match frozen predictions')
    if (provenance.get('model_name_or_path') != f"{identity['tag']}-{arm}"
            or provenance.get('predictions_file') != f'predictions_{arm}.jsonl'):
        raise ValueError(f'{arm}: prediction label mismatch')
    for name in ('matrix_sha256', 'report_sha256', 'predictions_sha256'):
        value = provenance.get(name)
        if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError(f'{arm}: missing or invalid {name}')
    # Standard harness reports need not duplicate these fields. If present,
    # contradictory metadata must not be waved through by a matching sidecar.
    claims = {'run_id': identity['tag'], 'tag': identity['tag'], 'config_hash': identity['config_hash'],
              'split': identity['split'], 'arm': arm, 'seed': identity['seed'],
              'repeat_index': identity['repeat_index'], 'model_name_or_path': provenance['model_name_or_path'],
              'predictions_sha256': provenance['predictions_sha256']}
    for field, expected_value in claims.items():
        if field in report and report[field] != expected_value:
            raise ValueError(f'{arm}: report claims a different {field}')
    for field in VERDICT_FIELDS:
        values = report.get(field, []) or []
        if not isinstance(values, list) or any(not isinstance(i, str) or i not in expected for i in values):
            raise ValueError(f'{arm}: report contains a verdict outside submitted predictions')


def sidecar_path(report_path: Path) -> Path:
    return report_path.with_name(report_path.name + '.provenance.json')


def validate_artifact_files(matrix_path: Path, report_path: Path, arm: str,
                            provenance: Mapping[str, Any]) -> None:
    """CLI also checks exact file bytes, including source predictions on disk."""
    matrix_bytes, report_bytes = matrix_path.read_bytes(), report_path.read_bytes()
    matrix, report = json.loads(matrix_bytes), json.loads(report_bytes)
    validate_provenance(matrix, arm, report, provenance)
    if (sha256_bytes(matrix_bytes) != provenance['matrix_sha256']
            or sha256_bytes(report_bytes) != provenance['report_sha256']):
        raise ValueError(f'{arm}: source matrix/report file bytes changed')
    predictions = (matrix_path.parent / f'predictions_{arm}.jsonl').read_bytes()
    manifest = prediction_manifest(matrix, arm, predictions)
    if any(provenance.get(field) != value for field, value in manifest.items()):
        raise ValueError(f'{arm}: source predictions changed after scoring')
