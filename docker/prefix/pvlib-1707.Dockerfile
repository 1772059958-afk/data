# A preparation image, created before generation. Never modify candidate envs.
FROM swebench/sweb.eval.x86_64.pvlib_1776_pvlib-python-1707@sha256:3c103594eb39c0564cfd71f12ecca0d75a9a4a821f33c6e43b036d2271e75de7
RUN /opt/miniconda3/envs/testbed/bin/python -m pip install --no-cache-dir numpy==1.26.4
RUN cd /testbed && git checkout --detach 40e9e978c170bdde4eeee1547729417665dbc34c \
    && git clean -fdq && git diff --quiet && git diff --cached --quiet
RUN cd /testbed && /opt/miniconda3/envs/testbed/bin/python -c "import numpy,pandas,scipy,pvlib,pytest; print(numpy.__version__)"
