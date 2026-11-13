"""The real driver loop stops a paid batch after an observed identity violation."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('identity_batch_runner', ROOT / 'scripts/run_cf.py')
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


def _assert_driver_stops(marker, marker_code, stop_reason):
    """No real transport, parquet parser, Docker or credential access is used."""
    raw = json.loads((ROOT / 'configs/proposal_v1.json').read_text(encoding='utf-8'))
    raw['execution'].update(total_cny=1, credential_source='project_dotenv')
    raw['execution'].pop('batch_ledger', None)
    raw['execution'].pop('docker_context', None)
    ids = ['offline__repo-1', 'offline__repo-2']
    rows = [{'instance_id': iid, 'repo': 'offline/repo', 'base_commit': 'offline-base',
             'problem_statement': 'Synthetic public input.'} for iid in ids]
    table = SimpleNamespace(to_pylist=lambda: rows)
    arrow = ModuleType('pyarrow')
    arrow.__path__ = []
    parquet = ModuleType('pyarrow.parquet')
    parquet.read_table = lambda path: table
    arrow.parquet = parquet
    clients, seen = [], []
    diff = '--- a/pkg.py\n+++ b/pkg.py\n@@ -1 +1 @@\n-old\n+new\n'

    class FakeClient:
        def __init__(self, config, *, guard, **kwargs):
            self.config, self._guard = config, guard
            self._identity_violation = None
            self._api_breakpoint = None
            self.api_calls = 0
            clients.append(self)

        def chat(self, *args, **kwargs):
            self.api_calls += 1
            raise AssertionError('this driver regression must never invoke model transport')

    def fake_case(row, client, passed_raw, **kwargs):
        seen.append(row['instance_id'])
        # Emulate the already-accounted successful HTTP response that failed
        # the identity check. The real driver must retain it before stopping.
        client._guard.book(SimpleNamespace(cost_cny=.01, prompt_tokens=10, output_tokens=20))
        setattr(client, marker, marker_code)
        kwargs['checkpoint']({'event': 'synthetic' + marker, 'cost_cny': .01})
        return {'instance_id': row['instance_id'], 'status': 'generation_error',
                'stages': {'prefix': {'status': 'generation_error', 'cost_cny': .01,
                                      'calls': [{'cost_cny': .01, 'prompt_tokens': 10,
                                                 'output_tokens': 20}]}},
                'submitted_patch': diff}

    with tempfile.TemporaryDirectory(dir=ROOT / 'runs') as folder:
        workspace = Path(folder)
        data = workspace / 'data/harness'
        data.mkdir(parents=True)
        fake_parquet = data / 'offline.parquet'
        fake_parquet.write_bytes(b'offline parquet parser fixture')
        manifest = {'splits': {'dev': {'local_file': 'data/harness/offline.parquet',
                                       'sha256': hashlib.sha256(fake_parquet.read_bytes()).hexdigest()}}}
        (data / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        out = workspace / 'runs/identity_stop'
        plan = {'output_directory': str(out), 'tag': 'offline_identity_stop',
                'mode': 'formal', 'arm': 'A', 'split': 'dev', 'calibration': False,
                'seed': 20261111, 'repeat_index': 0, 'designated_instances': ids,
                'config_hash': 'offline-identity-config', 'execute': True,
                'live_authorized': False}
        with patch.object(RUNNER, 'ROOT', workspace), \
             patch.dict(sys.modules, {'pyarrow': arrow, 'pyarrow.parquet': parquet}), \
             patch('swe_repair.llm.load_scoped_api_key', return_value='offline-fake-key') as credential, \
             patch('swe_repair.llm.DeepSeekClient', FakeClient), \
             patch('swe_repair.experiment.run_case', fake_case), \
             contextlib.redirect_stdout(io.StringIO()):
            code = RUNNER.execute(raw, plan)
        matrix = json.loads((out / 'matrix.json').read_text(encoding='utf-8'))
        predictions = [json.loads(line) for line in (out / 'predictions_A.jsonl').read_text(encoding='utf-8').splitlines()]
        assert code == 2 and seen == ids[:1]
        assert len(clients) == 1 and clients[0].api_calls == 0
        assert credential.call_count == 1  # Replaced loader; the actual .env is never read.
        assert matrix['designated_instances'] == ids
        assert len(matrix['cases']) == 1 and matrix['cases'][0]['instance_id'] == ids[0]
        assert matrix['batch_stopped'] == stop_reason
        if marker_code is not None:
            assert matrix[marker.removeprefix('_')] == marker_code
        assert matrix['new_generation_cost_cny'] == matrix['cumulative_batch_cost_cny'] == .01
        assert matrix['cases'][0]['stages']['prefix']['calls'][0]['output_tokens'] == 20
        assert len(predictions) == 1
        assert predictions[0]['instance_id'] == ids[0] and predictions[0]['model_patch'] == diff
        assert 'synthetic' + marker in (out / 'events.jsonl').read_text(encoding='utf-8')


def test_driver_stops_after_first_identity_violation_and_retains_predictions_and_paid_usage():
    _assert_driver_stops('_identity_violation', 'system_fingerprint_mismatch', 'served_model_identity_violation')


def test_driver_stops_after_first_account_breakpoint_and_retains_predictions_and_accounting():
    _assert_driver_stops('_api_breakpoint', 'api_http_402', 'api_access_or_quota_breakpoint')


def test_formal_interrupted_prefix_stops_before_another_case_or_cross_arm_regeneration():
    _assert_driver_stops('_api_breakpoint', None, 'formal_prefix_failed_no_cross_arm_regeneration')
