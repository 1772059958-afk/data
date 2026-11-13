"""Cache a bounded public dependency correction for observed baseline failures."""
import hashlib
import json
from pathlib import Path
import shutil
import ssl
import time
import urllib.error
import urllib.request

HERE = Path(__file__).resolve().parent
CACHE = Path(r"D:\CodexExperimentCache\test20_20261111\mpl_compat_wheels_20261112_05")
PINS = [("pytest", "7.1.3"), ("py", "1.11.0")]
PROFILES = {"matplotlib__matplotlib-23987": PINS}



def fetch(url):
    for attempt in range(3):
        try:
            return urllib.request.urlopen(url, context=ssl.create_default_context(), timeout=90)
        except urllib.error.URLError as exc:
            if getattr(exc, "code", None) in (401, 402, 403, 429) or attempt == 2:
                raise
            time.sleep(1)


def main():
    CACHE.mkdir(parents=True, exist_ok=False)
    rows = []
    for name, version in PINS:
        with fetch("https://pypi.org/pypi/" + name + "/" + version + "/json") as r:
            metadata = json.load(r)
        candidates = [r for r in metadata["urls"] if r["filename"].endswith("-none-any.whl")]
        if not candidates:
            candidates = [r for r in metadata["urls"] if r["filename"].endswith(".whl") and "-cp39-cp39-" in r["filename"] and "manylinux" in r["filename"] and "x86_64" in r["filename"]]
        if not candidates:
            candidates = [r for r in metadata["urls"] if r["packagetype"] == "sdist"]
        assert candidates, name
        selected = sorted(candidates, key=lambda r: r["filename"])[0]
        path = CACHE / selected["filename"]
        assert shutil.disk_usage(CACHE).free > selected["size"] + 4 * 1024**3
        with fetch(selected["url"]) as r, path.open("xb") as f:
            h = hashlib.sha256()
            for chunk in iter(lambda: r.read(1024**2), b""):
                h.update(chunk)
                f.write(chunk)
        assert path.stat().st_size == selected["size"] and h.hexdigest() == selected["digests"]["sha256"]
        rows.append({"name": name, "version": version, "filename": path.name, "path": str(path),
                     "sha256": h.hexdigest(), "size_bytes": path.stat().st_size,
                     "public_url": selected["url"], "metadata_url": "https://pypi.org/pypi/" + name + "/" + version + "/json",
                     "requires_python": selected.get("requires_python"), "packagetype": selected["packagetype"]})
    profiles = {}
    for iid, packages in PROFILES.items():
        lock = CACHE / (iid + ".lock.txt")
        selected = [next(r for r in rows if (r["name"], r["version"]) == pair) for pair in packages]
        payload = "\n".join(r["name"] + "==" + r["version"] + " --hash=sha256:" + r["sha256"] for r in selected) + "\n"
        with lock.open("x", encoding="utf-8") as f:
            f.write(payload)
        profiles[iid] = {"lock": str(lock), "lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(), "packages": selected}
    result = {"kind": "bounded_public_environment_dependency_correction", "cache": str(CACHE),
              "tls_verified": True, "official_pypi_hashes_verified": True, "model_calls": 0,
              "packages": rows, "profiles": profiles, "runtime_validation_complete": False,
              "basis": "Observed original public baseline failures only; no model outcomes or hidden verdicts used."}
    with (HERE / "formal_compat_dependencies_05.json").open("x", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
        f.write("\n")
    print(json.dumps({"artifacts": len(rows), "bytes": sum(r["size_bytes"] for r in rows), "profiles": len(profiles)}))


if __name__ == "__main__":
    main()
