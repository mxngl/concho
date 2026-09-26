"""P3.10 item 1: which 'Cogen Data' columns the reference reader uses.

Builds a minimal workbook with invented numbers (not course data): the course sheet has
B = fuel, F = MJ, G = H2O, H = ODP, I = MJ/kg, J = kgCO2/MJ.
"""

from __future__ import annotations

import pytest

openpyxl = pytest.importorskip("openpyxl")

from engines.stv.reference import STVReferenceData  # noqa: E402


def test_cogen_columns(tmp_path):
    wb = openpyxl.Workbook()
    wb.active.title = "LCA Data"
    wb.create_sheet("Lists")
    ws = wb.create_sheet("Cogen Data")
    for col, value in zip("BCDEFGHIJ", ["Test Fuel", "kg", "-", 0.5, 11.0, 22.0, 3.3e-9,
                                         40.0, 0.07], strict=True):
        ws[f"{col}5"] = value
    path = tmp_path / "reference.xlsx"
    wb.save(path)

    fuel = STVReferenceData.from_workbook(path).fuels["Test Fuel"]
    assert fuel.water == 22.0  # G (H2O), not F (MJ)
    assert fuel.ozone == 3.3e-9  # H (ODP), not G
    assert fuel.mj_per_fu == 40.0
    assert fuel.carbon_per_mj == 0.07
