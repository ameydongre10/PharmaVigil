"""
Pytest configuration and fixtures for isolated test execution.
Ensures tests use isolated temporary SQLite databases and environment state.
"""

import os
import pytest
import tempfile
import shutil
from pathlib import Path


@pytest.fixture(scope="session", autouse=True)
def set_test_environment():
    """Enable demo user seeding for all tests."""
    original_value = os.environ.get("PHARMAVIGIL_SEED_DEMO_USERS")
    os.environ["PHARMAVIGIL_SEED_DEMO_USERS"] = "true"
    yield
    if original_value is None:
        os.environ.pop("PHARMAVIGIL_SEED_DEMO_USERS", None)
    else:
        os.environ["PHARMAVIGIL_SEED_DEMO_USERS"] = original_value


@pytest.fixture(scope="function")
def temp_db_path(tmp_path):
    """Provide an isolated temporary database path for each test."""
    db_path = tmp_path / "test_pharmavigil.db"
    return db_path


@pytest.fixture(scope="function")
def temp_outputs_dir(tmp_path):
    """Provide an isolated temporary outputs directory for each test."""
    outputs = tmp_path / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    return outputs
