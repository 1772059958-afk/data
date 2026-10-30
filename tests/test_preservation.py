"""Integrity checks must detect changed/missing originals, not repair the baseline."""
import importlib.util
import json
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("verify_preservation_for_tests", ROOT / "scripts/verify_preservation.py")
preservation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preservation)


def fixture(root):
    (root / "data").mkdir()
    asset = root / "data/example.txt"
    asset.write_bytes(b"original evidence\r\n")
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps({"protected_files": {"data/example.txt": preservation.sha256(asset)}}), encoding="utf-8")
    return asset, manifest


def temp_root():
    base = ROOT / "work/preservation_tests"
    base.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(dir=base)


def test_protected_originals_and_archive_are_intact():
    assert preservation.verify()["ok"]
    assert preservation.verify_archive()["ok"]
    historical = ROOT / 'dustbin/legacy_20261029/docs/实验记录.md'
    assert (ROOT / 'docs/实验记录.md').read_bytes().startswith(historical.read_bytes())


def test_modification_is_reported_without_rewriting_evidence_or_manifest():
    with temp_root() as tmp:
        root = Path(tmp)
        asset, manifest = fixture(root)
        baseline = manifest.read_bytes()
        asset.write_bytes(b"changed")
        report = preservation.verify(root, manifest)
        assert report["changed"] == ["data/example.txt"]
        assert not report["ok"]
        assert manifest.read_bytes() == baseline
        assert asset.read_bytes() == b"changed"


def test_missing_original_is_not_silently_ignored():
    with temp_root() as tmp:
        root = Path(tmp)
        asset, manifest = fixture(root)
        asset.unlink()
        report = preservation.verify(root, manifest)
        assert report["missing"] == ["data/example.txt"]
        assert report["verified"] == 0
        assert not report["ok"]


def test_manifest_cannot_escape_workspace():
    with temp_root() as tmp:
        root = Path(tmp)
        _, manifest = fixture(root)
        manifest.write_text(json.dumps({"protected_files": {"../outside.txt": "0" * 64}}), encoding="utf-8")
        report = preservation.verify(root, manifest)
        assert report["invalid"] == ["../outside.txt"]
        assert not report["ok"]
