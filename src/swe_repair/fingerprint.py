"""Error classification and fingerprints for repair failures.

The router may only look at what the generation stage can observe: exit codes,
captured output and stack frames. Evaluation labels are not available here and
must never become available. This module turns raw output into two stable
quantities:

* ``ErrorClass`` -- one of the five categories named in section 4.2 of the
  proposal: patch format, syntax or import, behavioural assertion, missing
  public tests, environment preparation.
* ``fingerprint`` -- a short digest of the normalised message, so that "the
  same failure again" is detectable while genuinely different failures stay
  apart. Absolute paths are rewritten relative to the repository root, line
  numbers collapse to a placeholder and memory addresses are dropped; file
  names, symbols and error text are kept.

Classification is deliberately shallow. It exists to feed routing and failure
statistics, not to explain a bug. Every ambiguous case falls through to
``unknown`` rather than guessing, because a wrong category propagates straight
into a routing decision.
"""

from __future__ import annotations

import hashlib
import os
import posixpath
import re
from typing import Iterable, NamedTuple

# SWE-bench instances check the repository out at /testbed inside the container.
DEFAULT_REPO_ROOTS = ("/testbed", "/repo", "/workspace")

CLASSES = (
    "patch_format",
    "syntax_or_import",
    "behaviour_assertion",
    "public_test_missing",
    "env_setup",
    "unknown",
)

# Stages that the driver reports when it runs a command. They are the primary
# signal; the text patterns below only matter when the stage is generic.
STAGES = ("index", "localize", "generate", "apply_patch", "syntax_check", "test", "env", "repro")

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_ADDRESS = re.compile(r"0x[0-9a-fA-F]{4,}")
_FRAME = re.compile(r'File "([^"]+)", line (\d+)(?:, in (\S+))?')
_LINE_NO = re.compile(r"(line )(\d+)")
_TRACEBACK_HEAD = re.compile(r"^Traceback \(most recent call last\):", re.MULTILINE)

_ENV_PATTERNS = (
    r"could not find a version that satisfies the requirement",
    r"no matching distribution found",
    r"temporary failure in name resolution",
    r"could not resolve host",
    r"name or service not known",
    r"connection refused",
    r"connection reset by peer",
    r"read timed out",
    r"ssl: certificate_verify_failed",
    r"cannot connect to the docker daemon",
    r"failed to solve",
    r"failed to pull",
    r"error: subprocess-exited-with-error",
    r"is not a valid editable requirement",
    r"condahttperror",
    r"apt-get: (?:command )?not found|e: unable to locate package",
    r"no space left on device",
)

_PATCH_PATTERNS = (
    r"error: patch failed",
    r"patch does not apply",
    r"does not apply cleanly",
    r"corrupt patch at line",
    r"fatal: git apply",
    r"invalid patch",
    r"unexpected end of \S*input",
)

_MISSING_TEST_PATTERNS = (
    r"no tests ran",
    r"collected 0 items",
    r"error: not found: ",
    r"file or directory not found",
    r"no test matches the given testcase filter",
    r"module contains no tests",
)

_SYNTAX_PATTERNS = (
    r"\bsyntaxerror\b",
    r"\bindentationerror\b",
    r"\btaberror\b",
    r"\bmodulenotfounderror\b",
    r"\bimporterror\b",
    r"\bcannot import name\b",
    r"unexpected token",
)

_ASSERTION_PATTERNS = (
    r"\bassertionerror\b",
    r"^e\s+assert",
    r"^\s*assert\s+\w",
    r"^failed\s+\S+::",
    r"\b\d+ failed\b",
    r"\btest failed\b",
    r"selenium\.common\.exceptions",
)

# pytest exits 5 when a selection collects no tests at all.
_PYTEST_NO_TESTS_EXIT = 5


class Frame(NamedTuple):
    path: str  # repository-relative, POSIX separators
    line: int
    func: str


def strip_ansi(text: str) -> str:
    return _ANSI.sub("", text or "")


def normalise_repo_path(path: str, repo_root: str | os.PathLike[str] | None = None) -> str:
    """Rewrite a path to a repository-relative POSIX path.

    Absolute container paths are the norm (``/testbed/django/db/x.py``), and a
    fingerprint that keeps them would differ between machines. Anything that
    cannot be placed inside a known root keeps its basename.
    """
    raw = str(path).replace("\\", "/").strip()
    if not raw:
        return ""
    roots: list[str] = []
    if repo_root:
        roots.append(str(repo_root).replace("\\", "/").rstrip("/"))
    roots.extend(DEFAULT_REPO_ROOTS)
    for root in roots:
        if raw == root:
            return ""
        if raw.startswith(root + "/"):
            return raw[len(root) + 1 :]
    if not raw.startswith("/"):
        return posixpath.normpath(raw).lstrip("./")
    return posixpath.basename(raw)


def parse_frames(text: str, repo_root: str | os.PathLike[str] | None = None) -> tuple[Frame, ...]:
    """Extract ``File "...", line N, in func`` frames from captured output."""
    frames: list[Frame] = []
    for match in _FRAME.finditer(strip_ansi(text or "")):
        path = normalise_repo_path(match.group(1), repo_root)
        if not path:
            continue
        frames.append(Frame(path, int(match.group(2)), match.group(3) or "?"))
    return tuple(frames)


def repo_frames(text: str, repo_root: str | os.PathLike[str] | None = None) -> tuple[str, ...]:
    """Distinct repository files named by stack frames, in first-seen order."""
    seen: dict[str, None] = {}
    for frame in parse_frames(text, repo_root):
        if frame.path.endswith(".py"):
            seen.setdefault(frame.path, None)
    return tuple(seen)


def _head_of_error(text: str) -> str:
    """Keep the last traceback, or the whole text when there is none."""
    body = strip_ansi(text or "")
    heads = list(_TRACEBACK_HEAD.finditer(body))
    if heads:
        body = body[heads[-1].start() :]
    return body


def normalise_message(text: str, repo_root: str | os.PathLike[str] | None = None, limit: int = 30) -> str:
    """Normalise captured output into a stable, comparable form."""
    body = _head_of_error(text)
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    body = _ADDRESS.sub("0xADDR", body)

    def _frame_sub(match: re.Match[str]) -> str:
        path = normalise_repo_path(match.group(1), repo_root)
        func = f", in {match.group(3)}" if match.group(3) else ""
        return f'File "{path}", line N{func}'

    body = _FRAME.sub(_frame_sub, body)
    body = _LINE_NO.sub(r"\1N", body)
    # Absolute paths that are not stack frames (e.g. tmp dirs) are noise.
    body = re.sub(r"/(?:tmp|var/tmp|private/var)/[^\s\"']+", "/TMP", body)
    lines = [line.rstrip() for line in body.split("\n")]
    lines = [line for line in lines if line]
    return "\n".join(lines[:limit])


def classify(
    exit_code: int | None,
    text: str = "",
    stage: str | None = None,
) -> str:
    """Return one of ``CLASSES`` for a captured command outcome."""
    body = strip_ansi(text or "").lower()
    code = exit_code if exit_code is not None else 0

    if stage in ("env", "index") and code != 0:
        return "env_setup"
    if stage == "apply_patch" and code != 0:
        return "patch_format"
    if stage == "test" and code == _PYTEST_NO_TESTS_EXIT:
        return "public_test_missing"

    if any(re.search(p, body, re.MULTILINE) for p in _ENV_PATTERNS):
        return "env_setup"
    if any(re.search(p, body, re.MULTILINE) for p in _PATCH_PATTERNS):
        return "patch_format"
    if any(re.search(p, body, re.MULTILINE) for p in _MISSING_TEST_PATTERNS):
        return "public_test_missing"
    if code != 0 and stage == "test":
        if any(re.search(p, body, re.MULTILINE) for p in _ASSERTION_PATTERNS):
            return "behaviour_assertion"
        if any(re.search(p, body, re.MULTILINE) for p in _SYNTAX_PATTERNS):
            return "syntax_or_import"
    if any(re.search(p, body, re.MULTILINE) for p in _SYNTAX_PATTERNS):
        return "syntax_or_import"
    if any(re.search(p, body, re.MULTILINE) for p in _ASSERTION_PATTERNS):
        return "behaviour_assertion"
    return "unknown"


def fingerprint(
    text: str,
    error_class: str | None = None,
    repo_root: str | os.PathLike[str] | None = None,
) -> str:
    """Short digest of a normalised failure message.

    The class is part of the digest so that two messages with identical text
    but different classification cannot collide.
    """
    payload = f"{error_class or 'unknown'}\n{normalise_message(text, repo_root)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def describe(
    exit_code: int | None,
    stdout: str = "",
    stderr: str = "",
    stage: str | None = None,
    repo_root: str | os.PathLike[str] | None = None,
) -> dict[str, object]:
    """One-shot summary used by the executor when it records a failure."""
    combined = "\n".join(part for part in (stdout, stderr) if part)
    error_class = classify(exit_code, combined, stage)
    return {
        "stage": stage or "unknown",
        "exit_code": exit_code if exit_code is not None else -1,
        "error_class": error_class,
        "fingerprint": fingerprint(combined, error_class, repo_root),
        "repo_frames": repo_frames(combined, repo_root),
        "message_head": normalise_message(combined, repo_root, limit=4),
    }


def distinct(fingerprints: Iterable[str]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for value in fingerprints:
        if value:
            seen.setdefault(value, None)
    return tuple(seen)
