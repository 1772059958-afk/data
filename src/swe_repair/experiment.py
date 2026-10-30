"""Proposal-aligned formal runs and separate paired diagnostics. No network on import."""
from __future__ import annotations
import copy
import json
import random
import time
import uuid

from .budget import BudgetState
from .execution import Runtime, BudgetedClient, BudgetedContainer, ResourceLimit
from .interact import run_interactive, InteractionBudget, SYSTEM
from .prefix import (Container, PrefixResult, run_prefix, image_for, candidate_messages,
                     extract_patch, validate_candidate, EnvironmentFailure, recover_environment)
from .patchutil import repair_hunk_headers
from .router import RouterConfig, route_for_arm, evaluate_all, needs_env_recovery
from .spend import SpendGuard, SpendPolicy, SpendLimitExceeded
from .state import RepairState, TaskManifest, Candidate, FailureRecord, assert_generation_only


def clone_prefix(prefix: PrefixResult) -> PrefixResult:
    result = copy.copy(prefix)
    result.state = RepairState.from_dict(json.loads(prefix.state.to_json()))
    result.trace = copy.deepcopy(prefix.trace)
    return result


def seed_messages(problem, prefix):
    evidence = []
    for c in prefix.state.patches.candidates:
        evidence.append({'index': c.index, 'diff': c.diff, 'applies': c.applies_cleanly,
                         'syntax': c.syntax, 'validation': c.validation})
    feedback = [r.prompt_view() for r in prefix.state.failures.records]
    return [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content':
             f'Bug report:\n{problem}\nFiles:\n{prefix.context_text}\n'
             f'Prefix candidates:\n{json.dumps(evidence, ensure_ascii=False)}\n'
             f'Observed failures:\n{json.dumps(feedback, ensure_ascii=False)}'}]


def _new_budget(raw):
    cfg = RouterConfig.from_config(raw)
    return BudgetState.for_tier(raw['active_tier'], cfg.budget_tiers())


def _money(raw, records=()):
    guard = SpendGuard(SpendPolicy(ceiling_cny=raw['execution']['per_instance_cny']))
    guard.records.extend(records)
    return guard


def fixed_continuation(problem, prefix, client, box, raw):
    """Bounded fixed repair: keep the context fixed, feed back recorded checks.

    Every round supplies a complete candidate against the base. No new search
    is introduced, and historical valid candidates remain selectable.
    """
    state = prefix.state
    limit = raw['fixed_continuation']['max_candidates']
    trace = []
    reason = 'fixed_step_limit'
    for step in range(limit):
        if state.patches.has_public_pass():
            reason = 'early_stop_public_pass'
            break
        messages = candidate_messages(problem, prefix.context_text, step + 2)
        evidence = clone_prefix(prefix)
        messages[-1]['content'] += '\nRecorded candidates and structured feedback:\n' + seed_messages(problem, evidence)[1]['content']
        reply = client.chat(messages)
        diff = extract_patch(reply.text)
        diff, _ = repair_hunk_headers(diff) if diff else ('', 0)
        idx = max((c.index for c in state.patches.candidates), default=-1) + 1
        if diff:
            val = validate_candidate(box, Candidate.build(idx, diff, origin='fixed'),
                                     tuple(state.localization.symbols_union()))
            state.patches.add(val.candidate)
            for failure in val.failures:
                state.failures.add(failure)
            recovered = needs_env_recovery(state)
            if recovered and not recover_environment(box, state):
                raise EnvironmentFailure('public validation remains unrunnable after its deterministic retry')
            final_candidate = next(c for c in state.patches.candidates if c.index == idx)
            trace.append({'step': step, 'candidate': final_candidate.to_dict(), 'environment_recovery': recovered,
                          'test_command': val.test_command, 'test_exit_code': val.test_exit_code,
                          'test_category': val.test_category, 'raw_output': val.raw_output})
        else:
            state.failures.add(FailureRecord.from_output('extract complete diff', 1,
                               stage='apply_patch', stdout='empty or malformed model candidate'))
            trace.append({'step': step, 'empty_candidate': True})
        if state.patches.has_public_pass():
            reason = 'early_stop_public_pass'
            break
    return {'termination_reason': reason, 'trace': trace, 'attempted_candidates': len(trace)}


def run_case(row, client, raw, *, mode='formal', arm='D', seed=0,
             calibration=False, box_factory=Container, checkpoint=lambda event: None,
             cached_prefix=None):
    """Run one designated instance. All failed stages remain in the returned row.

    Formal: run only the selected branch. Diagnostic: run fixed/interactive
    alternatives from separately restored snapshots, plus independent B.
    """
    if mode not in ('formal', 'diagnostic') or arm not in 'ABCDE':
        raise ValueError('unknown experiment mode/arm')
    assert_generation_only(row, 'experiment input')
    cfg = RouterConfig.from_config(raw)
    iid, problem = row['instance_id'], row.get('problem_statement', '')
    ceiling = _new_budget(raw)
    outcome = {'instance_id': iid, 'mode': mode, 'arm': arm, 'seed': seed, 'config_hash': cfg.digest,
               'status': 'running', 'decisions': {}, 'stages': {}, 'prefix_snapshot': None,
               'lifecycle': []}
    box = None
    current_stage = None
    def close_box(*, strict=True):
        nonlocal box
        if box is not None:
            started = time.monotonic()
            error = None
            try:
                box.close()
            except Exception as exc:
                error = f'{type(exc).__name__}: {exc}'
                outcome.setdefault('cleanup_errors', []).append({'container': box.name, 'error': error})
                if current_stage in outcome['stages']:
                    outcome['stages'][current_stage].update(status='environment_error',
                                                           termination_reason='environment_cleanup_failed')
            finally:
                outcome['lifecycle'].append({'event': 'close', 'container': box.name,
                                             'elapsed_seconds': time.monotonic() - started, 'error': error})
                box = None
            if error and strict:
                raise EnvironmentFailure('container cleanup failed: ' + error)
    def open_box(stage):
        nonlocal box, current_stage
        close_box()
        current_stage = stage
        started = time.monotonic()
        box = box_factory(image_for(iid), f'proposal-{stage}-{iid[:24]}-{uuid.uuid4().hex[:10]}')
        try:
            box.start()
            digest = box.image_digest()
            if outcome.get('image_digest', digest) != digest:
                raise EnvironmentFailure('fresh branch image differs from prefix image')
            if box.head() != row['base_commit']:
                raise EnvironmentFailure('container checkout does not match designated base_commit')
            box.revert()  # checked preparation, before the strategy clock starts
        except Exception as exc:
            outcome['lifecycle'].append({'event': 'start_failed', 'stage': stage, 'container': box.name,
                                         'elapsed_seconds': time.monotonic() - started, 'error': str(exc)})
            raise EnvironmentFailure(str(exc)) from exc
        outcome.setdefault('image_digest', digest)
        outcome['lifecycle'].append({'event': 'start', 'stage': stage, 'container': box.name,
                                     'image_digest': digest, 'base_commit': row['base_commit'],
                                     'elapsed_seconds': time.monotonic() - started})
    def emit(stage, rt, state, status='completed', **extra):
        rt.sync()
        best = state.patches.best_candidate()
        payload = {'status': status, 'patch': best.diff if best else '',
                   'cost_cny': rt.cost_cny, 'budget': rt.state.to_dict(),
                   'calls': rt.records, 'events': rt.events, 'state': state.to_dict(), **extra}
        outcome['stages'][stage] = payload
        checkpoint({'instance_id': iid, 'stage': stage, **payload})
    try:
        open_box('standalone' if mode == 'formal' and arm == 'B' else 'prefix')
        if mode == 'formal' and arm == 'B':
            prefix = None
        else:
            if cached_prefix is not None:
                saved = copy.deepcopy(cached_prefix)
                if (saved['image_digest'] != outcome['image_digest'] or saved['config_hash'] != cfg.digest
                        or saved['stage']['state']['task_manifest']['instance_id'] != iid):
                    raise ValueError('cached prefix identity mismatch')
                stage = saved['stage']
                state = RepairState.from_dict(stage['state'])
                if state.task.base_commit != row['base_commit']:
                    raise ValueError('cached base commit mismatch')
                prefix = PrefixResult(state, row['base_commit'], tuple(stage['context_files']),
                                      tuple(stage['listing']), context_text=stage['context_text'], trace=stage['trace'])
                outcome['stages']['prefix'] = stage
                outcome['prefix_reused'] = True
                rt = Runtime(state.budget, money=_money(raw, [type('Booked', (), x)() for x in stage['calls']]))
                counted = BudgetedContainer(box, rt)
            else:
                rt = Runtime(ceiling, money=_money(raw), token_limit=int(ceiling.ceiling.token * cfg.prefix_fraction),
                             event_sink=lambda e: checkpoint({'instance_id': iid, 'stage': 'prefix', 'event': e}))
                wrapped = BudgetedClient(client, rt, expected_served_model=raw['model'].get('model_version'))
                counted = BudgetedContainer(box, rt)
                prefix = run_prefix(row, wrapped, config_version=cfg.config_version, config_hash=cfg.digest,
                                    n_candidates=raw['prefix'].get('n_candidates', 2), container=counted)
                prefix.state.budget = rt.state
            # Exactly one deterministic retry of the same public validation,
            # without installation/network access or hidden-test metadata.
            if cached_prefix is None and needs_env_recovery(prefix.state) and prefix.state.patches.candidates:
                rt.token_limit = None
                recover_environment(counted, prefix.state)
            if cached_prefix is None:
                prefix_error = next((x for x in prefix.trace if x.get('step') == 'prefix_error'), None)
                prefix_status = ('environment_error' if prefix_error and prefix_error['reason'].startswith('EnvironmentFailure:')
                                 else 'generation_error' if prefix_error else 'completed')
                emit('prefix', rt, prefix.state, prefix_status, trace=prefix.trace, context_text=prefix.context_text,
                     context_files=list(prefix.context_files), listing=list(prefix.listing))
            # Persist BEFORE either alternative. This is the only boundary used
            # by decisions and by all subsequent prompts.
            outcome['prefix_snapshot'] = json.loads(prefix.state.to_json())
            prefix = clone_prefix(prefix)
            outcome['features'] = prefix.features()
            outcome['router_rules'] = evaluate_all(prefix.state, cfg, allow_uncalibrated=calibration)
            for a in ('A', 'C', 'D', 'E'):
                # E is undefined until its dev trigger-rate matching is frozen.
                if a == 'E' and cfg.switch_probability is None and calibration:
                    continue
                decision = route_for_arm(a, prefix.state, cfg, rng=random.Random(f'{seed}:{iid}'),
                                         allow_uncalibrated=calibration)
                outcome['decisions'][a] = decision.to_dict()
            prefix_failure = next((x for x in prefix.trace if x.get('step') == 'prefix_error'), None)
            if prefix_failure:
                if prefix_failure['reason'].startswith('EnvironmentFailure:'):
                    raise EnvironmentFailure(prefix_failure['reason'])
                raise RuntimeError(prefix_failure['reason'])

        if mode == 'formal':
            selected = 'standalone' if arm == 'B' else outcome['decisions'][arm]['route']
            branches = [selected] if selected != 'stop' else []
        else:
            # Only continuable prefix failures are eligible for paired labels.
            eligible = outcome['decisions']['A']['route'] != 'stop'
            outcome['paired_eligible'] = eligible
            branches = (['fixed', 'interactive'] if eligible else []) + ['standalone']

        for branch in branches:
            branch_prefix = clone_prefix(prefix) if prefix else None
            state = (branch_prefix.state if branch != 'standalone' else
                     RepairState(TaskManifest.from_instance(row, cfg.config_version, cfg.digest)))
            if state.budget is None:
                state.budget = _new_budget(raw)
            inherited = outcome['stages'].get('prefix', {}).get('calls', []) if branch != 'standalone' else []
            rt = None
            status, details = 'completed', {}
            try:
                # A fresh container removes ignored files, /tmp, processes and
                # other filesystem effects of the prefix/previous alternative.
                # B's initial container has done identity checks only.
                if prefix is not None:
                    open_box(branch)
                rt = Runtime(state.budget, money=_money(raw, [type('Booked', (), x)() for x in inherited]),
                             event_sink=lambda e, b=branch: checkpoint({'instance_id': iid, 'stage': b, 'event': e}))
                counted = BudgetedContainer(box, rt)
                wrapped = BudgetedClient(client, rt, expected_served_model=raw['model'].get('model_version'))
                if branch == 'fixed':
                    details = fixed_continuation(problem, branch_prefix, wrapped, counted, raw)
                else:
                    ib = raw['interaction']
                    result = run_interactive(problem, client=wrapped, container=counted, state=state,
                                             instance_id=iid, budget=InteractionBudget(ib['model_calls'], ib['tool_calls'], ib['wallclock_seconds'], ib.get('stagnation_patience', 3)),
                                             seed_messages=seed_messages(problem, branch_prefix) if branch != 'standalone' else None)
                    details = {'ended_by': result.ended_by, 'transcript': result.transcript,
                               'trace': result.trace, 'named_tool_calls': result.tool_calls,
                               'termination_reason': result.ended_by}
                    if result.ended_by.startswith(('ResourceLimit:', 'SpendLimitExceeded:')):
                        status = 'budget_exhausted'
                    elif result.ended_by.startswith('EnvironmentFailure:'):
                        status = 'environment_error'
                    elif result.ended_by in ('wallclock', 'tool_budget', 'model_call_budget'):
                        status = 'budget_exhausted'
                    elif 'Error' in result.ended_by or 'Limit' in result.ended_by:
                        status = 'generation_error'
            except (ResourceLimit, SpendLimitExceeded) as exc:
                status, details = 'budget_exhausted', {'termination_reason': 'budget_exhausted', 'detail': str(exc)}
            except EnvironmentFailure as exc:
                status, details = 'environment_error', {'termination_reason': 'environment_error', 'detail': str(exc)}
            except Exception as exc:
                status, details = 'generation_error', {'termination_reason': 'generation_error', 'error': f'{type(exc).__name__}: {exc}'}
            finally:
                if rt is None:
                    rt = Runtime(state.budget)
                emit(branch, rt, state, status, **details)
                close_box()
        if mode == 'formal':
            outcome['selected_route'] = selected
            if selected == 'stop':
                outcome['submitted_patch'] = outcome['stages']['prefix']['patch']
            else:
                outcome['submitted_patch'] = outcome['stages'][selected]['patch']
            outcome['policy_cost_cny'] = (
                outcome['stages'].get('prefix', {}).get('cost_cny', 0.0)
                + (outcome['stages'][selected]['cost_cny'] if selected != 'stop' else 0.0))
        statuses = {s['status'] for s in outcome['stages'].values()}
        outcome['status'] = next((s for s in ('generation_error', 'environment_error', 'budget_exhausted')
                                  if s in statuses), 'completed')
        if mode == 'formal':
            if selected == 'stop':
                reason = outcome['decisions'][arm]['reason']
                outcome['termination_reason'] = reason
                if reason == 'stop_budget_insufficient':
                    outcome['status'] = 'budget_exhausted'
                elif reason == 'stop_env_failure':
                    outcome['status'] = 'environment_error'
            else:
                outcome['termination_reason'] = outcome['stages'][selected].get('termination_reason', outcome['status'])
        else:
            outcome['termination_reason'] = outcome['status']
    except Exception as exc:
        status = ('budget_exhausted' if isinstance(exc, (ResourceLimit, SpendLimitExceeded)) else
                  'environment_error' if isinstance(exc, EnvironmentFailure) else 'generation_error')
        if 'prefix' not in outcome['stages'] and 'rt' in locals():
            partial = prefix.state if 'prefix' in locals() and prefix else RepairState(
                TaskManifest.from_instance(row, cfg.config_version, cfg.digest))
            partial.budget = rt.state
            emit('prefix', rt, partial, status, termination_reason=status, error=f'{type(exc).__name__}: {exc}')
        # A failed later stage must not erase an already validated candidate.
        chosen = locals().get('selected', 'prefix')
        actual_stage = outcome['stages'].get(chosen)
        selected_stage = actual_stage or outcome['stages'].get('prefix', {})
        outcome.update(status=status, termination_reason=status, error=f'{type(exc).__name__}: {exc}',
                       submitted_patch=selected_stage.get('patch', ''))
        if mode == 'formal':
            outcome['selected_route'] = chosen
            outcome['policy_cost_cny'] = outcome['stages'].get('prefix', {}).get('cost_cny', 0.0) + (
                actual_stage.get('cost_cny', 0.0) if actual_stage and chosen not in ('prefix', 'stop') else 0.0)
    finally:
        # Final cleanup failures must remain in the returned audit row instead
        # of escaping and dropping the whole designated case from the matrix.
        close_box(strict=False)
        if outcome.get('cleanup_errors'):
            outcome.update(status='environment_error', termination_reason='environment_cleanup_failed')
        outcome['diagnostic_cost_cny'] = sum(s['cost_cny'] for s in outcome['stages'].values())
        outcome['new_generation_cost_cny'] = outcome['diagnostic_cost_cny'] - (
            outcome['stages']['prefix']['cost_cny'] if outcome.get('prefix_reused') else 0)
        checkpoint({'instance_id': iid, 'stage': 'case_complete', 'outcome': outcome})
    return outcome
