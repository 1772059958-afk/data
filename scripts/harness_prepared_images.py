"""Run the unchanged official harness with explicit prepared-image startup.

Prepared images may inherit /bin/bash as ENTRYPOINT from environment creation.
The official harness supplies `tail -f /dev/null` as CMD. Clear ENTRYPOINT only
for the explicitly frozen image IDs, preserving the exact image/root filesystem.
"""
import argparse
import json
from pathlib import Path
import runpy
import sys


def adapted_create(original, allowed, events):
    def create(collection, *args, **kwargs):
        image = kwargs.get('image', args[0] if args else None)
        if image not in allowed:
            raise ValueError('harness requested an image outside the frozen prepared set')
        if kwargs.get('command') != 'tail -f /dev/null' or 'entrypoint' in kwargs:
            raise ValueError('unexpected official harness startup command')
        kwargs['entrypoint'] = ''
        events.append({'image': image, 'command': kwargs['command'], 'entrypoint': ''})
        return original(collection, *args, **kwargs)
    return create


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--images', nargs='+', required=True)
    parser.add_argument('--audit', type=Path, required=True)
    args, rest = parser.parse_known_args()
    if not rest or rest[0] != '--':
        parser.error('official harness arguments must follow --')
    import docker
    from docker.models.containers import ContainerCollection
    client = docker.from_env()
    images = {}
    for image in args.images:
        obj = client.images.get(image)
        if obj.id != image:
            raise ValueError('prepared image identity changed')
        images[image] = {'entrypoint': obj.attrs['Config'].get('Entrypoint'),
                         'rootfs': obj.attrs.get('RootFS')}
    events = []
    original = ContainerCollection.create
    ContainerCollection.create = adapted_create(original, set(images), events)
    try:
        sys.argv = ['swebench.harness.run_evaluation'] + rest[1:]
        runpy.run_module('swebench.harness.run_evaluation', run_name='__main__')
    finally:
        ContainerCollection.create = original
        with args.audit.open('x', encoding='utf-8') as stream:
            json.dump({'kind': 'prepared_image_entrypoint_only_adapter', 'images': images,
                       'container_creates': events, 'official_harness_modified': False,
                       'image_ids_and_rootfs_preserved': True}, stream, indent=2)


if __name__ == '__main__':
    main()
