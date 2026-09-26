from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "tvd_synthetic"


@pytest.fixture
def synthetic_paths() -> dict[str, str]:
    return {
        "arch": str(FIXTURES / "arch.csv"),
        "struct": str(FIXTURES / "struct.csv"),
        "cost": str(FIXTURES / "cost_db.csv"),
    }
