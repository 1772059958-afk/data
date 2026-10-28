"""Small helpers for reading unified diffs without applying them.

These exist so that candidate bookkeeping uses a real parser over the diff
text instead of counting lines with string searches. The functions are
deliberately tolerant: a candidate that fails to parse is still recorded, with
``parsed=False``, because a malformed candidate is itself an observation.
"""

from __future__ import annotations

import posixpath
import re

_DIFF_HEADER = re.compile(r"^diff --git (?:\"?a/)?(\S+?)\"? (?:\"?b/)?(\S+?)\"?\s*$")
_MINUS_FILE = re.compile(r"^--- (?:a/)?(.+?)(?:\t.*)?$")
_PLUS_FILE = re.compile(r"^\+\+\+ (?:b/)?(.+?)(?:\t.*)?$")

_DEV_NULL = "/dev/null"


def _clean(path: str) -> str:
    raw = path.strip().replace("\\", "/")
    if raw.startswith("a/") or raw.startswith("b/"):
        raw = raw[2:]
    return posixpath.normpath(raw) if raw else ""


def files_touched(diff_text: str) -> tuple[str, ...]:
    """Repository-relative paths a unified diff modifies, in first-seen order."""
    seen: dict[str, None] = {}
    for line in (diff_text or "").replace("\r\n", "\n").split("\n"):
        match = _DIFF_HEADER.match(line)
        if match:
            path = _clean(match.group(2))
            if path and path != _DEV_NULL:
                seen.setdefault(path, None)
            continue
        match = _PLUS_FILE.match(line)
        if match:
            path = _clean(match.group(1))
            if path and path != _DEV_NULL:
                seen.setdefault(path, None)
    return tuple(seen)


def count_diff_lines(diff_text: str) -> int:
    """Changed lines: added plus removed, ignoring file headers and context."""
    changed = 0
    for line in (diff_text or "").replace("\r\n", "\n").split("\n"):
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+") or line.startswith("-"):
            changed += 1
    return changed


def parse_ok(diff_text: str) -> bool:
    """Whether the diff has the structural minimum of a unified diff."""
    text = diff_text or ""
    if "---" not in text or "+++" not in text:
        return False
    hunks = [line for line in text.split("\n") if line.startswith("@@")]
    return bool(hunks) and bool(files_touched(text))


def normalise(diff_text: str) -> str:
    """Whitespace-normalised diff, used when comparing candidates by eye."""
    lines = [line.rstrip() for line in (diff_text or "").replace("\r\n", "\n").split("\n")]
    return "\n".join(lines).strip()


_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")


def repair_hunk_headers(patch: str) -> tuple[str, int]:
    """Recompute the line counts in every ``@@`` header from the hunk body.

    Models routinely write a header whose counts do not match the body that
    follows. ``git apply`` rejects those outright ("malformed patch") even when
    the edit itself is right, so a wrong header looks like a wrong fix. Counting
    the body is mechanical, so it belongs here rather than in the prompt.

    Returns ``(patch, number_of_headers_rewritten)``.
    """
    lines = (patch or "").splitlines()
    out: list[str] = []
    repaired = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        match = _HUNK_HEADER.match(line)
        if not match:
            out.append(line)
            i += 1
            continue

        old_start, _, new_start, _, tail = match.groups()
        body: list[str] = []
        j = i + 1
        while j < len(lines):
            nxt = lines[j]
            if nxt.startswith("@@ ") or nxt.startswith("diff --git"):
                break
            # A new file section starts with "--- a/..." immediately followed by
            # "+++ b/..."; a hunk body line can also begin with "---", so only
            # the pair counts as a boundary.
            if (nxt.startswith("--- ") and j + 1 < len(lines)
                    and lines[j + 1].startswith("+++ ")):
                break
            body.append(nxt)
            j += 1

        old_n = new_n = 0
        for entry in body:
            if entry.startswith("\\"):        # "\ No newline at end of file"
                continue
            if entry.startswith("+"):
                new_n += 1
            elif entry.startswith("-"):
                old_n += 1
            else:                             # context line, possibly empty
                old_n += 1
                new_n += 1

        if f"{match.group(2) or 1},{match.group(4) or 1}" != f"{old_n},{new_n}":
            repaired += 1
        out.append(f"@@ -{old_start},{old_n} +{new_start},{new_n} @@{tail}")
        out.extend(body)
        i = j

    return "\n".join(out).rstrip() + "\n", repaired
