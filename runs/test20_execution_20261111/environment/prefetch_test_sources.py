"""Sequentially cache only the 20 preregistered public TEST baselines.

No Docker work, dependency installation, model calls, or evaluator fields.
The imported fetch helper creates one independent shallow repository per case.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

OUT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('verified_public_source_cache', OUT / 'prefetch_dev_sources.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


def main():
    path = OUT / 'test_source_cache_01.json'
    if path.exists():
        raise RuntimeError('refusing to overwrite prior test source-cache evidence')
    metadata = json.loads((OUT / 'public_metadata.json').read_text(encoding='utf-8'))
    sample_path = helper.ROOT / 'runs/test20_preparation_20261111/instances.json'
    sample = json.loads(sample_path.read_text(encoding='utf-8'))
    ids = sample['instance_ids']
    indexed = {row['instance_id']: row for row in metadata['test']['instances']}
    if len(ids) != 20 or len(set(ids)) != 20 or set(indexed) != set(ids):
        raise ValueError('exact preregistered test20 public metadata is required')
    results = []
    # Deliberately sequential: do not compete with active screen model/container load.
    for iid in ids:
        row = indexed[iid]
        try:
            item = helper.fetch(row)
        except Exception as exc:
            item = {'instance_id': iid, 'source_identity_verified': False,
                    'error_type': type(exc).__name__, 'error': str(exc)[:800]}
        results.append(item)
        print(json.dumps({'instance_id': iid, 'source_identity_verified': item['source_identity_verified']}), flush=True)
    result = {'kind': 'preregistered_test_public_source_cache', 'date': '2026-11-11',
        'cache': str(helper.CACHE / 'source'), 'split': 'test', 'designated_cases': 20,
        'concurrency': 1, 'fetched_cases': len(results),
        'verified_cases': sum(row['source_identity_verified'] for row in results),
        'sampling_manifest': str(sample_path),
        'sampling_manifest_sha256': hashlib.sha256(sample_path.read_bytes()).hexdigest(),
        'instance_ids': ids, 'instances': results,
        'source_instance_separation': 'independent shallow repositories; one specified public base commit each',
        'source_or_test_assertions_modified': False, 'model_calls': 0,
        'project_dotenv_read': False, 'hidden_fields_read': False,
        'docker_containers_started': 0, 'docker_images_built': 0, 'docker_data_moved': False,
        'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'fetch_helper_sha256': hashlib.sha256((OUT / 'prefetch_dev_sources.py').read_bytes()).hexdigest(),
        'git_bridge_sha256': hashlib.sha256((OUT / 'fetch_public_git.py').read_bytes()).hexdigest(),
        'C_free_bytes': shutil.disk_usage('C:/').free, 'D_free_bytes': shutil.disk_usage(helper.CACHE).free,
        'limitations': ['Git cache identity is not environment/container acceptance.',
            'No test outcome or evaluation field was used to prepare or replace an instance.',
            'All formal downloading/building must finish before formal generation starts.']}
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({'verified': result['verified_cases'], 'total': len(results),
                      'D_free_bytes': result['D_free_bytes']}), flush=True)


if __name__ == '__main__':
    main()
