"""Synthetic STV reference data for unit tests.

All numbers here are invented. They are NOT course data (no values from the course
workbook); they only exist to check the engine formulas.
"""

from __future__ import annotations

import pytest

from engines.stv.models import ImpactVector
from engines.stv.reference import FuelRecord, MaterialRecord, STVReferenceData, TeamFactors

TEAM = "Testteam"


def _material(assembly: str, material_type: str, unit_multiplier: float) -> MaterialRecord:
    materials = ImpactVector(carbon=2.0, energy=20.0, water=200.0, ozone=0.002)
    transport = ImpactVector(carbon=0.5, energy=5.0, water=50.0, ozone=0.0005)
    construction = ImpactVector(carbon=0.25, energy=2.5, water=25.0, ozone=0.00025)
    return MaterialRecord(
        assembly=assembly,
        material_type=material_type,
        embodied_total=materials + transport + construction,
        materials=materials,
        transport=transport,
        construction=construction,
        unit_multiplier=unit_multiplier,
    )


@pytest.fixture
def reference() -> STVReferenceData:
    records = [
        _material("Floor", "Test Slab (sf)", 1.0),
        _material("Column", "Test Column (kg)", 3.0),
    ]
    materials = {(r.assembly, r.material_type): r for r in records}
    materials_by_name: dict[str, list[MaterialRecord]] = {}
    for r in records:
        materials_by_name.setdefault(r.material_type, []).append(r)
    valid_materials = {
        "Floor": {"Test Slab (sf)"},
        "Columns": {"Test Column (kg)"},
    }
    teams = {
        TEAM: TeamFactors(
            team=TEAM,
            grid_electricity=ImpactVector(carbon=0.4, energy=9.0, water=1.5, ozone=1e-8),
            target_carbon_factor=0.5,
            target_water_factor=1234.5,
            target_energy_factor=0.25,
        )
    }
    fuels = {
        "Test Gas": FuelRecord(
            fuel_type="Test Gas", water=2.0, ozone=1e-6, mj_per_fu=40.0, carbon_per_mj=0.05
        )
    }
    return STVReferenceData(materials, materials_by_name, valid_materials, teams, fuels)
