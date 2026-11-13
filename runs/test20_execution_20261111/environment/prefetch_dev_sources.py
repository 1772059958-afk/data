"""Cache the remaining designated DEV public baselines on the approved D path.

No Docker/model work. Every instance gets its own shallow repository, so future
generation images do not inherit another instance's refs or future commits.
"""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
CACHE = Path('D:/CodexExperimentCache/test20_20261111').resolve()


def fetch(row):
    iid = row['instance_id']
    destination = CACHE / 'source' / iid / 'testbed'
    if not destination.resolve().is_relative_to(CACHE) or destination.exists():
        raise ValueError('refusing an existing/out-of-cache source destination')
    audit = OUT / ('dev_cache_' + iid + '_source_01.json')
    command = [sys.executable, str(OUT / 'fetch_public_git.py'),
               '--repo', row['repo'], '--commit', row['base_commit'],
               '--directory', str(destination), '--audit', str(audit)]
    started = time.monotonic()
    process = subprocess.run(command, capture_output=True, text=True, timeout=300)
    item = {'instance_id': iid, 'repo': row['repo'], 'base_commit': row['base_commit'],
            'directory': str(destination), 'exit_code': process.returncode,
            'stdout': process.stdout, 'stderr': process.stderr,
            'seconds': round(time.monotonic()-started, 3), 'container_validation': 'not_performed'}
    if audit.is_file():
        data = json.loads(audit.read_text(encoding='utf-8'))
        item.update(audit=audit.name, audit_sha256=hashlib.sha256(audit.read_bytes()).hexdigest(),
                    source_identity_verified=data['source_identity_verified'])
    else:
        item['source_identity_verified'] = False
    item['git_object_files'] = [dict(path=p.relative_to(destination).as_posix(),
        bytes=p.stat().st_size, sha256=hashlib.sha256(p.read_bytes()).hexdigest())
        for p in sorted((destination / '.git/objects').rglob('*')) if p.is_file()]
    return item


def main():
    result_path = OUT / 'dev_source_cache_01.json'
    if result_path.exists():
        raise ValueError('refusing to overwrite the existing source-cache evidence')
    if not CACHE.is_dir() or shutil.disk_usage(CACHE).free < 10 * 1024**3:
        raise RuntimeError('approved public cache is missing or has insufficient reserve')
    metadata = json.loads((OUT / 'public_metadata.json').read_text(encoding='utf-8'))
    screen = set(json.loads((ROOT / 'runs/test20_preparation_20261111/resource_screen_instances.json')
                            .read_text(encoding='utf-8'))['instance_ids'])
    rows = [row for row in metadata['dev']['instances'] if row['instance_id'] not in screen]
    if len(rows) != 20:
        raise ValueError('complete dev23 minus the three prespecified screen cases is required')
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = {executor.submit(fetch, row): row for row in rows}
        for future in concurrent.futures.as_completed(futures):
            row = futures[future]
            try:
                item = future.result()
            except Exception as exc:
                item = dict(instance_id=row['instance_id'], source_identity_verified=False,
                            error_type=type(exc).__name__, error=str(exc)[:800])
            results.append(item)
            print(json.dumps({'instance_id': item['instance_id'],
                              'source_identity_verified': item['source_identity_verified']}), flush=True)
    result = {'kind': 'approved_public_dev_source_cache', 'date': '2026-11-11',
        'cache': str(CACHE), 'designated_dev_total': 23, 'existing_screen_sources': sorted(screen),
        'fetched_cases': len(results), 'verified_cases': sum(r['source_identity_verified'] for r in results),
        'source_instance_separation': 'independent shallow repositories, one specified base commit each',
        'source_or_test_assertions_modified': False, 'model_calls': 0, 'project_dotenv_read': False,
        'docker_containers_started': 0, 'docker_images_built': 0, 'docker_data_moved': False,
        'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'git_bridge_sha256': hashlib.sha256((OUT / 'fetch_public_git.py').read_bytes()).hexdigest(),
        'C_free_bytes': shutil.disk_usage('C:/').free, 'D_free_bytes': shutil.disk_usage(CACHE).free,
        'instances': sorted(results, key=lambda row: row['instance_id']),
        'limitations': ['Cached public Git baselines are not container/environment acceptance.',
                        'The three screen sources remain in their original project work cache.',
                        'No hidden test or official developer patch dataset field was accessed.']}
    with result_path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({'verified': result['verified_cases'], 'total': len(results),
                      'D_free_bytes': result['D_free_bytes']}), flush=True)


if __name__ == '__main__':
    main()
