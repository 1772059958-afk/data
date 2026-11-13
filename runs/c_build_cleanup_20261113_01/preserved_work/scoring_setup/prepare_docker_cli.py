"""Obtain only the official Linux CLI, verifying Docker's signed APT hashes."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import requests

root = Path(__file__).resolve().parents[2]
work = root / 'work/scoring_setup/docker_cli'
upstream = root / 'runs/dev2_acceptance_20261106/environment/scoring/cli_upstream'
work.mkdir(exist_ok=True)
upstream.mkdir(exist_ok=True)
session = requests.Session()
base = 'https://download.docker.com/linux/ubuntu/'
def fetch(url, name):
    if (upstream / name).is_file():
        return (upstream / name).read_bytes()
    response = session.get(url, timeout=(15, 120))
    response.raise_for_status()
    payload = response.content
    (upstream / name).write_bytes(payload)
    return payload

static = 'https://download.docker.com/linux/static/stable/x86_64/docker-29.9.2.tgz'
static_checksums = {}
for suffix in ('.sha256', '.sha256sum'):
    response = session.get(static + suffix, timeout=(15, 30))
    static_checksums[static + suffix] = response.status_code
if 200 in static_checksums.values():
    raise RuntimeError('a static checksum is available; review it before using the APT fallback')

key = fetch(base + 'gpg', 'docker.asc')
release = fetch(base + 'dists/jammy/InRelease', 'InRelease')
gpg_home = work / 'gnupg'
gpg_home.mkdir(exist_ok=True)
gpg = Path('C:/Program Files/Git/usr/bin/gpg.exe')
gpg_cmd = [str(gpg), '--batch', '--homedir', str(gpg_home)]
show = subprocess.run(gpg_cmd + ['--with-colons', '--show-keys', str(upstream / 'docker.asc')],
                      capture_output=True, text=True, check=True)
fingerprint = next(line.split(':')[9] for line in show.stdout.splitlines() if line.startswith('fpr:'))
assert fingerprint == '9DC858229FC7DD38854AE2D88D81803C0EBFCD88'
subprocess.run(gpg_cmd + ['--import', str(upstream / 'docker.asc')], capture_output=True, check=True)
verified = subprocess.run(gpg_cmd + ['--status-fd', '1', '--verify', str(upstream / 'InRelease')],
                          capture_output=True, text=True, check=True)
assert 'VALIDSIG' in verified.stdout and fingerprint in verified.stdout
subprocess.run(gpg_cmd + ['--output', str(upstream / 'Release'), '--decrypt', str(upstream / 'InRelease')],
               capture_output=True, check=True)
release_text = (upstream / 'Release').read_text(encoding='utf-8')
sha256_section = release_text.split('SHA256:\n', 1)[1].split('\n\n', 1)[0]
path = 'stable/binary-amd64/Packages.gz'
expected_hash, expected_size, _ = next(line.split() for line in sha256_section.splitlines()
                                     if line.strip().endswith(' ' + path))
packages_gz = fetch(base + 'dists/jammy/' + path, 'Packages.gz')
assert len(packages_gz) == int(expected_size)
assert hashlib.sha256(packages_gz).hexdigest() == expected_hash
paragraphs = gzip.decompress(packages_gz).decode('utf-8').split('\n\n')
entries = []
for paragraph in paragraphs:
    entry = dict(line.split(': ', 1) for line in paragraph.splitlines() if ': ' in line and not line.startswith(' '))
    if (entry.get('Package') == 'docker-ce-cli' and entry.get('Version', '').startswith('5:29.9.2-')
            and entry.get('Architecture') == 'amd64'):
        entries.append(entry)
assert len(entries) == 1
entry = entries[0]
package = fetch(base + entry['Filename'], 'docker-ce-cli.deb')
assert len(package) == int(entry['Size'])
package_hash = hashlib.sha256(package).hexdigest()
assert package_hash == entry['SHA256']
assert package.startswith(b'!<arch>\n')
position = 8
data = None
while position + 60 <= len(package):
    header = package[position:position + 60]
    name, size = header[:16].decode().strip().rstrip('/'), int(header[48:58])
    position += 60
    if name.startswith('data.tar'):
        data = package[position:position + size]
        break
    position += size + size % 2
assert data is not None
with tarfile.open(fileobj=io.BytesIO(data), mode='r:*') as archive:
    member = next(m for m in archive.getmembers() if m.name.lstrip('./') == 'usr/bin/docker')
    binary = archive.extractfile(member).read()
assert binary.startswith(b'\x7fELF')
target = work / 'bin/docker'
target.parent.mkdir()
target.write_bytes(binary)
metadata = {'upstream': base, 'version': entry['Version'], 'architecture': entry['Architecture'],
            'package_filename': entry['Filename'], 'package_sha256': package_hash,
            'binary_sha256': hashlib.sha256(binary).hexdigest(),
            'signed_release_verified': True, 'release_signer_primary_fingerprint': fingerprint,
            'packages_index_sha256': expected_hash,
            'static_checksum_probes': static_checksums,
            'selection_reason': 'official static checksum URLs unavailable; signed official APT SHA256 chain used',
            'installed_component': 'usr/bin/docker only; no daemon',
            'linux_binary': True}
with (upstream / 'verification.json').open('x', encoding='utf-8') as stream:
    json.dump(metadata, stream, indent=2)
print(json.dumps(metadata))
