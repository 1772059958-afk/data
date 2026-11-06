"""Prefix-only stops before routing; live probes stay scoped and budgeted."""
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as NS
import tempfile
from unittest.mock import patch

from swe_repair import experiment as ex, llm
from swe_repair.evaluation import frozen_predictions

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


fixture = module('prefix_fixtures', 'tests/test_experiment.py')


def test_prefix_only_never_routes_or_runs_any_continuation():
    client = fixture.Client()
    raw = json.loads((ROOT / 'configs/proposal_v1.json').read_text(encoding='utf-8'))
    with patch.object(ex, 'run_prefix', fixture.prefix), \
         patch.object(ex, 'evaluate_all', side_effect=AssertionError('must not route')), \
         patch.object(ex, 'run_interactive', side_effect=AssertionError('must not interact')), \
         patch.object(ex, 'fixed_continuation', side_effect=AssertionError('must not continue')):
        result = ex.run_case(fixture.ROW, client, raw, mode='prefix', box_factory=fixture.Box)
    assert result['status'] == 'completed', result
    assert result['arm'] == 'PREFIX' and result['selected_route'] == 'prefix'
    assert set(result['stages']) == {'prefix'} and not result['decisions']
    assert result['submitted_patch'] == fixture.DIFF and len(client.requests) == 1
    assert result['policy_cost_cny'] == result['new_generation_cost_cny'] == .01
    assert result['prefix_snapshot']['budget_state']['consumed']['model_call'] == 1


def test_prefix_budget_stop_and_error_preserve_partial_patch_and_cost():
    for event, expected in [('prefix_stop', 'budget_exhausted'), ('prefix_error', 'generation_error')]:
        def stopped(*args, **kwargs):
            result = fixture.prefix(*args, **kwargs)
            result.trace.append({'step': event, 'reason': 'RuntimeError: synthetic interruption'})
            return result
        with patch.object(ex, 'run_prefix', stopped):
            result = ex.run_case(fixture.ROW, fixture.Client(), fixture.config(), mode='prefix', box_factory=fixture.Box)
        assert result['status'] == expected
        assert result['submitted_patch'] == fixture.DIFF and result['policy_cost_cny'] == .01
        assert result['stages']['prefix']['status'] == expected


def test_prefix_plan_does_not_need_calibrated_thresholds_or_live_imports():
    runner = fixture.runner()
    raw, plan = runner.load_plan(runner.parser().parse_args(['--mode', 'prefix']))
    assert plan['arm'] == 'PREFIX' and not plan['execute'] and not plan['live_authorized']
    assert raw['router']['localization_disagreement_threshold'] is None
    assert runner.predictions({'stages': {'prefix': {'patch': 'prefix patch'}}}, 'prefix', 'PREFIX') == {'PREFIX': 'prefix patch'}


def scoped_config():
    raw = json.loads((ROOT / 'configs/proposal_v1.json').read_text(encoding='utf-8'))
    raw['execution'].update(live_authorized=True, allowed_modes=['prefix'], allowed_splits=['dev'],
                            allowed_instances=['pvlib__pvlib-python-1707'], max_instances=1,
                            model_probe_authorized=True)
    raw['model']['model_version'] = 'observed-test-model'
    return raw


def test_live_prefix_scope_cannot_enable_diagnostic_formal_or_other_instances():
    runner = fixture.runner()
    with tempfile.TemporaryDirectory() as tmp:
        path, ids = Path(tmp) / 'config.json', Path(tmp) / 'ids.json'
        path.write_text(json.dumps(scoped_config()), encoding='utf-8')
        ids.write_text(json.dumps({'instance_ids': ['pvlib__pvlib-python-1707']}), encoding='utf-8')
        base = ['--config', str(path), '--instances-file', str(ids), '--execute', '--allow-paid']
        _, plan = runner.load_plan(runner.parser().parse_args(base + ['--mode', 'prefix']))
        assert plan['execute'] and plan['arm'] == 'PREFIX'
        for mode in ('formal', 'diagnostic'):
            try: runner.load_plan(runner.parser().parse_args(base + ['--mode', mode]))
            except ValueError as exc: assert 'authorized scope' in str(exc)
            else: raise AssertionError('scoped config enabled another experiment mode')
        ids.write_text(json.dumps({'instance_ids': ['pydicom__pydicom-1139']}), encoding='utf-8')
        try: runner.load_plan(runner.parser().parse_args(base + ['--mode', 'prefix']))
        except ValueError as exc: assert 'authorized scope' in str(exc)
        else: raise AssertionError('instance scope was bypassed')


def test_prefix_predictions_cannot_be_relabeled_as_a_formal_arm():
    matrix = {'mode': 'prefix', 'arm': 'PREFIX', 'designated_instances': ['x'],
              'cases': [{'instance_id': 'x', 'mode': 'prefix', 'arm': 'PREFIX', 'submitted_patch': 'diff'}]}
    assert frozen_predictions(matrix, 'PREFIX') == {'x': 'diff'}
    try: frozen_predictions(matrix, 'D')
    except ValueError: pass
    else: raise AssertionError('prefix was relabeled as arm D')


def test_probe_default_is_offline_and_live_requires_its_own_authorization():
    probe = module('probe_script', 'scripts/probe_model.py')
    with tempfile.TemporaryDirectory(dir=ROOT / 'work') as tmp:
        out = ROOT / 'runs' / Path(tmp).name
        args = probe.parser().parse_args(['--out', str(out)])
        _, plan = probe.load_plan(args)
        assert plan['execute'] is False and plan['model_calls_limit'] == 1 and not out.exists()
        args.execute, args.allow_paid = True, True
        try: probe.load_plan(args)
        except ValueError: pass
        else: raise AssertionError('probe accepted the unauthorized main config')


def test_probe_success_and_failure_book_actual_request_and_never_invent_model_identity():
    probe = module('probe_script_live', 'scripts/probe_model.py')
    original = llm.DeepSeekClient
    for reported in (True, False):
        posts = []
        class Session:
            def post(self, *args, **kwargs):
                posts.append(json.loads(kwargs['data']))
                payload = {'choices': [{'message': {'content': 'OK'}, 'finish_reason': 'stop'}],
                           'usage': {'prompt_tokens': 5, 'completion_tokens': 1}}
                if reported: payload['model'] = 'server-model-observed'
                return NS(status_code=200, json=lambda: payload)
        class Client(original):
            def __init__(self, config, **kwargs):
                super().__init__(config, api_key='fake-offline-only', guard=kwargs['guard'], session=Session())
        with tempfile.TemporaryDirectory() as tmp:
            plan = {'output_directory': str(Path(tmp) / 'probe'), 'kind': 'model_identity_probe',
                    'model': 'deepseek-flash', 'ceiling_cny': .05, 'max_output_tokens': 256}
            with patch.object(llm, 'DeepSeekClient', Client), patch.object(llm, 'load_scoped_api_key', return_value='fake-offline-only'):
                exit_code = probe.execute(scoped_config(), plan)
            result = json.loads((Path(plan['output_directory']) / 'result.json').read_text(encoding='utf-8'))
            assert len(posts) == 1 and posts[0]['max_tokens'] == 256
            assert result['budget']['consumed']['model_call'] == 1 and result['cost_cny'] > 0
            assert exit_code == (0 if reported else 1)
            assert ('observed_served_model' in result) is reported


def test_project_credential_source_never_falls_back_to_system_key():
    import os
    with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'fake-system'}):
        path = Path(tmp) / '.env'
        path.write_text('DEEPSEEK_API_KEY=fake-project\n', encoding='utf-8')
        assert llm.load_scoped_api_key({'credential_source': 'project_dotenv'}, tmp) == 'fake-project'
        path.write_text('DEEPSEEK_API_KEY=\n', encoding='utf-8')
        try: llm.load_scoped_api_key({'credential_source': 'project_dotenv'}, tmp)
        except llm.MissingApiKeyError: pass
        else: raise AssertionError('project-only source silently used system credentials')


def test_probe_authentication_failure_records_safe_status_and_does_not_retry():
    probe = module('probe_auth_failure', 'scripts/probe_model.py')
    original, posts = llm.DeepSeekClient, []
    class Session:
        def post(self, *args, **kwargs):
            posts.append(1)
            return NS(status_code=401, json=lambda: {'error': {'message': 'invalid fake-offline-only'}})
    class Client(original):
        def __init__(self, config, **kwargs):
            super().__init__(config, api_key='fake-offline-only', guard=kwargs['guard'], session=Session())
    with tempfile.TemporaryDirectory() as tmp:
        plan = {'output_directory': str(Path(tmp) / 'probe'), 'kind': 'model_identity_probe',
                'model': 'deepseek-flash', 'ceiling_cny': .05, 'max_output_tokens': 256}
        with patch.object(llm, 'DeepSeekClient', Client), patch.object(llm, 'load_scoped_api_key', return_value='fake-offline-only'):
            assert probe.execute(scoped_config(), plan) == 1
        payload = (Path(plan['output_directory']) / 'result.json').read_text(encoding='utf-8')
        result = json.loads(payload)
        assert result['http_status'] == 401 and len(posts) == 1 and result['cost_complete'] is False
        assert 'fake-offline-only' not in payload
