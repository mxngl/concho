from pathlib import Path

import pytest

from engines.common.config import load_config

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "tvd_synthetic"
ISLAND_CONFIG = REPO_ROOT / "engines" / "common" / "examples" / "island_2026.project_config.json"
RIVER_CONFIG = REPO_ROOT / "tests" / "fixtures" / "configs" / "river_test.project_config.json"


@pytest.fixture
def synthetic_paths() -> dict[str, str]:
    return {
        "arch": str(FIXTURES / "arch.csv"),
        "struct": str(FIXTURES / "struct.csv"),
        "cost": str(FIXTURES / "cost_db.csv"),
        "config": str(ISLAND_CONFIG),
    }


@pytest.fixture(scope="session")
def island_config():
    return load_config(ISLAND_CONFIG)


@pytest.fixture(scope="session")
def river_config():
    return load_config(RIVER_CONFIG)
