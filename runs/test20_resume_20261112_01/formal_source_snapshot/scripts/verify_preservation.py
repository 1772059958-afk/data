"""Read-only SHA-256 verification of the original experiment assets.

The baseline was captured before proposal-alignment edits. New files are
allowed, but none of the original data/report bytes may change or disappear.
This utility never rewrites the manifest and never contacts a service.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "dustbin/legacy_20261029/preservation_manifest.json"
ARCHIVE_INVENTORY = ROOT / "dustbin/legacy_20261029/archive_inventory.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(root: Path = ROOT, manifest: Path = DEFAULT_MANIFEST) -> dict:
    root = root.resolve()
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    protected = payload.get("protected_files")
    if not isinstance(protected, dict) or not protected:
        raise ValueError("manifest has no protected_files map")
    missing, changed, invalid = [], [], []
    for relative, expected in sorted(protected.items()):
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            invalid.append(relative)
            continue
        if not relative.startswith(("data/", "reports/")) or len(expected) != 64:
            invalid.append(relative)
        elif not path.is_file():
            missing.append(relative)
        elif sha256(path) != expected:
            changed.append(relative)
    return {
        "baseline_commit": payload.get("baseline_commit"),
        "protected_total": len(protected),
        "verified": len(protected) - len(missing) - len(changed) - len(invalid),
        "missing": missing,
        "changed": changed,
        "invalid": invalid,
        "ok": not (missing or changed or invalid),
    }


def verify_archive(inventory: Path = ARCHIVE_INVENTORY) -> dict:
    payload = json.loads(inventory.read_text(encoding="utf-8"))
    base = inventory.parent.resolve()
    missing, changed, invalid = [], [], []
    for relative, expected in sorted(payload["files"].items()):
        path = (base / relative).resolve()
        try:
            path.relative_to(base)
        except ValueError:
            invalid.append(relative)
            continue
        if not path.is_file():
            missing.append(relative)
        elif sha256(path) != expected:
            changed.append(relative)
    return {"archived_total": len(payload["files"]), "missing": missing,
            "changed": changed, "invalid": invalid,
            "ok": not (missing or changed or invalid)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--archive", action="store_true", help="also verify retired originals")
    args = parser.parse_args(argv)
    report = {"experiments": verify(manifest=args.manifest)}
    if args.archive:
        report["archive"] = verify_archive()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if all(item["ok"] for item in report.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
