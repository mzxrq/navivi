"""Shared pytest fixtures for the src-python test suite."""

import sys
from pathlib import Path

# Ensure `services.*` imports resolve regardless of the invocation cwd.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


import pytest


@pytest.fixture(autouse=True)
def _isolated_job_config_singleton():
    """JobConfigManager is a process-wide singleton (see services/config/job_config.py).
    Reset it before and after every test so state from one test can't leak
    into the next via the shared _instance."""
    from services.config.job_config import JobConfigManager

    JobConfigManager._instance = None
    yield
    JobConfigManager._instance = None
