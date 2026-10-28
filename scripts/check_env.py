"""Check whether this machine can run the containerised SWE-bench pipeline.

Reports, in the order they block progress: the container runtime, the registry
mirror, the Python harness, and the frozen dataset. Exits non-zero if any
blocking requirement is missing.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):  # pragma: no cover
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIRRORS = (
    "https://docker.m.daocloud.io/v2/",
    "https://docker.1panel.live/v2/",
)

results: list[tuple[str, bool, str]] = []


def add(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))


def check_container_runtime() -> None:
    exe = shutil.which("docker") or shutil.which("podman")
    if not exe:
        add("container runtime", False,
            "docker/podman not found on PATH. Run scripts/setup_docker.ps1 in an elevated "
            "PowerShell window, then reboot if prompted.")
        return
    try:
        out = subprocess.run([exe, "info", "--format", "{{.ServerVersion}}"],
                             capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            add("container runtime", False,
                f"{os.path.basename(exe)} found but the daemon is not reachable: "
                f"{out.stderr.strip()[:160]}")
            return
        add("container runtime", True, f"{os.path.basename(exe)} {out.stdout.strip()}")
    except Exception as exc:  # noqa: BLE001
        add("container runtime", False, f"{type(exc).__name__}: {exc}")


def check_registry_mirrors() -> None:
    reachable = []
    for url in MIRRORS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "docker/24.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status in (200, 401):  # 401 is the normal registry greeting
                    reachable.append(url)
        except Exception:  # noqa: BLE001
            continue
    add("registry mirror", bool(reachable),
        ", ".join(reachable) if reachable else "no mirror reachable; image pulls will fail")


def check_harness() -> None:
    spec = importlib.util.find_spec("swebench")
    add("python harness", spec is not None,
        "swebench installed" if spec else "run: pip install swebench")


def check_dataset() -> None:
    path = os.path.join(ROOT, "data", "frozen", "manifest.json")
    if not os.path.exists(path):
        add("frozen dataset", False, "run: python scripts/freeze_dataset.py")
        return
    with open(path, encoding="utf-8") as fh:
        manifest = json.load(fh)
    counts = {k: v["n_instances"] for k, v in manifest["splits"].items()}
    add("frozen dataset", True,
        f"revision {manifest['revision'][:10]}... splits {counts}")


def main() -> int:
    check_container_runtime()
    check_registry_mirrors()
    check_harness()
    check_dataset()

    width = max(len(n) for n, _, _ in results)
    blocking = 0
    for name, ok, detail in results:
        mark = "OK  " if ok else "FAIL"
        if not ok:
            blocking += 1
        print(f"[{mark}] {name.ljust(width)}  {detail}")
    print()
    if blocking:
        print(f"{blocking} blocking item(s).")
    else:
        print("environment ready for the containerised pipeline.")
    return 1 if blocking else 0


if __name__ == "__main__":
    raise SystemExit(main())
