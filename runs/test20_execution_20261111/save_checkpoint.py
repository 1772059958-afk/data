"""Preserve the stopped session only; never run experimental entry points."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo
import zipfile

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
CHECKPOINT = Path(r"D:\CodexExperimentCache\test20_20261111\checkpoint")


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_new(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main():
    shutdown = read(OUT / "shutdown_audit.json")
    cost = read(OUT / "final_cost_audit.json")
    validation = read(OUT / "stop_validation.json")
    ledger = OUT / "batch_ledger.json"
    assert digest(ledger) == cost["ledger_sha256"]
    assert read(ledger)["pending"] is None
    assert not shutdown["experiment_containers_remaining"]
    assert not shutdown["docker_wsl_running"]
    assert shutdown["docker_desktop_stop_exit_code"] == 0
    resume = read(ROOT / "configs/dev_screen_resume_20261111.json")
    assert resume["execution"]["live_authorized"] is False
    assert not (OUT / "SESSION_SAVED.json").exists()
    check = subprocess.run(
        ["git", "-c", "core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol", "diff", "--check"],
        cwd=ROOT, capture_output=True,
    )
    with (OUT / "save_diff_check_crlf_aware.log").open("xb") as f:
        f.write(check.stdout + check.stderr)
    assert check.returncode == 0, "CRLF-aware diff check failed; source left unchanged"

    files = set()
    excluded_parts = {".env", ".venv", ".git", "__pycache__", ".pytest_cache"}
    self_refs = {"artifact_manifest.json", "project_archive.json", "SESSION_SAVED.json"}

    def add(path):
        if path.is_symlink():
            return
        if path.is_dir():
            for child in path.iterdir():
                if child.name not in excluded_parts:
                    add(child)
            return
        if not path.is_file():
            return
        rel = path.relative_to(ROOT)
        if any(x in excluded_parts for x in rel.parts):
            return
        if path.name.startswith(".env") or path.name in self_refs:
            return
        files.add(path)

    for name in ["runs/test20_execution_20261111", "runs/dev_screen_baseline_20261111_01", "runs/test20_preparation_20261111", "src/swe_repair", "tests", "docker"]:
        add(ROOT / name)
    matrix = read(ROOT / "runs/dev_screen_baseline_20261111_01/matrix.json")
    add(ROOT / "runs/prefix_cache" / matrix["config_hash"])
    for pattern in ["configs/*20261111*.json", "docs/*.md", "scripts/*.py", "requirements*.txt", "data/frozen/*.json", "data/frozen/instances*.txt"]:
        for path in ROOT.glob(pattern):
            add(path)
    for name in ["configs/proposal_v1.json", "scripts/score_all_arms.sh", "AGENTS.md", "README.md", ".gitattributes", ".gitignore", "reports/README.md", "dustbin/README.md", "dustbin/legacy_20261029/preservation_manifest.json", "dustbin/legacy_20261029/archive_inventory.json"]:
        add(ROOT / name)
    rows = [{"path": p.relative_to(ROOT).as_posix(), "size_bytes": p.stat().st_size, "sha256": digest(p)} for p in sorted(files)]
    manifest = OUT / "artifact_manifest.json"
    write_new(manifest, {
        "kind": "stopped_session_file_inventory", "status": "stopped_saved_not_frozen",
        "files": rows, "file_count": len(rows), "credentials_included": False,
        "self_references_excluded": sorted(self_refs),
        "source_bytes_preserved": True,
        "diff_check": {"crlf_aware_exit_code": check.returncode, "raw_check_log": "save_diff_check.log", "interpretation": "Raw check reports CRLF as trailing whitespace; CRLF-aware check passes. Source bytes left unchanged."},
    })
    CHECKPOINT.mkdir(parents=True, exist_ok=True)
    archive = CHECKPOINT / "project-session-20261111-stopped.zip"
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as z:
        for path in sorted(files | {manifest}):
            z.write(path, path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        assert len(z.infolist()) == len(files) + 1
    for row in rows:
        assert digest(ROOT / row["path"]) == row["sha256"], row["path"]
    archive_info = {
        "path": str(archive), "size_bytes": archive.stat().st_size, "sha256": digest(archive),
        "included_files": len(files) + 1, "zip_crc_verified": True,
        "exclusions": [".env and credential files", ".venv", ".git", "bytecode", "external Docker VHDX and public caches, separately preserved"],
    }
    write_new(OUT / "project_archive.json", archive_info)
    handoff = ROOT / "docs/现场保存与续跑_20261111.md"
    saved = {
        "kind": "stopped_experiment_session_checkpoint",
        "saved_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "status": "stopped_saved_not_frozen",
        "user_stop_instruction": "dev也留下次 现在直接进行现场保存",
        "handoff": {"path": handoff.relative_to(ROOT).as_posix(), "sha256": digest(handoff)},
        "configuration_frozen": False, "full_dev23_calibration_complete": False,
        "new_prediction_independent_scoring_complete": False, "formal_test20_started": False,
        "cost": cost,
        "owned_experiment_processes_remaining": read(OUT / "owned_process_audit.json")["count"],
        "containers_remaining": [], "docker_desktop_stopped": True, "docker_wsl_running": False,
        "preserved_image_tag_rows": shutdown["image_tag_rows_preserved"],
        "active_docker_data": shutdown["active_data_directory_preserved"],
        "cold_backup": shutdown["current_checkpoint_backup"],
        "project_archive": archive_info, "artifact_manifest": manifest.relative_to(ROOT).as_posix(),
        "resume_config": "configs/dev_screen_resume_20261111.json", "resume_config_live_authorized": False,
        "requires_explicit_user_resume": True, "scheduled_restart": False,
        "drafts_pending": ["dev23 environment runner final self-check", "dev23 preparation manifest", "nose-only dependency lock"],
        "validation": validation, "source_bytes_modified_during_save": False,
        "commit_or_push_performed": False, "model_calls_during_save": 0,
    }
    write_new(OUT / "SESSION_SAVED.json", saved)
    for name in ["SESSION_SAVED.json", "project_archive.json", "artifact_manifest.json"]:
        target = CHECKPOINT / name
        assert not target.exists(), target
        shutil.copy2(OUT / name, target)
        assert digest(target) == digest(OUT / name)
    assert digest(ledger) == cost["ledger_sha256"]
    print(json.dumps({"status": saved["status"], "cost_estimate_cny": cost["booked_estimate_cny"], "pending": None, "docker_stopped": True, "files_archived": archive_info["included_files"], "archive_size_bytes": archive_info["size_bytes"], "archive": str(archive)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
