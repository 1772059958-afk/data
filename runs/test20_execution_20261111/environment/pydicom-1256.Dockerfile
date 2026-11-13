# Public-only baseline overlay; host-fetched real Git objects, no hidden data.
FROM prefix-env/pydicom-1139:base-b9fb05c1-pytest7-20261106@sha256:bd5edf8694cde12aaf99beb18b3935b15e076e81ac7e52aef46b1ca3d9071428
RUN rm -rf /testbed && mkdir /testbed
COPY testbed/.git /testbed/.git
RUN cd /testbed && git config core.autocrlf false && git config core.filemode true && git config core.symlinks true && git reset --hard HEAD && test "$(git rev-parse HEAD)" = 49a3da4a3d9c24d7e8427a25048a1c7d5c4f7724 && test -z "$(git status --porcelain)"
RUN /opt/miniconda3/envs/testbed/bin/python -m pip install --no-index --no-deps --no-build-isolation -e /testbed
RUN cd /testbed && /opt/miniconda3/envs/testbed/bin/python -c "import pydicom,numpy,pytest; print(pydicom.__version__,numpy.__version__,pytest.__version__)" && test -z "$(git status --porcelain)"
