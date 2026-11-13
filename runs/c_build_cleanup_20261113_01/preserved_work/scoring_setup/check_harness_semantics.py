"""Synthetic, public grading semantics only: no dataset, patch or real test log."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from swebench.harness.constants import START_TEST_OUTPUT, END_TEST_OUTPUT, TEST_EXIT_CODE, EvalType
from swebench.harness.grading import get_logs_eval, get_eval_report
from swebench.harness.infra_failure import classify_text

text = (f'{START_TEST_OUTPUT}\n'
        'PASSED synthetic_public.py::test_healthy\n'
        'ERROR synthetic_public.py::test_initialization - AttributeError: synthetic missing setup\n'
        f'{END_TEST_OUTPUT}\n{TEST_EXIT_CODE}: 1\n')
spec = SimpleNamespace(instance_id='synthetic-only', log_parser='parse_log_pytest_options',
                       eval_type=EvalType.PASS_AND_FAIL.value,
                       FAIL_TO_PASS=['synthetic_public.py::test_initialization'],
                       PASS_TO_PASS=['synthetic_public.py::test_healthy'])
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / 'synthetic.log'
    path.write_text(text)
    statuses, found = get_logs_eval(spec, str(path))
    report = get_eval_report(spec, {'instance_id': spec.instance_id, 'model_patch': 'synthetic-only'},
                             str(path), include_tests_status=False)[spec.instance_id]
    result = {'synthetic_only': True, 'hidden_dataset_rows_read': 0, 'model_calls': 0,
              'exit_code': 1, 'parseable_results': found, 'parsed_statuses': sorted(set(statuses.values())),
              'official_resolved': report['resolved'], 'official_instance_infra_flag': report['infra_failure'],
              'official_posthoc_classification': classify_text(text),
              'missing_module_control': classify_text('ModuleNotFoundError: synthetic'),
              'network_failure_control': classify_text('Temporary failure in name resolution')}
    assert found and not result['official_resolved'] and result['official_posthoc_classification'] is None
    print(json.dumps(result))
