"""Finish verified public layers with bounded retries for transient TLS/IO only."""
import concurrent.futures
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import ssl
import threading
import time
import urllib.error

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


def event(row):
    with lock, (HERE / "official_oci_download_events_03.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
        f.flush()
        os.fsync(f.fileno())


def cache_blob(item):
    digest, descriptor, repository = item
    target = CACHE / "blobs/sha256" / digest.removeprefix("sha256:")
    if target.exists():
        assert target.stat().st_size == descriptor["size"] and sha(target) == digest
        return {"digest": digest, "status": "verified_existing", "size_bytes": target.stat().st_size, "network_attempts": 0}
    if stop.is_set():
        return {"digest": digest, "status": "not_started_after_breakpoint"}
    for attempt in (1, 2, 3):
        partial = target.with_suffix(".partial03_attempt" + str(attempt))
        size = 0
        try:
            client = PublicRegistry(repository)
            h = hashlib.sha256()
            with client.open("blobs", digest, timeout=180) as response, partial.open("xb") as f:
                while True:
                    if stop.is_set():
                        raise RuntimeError("another request reached a nonrecoverable breakpoint")
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
            row = {"digest": digest, "status": "downloaded_sha256_verified", "size_bytes": size, "network_attempts": attempt}
            event(row)
            return row
        except Exception as exc:
            code = getattr(exc, "code", None)
            transient = isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError, ssl.SSLError)) and code not in (401, 402, 403, 429)
            row = {"digest": digest, "status": "transient_attempt_failed" if transient and attempt < 3 else "failed_breakpoint",
                   "error_type": type(exc).__name__, "reason_type": type(getattr(exc, "reason", None)).__name__,
                   "http_status": code, "network_attempt": attempt, "partial_bytes": size, "partial_path": str(partial)}
            event(row)
            if not transient or attempt == 3:
                stop.set()
                return row
            time.sleep(1)


def main():
    inventory = json.loads((HERE / "official_test20_registry_inventory_01.json").read_text(encoding="utf-8"))
    assert len(inventory["instances"]) == 20
    inputs = {}
    for row in inventory["instances"]:
        assert row["status"] == "verified_public_manifest"
        for descriptor in [row["config"], *row["layers"]]:
            inputs.setdefault(descriptor["digest"], (descriptor, row["repository"]))
    missing = sum(d["size"] for sha, (d, _) in inputs.items() if not (CACHE / "blobs/sha256" / sha.removeprefix("sha256:")).exists())
    assert shutil.disk_usage(CACHE).free > missing + RESERVE
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        rows = list(pool.map(cache_blob, [(d, x, repo) for d, (x, repo) in inputs.items()]))
    complete = not stop.is_set() and all(r["status"] in ("verified_existing", "downloaded_sha256_verified") for r in rows)
    result = {"kind": "official_oci_blob_cache", "cache": str(CACHE), "tls_verified": True,
              "credential_files_read": False, "anonymous_tokens_saved": False, "model_calls": 0,
              "docker_loads": 0, "containers_started": 0, "all_blobs_verified": complete, "blobs": rows,
              "transient_network_attempt_limit_per_missing_blob": 3,
              "no_retry_http_codes": [401, 402, 403, 429], "all_prior_audits_and_partials_preserved": True}
    if complete:
        layers = {x["digest"]: x for row in inventory["instances"] for x in row["layers"]}
        expanded = []
        for digest, descriptor in layers.items():
            path = CACHE / "blobs/sha256" / digest.removeprefix("sha256:")
            assert descriptor["mediaType"].endswith("+gzip") or descriptor["mediaType"].endswith(".gzip")
            size = 0
            with gzip.open(path, "rb") as f:
                for data in iter(lambda: f.read(4 * 1024**2), b""):
                    size += len(data)
            expanded.append({"digest": digest, "uncompressed_tar_bytes": size})
        result["uncompressed_layers"] = expanded
        result["unique_uncompressed_layer_bytes"] = sum(r["uncompressed_tar_bytes"] for r in expanded)
    payload = (json.dumps(result, indent=2) + "\n").encode()
    with (HERE / "official_oci_cache_03.json").open("xb") as f:
        f.write(payload)
    with (CACHE / "cache_audit_03.json").open("xb") as f:
        f.write(payload)
    print(json.dumps({"all_blobs_verified": complete, "compressed_gib": round(sum(r.get("size_bytes", 0) for r in rows) / 1024**3, 3),
                      "uncompressed_gib": round(result.get("unique_uncompressed_layer_bytes", 0) / 1024**3, 3),
                      "failed": [r for r in rows if r["status"] == "failed_breakpoint"]}))
    return 0 if complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
