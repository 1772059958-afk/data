# Public-source fallback after the official instance image's large layers stalled.
# This is a distinct preparation environment, not the official pydicom image.
FROM prefix-env/pvlib-1707:base-40e9e978-20261106@sha256:6bddca9c6360684b088cba4a502969e84c3a2f125550983e48e38e2e252b660c
RUN mv /testbed /public_source_pvlib && mkdir /testbed \
    && cd /testbed && git init \
    && git remote add origin https://github.com/pydicom/pydicom.git \
    && git fetch --depth=1 origin b9fb05c177b685bf683f7f57b2d57374eb7d882d \
    && git checkout --detach FETCH_HEAD \
    && test "$(git rev-parse HEAD)" = b9fb05c177b685bf683f7f57b2d57374eb7d882d
RUN /opt/miniconda3/envs/testbed/bin/python -m pip install --no-deps --no-build-isolation -e /testbed
RUN cd /testbed && /opt/miniconda3/envs/testbed/bin/python -c "import pydicom,numpy,pytest; print(pydicom.__version__); print(numpy.__version__)"
