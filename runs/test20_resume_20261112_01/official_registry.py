"""Read only official public OCI metadata using Windows trusted TLS roots."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import ssl
import urllib.parse
import urllib.request

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ACCEPT = ", ".join([
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
])


class PublicRegistry:
    def __init__(self, repository):
        assert repository.startswith("swebench/sweb.eval.x86_64.")
        self.repository = repository
        self.context = ssl.create_default_context()
        query = urllib.parse.urlencode({"service": "registry.docker.io", "scope": "repository:" + repository + ":pull"})
        with urllib.request.urlopen("https://auth.docker.io/token?" + query, context=self.context, timeout=30) as r:
            self.token = json.load(r)["token"]

    def open(self, kind, reference, timeout=60):
        request = urllib.request.Request(
            "https://registry-1.docker.io/v2/" + self.repository + "/" + kind + "/" + reference,
            headers={"Authorization": "Bearer " + self.token, "Accept": ACCEPT})
        return urllib.request.urlopen(request, context=self.context, timeout=timeout)

    def manifest(self, reference):
        with self.open("manifests", reference) as response:
            payload = response.read()
            digest = "sha256:" + hashlib.sha256(payload).hexdigest()
            assert response.headers.get("Docker-Content-Digest") == digest
            if reference.startswith("sha256:"):
                assert digest == reference
            return digest, payload, json.loads(payload)


def resolve(iid):
    repository = "swebench/sweb.eval.x86_64." + iid.replace("__", "_1776_")
    row = {"instance_id": iid, "repository": repository, "tag": "latest", "tls_verified": True}
    try:
        client = PublicRegistry(repository)
        root_digest, root_bytes, root = client.manifest("latest")
        if "manifests" in root:
            candidates = [x for x in root["manifests"] if x.get("platform", {}).get("os") == "linux" and x.get("platform", {}).get("architecture") == "amd64"]
            assert len(candidates) == 1
            digest, payload, manifest = client.manifest(candidates[0]["digest"])
        else:
            digest, payload, manifest = root_digest, root_bytes, root
        assert manifest["schemaVersion"] == 2 and manifest["config"]["digest"].startswith("sha256:")
        directory = HERE / "registry_metadata"
        directory.mkdir(exist_ok=True)
        for sha, data in [(root_digest, root_bytes), (digest, payload)]:
            target = directory / (sha.removeprefix("sha256:") + ".json")
            if target.exists():
                assert target.read_bytes() == data
            else:
                with target.open("xb") as f:
                    f.write(data)
        row.update(status="verified_public_manifest", index_digest=root_digest, linux_amd64_manifest_digest=digest,
                   config=manifest["config"], layers=manifest["layers"],
                   compressed_layer_bytes=sum(x["size"] for x in manifest["layers"]))
    except Exception as exc:
        row.update(status="failed", error_type=type(exc).__name__, http_status=getattr(exc, "code", None))
    return row


if __name__ == "__main__":
    sample = json.loads((ROOT / "runs/test20_preparation_20261111/instances.json").read_text(encoding="utf-8"))
    ids = sample["instance_ids"]
    assert len(ids) == len(set(ids)) == 20
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(resolve, ids))
    unique = {x["digest"]: x["size"] for r in rows for x in r.get("layers", [])}
    result = {"kind": "official_test20_public_oci_manifest_inventory", "date": "2026-11-12",
              "tls_verification": True, "credential_file_read": False, "model_calls": 0,
              "image_downloads": 0, "containers_started": 0, "instances": rows,
              "unique_compressed_layer_bytes": sum(unique.values()),
              "selection": "All registered20, metadata only; no model or official verdict filtering"}
    with (HERE / "official_test20_registry_inventory_01.json").open("x", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
        f.write("\n")
    print(json.dumps({"verified": sum(r["status"] == "verified_public_manifest" for r in rows),
                      "unique_compressed_gib": round(sum(unique.values()) / 1024**3, 3),
                      "cases": [{"id": r["instance_id"], "status": r["status"], "compressed_gib": round(r.get("compressed_layer_bytes", 0) / 1024**3, 3), "http_status": r.get("http_status")} for r in rows]}))
