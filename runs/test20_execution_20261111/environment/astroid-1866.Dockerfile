# Public-only source baseline with hash-verified Linux CP39 dependencies.
FROM prefix-env/pydicom-1139:base-b9fb05c1-pytest7-20261106@sha256:bd5edf8694cde12aaf99beb18b3935b15e076e81ac7e52aef46b1ca3d9071428
RUN rm -rf /testbed && mkdir /testbed
COPY testbed/.git /testbed/.git
RUN cd /testbed && git config core.autocrlf false && git config core.filemode true && git config core.symlinks true && git reset --hard HEAD && git config remote.origin.url https://github.com/pylint-dev/astroid.git && test "$(git rev-parse HEAD)" = 6cf238d089cf4b6753c94cfc089b4a47487711e5
COPY wheels /tmp/public-wheels
RUN /opt/miniconda3/envs/testbed/bin/python -m pip install --no-index --no-deps /tmp/public-wheels/*.whl && /opt/miniconda3/envs/testbed/bin/python -m pip install --no-index --no-deps --no-build-isolation -e /testbed
RUN cd /testbed && /opt/miniconda3/envs/testbed/bin/python -c "import astroid,lazy_object_proxy,wrapt,pytest; print(astroid.__version__,lazy_object_proxy.__version__,wrapt.__version__,pytest.__version__)" && test -z "$(git status --porcelain)"
