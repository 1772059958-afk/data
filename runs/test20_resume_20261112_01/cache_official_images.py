"""Cache hash-verified official test20 OCI blobs; never start a container."""
import concurrent.futures
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import threading
import time

from official_registry import HERE, PublicRegistry

CACHE = Path(r"D:\CodexExperimentCache\test20_20261111\official_oci_20261112")
RESERVE = 4 * 1024**3
stop = threading.Event()
lock = threading.Lock()


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for data in iter(lambda: f.read(1024**2), b""):
            h.update(data)
    return "sha256:" + h.hexdigest()


def cache_blob(item):
    digest, descriptor, repository = item
    target = CACHE / "blobs/sha256" / digest.removeprefix("sha256:")
    if target.exists():
        assert target.stat().st_size == descriptor["size"] and sha(target) == digest
        return {"digest": digest, "status": "verified_existing", "size_bytes": target.stat().st_size}
    if stop.is_set():
        return {"digest": digest, "status": "not_started_after_breakpoint"}
    partial = target.with_suffix(".partial")
    h = hashlib.sha256()
    size = 0
    started = time.monotonic()
    try:
        client = PublicRegistry(repository)
        with client.open("blobs", digest, timeout=60) as response, partial.open("xb") as f:
            while True:
                if stop.is_set():
                    raise RuntimeError("another cache request reached a breakpoint")
                if shutil.disk_usage(CACHE).free < RESERVE + 64 * 1024**2:
                    raise RuntimeError("disk reserve reached")
                data = response.read(1024**2)
                if not data:
                    break
                f.write(data)
                h.update(data)
                size += len(data)
            f.flush()
            os.fsync(f.fileno())
        assert size == descriptor["size"] and "sha256:" + h.hexdigest() == digest
        assert not target.exists()
        partial.rename(target)
        row = {"digest": digest, "status": "downloaded_sha256_verified", "size_bytes": size,
               "seconds": round(time.monotonic() - started, 3)}
    except Exception as exc:
        stop.set()
        row = {"digest": digest, "status": "failed_breakpoint", "error_type": type(exc).__name__,
               "http_status": getattr(exc, "code", None), "partial_bytes": size,
               "partial_path": str(partial), "model_calls": 0}
    with lock, (HERE / "official_oci_download_events.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps(row) + "\n")
        log.flush()
        os.fsync(log.fileno())
    return row


def main():
    inventory = json.loads((HERE / "official_test20_registry_inventory_01.json").read_text(encoding="utf-8"))
    assert len(inventory["instances"]) == 20 and all(r["status"] == "verified_public_manifest" for r in inventory["instances"])
    CACHE.mkdir(parents=True, exist_ok=False)
    (CACHE / "blobs/sha256").mkdir(parents=True)
    for p in (HERE / "registry_metadata").glob("*.json"):
        assert hashlib.sha256(p.read_bytes()).hexdigest() == p.stem
        shutil.copy2(p, CACHE / "blobs/sha256" / p.stem)
    inputs = {}
    for row in inventory["instances"]:
        for descriptor in [row["config"], *row["layers"]]:
            inputs.setdefault(descriptor["digest"], (descriptor, row["repository"]))
    missing_bytes = sum(d["size"] for d, _ in inputs.values())
    assert shutil.disk_usage(CACHE).free > missing_bytes + RESERVE + 4 * 1024**3
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        rows = list(pool.map(cache_blob, [(digest, descriptor, repository) for digest, (descriptor, repository) in inputs.items()]))
    result = {"kind": "official_oci_blob_cache", "cache": str(CACHE), "tls_verified": True,
              "credential_files_read": False, "anonymous_tokens_saved": False, "model_calls": 0,
              "docker_loads": 0, "containers_started": 0,
              "all_blobs_verified": not stop.is_set() and all(r["status"] in ("verified_existing", "downloaded_sha256_verified") for r in rows),
              "blobs": rows, "cache_excludes_project_credentials": True}
    if result["all_blobs_verified"]:
        layers = {}
        for row in inventory["instances"]:
            for descriptor in row["layers"]:
                layers[descriptor["digest"]] = descriptor
        expanded = []
        for digest, descriptor in layers.items():
            path = CACHE / "blobs/sha256" / digest.removeprefix("sha256:")
            size = 0
            if descriptor["mediaType"].endswith("+gzip") or descriptor["mediaType"].endswith(".gzip"):
                with gzip.open(path, "rb") as f:
                    for data in iter(lambda: f.read(4 * 1024**2), b""):
                        size += len(data)
            else:
                size = path.stat().st_size
            expanded.append({"digest": digest, "uncompressed_tar_bytes": size})
        result["uncompressed_layers"] = expanded
        result["unique_uncompressed_layer_bytes"] = sum(r["uncompressed_tar_bytes"] for r in expanded)
    with (HERE / "official_oci_cache_01.json").open("x", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
        f.write("\n")
    shutil.copy2(HERE / "official_oci_cache_01.json", CACHE / "cache_audit.json")
    print(json.dumps({"all_blobs_verified": result["all_blobs_verified"], "blobs": len(rows),
                      "compressed_gib": round(sum(r.get("size_bytes", 0) for r in rows) / 1024**3, 3),
                      "uncompressed_gib": round(result.get("unique_uncompressed_layer_bytes", 0) / 1024**3, 3),
                      "failed": [r for r in rows if r["status"] == "failed_breakpoint"]}))
    return 0 if result["all_blobs_verified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
