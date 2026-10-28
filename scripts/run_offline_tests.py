"""A minimal test runner, used when pytest is not installed in the venv.

The offline tests are plain ``def test_*()`` functions with no fixtures and no
pytest imports, so running them needs nothing but ``importlib`` and a traceback
printer. This exists so the suite is never blocked on installing a package in an
environment that has no route to a package index.

    /opt/swe-env/bin/python scripts/run_offline_tests.py
    /opt/swe-env/bin/python scripts/run_offline_tests.py tests/test_cf.py
"""

from __future__ import annotations

import importlib.util
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
TESTS = os.path.join(REPO, "tests")
sys.path.insert(0, os.path.join(REPO, "src"))


def load_module(path: str):
    name = "offline_" + os.path.basename(path)[:-3]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main(argv: list[str]) -> int:
    paths = argv or sorted(
        os.path.join(TESTS, f) for f in os.listdir(TESTS)
        if f.startswith("test_") and f.endswith(".py")
    )
    total = passed = 0
    failures: list[tuple[str, str, str]] = []
    for path in paths:
        label = os.path.basename(path)
        try:
            module = load_module(path)
        except Exception:
            failures.append((label, "<import>", traceback.format_exc()))
            total += 1
            continue
        names = sorted(n for n in dir(module) if n.startswith("test_") and callable(getattr(module, n)))
        print(f"{label}: {len(names)} test(s)")
        for name in names:
            total += 1
            try:
                getattr(module, name)()
                passed += 1
            except Exception:
                failures.append((label, name, traceback.format_exc()))

    print()
    for label, name, tb in failures:
        print(f"FAIL {label}::{name}")
        print(tb)
    print(f"{passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
