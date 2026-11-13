"""Replay public DEV environment preparation; default is a Docker-free plan.

No network/model client, credential loading, hidden data or source edits. Actual
execution is serial and requires --execute after root verifies Docker migration.
Each candidate is independently checked before/after its public smoke; failed
cases remain in the 23-case ledger and never enter the accepted image map.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import time

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[2]
SHA = re.compile(r'sha256:[0-9a-f]{64}')
RESERVE = 4 * 1024**3


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024**2), b''):
            h.update(block)
    return h.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def explicit_container_absence(text, name):
    return name in text and re.search(r'no such (?:container|object)\b', text, re.IGNORECASE) is not None


def validate_manifest(path):
    data = read_json(path)
    ids = (PROJECT / 'data/frozen/instances_dev.txt').read_text(encoding='utf-8').splitlines()
    cases = data.get('instances', [])
    if (data.get('kind') != 'serial_public_dev23_preparation_manifest'
            or len(cases) != 23 or {row['instance_id'] for row in cases} != set(ids)
            or len({row['instance_id'] for row in cases}) != 23):
        raise ValueError('the complete designated DEV23 population is required')
    for row in cases:
        if (not re.fullmatch(r'[0-9a-f]{40}', row['base_commit'])
                or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', row['repo'])
                or row['dependency_profile'] not in data['profiles']):
            raise ValueError('invalid source identity/profile')
        if not (Path(row['source_directory']) / '.git/HEAD').is_file():
            raise ValueError('missing independently cached Git baseline: ' + row['instance_id'])
        allowed_sources = {(PROJECT / 'work/test20_environment_20261111' / row['instance_id'] / 'testbed').resolve(),
                           (Path('D:/CodexExperimentCache/test20_20261111/source') / row['instance_id'] / 'testbed').resolve()}
        if Path(row['source_directory']).resolve() not in allowed_sources:
            raise ValueError('source directory is not the approved instance-specific public cache')
        modules = {'marshmallow-code/marshmallow': 'marshmallow', 'pvlib/pvlib-python': 'pvlib',
                   'pydicom/pydicom': 'pydicom', 'pylint-dev/astroid': 'astroid',
                   'pyvista/pyvista': 'pyvista', 'sqlfluff/sqlfluff': 'sqlfluff'}
        if modules.get(row['repo']) != row['module']:
            raise ValueError('unexpected public source module')
        if not row['expected_files'] or any(not re.fullmatch(r'[0-9a-f]{40}', f['git_blob_sha1'])
                                           for f in row['expected_files']):
            raise ValueError('public Git blob identities are required')
        for item in row['expected_files']:
            relative = Path(item['relative_path'])
            if relative.is_absolute() or '..' in relative.parts or '.git' in relative.parts:
                raise ValueError('public validation paths must stay in the checkout')
        if row['repo'] == 'pvlib/pvlib-python' and row['dependency_profile'] != 'pvlib_initial':
            amendment = row.get('public_baseline_amendment', {})
            evidence_path = Path(amendment.get('report', '')).resolve()
            if (not evidence_path.is_relative_to(HERE) or not evidence_path.is_file()
                    or digest(evidence_path) != amendment.get('sha256')
                    or row['dependency_profile'] not in ('pvlib_nose_only', 'pvlib_legacy_pandas')):
                raise ValueError('legacy pvlib changes require a bound real baseline-failure report')
            evidence = read_json(evidence_path)
            identity = evidence.get('baseline_before_install', evidence.get('reuse_validation', {}).get('identity_before', {}))
            if (evidence.get('instance_id') != row['instance_id'] or evidence.get('base_commit') != row['base_commit']
                    or evidence.get('patch_applied') is not False or identity.get('clean') is not True
                    or evidence.get('source_or_tests_modified') is not False
                    or identity.get('head') != row['base_commit']):
                raise ValueError('pvlib amendment must refer to its untouched public baseline')
            smoke = evidence.get('initial_public_smoke', evidence.get('reuse_validation', {}).get('public_smoke', {}))
            log_path = (evidence_path.parent / smoke.get('log', '')).resolve()
            if (smoke.get('exit_code') in (None, 0) or not log_path.is_relative_to(evidence_path.parent)
                    or not log_path.is_file() or digest(log_path) != smoke.get('log_sha256')):
                raise ValueError('pvlib amendment requires original failed public stdout/stderr bytes')
            text = log_path.read_text(encoding='utf-8')
            if row['dependency_profile'] == 'pvlib_nose_only':
                if "No module named 'nose'" not in text and 'No module named "nose"' not in text:
                    raise ValueError('nose profile requires an observed missing-nose error')
            elif ('pandas' not in text.lower() or not any(term in text.lower() for term in
                    ('has no attribute', 'unexpected keyword', 'cannot import name', 'removed'))
                    or not amendment.get('reason')):
                raise ValueError('pandas candidate requires observed API-compatibility evidence and review rationale')
    for item in data['bound_inputs']:
        source = (HERE / item['path']).resolve()
        if not source.is_relative_to(HERE) or digest(source) != item['sha256']:
            raise ValueError('preparation input bytes changed: ' + item['path'])
    for profile in data['profiles'].values():
        verify_profile(profile)
    return data


def verify_profile(profile):
    if not SHA.fullmatch(profile['parent_image']):
        raise ValueError('dependency parent must be an actual fixed local image ID')
    if profile.get('lock'):
        lock = Path(profile['lock']['path'])
        if digest(lock) != profile['lock']['sha256']:
            raise ValueError('dependency lock changed')
        for wheel in profile['wheels']:
            if digest(wheel['path']) != wheel['sha256']:
                raise ValueError('cached wheel bytes changed')


def identity_program(case, *, imports=True):
    files = {row['relative_path']: row['git_blob_sha1'] for row in case['expected_files']}
    trees = case.get('expected_trees', {})
    return f'''import hashlib, importlib, importlib.metadata, json, pathlib, subprocess, sys
root=pathlib.Path('/testbed')
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
clean=subprocess.check_output(['git','status','--porcelain'],cwd=root,text=True).strip()
assert head=={case['base_commit']!r}, (head,'base mismatch')
assert not clean, clean
for relative,expected in {files!r}.items():
    payload=(root/relative).read_bytes()
    actual=hashlib.sha1(b'blob '+str(len(payload)).encode()+b'\\0'+payload).hexdigest()
    assert actual==expected, (relative,actual,expected)
for relative,expected in {trees!r}.items():
    actual=subprocess.check_output(['git','rev-parse','HEAD:'+relative],cwd=root,text=True).strip()
    assert actual==expected, (relative,actual,expected)
result={{'head':head,'clean':True,'selected_git_blob_bytes_verified':True,'python':sys.version.split()[0]}}
if {imports!r}:
    module=importlib.import_module({case['module']!r})
    location=pathlib.Path(module.__file__).resolve()
    assert location.is_relative_to(root), str(location)
    result.update(module_file=str(location),module_version=getattr(module,'__version__',None))
    result['distributions']={{}}
    for name in {case['record_distribution_versions']!r}:
        try: result['distributions'][name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: result['distributions'][name]=None
print('__DEV23_IDENTITY__'+json.dumps(result))
'''


class Preparation:
    def __init__(self, args, manifest, output):
        self.args, self.manifest, self.output = args, manifest, output
        self.owned = {}
        self.layer_images = {}
        self.counter = 0
        self.log = (output / 'events.jsonl').open('x', encoding='utf-8', newline='\n')

    def event(self, item):
        self.log.write(json.dumps(item, ensure_ascii=False) + '\n')
        self.log.flush()
        os.fsync(self.log.fileno())

    def guard(self):
        points = {'system': Path('C:/'), 'public_cache': Path(self.manifest['wheel_cache']),
                  'declared_docker_storage': Path(self.args.docker_data_host_path)}
        free = {key: shutil.disk_usage(path).free for key, path in points.items()}
        if min(free.values()) < RESERVE + 64 * 1024**2:
            raise RuntimeError('host or target volume approaching the 4 GiB reserve: ' + str(free))
        return free

    def run(self, label, arguments, *, timeout=180, check=True, cleanup=False):
        if not cleanup:
            self.guard()
        self.counter += 1
        path = self.output / f'{self.counter:04d}_{re.sub("[^A-Za-z0-9_-]", "_", label)[:96]}.log'
        started = time.monotonic()
        with path.open('x', encoding='utf-8', newline='\n') as log:
            process = subprocess.Popen(arguments, stdout=log, stderr=subprocess.STDOUT,
                                       text=True, encoding='utf-8', errors='replace')
            try:
                while process.poll() is None:
                    if not cleanup:
                        self.guard()
                    if time.monotonic()-started > timeout:
                        raise TimeoutError(label + ' preparation timeout')
                    time.sleep(0.4)
            except BaseException:
                process.terminate()
                process.wait(timeout=15)
                raise
        result = {'label': label, 'arguments': arguments, 'exit_code': process.returncode,
                  'log': path.name, 'log_sha256': digest(path),
                  'seconds': round(time.monotonic()-started, 3)}
        self.event(result)
        text = path.read_text(encoding='utf-8')
        if check and process.returncode:
            raise RuntimeError(label + ' failed; see ' + path.name)
        return result, text

    def docker(self, label, *arguments, **options):
        return self.run(label, ['docker', '--context', self.args.context, *arguments], **options)

    def start(self, label, image, *, profile=None):
        name = 'dev23prep-' + self.args.tag + '-' + hashlib.sha256(label.encode()).hexdigest()[:12]
        existing, absence = self.docker(label + '_name_check', 'inspect', '--type', 'container', name, check=False)
        if existing['exit_code'] == 0:
            raise RuntimeError('container name already exists; refusing reuse/removal')
        if not explicit_container_absence(absence, name):
            raise RuntimeError('could not establish container-name absence: ' + absence[-500:])
        command = ['run', '-d', '--pull=never', '--network', 'none', '--name', name,
                   '--label', 'codex.dev23.preparation=' + self.args.tag]
        if profile and profile.get('lock'):
            command += ['--mount', f'type=bind,source={self.manifest["wheel_cache"]},target=/public-wheels,readonly',
                        '--mount', f'type=bind,source={profile["lock"]["path"]},target=/public-profile.lock,readonly']
        command += ['--entrypoint', '/bin/bash', image, '-lc', 'sleep infinity']
        self.owned[name] = None
        _, text = self.docker(label + '_start', *command)
        self.owned[name] = text.strip().splitlines()[-1]
        return name

    def clean(self, name):
        expected = self.owned.get(name)
        if name not in self.owned:
            return
        if expected is None:
            time.sleep(2)  # let an interrupted, already-sent Docker start settle
        check, text = self.docker('cleanup_identity', 'inspect', '--type', 'container',
                                 '--format', '{{.Id}} {{index .Config.Labels "codex.dev23.preparation"}}',
                                 name, check=False, cleanup=True, timeout=30)
        parts = text.strip().split()
        if (check['exit_code'] == 0 and len(parts) == 2 and parts[1] == self.args.tag
                and (expected is None or parts[0] == expected)):
            self.docker('cleanup_owned', 'rm', '-f', name, cleanup=True, timeout=30)
        elif check['exit_code'] == 0:
            raise RuntimeError('owned container name was reused; refusing to remove a different container')
        elif not explicit_container_absence(text, name):
            raise RuntimeError('cannot verify owned container identity/absence: ' + text[-500:])
        gone, absence = self.docker('cleanup_absence', 'inspect', '--type', 'container', name,
                              check=False, cleanup=True, timeout=30)
        if gone['exit_code'] == 0 or not explicit_container_absence(absence, name):
            raise RuntimeError('owned preparation container absence is unverified: ' + absence[-500:])
        del self.owned[name]

    def shell(self, name, label, script, **options):
        return self.docker(label, 'exec', name, 'bash', '-lc', script, **options)

    def identity(self, name, case, label, *, imports=True):
        _, text = self.shell(name, label,
            'cd /testbed && python -c ' + shlex.quote(identity_program(case, imports=imports)))
        line = next(line for line in reversed(text.splitlines()) if line.startswith('__DEV23_IDENTITY__'))
        return json.loads(line.removeprefix('__DEV23_IDENTITY__'))

    def layer(self, key):
        if key in self.layer_images:
            return self.layer_images[key]
        profile = self.manifest['profiles'][key]
        verify_profile(profile)
        self.docker('parent_' + key, 'image', 'inspect', '--format', '{{.Id}}', profile['parent_image'])
        if not profile.get('lock'):
            self.layer_images[key] = profile['parent_image']
            return profile['parent_image']
        name = self.start('dependency_' + key, profile['parent_image'], profile=profile)
        try:
            self.shell(name, 'dependency_install_' + key,
                'python -m pip install --no-index --no-deps --no-cache-dir --require-hashes '
                '--find-links /public-wheels -r /public-profile.lock')
            tag = 'dev23-prepared/dependencies:' + self.args.tag + '-' + key.replace('_', '-')
            self.docker('dependency_commit_' + key, 'commit', name, tag)
            _, text = self.docker('dependency_id_' + key, 'image', 'inspect', '--format', '{{.Id}}', tag)
            image = text.strip()
            if not SHA.fullmatch(image):
                raise RuntimeError('dependency image identity unavailable')
            self.layer_images[key] = image
            return image
        finally:
            self.clean(name)

    def validate_existing(self, case, image):
        name = self.start(case['instance_id'] + '_verify', image)
        try:
            _, actual = self.docker('actual_image', 'inspect', '--format', '{{.Image}}', name)
            if actual.strip() != image:
                raise RuntimeError('running image identity differs')
            before = self.identity(name, case, 'identity_before', imports=False)
            imported = self.identity(name, case, 'import_before')
            smoke, _ = self.shell(name, 'public_smoke', 'cd /testbed && ' + case['public_smoke_command'], check=False)
            after = self.identity(name, case, 'identity_after')
            return {'actual_image_id': actual.strip(), 'identity_before': before,
                    'imports': imported, 'public_smoke': smoke, 'identity_after': after,
                    'passed': smoke['exit_code'] == 0}
        finally:
            self.clean(name)

    def prepare_case(self, case, reusable):
        result = {'instance_id': case['instance_id'], 'base_commit': case['base_commit'],
                  'repo': case['repo'], 'dependency_profile': case['dependency_profile'],
                  'status': 'not_prepared', 'patch_applied': False, 'model_calls': 0,
                  'smoke_scope_only': True, 'source_or_tests_modified': None}
        try:
            image = reusable.get(case['instance_id'], case.get('reusable_candidate_image'))
            if image:
                if image in case.get('incomplete_images_not_for_reuse', []):
                    raise RuntimeError('known incomplete environment requires a new corrected image')
                if not SHA.fullmatch(image):
                    raise ValueError('reusable image must be an exact ID')
                validation = self.validate_existing(case, image)
                result['reuse_validation'] = validation
                result['source_or_tests_modified'] = False
                if not validation['passed']:
                    result['status'] = 'public_smoke_failed'
                    return result
                result.update(status='public_smoke_ready', image_id=image, reused=True)
                return result
            if case.get('requires_corrected_external_image'):
                result['status'] = 'blocked_pending_corrected_pyvista_image'
                return result
            parent = self.layer(case['dependency_profile'])
            name = self.start(case['instance_id'] + '_prepare', parent)
            try:
                self.shell(name, 'empty_testbed', 'rm -rf /testbed && mkdir /testbed')
                self.docker('copy_real_git', 'cp', str(Path(case['source_directory']) / '.git'), name + ':/testbed/.git')
                self.shell(name, 'materialize_exact_baseline', 'cd /testbed && git config core.autocrlf false '
                    '&& git config core.filemode true && git config core.symlinks true '
                    '&& git reset --hard HEAD && git config remote.origin.url ' + shlex.quote('https://github.com/' + case['repo'] + '.git')
                    + ' && test "$(git rev-parse HEAD)" = ' + shlex.quote(case['base_commit'])
                    + ' && test -z "$(git status --porcelain)"')
                result['baseline_before_install'] = self.identity(name, case, 'baseline_before_install', imports=False)
                self.shell(name, 'editable_install', 'python -m pip install --no-index --no-deps '
                    '--no-build-isolation --no-cache-dir -e /testbed')
                result['installed_imports'] = self.identity(name, case, 'installed_imports')
                smoke, _ = self.shell(name, 'public_smoke', 'cd /testbed && ' + case['public_smoke_command'], check=False)
                result['initial_public_smoke'] = smoke
                result['baseline_after_smoke'] = self.identity(name, case, 'baseline_after_smoke')
                result['source_or_tests_modified'] = False
                if smoke['exit_code']:
                    result['status'] = 'public_smoke_failed'
                    result['next_step'] = 'Review untouched-baseline errors before any bounded dependency amendment; no automatic latest install.'
                    return result
                tag = 'dev23-prepared/' + case['instance_id'].replace('__', '-') + ':' + self.args.tag
                self.docker('commit_case', 'commit', name, tag)
                _, text = self.docker('inspect_case_image', 'image', 'inspect', '--format', '{{.Id}}', tag)
                image = text.strip()
                if not SHA.fullmatch(image):
                    raise RuntimeError('new image identity unavailable')
                result['prepared_candidate_image'] = image
            finally:
                self.clean(name)
            validation = self.validate_existing(case, image)
            result['fresh_image_validation'] = validation
            if validation['passed']:
                result.update(status='public_smoke_ready', image_id=image, reused=False)
            else:
                result['status'] = 'fresh_public_smoke_failed'
        except Exception as exc:
            result.update(status='preparation_error', error_type=type(exc).__name__, error=str(exc))
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=HERE / 'dev23_prepare_manifest_01.json')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--tag')
    parser.add_argument('--docker-data-host-path', type=Path)
    parser.add_argument('--context', default='desktop-linux')
    parser.add_argument('--instances', nargs='+')
    parser.add_argument('--reusable-images-json', type=Path)
    args = parser.parse_args(argv)
    manifest = validate_manifest(args.manifest)
    ids = {case['instance_id'] for case in manifest['instances']}
    selected = set(args.instances or ids)
    if not selected or not selected <= ids:
        parser.error('instance selection lies outside designated DEV23')
    if not args.execute:
        print(json.dumps({'kind': 'offline_preparation_plan', 'execute': False,
            'designated_dev_total': 23, 'selected': sorted(selected),
            'profiles': manifest['profiles'], 'instances': manifest['instances'],
            'docker_operations': 0, 'model_calls': 0}, ensure_ascii=False, indent=2))
        return 0
    if (not args.tag or not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', args.tag)
            or args.docker_data_host_path is None or not args.docker_data_host_path.exists()):
        parser.error('execution needs a new safe tag and the verified existing Docker host storage path')
    if min(shutil.disk_usage(point).free for point in
           ('C:/', manifest['wheel_cache'], args.docker_data_host_path)) < RESERVE + 64*1024**2:
        parser.error('host or target volume is already at the 4 GiB reserve')
    output = HERE / 'dev23_preparation_runs' / args.tag
    if output.exists():
        parser.error('refusing to overwrite an existing preparation run')
    reused = read_json(args.reusable_images_json) if args.reusable_images_json else {}
    if not isinstance(reused, dict) or set(reused) - ids or any(not SHA.fullmatch(v) for v in reused.values()):
        parser.error('reusable image overrides must map only designated dev IDs to actual sha256 IDs')
    output.mkdir(parents=True)
    runner = Preparation(args, manifest, output)
    results = []
    try:
        runner.guard()
        runner.docker('engine_ready', 'info', '--format', '{{.DockerRootDir}}', timeout=30)
        for case in manifest['instances']:
            result = runner.prepare_case(case, reused) if case['instance_id'] in selected else {
                'instance_id': case['instance_id'], 'base_commit': case['base_commit'], 'status': 'not_selected_not_prepared'}
            results.append(result)
            with (output / (case['instance_id'] + '.json')).open('x', encoding='utf-8', newline='\n') as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
            if result['status'] == 'preparation_error' and 'reserve' in result.get('error', ''):
                raise RuntimeError('disk reserve reached; stop before the next case')
    finally:
        cleanup_errors = []
        for name in list(runner.owned):
            try:
                runner.clean(name)
            except Exception as exc:
                cleanup_errors.append({'container': name, 'error': str(exc)})
        runner.log.close()
        complete = {row['instance_id']: row for row in results}
        all_results = [complete.get(row['instance_id'], dict(instance_id=row['instance_id'],
            base_commit=row['base_commit'], status='not_prepared_after_interruption')) for row in manifest['instances']]
        accepted = {row['instance_id']: row['image_id'] for row in all_results if row['status'] == 'public_smoke_ready'}
        report = {'kind': 'public_dev23_environment_preparation_results', 'designated_total': 23,
            'manifest_sha256': digest(args.manifest), 'script_sha256': digest(Path(__file__)),
            'instances': all_results, 'accepted_public_smoke_images': accepted,
            'all23_public_smoke_ready': len(accepted) == 23 and not cleanup_errors and not runner.owned,
            'model_calls': 0,
            'formal_test_execution': False, 'project_dotenv_read': False,
            'cleanup_errors': cleanup_errors, 'owned_containers_remaining': dict(runner.owned),
            'storage_host_path_declared_by_operator': str(args.docker_data_host_path),
            'storage_location_must_be_verified_by_root_migration_audit': True,
            'scope_limit': 'Selected public smoke only; not full repo/hidden harness acceptance.'}
        for name, value in [('summary.json', report), ('public_smoke_images.json', accepted)]:
            with (output / name).open('x', encoding='utf-8', newline='\n') as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
    print(output / 'summary.json')
    return 0 if len(accepted) == len(selected) and not cleanup_errors else 2


if __name__ == '__main__':
    raise SystemExit(main())
