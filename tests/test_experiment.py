"""Offline integration checks: real orchestration, fake model/container only."""
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
import tempfile

from swe_repair import experiment as ex
from swe_repair.llm import ChatResult
from swe_repair.prefix import PrefixResult, ValidationResult
from swe_repair.state import RepairState, TaskManifest, Candidate, Localization

ROOT = Path(__file__).resolve().parents[1]
DIFF = '--- a/pkg/x.py\n+++ b/pkg/x.py\n@@ -1 +1 @@\n-old\n+PREFIX\n'
ROW = {'instance_id': 'demo__repo-1', 'repo': 'demo/repo', 'base_commit': 'base', 'problem_statement': 'fix'}


def config():
    raw = json.loads((ROOT / 'configs/proposal_v1.json').read_text(encoding='utf-8'))
    raw['router'].update(localization_disagreement_threshold=.5, duplicate_rate_threshold=.5, switch_probability=.5)
    return raw


class Box:
    def __init__(self, image, name):
        self.image, self.name, self.workdir = image, name, '/testbed'
    def start(self): pass
    def close(self): pass
    def revert(self): pass
    def head(self): return 'base'
    def image_digest(self): return 'sha256:fake'


class Client:
    def __init__(self):
        self.config = NS(max_tokens=100, model='deepseek-flash')
        self.requests = []
    def chat(self, messages, **kwargs):
        self.requests.append(copy.deepcopy(messages))
        text = DIFF.replace('PREFIX', 'AFTER_FIXED')
        record = NS(cost_cny=.01, prompt_tokens=10, output_tokens=10, served_model='deepseek-flash', finish_reason='stop')
        return ChatResult(record, {'content': text}, text, '', [])


def prefix(row, client, *, config_version, config_hash, **kwargs):
    client.chat([{'role': 'user', 'content': 'prefix call'}])
    state = RepairState(TaskManifest.from_instance(row, config_version, config_hash))
    state.patches.add(Candidate.build(0, DIFF, applies_cleanly=True, validation='fail', syntax='pass'))
    state.localization = Localization.from_file_sets({'a': ['pkg/x.py'], 'b': ['pkg/x.py']})
    return PrefixResult(state, 'base', ('pkg/x.py',), ('pkg',), context_text='old', calls=1, tokens=20)


def validation(box, c, *args):
    return ValidationResult(Candidate.build(c.index, c.diff, applies_cleanly=True, validation='fail', syntax='pass', origin=c.origin))


def interactive(problem, *, state, client, seed_messages=None, **kwargs):
    client.chat(seed_messages or [{'role': 'user', 'content': problem}])
    state.patches.add(Candidate.build(10, DIFF.replace('PREFIX', 'INTERACTIVE'), applies_cleanly=True, validation='pass', syntax='pass'))
    return NS(ended_by='finish_tool', transcript=seed_messages or [], trace=[], tool_calls=1)


def run(**kwargs):
    client = kwargs.pop('client', Client())
    with patch.object(ex, 'run_prefix', prefix), patch.object(ex, 'validate_candidate', validation), patch.object(ex, 'run_interactive', interactive):
        result = ex.run_case(ROW, client, config(), box_factory=Box, **kwargs)
    return result, client


def test_formal_runs_only_selected_fixed_branch():
    result, client = run(mode='formal', arm='D')
    assert result['status'] == 'completed', result
    assert set(result['stages']) == {'prefix', 'fixed'}
    assert len(client.requests) == 2
    assert result['selected_route'] == 'fixed'
    assert abs(result['policy_cost_cny'] - .02) < 1e-9


def test_formal_cascade_runs_only_interactive_branch():
    result, _ = run(mode='formal', arm='C')
    assert set(result['stages']) == {'prefix', 'interactive'}, result


def test_standalone_never_runs_prefix():
    result, _ = run(mode='formal', arm='B')
    assert set(result['stages']) == {'standalone'}, result


def test_diagnostic_alternatives_have_identical_prefix_and_no_fixed_leak():
    result, client = run(mode='diagnostic')
    assert result['status'] == 'completed', result
    assert set(result['stages']) == {'prefix', 'fixed', 'interactive', 'standalone'}
    assert 'AFTER_FIXED' not in json.dumps(client.requests[2])
    assert 'AFTER_FIXED' not in json.dumps(result['prefix_snapshot'])
    prefix_budget = result['prefix_snapshot']['budget_state']['consumed']
    for name in ('fixed', 'interactive'):
        assert result['stages'][name]['budget']['consumed']['model_call'] == prefix_budget['model_call'] + 1
    assert len(result['prefix_snapshot']['patch_history']['candidates']) == 1


def test_shared_early_stop_does_not_collect_ineligible_pair():
    def passing(*args, **kwargs):
        p = prefix(*args, **kwargs)
        p.state.patches.candidates[0] = Candidate.build(0, DIFF, applies_cleanly=True, validation='pass', syntax='pass')
        return p
    with patch.object(ex, 'run_prefix', passing), patch.object(ex, 'run_interactive', interactive):
        result = ex.run_case(ROW, Client(), config(), mode='diagnostic', box_factory=Box)
    assert not result['paired_eligible']
    assert set(result['stages']) == {'prefix', 'standalone'}, result
    assert all(d['route'] == 'stop' for d in result['decisions'].values())


def test_shared_prefix_cache_reused_without_new_prefix_model_cost():
    first, _ = run(mode='formal', arm='A')
    saved = {'image_digest': first['image_digest'], 'config_hash': first['config_hash'], 'stage': first['stages']['prefix']}
    result, client = run(mode='formal', arm='C', cached_prefix=saved)
    assert result['prefix_reused'], result
    assert len(client.requests) == 1
    assert result['prefix_snapshot'] == first['prefix_snapshot']
    assert abs(result['new_generation_cost_cny'] - .01) < 1e-9
    assert abs(result['policy_cost_cny'] - .02) < 1e-9


def test_bad_cache_identity_fails_without_model_request():
    first, _ = run(mode='formal', arm='A')
    saved = {'image_digest': 'wrong', 'config_hash': first['config_hash'], 'stage': first['stages']['prefix']}
    result, client = run(mode='formal', arm='C', cached_prefix=saved)
    assert result['status'] == 'generation_error'
    assert not client.requests


def test_failed_branch_keeps_designated_instance_partial_state_and_cost():
    def fail(*args, **kwargs): raise ValueError('broken validator')
    events = []
    with patch.object(ex, 'run_prefix', prefix), patch.object(ex, 'validate_candidate', fail):
        result = ex.run_case(ROW, Client(), config(), mode='formal', arm='A', box_factory=Box, checkpoint=events.append)
    assert result['instance_id'] == ROW['instance_id']
    assert result['stages']['fixed']['status'] == 'generation_error'
    assert result['status'] == 'generation_error'
    assert result['policy_cost_cny'] >= .02 - 1e-9
    assert events[-1]['stage'] == 'case_complete'


def runner():
    spec = importlib.util.spec_from_file_location('new_runner', ROOT / 'scripts/run_cf.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_default_plan_needs_no_live_dependencies():
    mod = runner()
    raw, plan = mod.load_plan(mod.parser().parse_args(['--dry-run']))
    assert not plan['execute'] and len(plan['designated_instances']) == 23
    assert raw['execution']['live_authorized'] is False


def test_execute_and_paid_flag_still_refused_by_draft_authorization():
    mod = runner()
    try: mod.load_plan(mod.parser().parse_args(['--execute', '--allow-paid']))
    except ValueError as exc: assert 'paid execution disabled' in str(exc)
    else: raise AssertionError('unauthorized live execution passed')


def test_test_split_has_full_denominator_and_no_calibration_escape():
    mod = runner()
    _, plan = mod.load_plan(mod.parser().parse_args(['--split', 'test']))
    assert len(plan['designated_instances']) == 300
    try: mod.load_plan(mod.parser().parse_args(['--split', 'test', '--calibration']))
    except ValueError: pass
    else: raise AssertionError('test split accepted calibration')


def test_plan_accepts_frozen_stratified_json_selection():
    mod = runner()
    with tempfile.TemporaryDirectory() as tmp:
        selection = Path(tmp) / 'sample.json'
        ids = (ROOT / 'data/frozen/instances_test.txt').read_text(encoding='utf-8').splitlines()[:3]
        selection.write_text(json.dumps({'instance_ids': ids, 'seed': 123}), encoding='utf-8')
        _, plan = mod.load_plan(mod.parser().parse_args(['--split', 'test', '--instances-file', str(selection)]))
        assert plan['designated_instances'] == ids


def test_gold_plan_never_calls_subprocess_or_model():
    spec = importlib.util.spec_from_file_location('gold_scan', ROOT / 'scripts/scan_gold.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with patch.object(mod.subprocess, 'run', side_effect=AssertionError('must stay offline')):
        record = mod.plan(NS(instances_file=None, split='test', tag='offline_gold', max_workers=1))
    assert record['model_calls'] == 0 and len(record['designated_instances']) == 300
    assert record['command'][record['command'].index('--predictions_path') + 1] == 'gold'
    assert str(ROOT / 'runs') in record['output_directory']


def test_configured_stagnation_ablation_reaches_interactive_executor():
    raw = config()
    raw['interaction']['stagnation_patience'] = 0
    seen = []
    def inspect(*args, **kwargs):
        seen.append(kwargs['budget'].stagnation_patience)
        return interactive(*args, **kwargs)
    with patch.object(ex, 'run_prefix', prefix), patch.object(ex, 'run_interactive', inspect):
        result = ex.run_case(ROW, Client(), raw, mode='formal', arm='C', box_factory=Box)
    assert seen == [0] and result['status'] == 'completed'


def test_malformed_success_response_reserves_batch_and_instance_money():
    from swe_repair.llm import DeepSeekClient, ModelConfig
    from swe_repair.execution import Runtime, BudgetedClient
    from swe_repair.budget import BudgetState, Budget
    from swe_repair.spend import SpendGuard, SpendPolicy
    class Response:
        status_code = 200
        def json(self): return {'usage': 'not a usage object'}
    class Session:
        def post(self, *args, **kwargs): return Response()
    batch = SpendGuard(SpendPolicy(ceiling_cny=1))
    local = SpendGuard(SpendPolicy(ceiling_cny=1))
    rt = Runtime(BudgetState('test', Budget(100000, 3, 5, 20)), money=local)
    client = DeepSeekClient(ModelConfig(max_tokens=100, max_retries=0), api_key='fake', session=Session(), guard=batch)
    try: BudgetedClient(client, rt).chat([])
    except ValueError: pass
    else: raise AssertionError('malformed payload was accepted')
    assert batch.spent_cny > 0 and local.spent_cny > 0
    assert rt.state.consumed.model_call == 1
    assert rt.records[0]['billing'] == 'unknown'
