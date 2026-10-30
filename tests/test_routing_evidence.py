"""Source evidence is confined to the checkout and excludes every test convention."""
from pathlib import Path

from swe_repair import fingerprint as fp
from swe_repair.budget import Budget, BudgetState
from swe_repair.patchutil import is_source_path, is_test_path, patch_scope_valid
from swe_repair.router import RouterConfig, route_for_arm
from swe_repair.state import ContextView, FailureRecord, Localization, RepairState, TaskManifest


def state_with_frame(path):
    state = RepairState(TaskManifest('synthetic__repo-1', 'synthetic/repo', 'base', 'test', 'test'))
    state.budget = BudgetState('test', Budget(100000, 12, 80, 1200))
    state.context = ContextView(read_files=frozenset({'pkg/x.py'}))
    state.localization = Localization.from_file_sets({'one': ['pkg/x.py'], 'two': ['pkg/x.py']})
    state.failures.add(FailureRecord.from_output('public test', 1, stage='test', repo_root='/testbed',
        stdout=f'Traceback (most recent call last):\n  File "{path}", line 1, in f\nAssertionError: synthetic'))
    return state


def config():
    return RouterConfig.from_file(Path(__file__).parents[1] / 'configs/proposal_v1.json').with_thresholds(.5, .5)


def test_external_dependency_keeps_auditable_path_without_triggering_interaction():
    path = '/opt/venv/lib/python/site-packages/dependency/helper.py'
    state = state_with_frame(path)
    assert state.failures.latest.repo_frames == ()
    assert path in state.failures.latest.message_head
    frames = fp.parse_frames(f'  File "{path}", line 1, in f', '/testbed')
    assert frames[0].raw_path == path and frames[0].path == path
    assert not frames[0].in_repository
    assert route_for_arm('D', state, config()).route == 'fixed'


def test_all_test_path_conventions_are_excluded_from_both_routing_and_patches():
    for path in ('tests/fixture.py', 'test/fixture.py', 'pkg/test_widget.py', 'pkg/widget_test.py'):
        assert is_test_path(path) and not is_source_path(path)
        diff = f'--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-old\n+new\n'
        assert not patch_scope_valid(diff)
        state = state_with_frame('/testbed/' + path)
        assert route_for_arm('D', state, config()).route == 'fixed'


def test_unseen_checkout_source_still_triggers_interaction():
    state = state_with_frame('/testbed/pkg/new.py')
    assert state.failures.latest.repo_frames == ('pkg/new.py',)
    assert route_for_arm('D', state, config()).rule == 'interactive_on_out_of_scope_stack_evidence'
    assert is_source_path('pkg/new.py')
    assert patch_scope_valid('--- a/pkg/new.py\n+++ b/pkg/new.py\n@@ -1 +1 @@\n-old\n+new\n')


def test_root_prefix_and_path_traversal_cannot_claim_checkout_membership():
    paths = ('/testbed-other/pkg/x.py', '/testbed/../outside.py', '../outside.py',
             '/testbed/pkg/../../outside.py', 'C:\\venv\\lib\\helper.py', '/repo/pkg/x.py')
    for path in paths:
        assert fp.repository_path(path, '/testbed') is None
        assert state_with_frame(path).failures.latest.repo_frames == ()
    assert fp.repository_path('./pkg/x.py', '/testbed') == 'pkg/x.py'
    assert fp.repository_path('/testbed/pkg/../x.py', '/testbed') == 'x.py'
    assert fp.repository_path('/repo/pkg/x.py') == 'pkg/x.py'


def test_same_external_basename_remains_distinct_in_failure_fingerprints():
    one = '  File "/opt/one/helper.py", line 1, in f\nAssertionError: synthetic'
    two = '  File "/opt/two/helper.py", line 1, in f\nAssertionError: synthetic'
    assert fp.fingerprint(one, repo_root='/testbed') != fp.fingerprint(two, repo_root='/testbed')


def test_metadata_and_escaping_paths_cannot_trigger_source_rule_even_in_replayed_states():
    from dataclasses import replace
    for path in ('.git/helper.py', '../helper.py', '/opt/helper.py', 'pkg/widget_test.py'):
        state = state_with_frame('/testbed/pkg/x.py')
        state.failures.records[-1] = replace(state.failures.latest, repo_frames=(path,))
        assert route_for_arm('D', state, config()).route == 'fixed'
