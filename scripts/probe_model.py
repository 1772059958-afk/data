"""One explicitly authorized, budgeted model identity probe; default is a plan."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def load_plan(args):
    config = args.config if args.config.is_absolute() else ROOT / args.config
    raw = json.loads(config.read_text(encoding='utf-8'))
    target = args.out.resolve()
    if not target.is_relative_to(ROOT / 'runs') or target.exists():
        raise ValueError('probe output must be a new directory under runs/')
    if args.execute and (not args.allow_paid or raw['execution'].get('live_authorized') is not True
                         or raw['execution'].get('model_probe_authorized') is not True):
        raise ValueError('model probe requires explicit scoped authorization and --allow-paid')
    return raw, {'kind': 'model_identity_probe', 'execute': args.execute,
                 'output_directory': str(target), 'config_sha256': hashlib.sha256(config.read_bytes()).hexdigest(),
                 'model': raw['model']['model'], 'model_calls_limit': 1,
                 'max_output_tokens': 256, 'ceiling_cny': 0.05,
                 'note': 'Integration only; observed response identity is not an immutable model freeze.'}


def execute(raw, plan):
    from swe_repair.budget import Budget, BudgetState
    from swe_repair.execution import Runtime, BudgetedClient
    from swe_repair.llm import DeepSeekClient, ModelConfig, load_scoped_api_key
    from swe_repair.spend import SpendGuard, SpendPolicy
    target = Path(plan['output_directory'])
    target.mkdir(parents=True, exist_ok=False)
    (target / 'plan.json').write_text(json.dumps(plan, indent=2), encoding='utf-8')
    ledger = raw['execution'].get('batch_ledger')
    if ledger:
        from swe_repair.batch_ledger import LedgerSpendGuard
        ledgerpath = (ROOT / ledger).resolve()
        if not ledgerpath.is_relative_to(ROOT / 'runs'):
            raise ValueError('probe cumulative ledger must stay under runs/')
        batch = LedgerSpendGuard(ledgerpath, raw['execution']['total_cny'], target.name)
    else:
        batch = SpendGuard(SpendPolicy(ceiling_cny=plan['ceiling_cny'], max_calls=1))
    starting_spend = batch.spent_cny
    runtime = Runtime(BudgetState('probe', Budget(4096, 1, 0, 60)),
                      money=SpendGuard(SpendPolicy(ceiling_cny=plan['ceiling_cny'], max_calls=1)))
    result = {'kind': plan['kind'], 'status': 'not_sent', 'model': plan['model']}
    try:
        m = raw['model']
        client = DeepSeekClient(ModelConfig(model=m['model'], thinking=m['thinking'], effort=m['effort'],
            max_tokens=plan['max_output_tokens'], max_retries=0, timeout_seconds=45),
            api_key=load_scoped_api_key(raw['execution'], str(ROOT)), guard=batch, allow_live=True)
        reply = BudgetedClient(client, runtime).chat([{'role': 'user', 'content': 'Reply with the single word OK.'}])
        if not reply.record.served_model_reported:
            raise ValueError('response did not report a model identity; do not pin a fallback alias')
        result.update(status='completed', observed_served_model=reply.record.served_model,
                      response_text=reply.text[:100], record=reply.record.as_dict())
    except Exception as exc:
        # Credential-bearing transport errors must never be copied to artifacts.
        result.update(status='failed', error_type=type(exc).__name__)
        status = re.search(r'HTTP (\d{3})', str(exc))
        if status:
            result['http_status'] = int(status.group(1))
    finally:
        runtime.sync()
        result.update(cost_cny=runtime.cost_cny, budget=runtime.state.to_dict(), calls=runtime.records,
                      cost_complete=bool(runtime.records) and all(r.get('billing') != 'unknown' for r in runtime.records),
                      new_generation_cost_cny=batch.spent_cny - starting_spend,
                      cumulative_batch_cost_cny=batch.spent_cny)
        (target / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        if ledger:
            batch.close()
    print(target / 'result.json')
    return 0 if result['status'] == 'completed' else 1


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', type=Path, default=Path('configs/proposal_v1.json'))
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--execute', action='store_true')
    p.add_argument('--allow-paid', action='store_true')
    return p


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    try:
        raw, plan = load_plan(args)
        if not args.execute:
            print(json.dumps(plan, indent=2))
            return 0
        return execute(raw, plan)
    except (OSError, ValueError) as exc:
        p.error(str(exc))


if __name__ == '__main__':
    raise SystemExit(main())
