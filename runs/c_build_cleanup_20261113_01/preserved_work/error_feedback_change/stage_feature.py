from pathlib import Path
import subprocess

base = Path('work/error_feedback_change/feature_head')
if subprocess.check_output(['git', 'diff', '--cached', '--name-only']).strip():
    raise SystemExit('Index already contains changes; refusing to overwrite them.')
paths = sorted(p for p in base.rglob('*') if p.is_file())
for path in paths:
    name = path.relative_to(base).as_posix()
    payload = path.read_bytes()
    if any(marker in payload for marker in (b'<<<<<<<', b'>>>>>>>')):
        raise SystemExit('Unresolved conflict in ' + name)
    oid = subprocess.check_output(['git', 'hash-object', '-w', '--stdin'], input=payload).decode().strip()
    subprocess.run(['git', 'update-index', '--add', '--cacheinfo', '100644', oid, name], check=True)
print('Staged', len(paths), 'scoped feature files; working files unchanged.')
