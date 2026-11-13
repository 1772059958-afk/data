import importlib.metadata
import json
import platform
import docker
import pyarrow.parquet as pq
from swebench.harness.utils import make_test_spec

schema = pq.read_schema('/input/dev.parquet')
required = {'instance_id', 'image', 'repo', 'version', 'eval_script',
            'eval_type', 'log_parser', 'FAIL_TO_PASS', 'PASS_TO_PASS'}
assert len(schema) == 17 and required <= set(schema.names)
client = docker.from_env()
assert client.ping()
data = {'python': platform.python_version(),
        'swebench': importlib.metadata.version('swebench'),
        'pyarrow': importlib.metadata.version('pyarrow'),
        'docker_sdk': importlib.metadata.version('docker'),
        'docker_server': client.version()['Version'],
        'protected_schema_columns': len(schema), 'required_schema_fields_present': True,
        'test_spec_import': make_test_spec.__module__,
        'docker_socket_ping': True, 'network': 'none', 'model_calls': 0,
        'evaluator_rows_read': 0}
assert data['swebench'] == '5.0.2'
print(json.dumps(data))
