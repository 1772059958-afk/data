"""Cache a minimal public-test dependency fix; no Docker or package install.

Target: exact PyVista db6ee8dd public baseline. The original screen and its
environment-failure evidence are immutable; future acceptance needs a new image.
"""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile
from email.parser import BytesParser

import requests

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
CACHE = Path('D:/CodexExperimentCache/test20_20261111/dependency_wheels').resolve()
SOURCE = ROOT / 'work/test20_environment_20261111/pyvista__pyvista-4315/testbed'
PINS = {'meshio': '5.3.4', 'tqdm': '4.64.1', 'rich': '13.9.4',
        'markdown-it-py': '3.0.0', 'mdurl': '0.1.2'}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    target = OUT / 'pyvista_public_test_dependency_fix_cache_01.json'
    if target.exists():
        raise RuntimeError('refusing to overwrite prior fix-cache evidence')
    if not CACHE.is_dir() or shutil.disk_usage(CACHE).free < 1024**3:
        raise RuntimeError('approved public cache is absent or has insufficient reserve')
    rows = []
    for name, version in PINS.items():
        metadata_url = f'https://pypi.org/pypi/{name}/{version}/json'
        response = requests.get(metadata_url, timeout=30)
        response.raise_for_status()
        metadata = response.json()
        wheels = [row for row in metadata['urls'] if not row.get('yanked')
                  and (row['filename'].endswith('py3-none-any.whl')
                       or row['filename'].endswith('py2.py3-none-any.whl'))]
        wheel = sorted(wheels, key=lambda row: row['filename'])[0]
        destination = (CACHE / wheel['filename']).resolve()
        if destination.parent != CACHE or wheel['size'] > 1024**2:
            raise ValueError('unexpected wheel target or size')
        reused = destination.exists()
        if not reused:
            package = requests.get(wheel['url'], timeout=40)
            package.raise_for_status()
            data = package.content
            if len(data) != wheel['size'] or hashlib.sha256(data).hexdigest() != wheel['digests']['sha256']:
                raise RuntimeError('official wheel size/hash mismatch')
            with destination.open('xb') as stream:
                stream.write(data)
        if destination.stat().st_size != wheel['size'] or sha(destination) != wheel['digests']['sha256']:
            raise RuntimeError('cached wheel bytes differ from official SHA256')
        with zipfile.ZipFile(destination) as archive:
            names = [item for item in archive.namelist() if item.endswith('.dist-info/METADATA')]
            wheel_metadata = BytesParser().parsebytes(archive.read(names[0]))
        rows.append({'package': name, 'version': version, 'metadata_url': metadata_url,
            'filename': wheel['filename'], 'url': wheel['url'], 'cache_path': str(destination),
            'sha256': sha(destination), 'bytes': destination.stat().st_size, 'reused_cached_bytes': reused,
            'requires_python': wheel_metadata.get('Requires-Python'),
            'requires_dist': wheel_metadata.get_all('Requires-Dist', []), 'verified_https': True})
    lock = CACHE / 'pyvista_public_tests_fix_candidate.additions.lock.txt'
    with lock.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write('# Candidate additions for exact PyVista public baseline db6ee8dd; not installed or validated.\n')
        for row in rows:
            stream.write(f"{row['package']}=={row['version']} --hash=sha256:{row['sha256']}\n")
    evidence = []
    for filename in ('pyproject.toml', 'requirements_test.txt', 'requirements_docs.txt'):
        path = SOURCE / filename
        evidence.append({'file': str(path), 'sha256': sha(path),
            'relevant_lines': [dict(line_number=i, text=line) for i, line in
                enumerate(path.read_text(encoding='utf-8').splitlines(), 1)
                if 'meshio' in line or 'tqdm' in line]})
    record = {'kind': 'public_pyvista_dependency_fix_cache', 'date': '2026-11-11',
        'status': 'candidate_cached_not_installed',
        'source_base_commit': 'db6ee8dd4a747b8864caae36c5d05883976a3ae5',
        'original_image': 'sha256:c3d02ef66da989070d532ea6993104f9d4b76e3d5f86fea85d7e4da1fba2e230',
        'baseline_failure_report': 'pyvista_public_baseline_extended_classification_01.json',
        'baseline_failure_report_sha256': sha(OUT / 'pyvista_public_baseline_extended_classification_01.json'),
        'source_evidence': evidence, 'target_python': 'CPython 3.9.23 Linux x86_64',
        'wheels': rows, 'candidate_lock': {'path': str(lock), 'sha256': sha(lock)},
        'declared_inherited_dependencies': {'numpy': '1.24.4', 'Pygments': '2.19.1'},
        'compatibility_basis': [
            'meshio5.3.4 exactly matches the same-commit requirements_docs pin and satisfies io>=5.2 and test<5.4.0.',
            'tqdm4.64.1 satisfies the same-commit test requirement <4.66.0 and reuses verified cached bytes.',
            'rich13.9.4 supports Python>=3.8; markdown-it-py3.0.0 supports Python>=3.8; mdurl0.1.2 supports Python>=3.7.',
            'meshio needs numpy>=1.20.0 and rich; rich needs markdown-it-py>=2.2.0 and pygments>=2.13,<3; markdown-it-py needs mdurl~=0.1.',
            'This is metadata-level compatibility only; exact public baseline rerun remains mandatory.'],
        'formal_test_execution': 'deferred_by_user; this session stops after dev calibration and freeze',
        'packages_installed': False, 'docker_operations': False, 'model_calls': 0,
        'project_dotenv_read': False, 'source_or_tests_modified': False,
        'script_sha256': sha(Path(__file__)),
        'new_download_bytes': sum(row['bytes'] for row in rows if not row['reused_cached_bytes']),
        'total_fix_wheel_bytes': sum(row['bytes'] for row in rows),
        'D_free_bytes': shutil.disk_usage(CACHE).free}
    with target.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({'wheels': len(rows), 'new_download_bytes': record['new_download_bytes'],
                      'total_fix_wheel_bytes': record['total_fix_wheel_bytes'],
                      'lock': str(lock), 'docker_operations': False}))


if __name__ == '__main__':
    main()
