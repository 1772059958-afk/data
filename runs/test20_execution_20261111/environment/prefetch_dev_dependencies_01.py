"""Fetch only public, SHA256-verified candidate wheels into the authorised D cache.

No package is installed and no Docker/model/credential operation is performed.
These additions are candidate environment locks, not validated runtime claims.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import zipfile

import requests

ROOT = Path(__file__).resolve().parents[3]
ENVIRONMENT = ROOT / 'runs/test20_execution_20261111/environment'
CACHE = Path('D:/CodexExperimentCache/test20_20261111/dependency_wheels').resolve()
AUDIT = ENVIRONMENT / 'dev_dependency_prefetch_01.json'
PARENT = 'sha256:bd5edf8694cde12aaf99beb18b3935b15e076e81ac7e52aef46b1ca3d9071428'

# Versions are bounded candidates chosen for CPython3.9 and the public historical
# requirements. Actual public baseline tests still decide whether they work.
PINS = {
    'wrapt': '1.13.3', 'lazy-object-proxy': '1.10.0',
    'simplejson': '3.19.3', 'nose': '1.3.7',
    'appdirs': '1.4.4', 'cached-property': '1.5.2', 'chardet': '4.0.0',
    'click': '8.0.4', 'colorama': '0.4.6', 'configparser': '5.3.0',
    'diff-cover': '5.2.0', 'Jinja2': '3.0.3', 'jinja2-pluralize': '0.3.0',
    'MarkupSafe': '2.1.5', 'oyaml': '1.0', 'pathspec': '0.9.0',
    'toml': '0.10.2', 'tblib': '1.7.0', 'regex': '2022.10.31',
    'tqdm': '4.64.1', 'pandas': '1.5.3',
}
PROFILES = {
    'astroid_legacy': ['wrapt', 'lazy-object-proxy'],
    'marshmallow_tests': ['simplejson'],
    'pvlib_legacy_candidate': ['nose', 'pandas'],
    'sqlfluff_06_08_candidate': [p for p in PINS if p not in
        {'wrapt', 'lazy-object-proxy', 'simplejson', 'nose', 'pandas'}],
}


def canonical(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def safe_cache_path(filename):
    target = (CACHE / filename).resolve()
    if target.parent != CACHE or not filename.endswith('.whl'):
        raise ValueError('wheel path escapes the explicitly authorised cache')
    return target


def metadata(item):
    name, version = item
    url = f'https://pypi.org/pypi/{name}/{version}/json'
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    document = response.json()
    wheels = [entry for entry in document.get('urls', [])
              if entry['filename'].endswith('.whl') and not entry.get('yanked')]
    def compatible(entry):
        filename = entry['filename']
        if filename.endswith('-none-any.whl'):
            return filename.rsplit('-', 3)[1] in ('py3', 'py2.py3', 'py2.py3.py34.py35')
        return ('-cp39-cp39-' in filename and 'manylinux' in filename
                and filename.endswith('x86_64.whl'))
    candidates = sorted((entry for entry in wheels if compatible(entry)),
                        key=lambda entry: entry['filename'])
    if not candidates:
        raise ValueError(f'no matching public Linux CP39/universal wheel for {name}=={version}')
    selected = candidates[0]
    if selected['size'] > 20 * 1024**2:
        raise ValueError('candidate exceeds the per-wheel download size guard')
    return {'package': name, 'version': version, 'metadata_url': url,
            'filename': selected['filename'], 'url': selected['url'],
            'sha256': selected['digests']['sha256'], 'bytes': selected['size'],
            'requires_python': document['info'].get('requires_python'),
            'requires_dist': document['info'].get('requires_dist') or [],
            'wheel_requires_python': selected.get('requires_python'),
            'metadata_source': 'official PyPI JSON; TLS verification enabled',
            'compatibility_basis': 'exact CP39/CP39 manylinux x86_64 tag or universal Python3 wheel; runtime still unverified'}


def main():
    if AUDIT.exists():
        raise FileExistsError('audit output is immutable; use a new attempt tag')
    allowed = Path('D:/CodexExperimentCache/test20_20261111').resolve()
    if CACHE.parent != allowed:
        raise ValueError('cache must stay within the explicitly authorised public-cache root')
    CACHE.mkdir(parents=True, exist_ok=True)
    rows = list(ThreadPoolExecutor(max_workers=4).map(metadata, PINS.items()))
    if sum(row['bytes'] for row in rows) > 35 * 1024**2:
        raise ValueError('candidate wheel set exceeds the 35MiB prefetch guard')
    downloaded = 0
    for row in rows:
        target = safe_cache_path(row['filename'])
        if target.exists():
            if target.stat().st_size != row['bytes'] or sha(target) != row['sha256']:
                raise ValueError('existing cache entry differs from official PyPI identity')
            row['cache_status'] = 'existing_sha256_verified'
        else:
            if shutil.disk_usage(CACHE).free < 1024**3 + row['bytes']:
                raise RuntimeError('D cache free space guard reached')
            partial = safe_cache_path(row['filename'] + '.partial.whl')
            if partial.exists():
                raise FileExistsError('partial download requires explicit audit before retry')
            with requests.get(row['url'], timeout=60, stream=True) as response:
                response.raise_for_status()
                with partial.open('xb') as stream:
                    written = 0
                    for chunk in response.iter_content(256 * 1024):
                        written += len(chunk)
                        if written > row['bytes']:
                            raise ValueError('wheel response exceeded official declared size')
                        stream.write(chunk)
            if partial.stat().st_size != row['bytes'] or sha(partial) != row['sha256']:
                raise ValueError('download differs from official PyPI SHA256/size')
            partial.rename(target)
            downloaded += row['bytes']
            row['cache_status'] = 'downloaded_sha256_verified'
        row['cache_path'] = str(target)
        with zipfile.ZipFile(target) as wheel:
            paths = [name for name in wheel.namelist() if name.endswith('.dist-info/METADATA')]
            if len(paths) != 1:
                raise ValueError('wheel metadata is missing or ambiguous')
            from email.parser import BytesParser
            actual = BytesParser().parsebytes(wheel.read(paths[0]))
            if canonical(actual['Name']) != canonical(row['package']) or actual['Version'] != row['version']:
                raise ValueError('wheel metadata package/version differs from pinned public identity')
            row['wheel_requires_dist'] = actual.get_all('Requires-Dist', [])
    indexed = {row['package']: row for row in rows}
    locks = []
    for profile, packages in PROFILES.items():
        path = CACHE / f'{profile}.additions.lock.txt'
        body = ['# Candidate additions for public-baseline testing; not installed/validated.',
                '# Exact parent image: ' + PARENT,
                '# Install alongside its separately recorded inherited dependencies.',
                '# --no-deps is deliberate: inherited/transitive closure must be checked before use.']
        body += [f"{name}=={PINS[name]} --hash=sha256:{indexed[name]['sha256']}" for name in packages]
        with path.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write('\n'.join(body) + '\n')
        locks.append({'profile': profile, 'path': str(path), 'sha256': sha(path),
                      'packages': packages, 'scope': 'candidate additions only, not a fully validated environment lock'})
    report = {
        'kind': 'public_dev_dependency_prefetch', 'date': '2026-11-11',
        'status': 'candidate_wheels_cached_no_install_or_runtime_validation',
        'cache_root': str(CACHE), 'authorisation_basis': 'Root confirmed newly authorised D public experiment cache; no Docker data relocation',
        'python_target': 'CPython3.9 Linux x86_64', 'candidate_parent_image_id': PARENT,
        'wheels': rows, 'locks': locks, 'new_download_bytes': downloaded,
        'all_cached_wheel_bytes': sum(row['bytes'] for row in rows),
        'inherited_dependencies_not_redownloaded': {
            'pytest': '7.4.4', 'pytz': '2024.1', 'python-dateutil': '2.9.0.post0',
            'six': '1.17.0', 'typing-extensions': '4.13.2', 'numpy': '1.26.4',
            'PyYAML': '6.0.2', 'Pygments': '2.19.1', 'pluggy': '1.5.0'},
        'source_evidence': ['environment/full_dev_preparation_plan.json exactcommit public dependency provenance',
            'SQLFluff304a197... src/sqlfluff/config.ini version0.6.8 (not0.4.0)',
            'astroid2.9/2.10 wrapt>=1.11,<1.14; marshmallowtests.base imports simplejson+pytz',
            'nose is for older pvlib test extras, not a proven marshmallow requirement'],
        'unknowns': ['No wheel was installed or imported in the target image',
            'Candidate additions are not a solver-certified full transitive environment lock',
            'SQLFluff old CLI/Jinja/diff-cover/pluggy interactions require public baseline validation',
            'pandas1.5.3 is an optional legacy compatibility candidate, not a proven requirement or fix',
            'Old pvlib may also expose SciPy1.13 API removals; no extra SciPy wheel fetched',
            'PyVista graphics support and official evaluation are outside this prefetch task'],
        'actions': {'models_called': 0, 'credentials_read': False, 'docker_builds': 0,
                    'package_installs': 0, 'docker_data_moved': False, 'tls_verification_disabled': False},
        'D_free_bytes_after': shutil.disk_usage(CACHE).free,
    }
    with AUDIT.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'audit': str(AUDIT), 'wheels': len(rows), 'downloaded_bytes': downloaded,
                      'all_cached_bytes': report['all_cached_wheel_bytes'], 'locks': len(locks)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
