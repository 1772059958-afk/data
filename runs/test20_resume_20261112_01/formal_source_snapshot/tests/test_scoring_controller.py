"""Linux scoring dispatch and evaluator input binding; no Docker or network."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import types
from unittest.mock import patch

from swe_repair.evaluation import build_provenance, sidecar_path

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


fixture = load('controller_fixtures', 'tests/test_scoring_identity.py')
scoring = load('controller_scoring', 'scripts/score_run.py')
cli_prepare = load('controller_cli_prepare', 'docker/scoring/prepare_cli.py')


def temporary():
    return tempfile.TemporaryDirectory(prefix='controller_offline_', dir=ROOT / 'runs')


def test_controller_plan_is_offline_and_excludes_workspace_secrets():
    with temporary() as tmp:
        path = Path(tmp)
        fixture.materialize(path)
        with patch.object(scoring.subprocess, 'run', side_effect=AssertionError('planning cannot dispatch')):
            plan = scoring.controller_plan(path, 'local/controller:test', max_workers=1)
        assert plan['execute'] is False and plan['model_calls'] == 0
        command = plan['command']
        mounts = [command[i + 1] for i, value in enumerate(command) if value == '--mount']
        assert command[command.index('--network') + 1] == 'none'
        assert any('src=/var/run/docker.sock' in value for value in mounts)
        assert any('dst=/workspace/src,readonly' in value for value in mounts)
        assert any('dst=/workspace/data/harness,readonly' in value for value in mounts)
        assert not any('.env' in value or '.venv' in value for value in command)
        assert not any('DEEPSEEK' in value for value in command)
        assert not any(value.startswith(f'type=bind,src={ROOT},') for value in mounts)
        assert not (path / 'controller').exists() and not (path / 'scoring').exists()


def test_controller_cli_defaults_to_plan_without_invoking_docker():
    with temporary() as tmp:
        path = Path(tmp)
        fixture.materialize(path)
        output = io.StringIO()
        with contextlib.redirect_stdout(output), \
             patch.object(scoring, 'execute_controller', side_effect=AssertionError('must plan')):
            assert scoring.main([str(path), '--controller-image', 'local/controller:test']) == 0
        assert json.loads(output.getvalue())['execute'] is False


def test_controller_pins_actual_image_and_verifies_report_after_fake_dispatch():
    with temporary() as tmp:
        path = Path(tmp)
        matrix, report, _ = fixture.materialize(path)
        calls = []
        digest = 'sha256:' + '1' * 64
        def fake(command, **kwargs):
            calls.append(command)
            if 'inspect' in command:
                return types.SimpleNamespace(returncode=0, stdout=digest + '\n')
            assert digest in command and 'local/controller:test' not in command
            assert kwargs['stderr'] == scoring.subprocess.STDOUT
            assert kwargs['stdout'].name == str(path / 'controller/console.log')
            directory = path / 'scoring/D'
            directory.mkdir(parents=True)
            report_path = directory / 'identity_dev-D.identity_dev.json'
            report_path.write_text(json.dumps(report), encoding='utf-8')
            matrix_bytes = (path / 'matrix.json').read_bytes()
            provenance = build_provenance(matrix, 'D', (path / 'predictions_D.jsonl').read_bytes(), report,
                matrix_bytes=matrix_bytes, report_bytes=report_path.read_bytes())
            provenance['harness_environment'] = {'python': '3.11', 'swebench': '5.0.2'}
            descriptor = scoring.dataset_descriptor(matrix, path)
            descriptor['effective_dataset_sha256'] = descriptor['source_sha256']
            provenance['evaluation_dataset'] = descriptor
            sidecar_path(report_path).write_text(json.dumps(provenance), encoding='utf-8')
            return types.SimpleNamespace(returncode=0)
        reports = scoring.execute_controller(path, 'local/controller:test', runner=fake)
        assert len(calls) == 2 and len(reports) == 1
        manifest = json.loads((path / 'controller/input_manifest.json').read_text(encoding='utf-8'))
        assert manifest['controller_image_id'] == digest
        try: scoring.execute_controller(path, 'local/controller:test', runner=fake)
        except FileExistsError: pass
        else: raise AssertionError('existing scoring was reused')
        assert len(calls) == 2


def test_controller_rejects_replaced_inputs_even_with_valid_inner_sidecar():
    for replaced in ('matrix.json', 'predictions_D.jsonl'):
        with temporary() as tmp:
            path = Path(tmp)
            matrix, report, _ = fixture.materialize(path)
            def fake(command, **kwargs):
                if 'inspect' in command:
                    return types.SimpleNamespace(returncode=0, stdout='sha256:' + '1' * 64)
                selected = path / replaced
                selected.write_bytes(selected.read_bytes() + b'\n')
                directory = path / 'scoring/D'
                directory.mkdir(parents=True)
                report_path = directory / 'identity_dev-D.identity_dev.json'
                report_path.write_text(json.dumps(report), encoding='utf-8')
                provenance = build_provenance(matrix, 'D', (path / 'predictions_D.jsonl').read_bytes(), report,
                    matrix_bytes=(path / 'matrix.json').read_bytes(), report_bytes=report_path.read_bytes())
                provenance['harness_environment'] = {'python': '3.11', 'swebench': '5.0.2'}
                descriptor = scoring.dataset_descriptor(matrix, path)
                descriptor['effective_dataset_sha256'] = descriptor['source_sha256']
                provenance['evaluation_dataset'] = descriptor
                sidecar_path(report_path).write_text(json.dumps(provenance), encoding='utf-8')
                return types.SimpleNamespace(returncode=0)
            try:
                scoring.execute_controller(path, 'local/controller:test', runner=fake)
            except ValueError as exc:
                assert 'outer frozen plan' in str(exc)
            else:
                raise AssertionError('controller accepted a replacement despite outer frozen hashes')


def test_prepared_image_evaluator_projection_never_mutates_protected_dataset():
    with temporary() as tmp:
        path = Path(tmp)
        matrix, _, _ = fixture.materialize(path)
        iid = matrix['designated_instances'][0]
        ref = 'sha256:' + '2' * 64
        matrix['effective_config'] = {'execution': {'images': {iid: ref}}}
        descriptor = scoring.dataset_descriptor(matrix, path)
        original = Path(descriptor['source']).read_bytes()
        rows = [{'instance_id': iid, 'image': 'upstream/image', 'patch': 'fake-hidden-gold',
                 'test_patch': 'fake-hidden-tests', 'eval_script': 'fake-evaluation-script'}]
        arrow, parquet = types.ModuleType('pyarrow'), types.ModuleType('pyarrow.parquet')
        def read_table(source, *, filters):
            assert source == descriptor['source']
            assert filters == [('instance_id', 'in', [iid])]
            return types.SimpleNamespace(to_pylist=lambda: copy.deepcopy(rows))
        parquet.read_table = read_table
        arrow.parquet = parquet
        (path / 'scoring').mkdir()
        with patch.dict(sys.modules, {'pyarrow': arrow, 'pyarrow.parquet': parquet}):
            prepared = scoring.prepare_evaluator_dataset(matrix, descriptor)
        saved = json.loads(Path(descriptor['dataset_path']).read_text(encoding='utf-8'))
        assert saved[0]['image'] == ref and saved[0]['test_patch'] == 'fake-hidden-tests'
        assert rows[0]['image'] == 'upstream/image'
        assert Path(descriptor['source']).read_bytes() == original
        scoring.validate_evaluator_dataset(prepared)
        scoring.validate_dataset_binding(matrix, path, {'evaluation_dataset': prepared})
        Path(descriptor['dataset_path']).write_text('tampered', encoding='utf-8')
        try: scoring.validate_evaluator_dataset(prepared)
        except ValueError: pass
        else: raise AssertionError('changed hidden evaluator input was accepted')


def test_mutable_prepared_images_are_refused_before_dispatch():
    with temporary() as tmp:
        path = Path(tmp)
        matrix, _, _ = fixture.materialize(path)
        matrix['effective_config'] = {'execution': {'images': {matrix['designated_instances'][0]: 'mutable:latest'}}}
        try: scoring.dataset_descriptor(matrix, path)
        except ValueError: pass
        else: raise AssertionError('mutable prepared image accepted')


def test_incomplete_generation_cannot_start_an_evaluator():
    with temporary() as tmp:
        path = Path(tmp)
        matrix, _, _ = fixture.materialize(path)
        matrix['designated_instances'].append('not_frozen')
        (path / 'matrix.json').write_text(json.dumps(matrix), encoding='utf-8')
        with patch.object(scoring.subprocess, 'run', side_effect=AssertionError('cannot dispatch')):
            try: scoring.controller_plan(path, 'local/controller:test')
            except ValueError as exc: assert 'not frozen' in str(exc)
            else: raise AssertionError('incomplete generation was evaluated')


def test_controller_failure_preserves_exit_and_never_emits_false_verdict():
    with temporary() as tmp:
        path = Path(tmp)
        fixture.materialize(path)
        def fake(command, **kwargs):
            return types.SimpleNamespace(returncode=0, stdout='sha256:' + '3' * 64) if 'inspect' in command else types.SimpleNamespace(returncode=7)
        try: scoring.execute_controller(path, 'local/controller:test', runner=fake)
        except RuntimeError: pass
        else: raise AssertionError('controller failure accepted')
        assert json.loads((path / 'controller/exit_status.json').read_text())['returncode'] == 7
        assert not list(path.rglob('*.provenance.json'))


def test_cli_preparation_defaults_to_download_free_plan():
    output = io.StringIO()
    requests = types.ModuleType('requests')
    requests.get = lambda *a, **kw: (_ for _ in ()).throw(AssertionError('planning cannot download'))
    with patch.dict(sys.modules, {'requests': requests}), contextlib.redirect_stdout(output):
        assert cli_prepare.main([]) == 0
    plan = json.loads(output.getvalue())
    assert plan['execute'] is False and plan['model_calls'] == 0
    assert plan['url'].startswith('https://download.docker.com/')


def test_cli_archive_hash_is_checked_before_parsing():
    with patch.object(cli_prepare.tarfile, 'open', side_effect=AssertionError('unverified archive parsed')):
        try:
            cli_prepare.extract_cli(b'tampered official archive')
        except ValueError as exc:
            assert 'SHA256 mismatch' in str(exc)
        else:
            raise AssertionError('tampered upstream package accepted')
