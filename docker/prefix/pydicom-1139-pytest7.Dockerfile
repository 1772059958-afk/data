# Public-only compatibility preparation; preserves the original prepared image.
# pytest 7.4 retains legacy setup/teardown support, removed by pytest 8.0.
FROM prefix-env/pydicom-1139:base-b9fb05c1-20261106@sha256:ccf2918b7408c41e80c71bad3f9ee49138a971543dde0c59b0a33c5ce8396daa
RUN /opt/miniconda3/envs/testbed/bin/python -m pip install --no-deps pytest==7.4.4
# Public Zenodo download is validated before staging this build input. Validate
# it again against the SHA256 already declared in this exact public commit.
# Use the normal external data cache, leaving checkout files byte-for-byte intact.
COPY fixtures/MR-SIEMENS-DICOM-WithOverlays.dcm /tmp/public-pydicom-overlay.dcm
RUN /opt/miniconda3/envs/testbed/bin/python -c "from pathlib import Path; import shutil; from pydicom.data.download import get_cached_filehash,get_data_dir,data_path_with_download,calculate_file_hash; name='MR-SIEMENS-DICOM-WithOverlays.dcm'; expected='094faf56c63bff84c30567e29de0c67d7c5a8ae05cf880ac12175491b6b645d2'; source=Path('/tmp/public-pydicom-overlay.dcm'); assert get_cached_filehash(name)==expected; assert calculate_file_hash(source)==expected; path=get_data_dir()/name; shutil.copyfile(source,path); assert data_path_with_download(name)==path.resolve(); assert calculate_file_hash(path)==expected; source.unlink(); print(str(path)); print(expected)"
RUN cd /testbed && test "$(git rev-parse HEAD)" = b9fb05c177b685bf683f7f57b2d57374eb7d882d && test -z "$(git status --porcelain)" && /opt/miniconda3/envs/testbed/bin/python -m pytest --version
