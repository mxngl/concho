"""Unit tests for the STV engine formulas, using invented reference data (see conftest.py)."""

from __future__ import annotations

import pytest
from conftest import TEAM

from engines.stv import STVEngine, STVInputs
from engines.stv.engine import LIFETIME_YEARS

GAL_TO_WATER_KG = (1 + 0.00113 * 1000) * 3.79


def _run(reference, *, items=(), use_phase=None):
    payload = {"team": TEAM, "construction_items": list(items), "use_phase": use_phase or {}}
    return STVEngine(reference).calculate(STVInputs.from_dict(payload))


def test_lifetime_is_50_years():
    assert LIFETIME_YEARS == 50


def test_targets(reference):
    targets = _run(reference).targets
    assert targets.carbon == pytest.approx(6.38e6 * 0.5)
    assert targets.energy == pytest.approx(1.51e8 * 0.25)
    assert targets.water == pytest.approx(1234.5)
    assert targets.ozone == 0.0


def test_embodied_is_amount_times_factor_times_unit_multiplier(reference):
    results = _run(
        reference,
        items=[
            {"assembly": "Floor", "material_type": "Test Slab (sf)", "amount": 100.0},
            # "Columns" (Lists sheet name) resolves to the "Column" LCA record, multiplier 3.
            {"assembly": "Columns", "material_type": "Test Column (kg)", "amount": 10.0},
        ],
    )
    slab, column = results.construction_items
    assert slab.embodied_total.carbon == pytest.approx(100.0 * 2.75 * 1.0)
    assert column.unit_multiplier == 3.0
    assert column.embodied_total.carbon == pytest.approx(10.0 * 2.75 * 3.0)
    assert column.materials.energy == pytest.approx(10.0 * 20.0 * 3.0)
    assert column.transport.water == pytest.approx(10.0 * 50.0 * 3.0)
    assert column.construction.ozone == pytest.approx(10.0 * 0.00025 * 3.0)

    scaled_amount = 100.0 * 1.0 + 10.0 * 3.0
    breakdown = results.breakdown
    assert breakdown.embodied_materials.carbon == pytest.approx(scaled_amount * 2.0)
    assert breakdown.embodied_transport.carbon == pytest.approx(scaled_amount * 0.5)
    assert breakdown.embodied_construction.carbon == pytest.approx(scaled_amount * 0.25)
    assert breakdown.embodied.carbon == pytest.approx(scaled_amount * 2.75)
    assert breakdown.use_phase.carbon == 0.0


def test_invalid_material_is_rejected(reference):
    with pytest.raises(ValueError, match="not valid for assembly"):
        _run(reference, items=[{"assembly": "Floor", "material_type": "Nope", "amount": 1}])


def test_grid_electricity_times_50_years(reference):
    results = _run(reference, use_phase={"electricity_from_grid_kwh": 1000.0})
    electricity = results.breakdown.use_electricity
    assert electricity.carbon == pytest.approx(1000.0 * 0.4 * 50)
    assert electricity.energy == pytest.approx(1000.0 * 9.0 * 50)
    assert electricity.water == pytest.approx(1000.0 * 1.5 * 50)
    assert results.breakdown.life_cycle.carbon == pytest.approx(1000.0 * 0.4 * 50)


def test_natural_gas(reference):
    m3 = 500.0
    heating = _run(reference, use_phase={"natural_gas_m3": m3}).breakdown.use_heating
    annual_carbon = m3 * 37e6 / 1.055e9 * (117 / 2.2) + m3 * 0.38
    assert heating.carbon == pytest.approx(annual_carbon * 50)
    assert heating.energy == pytest.approx(37 * m3 * 50)
    assert heating.water == pytest.approx(0.00618 * 1000 * m3 * 50)
    assert heating.ozone == pytest.approx(m3 * 3.07e-7 * 50)


def test_water_fixtures(reference):
    water_use = {
        "toilet_gpf": 1.6,
        "wc_sink_gpm": 0.5,
        "lab_sink_gpm": 1.0,
        "kitchen_sink_gpm": 2.0,
        "shower_gpm": 1.5,
        "landscaping_gal": 1000.0,
    }
    water = _run(reference, use_phase={"water_use": water_use}).breakdown.use_water
    gallons = (
        900 * 3 * 250 * 1.6  # toilet, no urinal -> occupancy factor 1.0
        + 900 * 0.5 * 3 * 250 * 0.5
        + 900 * 0.2 * 1 * 250 * 1.0
        + 900 * 0.25 * 1 * 250 * 2.0
        + 900 * 0.01 * 10 * 250 * 1.5
        + 1000.0
    )
    assert water.water == pytest.approx(gallons * GAL_TO_WATER_KG * 50)
    assert water.carbon == pytest.approx(gallons * 0.000317 * 3.79 * 50)
    assert water.energy == pytest.approx(gallons * 8.44e-5 * 41.868 * 3.79 * 50)
    assert water.ozone == pytest.approx(gallons * 1.62e-11 * 3.79 * 50)


def test_toilet_factor_applies_only_with_urinal(reference):
    water = _run(
        reference, use_phase={"water_use": {"toilet_gpf": 1.6, "urinal_gpf": 0.5}}
    ).breakdown.use_water
    gallons = 900 * 3 * 250 * 0.75 * 1.6 + 900 * 3 * 250 * 0.25 * 0.5
    assert water.water == pytest.approx(gallons * GAL_TO_WATER_KG * 50)


def test_rainwater_reduces_water(reference):
    water_use = {"landscaping_gal": 10_000.0, "rainwater_collection_gal": 4_000.0}
    water = _run(reference, use_phase={"water_use": water_use}).breakdown.use_water
    assert water.water == pytest.approx(6_000.0 * GAL_TO_WATER_KG * 50)
    # Rainwater only offsets water; carbon and energy stay those of the full demand.
    assert water.carbon == pytest.approx(10_000.0 * 0.000317 * 3.79 * 50)


def test_rainwater_is_capped_at_landscaping_water(reference):
    water_use = {"landscaping_gal": 1_000.0, "rainwater_collection_gal": 50_000.0}
    water = _run(reference, use_phase={"water_use": water_use}).breakdown.use_water
    assert water.water == pytest.approx(0.0)
    assert water.carbon == pytest.approx(1_000.0 * 0.000317 * 3.79 * 50)


def test_rainwater_cap_is_toilet_urinal_landscaping(reference):
    """P3.10 item 2, course formula: the credit is capped at toilet + urinal + landscaping
    water; sink and shower water stays."""
    water_use = {
        "toilet_gpf": 1.0,
        "urinal_gpf": 0.5,
        "wc_sink_gpm": 2.0,
        "shower_gpm": 1.5,
        "landscaping_gal": 1_000.0,
        "rainwater_collection_gal": 10_000_000.0,
    }
    water = _run(reference, use_phase={"water_use": water_use}).breakdown.use_water
    sinks_showers = 900 * 0.5 * 3 * 250 * 2.0 + 900 * 0.01 * 10 * 250 * 1.5
    assert water.water == pytest.approx(sinks_showers * GAL_TO_WATER_KG * 50)
    capped = 900 * 3 * 250 * 0.75 * 1.0 + 900 * 3 * 250 * 0.25 * 0.5 + 1_000.0
    total = capped + sinks_showers
    assert water.carbon == pytest.approx(total * 0.000317 * 3.79 * 50)


def test_cogeneration_uses_fuel_record(reference):
    cogen = {
        "fuel_type": "Test Gas",
        "electricity_kwh": 1000.0,
        "electricity_split": 1.0,
    }
    electricity = _run(
        reference, use_phase={"cogeneration": cogen}
    ).breakdown.use_electricity
    base_mj = 1000.0 * 3.6  # total split 1 -> demand / 1 * (1 / 1) * 3.6
    assert electricity.energy == pytest.approx(base_mj * 50)
    assert electricity.carbon == pytest.approx(base_mj * 0.05 * 50)
    assert electricity.water == pytest.approx(base_mj * (2.0 / 40.0) * 50)
