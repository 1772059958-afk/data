import email
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[2]
site = root / 'work/scoring_setup/linux_site'
packages = []
for info in sorted(site.glob('*.dist-info')):
    metadata = email.message_from_string((info / 'METADATA').read_text(encoding='utf-8'))
    wheel = email.message_from_string((info / 'WHEEL').read_text(encoding='utf-8'))
    tags = wheel.get_all('Tag') or []
    if any('win' in tag or 'macos' in tag for tag in tags):
        raise ValueError('non-Linux binary wheel detected: ' + str(info))
    packages.append({'name': metadata['Name'], 'version': metadata['Version'], 'wheel_tags': tags})
lock = root / 'docker/scoring/requirements.lock.txt'
data = {'target_python': '3.11', 'target_platform': 'x86_64-manylinux_2_28',
        'package_count': len(packages), 'packages': packages,
        'installation': {'source_index': 'https://pypi.tuna.tsinghua.edu.cn/simple',
                         'hash_origin': 'official PyPI', 'require_hashes': True,
                         'only_binary': True},
        'requirements_lock_sha256': hashlib.sha256(lock.read_bytes()).hexdigest(),
        'windows_or_macos_wheels': 0,
        'shared_library_count': len(list(site.rglob('*.so')))}
out = root / 'runs/dev2_acceptance_20261106/environment/scoring'
out.mkdir(parents=True, exist_ok=True)
with (out / 'linux_packages.json').open('x', encoding='utf-8') as stream:
    json.dump(data, stream, ensure_ascii=False, indent=2)
print(json.dumps({key: data[key] for key in ('package_count', 'target_python', 'target_platform',
                                           'windows_or_macos_wheels', 'shared_library_count',
                                           'requirements_lock_sha256')}))
