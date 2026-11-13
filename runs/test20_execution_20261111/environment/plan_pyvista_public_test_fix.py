"""Offline metadata compatibility checks and an unexecuted amendment plan."""
import hashlib
import json
from pathlib import Path

from pip._vendor.packaging.markers import default_environment
from pip._vendor.packaging.requirements import Requirement
from pip._vendor.packaging.specifiers import SpecifierSet
from pip._vendor.packaging.utils import canonicalize_name

OUT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    cache_path = OUT / 'pyvista_public_test_dependency_fix_cache_01.json'
    cache = json.loads(cache_path.read_text(encoding='utf-8'))
    target = default_environment()
    target.update(implementation_name='cpython', implementation_version='3.9.23',
                  os_name='posix', platform_machine='x86_64', platform_system='Linux',
                  platform_release='6.6.114.1-microsoft-standard-WSL2',
                  platform_python_implementation='CPython', python_full_version='3.9.23',
                  python_version='3.9', sys_platform='linux', extra='')
    inherited = {'numpy': '1.24.4', 'Pygments': '2.19.1', 'typing-extensions': '4.13.2'}
    available = {canonicalize_name(k): v for k, v in inherited.items()}
    available.update({canonicalize_name(row['package']): row['version'] for row in cache['wheels']})
    python_checks, checks, inactive = [], [], []
    for row in cache['wheels']:
        allowed = SpecifierSet(row['requires_python'] or '').contains('3.9.23', prereleases=True)
        python_checks.append({'package': row['package'], 'requires_python': row['requires_python'],
                              'target': '3.9.23', 'satisfied': allowed})
        for text in row['requires_dist']:
            requirement = Requirement(text)
            if requirement.marker and not requirement.marker.evaluate(target):
                inactive.append({'from': row['package'], 'requirement': text})
                continue
            version = available.get(canonicalize_name(requirement.name))
            checks.append({'from': row['package'], 'requirement': text, 'available_version': version,
                           'satisfied': version is not None and requirement.specifier.contains(version, prereleases=True)})
    if not all(row['satisfied'] for row in checks + python_checks):
        raise RuntimeError('Candidate closure does not satisfy the recorded Python3.9 metadata')
    baseline = OUT / 'pyvista_public_baseline_extended_01.json'
    data = json.loads(baseline.read_text(encoding='utf-8'))
    plan = {'kind': 'public_pyvista_environment_amendment_plan', 'date': '2026-11-11',
        'status': 'cached_metadata_checked_waiting_for_docker_migration_no_execution',
        'scope': 'dev calibration and configuration freeze only; formal test20 deferred by user',
        'instance_id': 'pyvista__pyvista-4315', 'base_commit': cache['source_base_commit'],
        'derive_from_image': cache['original_image'], 'replace_original_image': False,
        'candidate_lock': cache['candidate_lock'], 'wheel_cache': str(Path(cache['wheels'][0]['cache_path']).parent),
        'cache_audit': cache_path.name, 'cache_audit_sha256': sha(cache_path),
        'baseline_report': baseline.name, 'baseline_report_sha256': sha(baseline),
        'acceptance_command': data['test_command'], 'required_test_exit_code': 0,
        'declared_inherited_versions': inherited, 'target_environment': target,
        'python_compatibility_checks': python_checks, 'active_requirements': checks,
        'inactive_optional_requirements': inactive,
        'metadata_clarification': 'meshio5.3.4 wheel METADATA declares numpy without a bound (the first cache narrative says >=1.20.0); actual METADATA governs. Rich also requires typing-extensions>=4,<5 for Python<3.11, satisfied by inherited4.13.2.',
        'planned_steps': [
            'Wait for root to confirm Docker migration has finished; no Docker operation before that.',
            'Inspect original image ID and create a new owned preparation container from that exact ID, with no network or credentials.',
            'Bind the approved wheel cache read-only; install only the five pinned hash-required additions with no dependency/network resolution.',
            'Verify actual container image ID, exact base HEAD and clean checkout, and imports/versions of all added packages.',
            'Run the exact same three-file public pytest command with no source/test changes; save complete real exit/log and verify checkout remains clean.',
            'Only after exit0, commit a separately tagged derived image, start a fresh container from its actual ID and repeat identity/acceptance checks.',
            'Preserve old image, old screen tags, all original costs and environment-failure logs. Do not splice them into the new environment results.',
            'Build a new complete three-case screen image map and run all three under one new configuration/tag; do not reuse old prefixes across image/config identities.',
            'Continue dev calibration and freeze, then safely stop owned processes; do not send formal test20 requests this session.'],
        'not_claimed': ['No package installation or Docker mutation has occurred for this amendment.',
                        'Metadata checks are not a public-test pass or full rendering acceptance.',
                        'The inherited parent has unrelated legacy package metadata; this addition check is not a complete reverse-dependency proof.'],
        'model_calls': 0, 'docker_operations': False, 'packages_installed': False,
        'project_dotenv_read': False, 'source_or_tests_modified': False,
        'script_sha256': sha(Path(__file__))}
    path = OUT / 'pyvista_public_test_environment_amendment_plan_01.json'
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(plan, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({'active_requirements_checked': len(checks), 'python_version_checks': len(python_checks),
                      'all_satisfied': True, 'runtime_validation': 'not_performed',
                      'acceptance_command': plan['acceptance_command']}))


if __name__ == '__main__':
    main()
