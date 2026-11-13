"""Offline checks of preparation identity and cleanup failure boundaries."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace

here = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("devprep", here / "prepare_dev23_offline.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
manifest = m.validate_manifest(here / "dev23_prepare_manifest_01.json")
checks = []
assert len(manifest["instances"]) == 23
for row in manifest["instances"]:
    compile(m.identity_program(row), "container_identity", "exec")
checks.append("complete23 manifest, pinned input/wheel hashes and generated identity syntax")
assert m.explicit_container_absence("Error: No such object: mine", "mine")
for text in ["daemon unavailable: mine", "permission denied: mine", "No such object: other"]:
    assert not m.explicit_container_absence(text, "mine")
checks.append("daemon/access errors cannot masquerade as missing owned container")

with tempfile.TemporaryDirectory(dir=here) as tmp:
    args = SimpleNamespace(tag="offline_selfcheck", context="unused")
    for label, reply in [
        ("daemon_unavailable", ({"exit_code": 1}, "daemon unavailable")),
        ("identity_reused", ({"exit_code": 0}, "wrongid otherlabel")),
    ]:
        out = Path(tmp) / label
        out.mkdir()
        p = m.Preparation(args, manifest, out)
        p.owned["mine"] = "expectedid"
        called = []
        def fake_docker(op, *arguments, **options):
            called.append((op, arguments))
            return reply
        p.docker = fake_docker
        try:
            p.clean("mine")
        except RuntimeError:
            pass
        else:
            raise AssertionError("cleanup accepted uncertain container identity")
        assert not any("rm" in a for _, a in called)
        assert "mine" in p.owned
        p.log.close()
    checks.append("uncertain/reused container identity refuses deletion and retains unresolved ownership")

report = {"status": "passed", "checks": checks, "docker_operations": 0, "network_calls": 0,
          "model_calls": 0, "script_sha256": m.digest(here / "prepare_dev23_offline.py"),
          "manifest_sha256": m.digest(here / "dev23_prepare_manifest_01.json"),
          "scope": "offline preparation boundaries only; actual imports/smokes still pending"}
with (here / "offline_selfcheck_01.json").open("x", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
    f.write("\n")
print(json.dumps(report))
