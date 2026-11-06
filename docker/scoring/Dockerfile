# Reuse the already verified local instance base and its Python 3.11 runtime.
# The isolated controller venv is separate from /opt/miniconda3/envs/testbed.
FROM swebench/sweb.eval.x86_64.pvlib_1776_pvlib-python-1707@sha256:3c103594eb39c0564cfd71f12ecca0d75a9a4a821f33c6e43b036d2271e75de7
RUN /opt/miniconda3/bin/python -m venv /opt/scoring
COPY requirements.lock.txt /opt/scoring-requirements.txt
RUN /opt/scoring/bin/python -m pip install --no-cache-dir --only-binary=:all: --require-hashes -r /opt/scoring-requirements.txt
WORKDIR /workspace
ENV HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 TZ=Asia/Shanghai
ENTRYPOINT ["/opt/scoring/bin/python"]
