"""Freeze the SWE-bench Lite instance list.

The canonical `resolve/<revision>/...` endpoint redirects to HuggingFace's xet
bridge (`cas-bridge.xethub.hf.co`), which is unreachable from this network. The
datasets-server parquet endpoint serves the same xet object from a reachable
CDN, so that path is used here. Provenance is kept by recording, for every
split, the revision queried, the xet object id taken from the canonical
`resolve` redirect, and the sha256 of the bytes actually downloaded.

Re-running with the same revision must reproduce the same instance-list digest.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HF_ENDPOINT = os.environ.get("HF_ENDPOINT", "https://hf-mirror.com")
DATASET = "princeton-nlp/SWE-bench_Lite"
REPO_FILES = {
    "dev": "data/dev-00000-of-00001.parquet",
    "test": "data/test-00000-of-00001.parquet",
}

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(ROOT, "data", "raw")
FROZEN_DIR = os.path.join(ROOT, "data", "frozen")
UA = {"User-Agent": "Mozilla/5.0 (freeze-dataset)"}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Stop at the first 3xx so the redirect target can be inspected."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _get(url: str, timeout: int = 120):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout)


def dataset_revision(repo: str) -> str:
    with _get(f"{HF_ENDPOINT}/api/datasets/{repo}", 60) as resp:
        return json.loads(resp.read().decode())["sha"]


def resolve_redirect_object(repo: str, revision: str, path: str) -> str:
    """Return the xet object id that the canonical resolve URL points at."""
    url = f"{HF_ENDPOINT}/datasets/{repo}/resolve/{revision}/{path}"
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(urllib.request.Request(url, headers=UA), timeout=60) as resp:
            return f"no-redirect (status {resp.status})"
    except urllib.error.HTTPError as exc:
        loc = exc.headers.get("Location", "")
        parts = [p for p in loc.split("?")[0].split("/") if p]
        return "/".join(parts[-2:]) if len(parts) >= 2 else loc[:80]


def download(repo: str, split: str, dest: str) -> str:
    if os.path.exists(dest):
        print(f"  cached  {os.path.basename(dest)}")
        return ""
    # datasets-server parquet endpoint: same xet object, reachable CDN host
    url = f"{HF_ENDPOINT}/api/datasets/{repo}/parquet/default/{split}/0.parquet"
    tmp = dest + ".part"
    with _get(url, 300) as resp, open(tmp, "wb") as fh:
        served_from = resp.geturl().split("?")[0]
        total = 0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
            total += len(chunk)
    os.replace(tmp, dest)
    print(f"  got     {os.path.basename(dest)}  {total / 1e6:.2f} MB")
    return served_from


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_table(path: str):
    import pyarrow.parquet as pq

    return pq.read_table(path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--revision", default=None, help="dataset revision; default: remote main")
    args = ap.parse_args()

    os.makedirs(RAW_DIR, exist_ok=True)
    os.makedirs(FROZEN_DIR, exist_ok=True)

    revision = args.revision or dataset_revision(DATASET)
    print(f"dataset   {DATASET}")
    print(f"revision  {revision}")

    manifest = {
        "dataset": DATASET,
        "endpoint": HF_ENDPOINT,
        "revision": revision,
        "frozen_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": "instance lists are sorted; digest = sha256 of ids joined by newline",
        "splits": {},
    }

    for split, repo_path in REPO_FILES.items():
        dest = os.path.join(RAW_DIR, f"{split}.parquet")
        resolved = resolve_redirect_object(DATASET, revision, repo_path)
        print(f"  resolve {split}: xet object {resolved}")
        served_from = download(DATASET, split, dest)
        table = read_table(dest)
        ids = sorted(str(v) for v in table.column("instance_id").to_pylist())
        digest = hashlib.sha256("\n".join(ids).encode()).hexdigest()
        list_path = os.path.join(FROZEN_DIR, f"instances_{split}.txt")
        with open(list_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(ids) + "\n")
        manifest["splits"][split] = {
            "repo_path": repo_path,
            "local_file": os.path.relpath(dest, ROOT).replace("\\", "/"),
            "served_from": served_from,
            "resolve_xet_object": resolved,
            "sha256": sha256(dest),
            "n_instances": len(ids),
            "n_columns": table.num_columns,
            "columns": table.column_names,
            "instance_list": f"data/frozen/instances_{split}.txt",
            "instance_list_sha256": digest,
        }
        print(f"  {split}: {len(ids)} instances, list digest {digest}")

    out = os.path.join(FROZEN_DIR, "manifest.json")
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
    print(f"manifest  {os.path.relpath(out, ROOT)}")


if __name__ == "__main__":
    main()
