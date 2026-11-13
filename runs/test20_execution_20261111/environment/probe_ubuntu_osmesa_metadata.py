"""Download bounded official APT metadata only, then inspect minimal GL closure.

No package binary, apt update, system change or credential is involved.
"""
from __future__ import annotations

from collections import deque
import hashlib
import json
import lzma
from pathlib import Path
import re
import time

import requests

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
OUT = HERE / 'ubuntu_gl_metadata_01.json'
CACHE = ROOT / 'work/test20_environment_20261111/ubuntu_metadata_01'
MAX_BYTES = 10 * 1024 * 1024
ROOT_PACKAGES = ('libgl1', 'libglx0', 'libglvnd0')


def paragraphs(text):
    for block in text.split('\n\n'):
        fields = {}
        last = None
        for line in block.splitlines():
            if line.startswith((' ', '\t')) and last:
                fields[last] += '\n' + line
            elif ':' in line:
                last, value = line.split(':', 1)
                fields[last] = value.strip()
        if fields:
            yield fields


def version_compare(left, right):
    """Debian's epoch, upstream, revision ordering (including tilde)."""
    def split(value):
        epoch, rest = value.split(':', 1) if ':' in value else ('0', value)
        upstream, revision = rest.rsplit('-', 1) if '-' in rest else (rest, '0')
        return int(epoch), upstream, revision

    def part_compare(a, b):
        i = j = 0
        def order(c):
            if c == '~': return -1
            if not c: return 0
            return ord(c) if c.isalpha() else ord(c) + 256
        while i < len(a) or j < len(b):
            while ((i < len(a) and not a[i].isdigit()) or
                   (j < len(b) and not b[j].isdigit())):
                aa = a[i] if i < len(a) and not a[i].isdigit() else ''
                bb = b[j] if j < len(b) and not b[j].isdigit() else ''
                if order(aa) != order(bb): return (order(aa) > order(bb)) * 2 - 1
                if aa: i += 1
                if bb: j += 1
            while i < len(a) and a[i] == '0': i += 1
            while j < len(b) and b[j] == '0': j += 1
            end_i, end_j = i, j
            while end_i < len(a) and a[end_i].isdigit(): end_i += 1
            while end_j < len(b) and b[end_j].isdigit(): end_j += 1
            aa, bb = a[i:end_i], b[j:end_j]
            if len(aa) != len(bb): return (len(aa) > len(bb)) * 2 - 1
            if aa != bb: return (aa > bb) * 2 - 1
            i, j = end_i, end_j
        return 0

    aa, bb = split(left), split(right)
    if aa[0] != bb[0]: return (aa[0] > bb[0]) * 2 - 1
    return part_compare(aa[1], bb[1]) or part_compare(aa[2], bb[2])


def parse_dependency(value):
    match = re.fullmatch(r'([a-z0-9+.-]+)(?::(?:any|native|amd64))?(?:\s*\((<<|<=|=|>=|>>)\s*([^()]+)\))?', value.strip())
    if not match:
        raise ValueError('unsupported dependency syntax: ' + value)
    return match.groups()


def satisfies(version, op, wanted):
    if op is None:
        return True
    comp = version_compare(version, wanted)
    return {'<<': comp < 0, '<=': comp <= 0, '=': comp == 0,
            '>=': comp >= 0, '>>': comp > 0}[op]


def main():
    if OUT.exists() or CACHE.exists():
        raise FileExistsError('refusing to reuse metadata output/cache')
    CACHE.mkdir(parents=True)
    transferred = 0
    records = []
    candidates = {}

    def fetch(url):
        nonlocal transferred
        started = time.monotonic()
        response = requests.get(url, timeout=(20, 60), stream=True)
        response.raise_for_status()
        pieces = []
        for piece in response.iter_content(65536):
            transferred += len(piece)
            if transferred > MAX_BYTES:
                raise ValueError('bounded metadata transfer limit exceeded')
            pieces.append(piece)
        return b''.join(pieces), round(time.monotonic() - started, 3), response.url

    for suite in ('jammy', 'jammy-updates'):
        release_url = f'https://archive.ubuntu.com/ubuntu/dists/{suite}/Release'
        release, elapsed_release, actual_release = fetch(release_url)
        release_fields = next(paragraphs(release.decode('utf-8')))
        path = 'main/binary-amd64/Packages.xz'
        entries = [line.split() for line in release_fields.get('SHA256', '').splitlines() if line.strip()]
        matching = [entry for entry in entries if len(entry) == 3 and entry[2] == path]
        if len(matching) != 1:
            raise ValueError('Release has no unique SHA256 for ' + path)
        expected_sha, expected_size, _ = matching[0]
        packages_url = f'https://archive.ubuntu.com/ubuntu/dists/{suite}/{path}'
        compressed, elapsed_packages, actual_packages = fetch(packages_url)
        actual_sha = hashlib.sha256(compressed).hexdigest()
        if len(compressed) != int(expected_size) or actual_sha != expected_sha:
            raise ValueError('Packages.xz does not match official Release SHA256/size')
        (CACHE / f'{suite}_Release').write_bytes(release)
        (CACHE / f'{suite}_Packages.xz').write_bytes(compressed)
        decoded = lzma.decompress(compressed).decode('utf-8')
        package_count = 0
        for fields in paragraphs(decoded):
            if fields.get('Architecture') not in ('amd64', 'all'):
                continue
            name = fields['Package']
            package_count += 1
            fields['_suite'] = suite
            if name not in candidates or version_compare(fields['Version'], candidates[name]['Version']) > 0:
                candidates[name] = fields
        records.append({'suite': suite, 'release_url': actual_release,
                        'release_sha256': hashlib.sha256(release).hexdigest(),
                        'release_date': release_fields.get('Date'),
                        'packages_url': actual_packages,
                        'packages_sha256_source': 'SHA256 section in the HTTPS official Release file',
                        'packages_expected_sha256': expected_sha,
                        'packages_actual_sha256': actual_sha,
                        'packages_compressed_bytes': len(compressed),
                        'packages_uncompressed_bytes': len(decoded.encode('utf-8')),
                        'package_count': package_count,
                        'elapsed_seconds': elapsed_release + elapsed_packages,
                        'tls_verification': True, 'gpg_signature_verified': False})

    installed_payload = json.loads((HERE / 'pydicom1139_dpkg_installed_01.json').read_text(encoding='utf-8'))
    installed = {row['name']: row['version'] for row in installed_payload['packages']}
    queue = deque([(name, None, None, 'root') for name in ROOT_PACKAGES])
    chosen, edges, already, missing = {}, [], {}, []
    while queue:
        name, op, wanted, parent = queue.popleft()
        if name in installed and satisfies(installed[name], op, wanted):
            already[name] = installed[name]
            continue
        candidate = candidates.get(name)
        if not candidate or not satisfies(candidate['Version'], op, wanted):
            missing.append({'name': name, 'constraint': [op, wanted], 'parent': parent})
            continue
        if name in chosen:
            if not satisfies(chosen[name]['Version'], op, wanted):
                missing.append({'name': name, 'constraint': [op, wanted], 'parent': parent})
            continue
        chosen[name] = candidate
        for dependencies in (candidate.get('Pre-Depends', ''), candidate.get('Depends', '')):
            for group in dependencies.split(','):
                if not group.strip():
                    continue
                alternatives = [parse_dependency(option) for option in group.split('|')]
                preferred = next((option for option in alternatives
                                  if option[0] in installed and satisfies(installed[option[0]], option[1], option[2])), None)
                preferred = preferred or next((option for option in alternatives
                                               if option[0] in candidates and satisfies(candidates[option[0]]['Version'], option[1], option[2])), None)
                if preferred is None:
                    missing.append({'parent': name, 'alternatives': alternatives})
                else:
                    edges.append({'parent': name, 'dependency': group.strip(), 'selected': preferred[0]})
                    queue.append((*preferred, name))
    rows = []
    for name, fields in sorted(chosen.items()):
        rows.append({'package': name, 'version': fields['Version'], 'suite': fields['_suite'],
                     'download_bytes': int(fields['Size']),
                     'installed_size_kib': int(fields['Installed-Size']),
                     'depends': fields.get('Depends'), 'pre_depends': fields.get('Pre-Depends'),
                     'filename': fields['Filename'], 'deb_sha256_from_packages': fields['SHA256'],
                     'previous_installed_version': installed.get(name)})
    result = {'kind': 'official_ubuntu_metadata_only_minimal_gl_closure', 'date': '2026-11-11',
              'root_packages': list(ROOT_PACKAGES), 'architecture': 'amd64',
              'baseline_image': installed_payload['image_id'],
              'repositories_considered': ['jammy/main', 'jammy-updates/main'],
              'metadata': records, 'metadata_transferred_bytes': transferred,
              'metadata_cache': CACHE.relative_to(ROOT).as_posix(),
              'dependency_edges': edges, 'new_or_upgrade_packages': rows,
              'already_installed_dependencies': already, 'unresolved_dependencies': missing,
              'compressed_deb_bytes_if_later_authorized': sum(row['download_bytes'] for row in rows),
              'installed_size_kib_if_later_authorized': sum(row['installed_size_kib'] for row in rows),
              'recommends_included': False, 'deb_downloaded': False, 'apt_update_performed': False,
              'packages_installed': False, 'images_built': False, 'credentials_read': False,
              'interpretation': 'Dependency and Installed-Size metadata, not a measured Docker layer delta. Package archive/download/cache and build temporary space are separate. No recommendation that a wheel works until a public runtime probe succeeds. Metadata HTTPS hashes checked; Release GPG signature not checked.'}
    with OUT.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({'output': str(OUT), 'metadata_bytes': transferred,
                      'packages': [(row['package'], row['version']) for row in rows],
                      'compressed_deb_bytes': result['compressed_deb_bytes_if_later_authorized'],
                      'installed_size_kib': result['installed_size_kib_if_later_authorized'],
                      'unresolved_dependencies': missing}, ensure_ascii=False))


if __name__ == '__main__':
    main()
