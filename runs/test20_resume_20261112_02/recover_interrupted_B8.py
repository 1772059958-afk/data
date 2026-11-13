"""Recover one interrupted public validation; replay paid replies, never send HTTP.

The frozen generator is unchanged. Every original request, message, completed
exec result and resource counter is checked before the missing validation runs.
Recovery filesystem restoration is lifecycle overhead, recorded separately.
"""
from pathlib import Path
from datetime import datetime, timezone
import copy, hashlib, importlib.util, json, sys, time

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
OLD = ROOT / 'runs/test20_B_20261112_01'
IID = 'mwaskom__seaborn-2848'
sys.path.insert(0, str(ROOT / 'src'))

def read(p): return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def canonical(v): return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
def write(p, v):
    with Path(p).open('x', encoding='utf-8') as f:
        json.dump(v, f, ensure_ascii=False, indent=2)

def preflight():
    snapshot = read(ROOT / 'runs/test20_resume_20261112_01/formal_source_snapshot/manifest.json')
    for f in snapshot['files']:
        assert sha(ROOT / f['path']) == f['sha256'], f['path']
    ledger = ROOT / 'runs/test20_execution_20261111/batch_ledger.json'
    money = read(ledger)
    assert money['pending'] is None and sum(r['cost_cny'] for r in money['records']) < 100
    matrix = read(OLD / 'matrix.json')
    ids = matrix['designated_instances']
    assert len(matrix['cases']) == 7 and ids[7] == IID
    events = [json.loads(s) for s in (OLD / 'events.jsonl').read_text(encoding='utf-8').splitlines()]
    tape = [r['event'] for r in events if r['instance_id'] == IID and isinstance(r.get('event'), dict)]
    assert len([e for e in tape if e['event'] == 'model_response']) == 6
    assert tape[-1]['event'] == 'container_exec'
    assert tape[-1]['command'] == 'cd /testbed && timeout 180 python -m pytest tests/test_core.py tests/test_axisgrid.py tests/test_categorical.py -q -p no:cacheprovider 2>&1; echo "__rc=$?"'
    assert tape[-1]['budget']['consumed']['model_call'] == 6
    responses = [e['record'] for e in tape if e['event'] == 'model_response']
    booked = {r['request_id']: r for r in money['records']}
    for record in responses:
        assert record['system_fingerprint'] == 'bc19ba97cbe016479903222bb1578db6'
        assert booked[record['request_id']]['cost_cny'] == record['cost_cny']
    return snapshot, matrix, tape, ledger

class Tape:
    def __init__(self, events):
        self.events, self.index, self.elapsed, self.live_started = events, 0, 0.0, None
        self.failures, self.restorations, self.new_execs = [], [], []
    def clock(self):
        return self.elapsed + (time.monotonic() - self.live_started if self.live_started is not None else 0)
    def check(self, value, expected, label):
        if canonical(value) != canonical(expected):
            self.failures.append(label)
            raise AssertionError('exact recovery replay mismatch: ' + label)
    def emit(self, runtime, event):
        if self.index < len(self.events):
            source = self.events[self.index]
            self.check(event, {k:v for k,v in source.items() if k != 'budget'}, 'event_' + str(self.index))
            self.elapsed = source['budget']['consumed']['wallclock_seconds']
            runtime.sync()
            self.check(runtime.state.to_dict(), source['budget'], 'budget_' + str(self.index))
            self.index += 1
            if self.index == len(self.events): self.live_started = time.monotonic()
    def next(self): return self.events[self.index] if self.index < len(self.events) else None

def main():
    from swe_repair import experiment as exp
    from swe_repair.execution import Runtime
    from swe_repair.llm import ModelConfig, CallRecord, ChatResult
    from swe_repair.prefix import Container
    from swe_repair.state import generation_view
    import pyarrow.parquet as pq
    snapshot, old, source_events, ledger = preflight()
    before = sha(ledger)
    spec = importlib.util.spec_from_file_location('frozen_run_cf', ROOT / 'scripts/run_cf.py')
    runner = importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)
    args = runner.parser().parse_args(['--config','configs/test20_frozen_20261112_01.json',
        '--mode','formal','--arm','B','--split','test','--seed','20261111','--repeat-index','0',
        '--instances-file','runs/test20_preparation_20261111/instances.json',
        '--tag','test20_B_20261112_02','--execute','--allow-paid'])
    raw, plan = runner.load_plan(args)
    assert plan['config_hash'] == old['config_hash']
    import os
    os.environ['DOCKER_CONTEXT'] = raw['execution']['docker_context']
    dataset = read(ROOT/'data/harness/manifest.json')['splits']['test']
    assert sha(ROOT/dataset['local_file']).lower() == dataset['sha256'].lower()
    rows = pq.read_table(ROOT/dataset['local_file']).to_pylist()
    row = generation_view(next(r for r in rows if r['instance_id'] == IID))
    tape = Tape(source_events)
    class ReplayRuntime(Runtime):
        def __init__(self, state, **kwargs): super().__init__(state, clock=tape.clock, **kwargs)
        def emit(self, event):
            tape.emit(self, event)
            super().emit(event)
    class RecordedClient:
        config = ModelConfig(**{k:v for k,v in raw['model'].items() if k in ModelConfig.__dataclass_fields__})
        def chat(self, messages, **kwargs):
            # BudgetedClient has already verified/consumed the exact model_request.
            response = tape.events[tape.index]
            message = tape.events[tape.index+1]
            assert response['event'] == 'model_response' and message['event'] == 'model_message'
            m = copy.deepcopy(message['message'])
            record = CallRecord(**response['record'])
            return ChatResult(record, m, m.get('content') or '', m.get('reasoning_content') or '', m.get('tool_calls') or [])
    class RecoveryBox:
        def __init__(self, image, name):
            self.real = Container(image, 'resume02-' + name)
            self.image, self.name, self.workdir = image, self.real.name, self.real.workdir
        def __getattr__(self, name): return getattr(self.real, name)
        def bash(self, script, timeout=300):
            next_event = tape.next()
            if next_event is not None:
                assert next_event['event'] == 'container_result' and next_event['command'] == script
                # Restore the already observed candidate filesystem, without
                # exposing a new observation or re-running historical searches.
                if ('base64 -d > /tmp/candidate.diff' in script or 'git apply /tmp/candidate.diff' in script
                        or 'python -m py_compile' in script):
                    start = time.monotonic(); code, output = self.real.bash(script, timeout=timeout)
                    tape.restorations.append({'command':script,'exit_code':code,'output':output,
                                              'elapsed_seconds':time.monotonic()-start})
                    tape.check([code,output], [next_event['exit_code'],next_event['output']], 'filesystem_restoration')
                return next_event['exit_code'], next_event['output']
            start = time.monotonic(); result = self.real.bash(script, timeout=timeout)
            tape.new_execs.append({'command':script,'timeout':timeout,'exit_code':result[0],
                                  'elapsed_seconds':time.monotonic()-start})
            return result
    original_runtime, original_interactive = exp.Runtime, exp.run_interactive
    exp.Runtime = ReplayRuntime
    exp.run_interactive = lambda *a,**kw: original_interactive(*a,clock=tape.clock,**kw)
    try:
        with (OUT/'B8_recovery_events.jsonl').open('x',encoding='utf-8') as log:
            def checkpoint(e):
                log.write(json.dumps(e,ensure_ascii=False)+'\n');log.flush()
            case = exp.run_case(row, RecordedClient(), raw, mode='formal',arm='B',seed=20261111,
                                split='test',box_factory=RecoveryBox,checkpoint=checkpoint)
    finally:
        exp.Runtime, exp.run_interactive = original_runtime, original_interactive
    assert not tape.failures and tape.index == len(tape.events), tape.failures
    assert sha(ledger) == before, 'recovery must never mutate or double book the shared paid ledger'
    assert case['stages']['standalone']['budget']['consumed']['model_call'] == 6
    assert [r['request_id'] for r in case['stages']['standalone']['calls']] == [
        e['record']['request_id'] for e in source_events if e['event']=='model_response']
    assert case['image_digest'] == raw['execution']['images'][IID]
    case['recovery_provenance'] = {'kind':'exact_recorded_interaction_replay_then_missing_public_validation',
        'source_tag':OLD.name,'source_events_sha256':sha(OLD/'events.jsonl'),
        'new_model_requests':0,'historical_replies_already_booked':6,
        'historical_model_cost_cny':case['stages']['standalone']['cost_cny'],
        'operational_adapter_sha256':sha(__file__)}
    write(OUT/'B8_recovered_case.json',case)
    write(OUT/'B8_recovery_audit.json',{'instance_id':IID,'original_event_count':len(source_events),
        'replayed_events':tape.index,'every_recorded_prompt_message_exec_result_and_budget_equal':True,
        'new_model_requests':0,'ledger_before_sha256':before,'ledger_after_sha256':sha(ledger),
        'recovery_lifecycle_restorations':tape.restorations,'new_public_validation_execs':tape.new_execs,
        'strategy_pause_excluded_from_wallclock':True,'status':case['status'],
        'case_sha256':sha(OUT/'B8_recovered_case.json'),'at':datetime.now(timezone.utc).isoformat()})
    print(json.dumps({'status':case['status'],'reason':case['termination_reason'],
        'new_model_requests':0,'new_public_execs':len(tape.new_execs)},ensure_ascii=False))

if __name__ == '__main__': main()
