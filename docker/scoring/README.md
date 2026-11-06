# Linux official-scoring controller

This image hosts the official SWE-bench 5.0.2 package. It does not contain the
project, a model client credential, or generated patches. Its base layers reuse
the already downloaded, digest-pinned pvlib instance image; the harness runs in
an isolated Python 3.11 virtual environment, not the instance's test environment.
The controller is for
independent evaluation after generation has frozen its matrix and predictions.

```powershell
docker --context desktop-linux build -t swe-repair/scoring-controller:20261106 docker/scoring
.venv/Scripts/python.exe scripts/score_run.py runs/<tag> --controller-image swe-repair/scoring-controller:20261106
```

If Docker's network downloads are slow, prepare Linux wheels with host `uv`
and use the offline image recipe. `--python-platform` and `--python-version`
are required: copying Windows binary packages into Linux is invalid.

```powershell
uv pip install --target work/scoring_setup/linux_site --python-version 3.11 --python-platform x86_64-manylinux_2_28 --only-binary :all: --no-config --cache-dir work/scoring_setup/uv_cache --require-hashes --no-deps -r docker/scoring/requirements.lock.txt
docker --context desktop-linux build --pull=false --network=none --build-context linux-dependencies=work/scoring_setup/linux_site -f docker/scoring/Dockerfile.offline -t swe-repair/scoring-controller:20261106 docker/scoring
```

`requirements.lock.txt` was resolved against official PyPI for Linux/Python
3.11, with exact versions and SHA256 hashes. A public package mirror can be
selected with `--default-index https://pypi.tuna.tsinghua.edu.cn/simple`; keep
`--require-hashes` so mirror bytes must still match the official lock file.

Before execution, extend the Python controller with the Linux Docker CLI:
the official harness uses it to stop/remove completed instance containers.

```powershell
.venv/Scripts/python.exe docker/scoring/prepare_cli.py --execute --audit-out runs/<tag>/environment/scoring_cli.json
docker --context desktop-linux image inspect swe-repair/scoring-controller:20261106 --format '{{.Id}}'
docker --context desktop-linux build --pull=false --network=none --build-context docker-cli=work/scoring_setup/docker_cli/bin -f docker/scoring/Dockerfile.cleanup -t swe-repair/scoring-controller:20261106-cli docker/scoring
.venv/Scripts/python.exe scripts/score_run.py runs/<tag> --controller-image swe-repair/scoring-controller:20261106-cli
```

The inspected parent ID must equal the expected ID recorded in
`Dockerfile.cleanup`. The new controller is also resolved to its actual image ID
before evaluation. The fixed CLI package and binary SHA256 hashes came from
Docker's GPG-verified official Ubuntu jammy repository metadata. The helper only
extracts `usr/bin/docker`; it installs no daemon and keeps raw binaries in ignored
`work/`. Its default without `--execute` is a download-free plan.

The scoring command only prints a plan. Add `--execute` only for an authorized
evaluation. The wrapper pins the controller's actual local image ID and mounts
only source scripts, evaluator data, and the selected run, not `.env` or the
whole workspace. Model credentials are never passed into the container. A
Docker socket is mounted because the official harness creates sibling instance
containers; use this controller only for the trusted official harness.

Inputs remain byte-bound to the run. A separate evaluation dataset is created
inside `scoring/` after prediction freeze and records any prepared-image
overrides, rather than editing protected `data/harness/*.parquet`. Its hash and
the protected source parquet hash enter the scoring provenance sidecar. Model
generation never receives this independent evaluator dataset.

Per-instance harness logs are persisted in the selected run's `controller/logs`.
Harness console output is captured in `controller/console.log`; the wrapper
returns only report paths and execution status, so hidden-test diagnostics do
not enter the calling generation context.
The official report, input manifest and provenance sidecar remain under that
run's `scoring/<arm>/`. Existing scoring/controller output directories are
refused rather than silently reused.
