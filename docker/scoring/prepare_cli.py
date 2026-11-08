"""Prepare the pinned Linux Docker CLI; default is a download-free plan.

The package/hash were verified through Docker's signed Ubuntu jammy InRelease
and Packages.gz. Only the CLI is extracted, never a daemon or host installer.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[2]
URL = ('https://download.docker.com/linux/ubuntu/dists/jammy/pool/stable/amd64/'
       'docker-ce-cli_29.9.2-1~ubuntu.22.04~jammy_amd64.deb')
PACKAGE_SHA256 = 'b40b9821da9d2bbed47b868624ee08d9205be28de6366bbd2824116dc364b226'
BINARY_SHA256 = 'f5000a4e1745a901bc9ecef3c3063da4454d9bcb7bfd581eb1bbeb3c3602da9b'


def extract_cli(package: bytes) -> bytes:
    if hashlib.sha256(package).hexdigest() != PACKAGE_SHA256 or not package.startswith(b'!<arch>\n'):
        raise ValueError('official Docker CLI package SHA256 mismatch')
    position = 8
    while position + 60 <= len(package):
        header = package[position:position + 60]
        name, size = header[:16].decode().strip().rstrip('/'), int(header[48:58])
        position += 60
        if name.startswith('data.tar'):
            with tarfile.open(fileobj=io.BytesIO(package[position:position + size]), mode='r:*') as archive:
                member = next(m for m in archive.getmembers() if m.name.lstrip('./') == 'usr/bin/docker')
                payload = archive.extractfile(member).read()
            if not payload.startswith(b'\x7fELF') or hashlib.sha256(payload).hexdigest() != BINARY_SHA256:
                raise ValueError('official Linux Docker CLI binary SHA256 mismatch')
            return payload
        position += size + size % 2
    raise ValueError('Docker CLI package has no data archive')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--audit-out', type=Path)
    args = parser.parse_args(argv)
    work = ROOT / 'work/scoring_setup/docker_cli'
    target = work / 'bin/docker'
    data = {'execute': args.execute, 'model_calls': 0, 'url': URL,
            'package_sha256': PACKAGE_SHA256, 'binary_sha256': BINARY_SHA256,
            'target': str(target), 'version': '29.9.2', 'architecture': 'linux-amd64'}
    if args.execute:
        import requests
        package_path = work / 'docker-ce-cli.deb'
        work.mkdir(parents=True, exist_ok=True)
        if package_path.exists():
            package = package_path.read_bytes()
        else:
            response = requests.get(URL, timeout=(15, 120))
            response.raise_for_status()
            package = response.content
        binary = extract_cli(package)
        if not package_path.exists():
            with package_path.open('xb') as stream:
                stream.write(package)
        if target.exists():
            if target.read_bytes() != binary:
                raise ValueError('refusing to overwrite an existing different CLI')
        else:
            target.parent.mkdir(exist_ok=True)
            with target.open('xb') as stream:
                stream.write(binary)
        data['hashes_verified'] = True
        if args.audit_out:
            audit = args.audit_out.resolve()
            if not audit.is_relative_to(ROOT / 'runs'):
                raise ValueError('audit output must be a new file under runs/')
            audit.parent.mkdir(parents=True, exist_ok=True)
            with audit.open('x', encoding='utf-8') as stream:
                json.dump(data, stream, indent=2)
    print(json.dumps(data, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
