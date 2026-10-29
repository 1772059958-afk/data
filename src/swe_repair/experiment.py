"""Proposal-aligned formal runs and separate paired diagnostics. No network on import."""
from __future__ import annotations
import copy
import json
import random
import uuid

from .budget import BudgetState
from .execution import Runtime, BudgetedClient, BudgetedContainer, ResourceLimit
from .interact import run_interactive, InteractionBudget, SYSTEM
from .prefix import (Container, PrefixResult, run_prefix, image_for, candidate_messages,
                     extract_patch, validate_candidate)
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
    feedback = [r.to_dict() for r in prefix.state.failures.records]
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
    outcome = {'instance_id': iid, 'mode': mode, 'arm': arm, 'config_hash': cfg.digest,
               'status': 'running', 'decisions': {}, 'stages': {}, 'prefix_snapshot': None}
    box = box_factory(image_for(iid), f'proposal-{iid[:32]}-{uuid.uuid4().hex[:10]}')
    def emit(stage, rt, state, status='completed', **extra):
        rt.sync()
        best = state.patches.best_candidate()
        payload = {'status': status, 'patch': best.diff if best else '',
                   'cost_cny': rt.cost_cny, 'budget': rt.state.to_dict(),
                   'calls': rt.records, 'events': rt.events, 'state': state.to_dict(), **extra}
        outcome['stages'][stage] = payload
        checkpoint({'instance_id': iid, 'stage': stage, **payload})
    try:
        box.start()
        outcome['image_digest'] = box.image_digest()
        if box.head() != row['base_commit']:
            raise RuntimeError('container checkout does not match designated base_commit')
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
                candidate = prefix.state.patches.candidates[-1]
                validation = validate_candidate(counted, candidate, tuple(prefix.state.localization.symbols_union()))
                prefix.state.patches.candidates[-1] = validation.candidate
                for failure in validation.failures:
                    prefix.state.failures.add(failure.with_recovery())
                if not any(f.is_environment for f in validation.failures):
                    prefix.state.failures.add(FailureRecord.from_output('public validation recovery', 0, stage='env'))
            if cached_prefix is None:
                emit('prefix', rt, prefix.state, trace=prefix.trace, context_text=prefix.context_text,
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
            box.revert()  # lifecycle isolation, outside model-visible observations
            branch_prefix = clone_prefix(prefix) if prefix else None
            state = (branch_prefix.state if branch != 'standalone' else
                     RepairState(TaskManifest.from_instance(row, cfg.config_version, cfg.digest)))
            if state.budget is None:
                state.budget = _new_budget(raw)
            inherited = outcome['stages'].get('prefix', {}).get('calls', []) if branch != 'standalone' else []
            rt = Runtime(state.budget, money=_money(raw, [type('Booked', (), x)() for x in inherited]),
                         event_sink=lambda e, b=branch: checkpoint({'instance_id': iid, 'stage': b, 'event': e}))
            counted = BudgetedContainer(box, rt)
            wrapped = BudgetedClient(client, rt, expected_served_model=raw['model'].get('model_version'))
            status, details = 'completed', {}
            try:
                if branch == 'fixed':
                    messages = candidate_messages(problem, branch_prefix.context_text, 2)
                    messages[-1]['content'] += '\nPrefix evidence:\n' + seed_messages(problem, branch_prefix)[1]['content']
                    reply = wrapped.chat(messages)
                    diff = extract_patch(reply.text)
                    if diff:
                        diff, _ = repair_hunk_headers(diff)
                        idx = max((c.index for c in state.patches.candidates), default=-1) + 1
                        val = validate_candidate(counted, Candidate.build(idx, diff, origin='fixed'),
                                                 tuple(state.localization.symbols_union()))
                        state.patches.add(val.candidate)
                        for f in val.failures:
                            state.failures.add(f)
                else:
                    ib = raw['interaction']
                    result = run_interactive(problem, client=wrapped, container=counted, state=state,
                                             instance_id=iid, budget=InteractionBudget(ib['model_calls'], ib['tool_calls'], ib['wallclock_seconds'], ib.get('stagnation_patience', 3)),
                                             seed_messages=seed_messages(problem, branch_prefix) if branch != 'standalone' else None)
                    details = {'ended_by': result.ended_by, 'transcript': result.transcript,
                               'trace': result.trace, 'named_tool_calls': result.tool_calls}
                    if result.ended_by.startswith(('ResourceLimit:', 'SpendLimitExceeded:')):
                        status = 'budget_exhausted'
                    elif 'Error' in result.ended_by or 'Limit' in result.ended_by:
                        status = 'generation_error'
            except (ResourceLimit, SpendLimitExceeded) as exc:
                status, details = 'budget_exhausted', {'termination_reason': 'budget_exhausted', 'detail': str(exc)}
            except Exception as exc:
                status, details = 'generation_error', {'error': f'{type(exc).__name__}: {exc}'}
            finally:
                emit(branch, rt, state, status, **details)
                box.revert()
        if mode == 'formal':
            outcome['selected_route'] = selected
            if selected == 'stop':
                outcome['submitted_patch'] = outcome['stages']['prefix']['patch']
            else:
                outcome['submitted_patch'] = outcome['stages'][selected]['patch']
            outcome['policy_cost_cny'] = (
                outcome['stages'].get('prefix', {}).get('cost_cny', 0.0)
                + (outcome['stages'][selected]['cost_cny'] if selected != 'stop' else 0.0))
        outcome['status'] = ('generation_error' if any(s['status'] == 'generation_error'
                                                     for s in outcome['stages'].values()) else 'completed')
    except Exception as exc:
        if 'prefix' not in outcome['stages'] and 'rt' in locals():
            partial = prefix.state if 'prefix' in locals() and prefix else RepairState(
                TaskManifest.from_instance(row, cfg.config_version, cfg.digest))
            partial.budget = rt.state
            emit('prefix', rt, partial, 'generation_error', error=f'{type(exc).__name__}: {exc}')
        outcome.update(status='generation_error', error=f'{type(exc).__name__}: {exc}', submitted_patch='')
    finally:
        box.close()
        outcome['diagnostic_cost_cny'] = sum(s['cost_cny'] for s in outcome['stages'].values())
        outcome['new_generation_cost_cny'] = outcome['diagnostic_cost_cny'] - (
            outcome['stages']['prefix']['cost_cny'] if outcome.get('prefix_reused') else 0)
        checkpoint({'instance_id': iid, 'stage': 'case_complete', 'outcome': outcome})
    return outcome
