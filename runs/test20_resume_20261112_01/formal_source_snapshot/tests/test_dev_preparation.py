"""DEV preparation uses IDs only and cannot start a model/container run."""
import importlib.util
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('dev_preparation', ROOT / 'scripts/prepare_dev.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_dev_selection_is_stable_and_spreads_repositories_without_outcomes():
    ids = (ROOT / 'data/frozen/instances_dev.txt').read_text(encoding='utf-8').splitlines()
    selected = module.select_dev(ids, 3, 20261030)
    assert selected == module.select_dev(list(reversed(ids)), 3, 20261030)
    assert len(selected) == len({i.rsplit('-', 1)[0] for i in selected}) == 3
    assert set(selected) <= set(ids)
    for invalid in (0, 24):
        try: module.select_dev(ids, invalid, 1)
        except ValueError: pass
        else: raise AssertionError('invalid dev size accepted')


def test_preparation_retains_full_population_and_never_executes():
    # Bind a private temporary repository output root to avoid leaving a fake
    # integration plan in runs/. Real loaders still read the original source.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / 'data/frozen').mkdir(parents=True)
        (root / 'data/frozen/instances_dev.txt').write_bytes((ROOT / 'data/frozen/instances_dev.txt').read_bytes())
        out = root / 'runs/prepare'
        with patch.object(module, 'ROOT', root):
            record = module.prepare(out, size=3)
            try: module.prepare(out, size=3)
            except ValueError: pass
            else: raise AssertionError('preparation overwrote an existing tag')
        assert record['execute'] is record['live_authorized'] is False
        ledger = json.loads((out / 'full_dev_coverage.json').read_text(encoding='utf-8'))
        assert len(ledger['instances']) == ledger['designated_total'] == 23
        assert sum(i['selected_for_integration'] for i in ledger['instances']) == 3
        first = json.loads((out / 'first_instance.json').read_text(encoding='utf-8'))['instance_ids']
        rest = json.loads((out / 'remaining_instances.json').read_text(encoding='utf-8'))['instance_ids']
        assert not set(first) & set(rest) and sorted(first + rest) == record['selected_instances']
        for name in ('first_instance', 'remaining', 'diagnostic'):
            plan = json.loads((out / f'{name}_plan.json').read_text(encoding='utf-8'))
            assert plan['execute'] is plan['live_authorized'] is False
            assert plan['effective_config']['status'] == 'draft-pending-calibration'
            assert plan['effective_config']['router']['switch_probability'] is None
            assert plan['formal_readiness_errors']
