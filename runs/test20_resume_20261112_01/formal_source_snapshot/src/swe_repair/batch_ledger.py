"""Durable cumulative money guard shared by sequential experiment runs.

An OS lock excludes concurrent clients. A reservation is persisted before each
HTTP attempt; an interrupted attempt requires reconciliation, never a free retry.
"""
from __future__ import annotations
import atexit
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace
import uuid

from .spend import SpendGuard, SpendLimitExceeded, SpendPolicy


class LedgerSpendGuard(SpendGuard):
    def __init__(self, path: Path, ceiling_cny: float, run_id: str):
        super().__init__(SpendPolicy(ceiling_cny=ceiling_cny), approved=True)
        self.path, self.run_id = Path(path), run_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.pending = None
        self._lock = open(self.path.with_suffix('.lock'), 'a+b')
        try:
            self._lock.seek(0, 2)
            if self._lock.tell() == 0:
                self._lock.write(b'0')
                self._lock.flush()
            self._lock.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self._lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            if not self.path.exists():
                raise ValueError('initialize and audit the batch ledger before live execution')
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if data.get('schema') != 'cumulative-model-spend-v1' or data.get('ceiling_cny') != ceiling_cny:
                raise ValueError('batch ledger schema or approved ceiling differs')
            self.pending = data.get('pending')
            for row in data['records']:
                value = row.get('cost_cny')
                if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                    raise ValueError('invalid booked cost in ledger')
                self.records.append(SimpleNamespace(**row))
            self.starting_spent_cny = self.spent_cny
            atexit.register(self.close)
        except Exception:
            self._lock.close()
            raise

    @property
    def spent_cny(self):
        return sum(float(r.cost_cny) for r in self.records)

    @property
    def remaining_cny(self):
        pending = float(self.pending['cost_cny']) if self.pending else 0.0
        return self.policy.ceiling_cny - self.spent_cny - pending

    def check_before(self, *args, **kwargs):
        if self.pending:
            raise SpendLimitExceeded('unreconciled request reservation; audit before another attempt')
        return super().check_before(*args, **kwargs)

    def reserve_before(self, model, *, prompt_tokens=None, max_output_tokens):
        cost = self.check_before(model, prompt_tokens=prompt_tokens, max_output_tokens=max_output_tokens)
        self.pending = {'reservation_id': uuid.uuid4().hex, 'run_id': self.run_id,
                        'cost_cny': cost, 'billing': 'unknown', 'model': model}
        self._save()

    def book(self, record):
        row = record.as_dict() if hasattr(record, 'as_dict') else dict(vars(record))
        row['run_id'] = self.run_id
        if self.pending:
            row['reservation_id'] = self.pending['reservation_id']
            if row.get('billing') == 'unknown':
                row['cost_cny'] = max(float(row['cost_cny']), self.pending['cost_cny'])
        self.records.append(SimpleNamespace(**row))
        self.pending = None
        self._save()
        if self.spent_cny > self.policy.ceiling_cny + 1e-9:
            raise SpendLimitExceeded('cumulative model ceiling crossed; cost retained')

    def _save(self):
        data = {'schema': 'cumulative-model-spend-v1', 'ceiling_cny': self.policy.ceiling_cny,
                'records': [vars(r) for r in self.records], 'pending': self.pending}
        tmp = self.path.with_suffix('.tmp')
        with tmp.open('w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        tmp.replace(self.path)

    def close(self):
        if self._lock and not self._lock.closed:
            self._lock.close()

