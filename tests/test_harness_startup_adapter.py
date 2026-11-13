import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('startup_adapter', Path(__file__).parents[1] / 'scripts/harness_prepared_images.py')
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


def test_startup_clears_only_entrypoint_preserving_image_and_all_other_harness_options():
    received, events = [], []
    def original(collection, *args, **kwargs):
        received.append((collection, args, kwargs))
        return 'owned-container'
    create = adapter.adapted_create(original, {'sha256:frozen'}, events)
    assert create('client', image='sha256:frozen', command='tail -f /dev/null',
                  user='root', detach=True, cap_add=['SYS_ADMIN']) == 'owned-container'
    assert received == [('client', (), {'image': 'sha256:frozen', 'command': 'tail -f /dev/null',
                                       'user': 'root', 'detach': True, 'cap_add': ['SYS_ADMIN'], 'entrypoint': ''})]
    assert events == [{'image': 'sha256:frozen', 'command': 'tail -f /dev/null', 'entrypoint': ''}]


def test_startup_rejects_other_images_or_changed_harness_command_without_creating():
    def reject(*args, **kwargs):
        raise AssertionError('unbound container created')
    create = adapter.adapted_create(reject, {'sha256:frozen'}, [])
    for kw in ({'image': 'mutable:latest', 'command': 'tail -f /dev/null'},
               {'image': 'sha256:frozen', 'command': 'changed'},
               {'image': 'sha256:frozen', 'command': 'tail -f /dev/null', 'entrypoint': '/bin/sh'}):
        try:
            create(None, **kw)
        except ValueError:
            pass
        else:
            raise AssertionError('unreviewed startup accepted')
