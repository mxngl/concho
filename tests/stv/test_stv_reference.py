"""P3.10: workbook readers (Cogen Data columns, item 1; urinal blank vs. 0, item 3).

Builds minimal workbooks with invented numbers (not course data). The course Cogen Data sheet has
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


@pytest.mark.parametrize("cell, expected", [(None, None), (0, 0.0), (0.125, 0.125)])
def test_workbook_urinal_blank_vs_zero(tmp_path, cell, expected):
    """Decision D11: a blank urinal cell = no urinals (None), 0 = course behaviour (0.0)."""
    from engines.stv.workbook_inputs import load_stv_workbook_inputs

    wb = openpyxl.Workbook()
    wb.active.title = "Construction and Materials"
    ws = wb.create_sheet("Use Phase")
    ws["B32"], ws["D32"] = "Toilet Flow Rate:", 1.28
    ws["B33"], ws["D33"] = "Urinal Flow Rate:", cell
    path = tmp_path / "inputs.xlsx"
    wb.save(path)

    water = load_stv_workbook_inputs(path)["use_phase"]["water_use"]
    assert water["toilet_gpf"] == 1.28
    assert water["urinal_gpf"] == expected
