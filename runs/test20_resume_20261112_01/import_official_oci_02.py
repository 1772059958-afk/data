"""Plan or import verified public OCI images via a streaming local Docker load."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile

HERE = Path(__file__).resolve().parent
RESERVE = 4 * 1024**3 + 128 * 1024**2


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024**2), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-audit", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--instances", nargs="+")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    assert args.out.resolve().is_relative_to(HERE) and not args.out.exists()
    audit = json.loads(args.cache_audit.read_text(encoding="utf-8"))
    assert audit["all_blobs_verified"] is True
    cache = Path(audit["cache"])
    inventory = json.loads((HERE / "official_test20_registry_inventory_01.json").read_text(encoding="utf-8"))
    designated = {r["instance_id"] for r in inventory["instances"]}
    selected = set(args.instances or designated)
    assert selected and selected <= designated
    rows = [r for r in inventory["instances"] if r["instance_id"] in selected]
    blobs, manifests = {}, []
    for row in rows:
        sha = row["linux_amd64_manifest_digest"]
        path = cache / "blobs/sha256" / sha.removeprefix("sha256:")
        assert digest(path) == sha
        manifest = json.loads(path.read_bytes())
        assert manifest["config"] == row["config"] and manifest["layers"] == row["layers"]
        blobs[sha] = path
        for item in [manifest["config"], *manifest["layers"]]:
            path = cache / "blobs/sha256" / item["digest"].removeprefix("sha256:")
            assert path.stat().st_size == item["size"]
            blobs[item["digest"]] = path
        manifests.append({"mediaType": manifest["mediaType"], "digest": sha,
                          "size": (cache / "blobs/sha256" / sha.removeprefix("sha256:")).stat().st_size,
                          "platform": {"architecture": "amd64", "os": "linux"},
                          "annotations": {"org.opencontainers.image.ref.name": "docker.io/" + row["repository"] + ":registered-20261112"}})
    expanded = {r["digest"]: r["uncompressed_tar_bytes"] for r in audit["uncompressed_layers"]}
    result = {"kind": "official_oci_local_import", "execute": args.execute,
              "instance_ids": [r["instance_id"] for r in rows], "model_calls": 0,
              "network_requests": 0, "new_containers": 0,
              "expected_image_ids": {r["instance_id"]: r["linux_amd64_manifest_digest"] for r in rows},
              "official_config_digests": {r["instance_id"]: r["config"]["digest"] for r in rows},
              "cache_audit_sha256": digest(args.cache_audit), "cache": str(cache)}
    if not args.execute:
        result["upper_uncompressed_bytes_before_layer_reuse"] = sum(expanded[x] for x in {d["digest"] for r in rows for d in r["layers"]})
        with args.out.open("x", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
            f.write("\n")
        print(json.dumps(result))
        return 0
    for sha, path in blobs.items():
        assert digest(path) == sha, "cached blob changed before local import"
    listed = subprocess.check_output(["docker", "--context", "desktop-linux", "image", "ls", "--no-trunc", "--format", "{{.ID}}"], text=True).splitlines()
    known = set()
    if listed:
        values = subprocess.check_output(["docker", "--context", "desktop-linux", "image", "inspect", *sorted(set(listed)), "--format", "{{json .RootFS.Layers}}"], text=True)
        for line in values.splitlines():
            known.update(json.loads(line) or [])
    required = {}
    for row in rows:
        config = json.loads(blobs[row["config"]["digest"]].read_bytes())
        diff_ids = config["rootfs"]["diff_ids"]
        assert len(diff_ids) == len(row["layers"])
        for diff_id, layer in zip(diff_ids, row["layers"]):
            if diff_id not in known:
                required[diff_id] = expanded[layer["digest"]]
    free = shutil.disk_usage(cache).free
    result.update(new_uncompressed_layer_upper_bytes=sum(required.values()), free_bytes_before=free)
    assert free > sum(required.values()) + RESERVE, "insufficient room for verified image layers plus4GiB reserve"
    log = args.out.with_suffix(".console.log")
    with log.open("xb") as console:
        process = subprocess.Popen(["docker", "--context", "desktop-linux", "load"], stdin=subprocess.PIPE,
                                   stdout=console, stderr=subprocess.STDOUT)
        try:
            with tarfile.open(fileobj=process.stdin, mode="w|") as tar:
                for name, value in [("oci-layout", {"imageLayoutVersion": "1.0.0"}),
                                    ("index.json", {"schemaVersion": 2, "mediaType": "application/vnd.oci.image.index.v1+json", "manifests": manifests})]:
                    payload = json.dumps(value).encode()
                    info = tarfile.TarInfo(name)
                    info.size = len(payload)
                    tar.addfile(info, io.BytesIO(payload))
                for sha, path in sorted(blobs.items()):
                    info = tarfile.TarInfo("blobs/sha256/" + sha.removeprefix("sha256:"))
                    info.size = path.stat().st_size
                    with path.open("rb") as stream:
                        tar.addfile(info, stream)
            process.stdin.close()
            code = process.wait()
        except BaseException:
            if process.stdin and not process.stdin.closed:
                process.stdin.close()
            process.wait(timeout=60)
            raise
    result.update(docker_load_exit_code=code, console_log=log.name)
    if code == 0:
        for iid, expected in result["expected_image_ids"].items():
            inspected = json.loads(subprocess.check_output(["docker", "--context", "desktop-linux", "image", "inspect", expected], text=True))[0]
            assert inspected["Id"] == expected and inspected["Descriptor"]["digest"] == expected, iid
            source = next(row for row in rows if row["instance_id"] == iid)
            config = json.loads(blobs[source["config"]["digest"]].read_bytes())
            assert inspected["RootFS"]["Layers"] == config["rootfs"]["diff_ids"], iid
            assert inspected["Architecture"] == config["architecture"] and inspected["Os"] == config["os"], iid
        result["all_imported_image_ids_verified"] = True
    result["free_bytes_after"] = shutil.disk_usage(cache).free
    with args.out.open("x", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
        f.write("\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ("expected_image_ids", "instance_ids")}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
