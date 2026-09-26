"""Island targets from the real course workbook. Skipped unless COURSE_STV_XLSX is set.

The workbook is course data and is never committed (roadmap §0, hard rule 2).
"""

from __future__ import annotations

import os

import pytest

from engines.stv import STVEngine, STVInputs
from engines.stv.reference import STVReferenceData

pytestmark = pytest.mark.skipif(
    not os.environ.get("COURSE_STV_XLSX"),
    reason="COURSE_STV_XLSX not set (course workbook must be supplied locally)",
)


def test_island_targets():
    reference = STVReferenceData.from_workbook(os.environ["COURSE_STV_XLSX"])
    results = STVEngine(reference).calculate(
        STVInputs.from_dict({"team": "Island", "construction_items": []})
    )
    assert results.targets.carbon == pytest.approx(7_396_873.85, rel=1e-6)
    assert results.targets.energy == pytest.approx(155_969_076.59, rel=1e-6)
    assert results.targets.water == pytest.approx(271_387_397.26, rel=1e-6)
