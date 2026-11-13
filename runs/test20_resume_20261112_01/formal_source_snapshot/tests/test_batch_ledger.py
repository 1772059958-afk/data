"""Durable multi-run budget and interrupted-request accounting, entirely offline."""
import json
from pathlib import Path
from types import SimpleNamespace as NS
import tempfile

from swe_repair.batch_ledger import LedgerSpendGuard
from swe_repair.spend import SpendLimitExceeded


def create(path, ceiling=1.0):
    path.write_text(json.dumps({'schema': 'cumulative-model-spend-v1', 'ceiling_cny': ceiling,
                                'records': [], 'pending': None}), encoding='utf-8')


def test_costs_survive_new_run_and_reduce_the_same_approved_ceiling():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'ledger.json'
        create(path)
        first = LedgerSpendGuard(path, 1.0, 'first')
        first.book(NS(cost_cny=.8, prompt_tokens=10, output_tokens=5, billing='estimated_from_usage'))
        first.close()
        second = LedgerSpendGuard(path, 1.0, 'second')
        try:
            assert abs(second.remaining_cny - .2) < 1e-9
            try: second.check_before('deepseek-flash', prompt_tokens=1000000, max_output_tokens=1)
            except SpendLimitExceeded: pass
            else: raise AssertionError('new tag reset the batch budget')
        finally: second.close()


def test_interrupted_reservation_blocks_retry_until_audit():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'ledger.json'
        create(path)
        first = LedgerSpendGuard(path, 1.0, 'first')
        first.reserve_before('deepseek-flash', prompt_tokens=100, max_output_tokens=100)
        first.close()
        second = LedgerSpendGuard(path, 1.0, 'second')
        try:
            assert second.pending and second.remaining_cny < 1
            try: second.check_before('deepseek-flash', max_output_tokens=1)
            except SpendLimitExceeded as exc: assert 'unreconciled' in str(exc)
            else: raise AssertionError('interrupted request was silently treated as free')
        finally: second.close()


def test_success_reconciles_reservation_and_unknown_failure_keeps_conservative_cost():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'ledger.json'
        create(path)
        guard = LedgerSpendGuard(path, 1.0, 'first')
        try:
            guard.reserve_before('deepseek-flash', prompt_tokens=1000, max_output_tokens=1000)
            reserved = guard.pending['cost_cny']
            guard.book(NS(cost_cny=.0001, prompt_tokens=1, output_tokens=1, billing='unknown'))
            assert guard.spent_cny == reserved and guard.pending is None
            guard.reserve_before('deepseek-flash', prompt_tokens=1000, max_output_tokens=1000)
            guard.book(NS(cost_cny=.0002, prompt_tokens=1, output_tokens=1, billing='estimated_from_usage'))
            assert abs(guard.spent_cny - reserved - .0002) < 1e-9
            assert len(json.loads(path.read_text())['records']) == 2
        finally: guard.close()


def test_concurrent_client_and_ceiling_change_are_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'ledger.json'
        create(path)
        guard = LedgerSpendGuard(path, 1.0, 'first')
        try:
            try: LedgerSpendGuard(path, 1.0, 'second')
            except (OSError, BlockingIOError): pass
            else: raise AssertionError('concurrent writer acquired the same batch')
        finally: guard.close()
        try: LedgerSpendGuard(path, 100.0, 'second')
        except ValueError: pass
        else: raise AssertionError('approved ceiling changed without ledger reconciliation')

