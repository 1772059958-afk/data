"""Bounded public error evidence and session-scoped, paginated raw log access.

This module never reads files or evaluator artifacts. Log references resolve
only against captured generation-side failure records supplied by the caller.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
LOG_REF = re.compile(r"log:[0-9a-f]{64}\Z")
EXCEPTION = re.compile(r"\b\w*(?:Error|Exception|Interrupt|Exit)\b(?::|$)")
FRAME = re.compile(r'File "[^"]+", line \d+|\S+\.py:\d+(?::|\b)')
ASSERTION = re.compile(r"^\s*(?:[E>]\s|assert\b|raise\b|FAILED\b|ERROR\b)")
FEEDBACK_LIMIT = 3000
PAGE_LIMIT = 3000


@dataclass
class ToolFeedback:
    observation: str
    progressed: bool
    record: object

    def __iter__(self):
        # Keep existing display callers and test doubles' two-value contract.
        yield self.observation
        yield self.progressed


def log_reference(raw: str) -> str | None:
    return 'log:' + hashlib.sha256(raw.encode('utf-8')).hexdigest() if raw else None


def _short(text: str, size: int) -> str:
    if len(text) <= size:
        return text
    # Preserve the exception value at the end of an unusually long line too.
    half = (size - 5) // 2
    return text[:half] + ' ... ' + text[-half:]


def error_evidence(raw: str, limit: int = 2400) -> str:
    """Select exceptions, assertion context, exact frames and tail, deterministically.

    L numbers address the original captured log. Source frame line numbers and
    exception values are left intact, unlike the separate fingerprint normalizer.
    """
    lines = raw.splitlines()
    clean = [ANSI.sub('', line) for line in lines]
    exceptions = [i for i, line in enumerate(clean) if EXCEPTION.search(line)]
    assertions = [i for i, line in enumerate(clean) if ASSERTION.search(line)]
    frames = [i for i, line in enumerate(clean) if FRAME.search(line)]
    sections = [('Exceptions', exceptions, 650), ('Assertions', assertions, 600),
                ('Frames and source', [j for i in frames for j in (i, i + 1) if j < len(lines)], 750),
                ('Output tail', list(range(max(0, len(lines) - 8), len(lines))), 350)]
    selected, output = set(), []
    for title, indices, cap in sections:
        rows, used = [], 0
        for i in reversed(indices):
            if i in selected or not clean[i].strip():
                continue
            room = cap - used
            if room < 50:
                break
            row = _short(f'L{i + 1}: {clean[i]}', min(360, room - 1))
            rows.append((i, row))
            selected.add(i)
            used += len(row) + 1
        if rows:
            output.append(title + ':\n' + '\n'.join(row for _, row in sorted(rows)))
    return _short('\n'.join(output), limit)


def failure_view(record) -> dict:
    """A prompt view, explicitly excluding the full raw output from serialization."""
    raw = record.raw_output
    return {'stage': record.stage, 'command': _short(record.command, 300),
            'exit_code': record.exit_code, 'error_class': record.error_class,
            'fingerprint': record.fingerprint,
            'candidate_index': getattr(record, 'candidate_index', None),
            'recovery_attempts': record.recovery_attempts,
            'log_ref': log_reference(raw), 'log_lines': len(raw.splitlines()),
            'evidence': error_evidence(raw) if raw else _short(record.message_head, 1200),
            'raw_available': bool(raw)}


def failure_feedback(record) -> str:
    view = failure_view(record)
    header = (f"stage={view['stage']}; command={view['command']}; exit_code={view['exit_code']}; "
              f"error_class={view['error_class']}; candidate={view['candidate_index']}\n")
    if view['log_ref']:
        header += f"{view['log_ref']} ({view['log_lines']} lines); read_region can read the raw log.\n"
    else:
        header += 'Raw log unavailable in this legacy record.\n'
    return header + view['evidence'][:max(0, FEEDBACK_LIMIT - len(header))]


def read_failure_log(records, reference: str, start: int, end: int, offset: int = 0) -> tuple[str, bool]:
    """Read bounded exact log text without touching the container or filesystem.

    offset is a character offset within start's line. The returned cursor allows
    lossless continuation even when one original line exceeds the page budget.
    """
    if not LOG_REF.fullmatch(reference):
        return 'Invalid captured-log reference.', False
    record = next((r for r in records if log_reference(r.raw_output) == reference), None)
    if record is None:
        return 'Captured log is not available in this branch state.', False
    if (any(isinstance(v, bool) or not isinstance(v, int) for v in (start, end, offset))
            or start < 1 or end < start or offset < 0):
        return 'Invalid log range: positive start <= end and nonnegative offset required.', False
    lines = record.raw_output.splitlines(keepends=True)
    if start > len(lines) or offset >= len(lines[start - 1]):
        return 'Log range or offset is outside the captured output.', False
    stop = min(end, start + 119, len(lines))
    header = f'{reference} lines {start}-{stop}/{len(lines)}; offset={offset}\n'
    chunks, remaining, cursor = [], PAGE_LIMIT - len(header) - 200, None
    for i in range(start - 1, stop):
        line = lines[i]
        begin = offset if i == start - 1 else 0
        part = line[begin:begin + remaining]
        chunks.append(part)
        remaining -= len(part)
        if begin + len(part) < len(line):
            cursor = (i + 1, begin + len(part))
            break
        if remaining <= 0:
            cursor = (i + 2, 0) if i + 1 < len(lines) else None
            break
    else:
        cursor = (stop + 1, 0) if stop < len(lines) else None
    footer = (f'\nNext: read_region path={reference} start={cursor[0]} end={max(end, cursor[0])} offset={cursor[1]}'
              if cursor else '\nEnd of captured log.')
    return header + ''.join(chunks) + footer, True
