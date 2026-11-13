"""Reuse the byte-preserved health probe with new post-migration identities."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('preserved_controller_health_probe', HERE / 'live_controller_probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
probe.OUT = HERE / 'readiness_after_migration.json'
probe.NAME = 'swe_scoring_preflight_after_migration_20261111_01'
probe.main()
