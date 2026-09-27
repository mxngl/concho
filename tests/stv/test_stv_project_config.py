"""P3.2: STV course team, lifetime and use phase from ``project_config``.

Uses invented reference data (see conftest.py) with an extra invented "River" team row, the
Island example config and the invented River config
(tests/fixtures/configs/river_test.project_config.json).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from conftest import TEAM

from engines.common.config import UsePhase, load_config
from engines.stv import STVEngine, STVInputs, cli
from engines.stv.custom_materials import (
    COLUMNS,
    CustomMaterialsError,
    load_custom_materials,
)
from engines.stv.engine import LIFETIME_YEARS
from engines.stv.models import ImpactVector
from engines.stv.project import STVProjectSettings, use_phase_payload
from engines.stv.reference import STVReferenceData, TeamFactors

REPO_ROOT = Path(__file__).resolve().parents[2]
ISLAND_CONFIG = REPO_ROOT / "engines" / "common" / "examples" / "island_2026.project_config.json"
RIVER_CONFIG = REPO_ROOT / "tests" / "fixtures" / "configs" / "river_test.project_config.json"
ITEMS = [{"assembly": "Floor", "material_type": "Test Slab (sf)", "amount": 100.0}]


@pytest.fixture
def reference_with_river(reference) -> STVReferenceData:
    reference.teams["River"] = TeamFactors(
        team="River",
        grid_electricity=ImpactVector(carbon=0.2, energy=11.0, water=2.5, ozone=2e-8),
        target_carbon_factor=0.3,
        target_water_factor=999.0,
        target_energy_factor=0.4,
    )
    return reference


def _calculate(reference, settings: STVProjectSettings):
    payload = {"team": settings.team, "construction_items": ITEMS,
               "use_phase": settings.use_phase}
    engine = STVEngine(reference, lifetime_years=settings.lifetime_years)
    return engine.calculate(STVInputs.from_dict(payload))


# ── settings from config ────────────────────────────────────────────────────

def test_island_settings():
    settings = STVProjectSettings.from_config(load_config(ISLAND_CONFIG))
    assert settings.team == "Island"
    assert settings.lifetime_years == LIFETIME_YEARS == 50
    assert settings.use_phase == {} and not settings.use_phase_modeled
    assert any("not_modeled" in w for w in settings.warnings)
    assert settings.custom_materials is None
    # P3.6: files.stv_mapping, resolved relative to the config file.
    settings = STVProjectSettings.from_config(load_config(ISLAND_CONFIG), ISLAND_CONFIG.parent)
    island_mapping = Path(__file__).resolve().parents[2] / "engines/stv/examples/island"
    assert settings.stv_mapping.resolve() == island_mapping / "stv_mapping.csv"


def test_river_settings():
    settings = STVProjectSettings.from_config(load_config(RIVER_CONFIG))
    assert settings.team == "River"
    assert settings.lifetime_years == 50
    assert settings.warnings == []
    assert settings.use_phase == {
        "electricity_from_grid_kwh": 100000,
        "onsite_renewable_kwh": 20000,
        "natural_gas_m3": 500,
        "water_use": {
            "toilet_gpf": 1.28, "urinal_gpf": None, "wc_sink_gpm": 0.5, "lab_sink_gpm": 0,
            "kitchen_sink_gpm": 1.5, "shower_gpm": 1.8, "landscaping_gal": 10000,
            "rainwater_collection_gal": 5000,
        },
    }


@pytest.mark.parametrize("urinal", [None, 0.0, 0.125])
def test_urinal_passed_as_is(urinal):
    """Decision D11: null stays None (toilet factor 1.0), 0 stays 0 (factor 0.75)."""
    data = json.loads(RIVER_CONFIG.read_text(encoding="utf-8"))["stv"]["use_phase"]
    data["water"]["urinal_gpf"] = urinal
    assert use_phase_payload(UsePhase.model_validate(data))["water_use"]["urinal_gpf"] == urinal


def test_cogeneration_is_mapped():
    data = json.loads(RIVER_CONFIG.read_text(encoding="utf-8"))["stv"]["use_phase"]
    data["cogeneration"] = {
        "fuel_type": "Test Gas", "electricity_kwh": 10, "heating_mj": 20, "cooling_kwh": 30,
        "splits": {"electricity": 0.5, "heating": 0.3, "cooling": 0.2}}
    up = UsePhase.model_validate(data)
    assert use_phase_payload(up)["cogeneration"] == {
        "fuel_type": "Test Gas", "electricity_kwh": 10, "heating_mj": 20, "cooling_kwh": 30,
        "electricity_split": 0.5, "heating_split": 0.3, "cooling_split": 0.2,
    }


def test_lifetime_other_than_50_warns_and_scales_use_phase(reference_with_river):
    config = load_config(RIVER_CONFIG)
    base = STVProjectSettings.from_config(config)
    config.stv.lifetime_years = 60
    settings = STVProjectSettings.from_config(config)
    assert any("course formula uses 50" in w for w in settings.warnings)

    r50 = _calculate(reference_with_river, base)
    r60 = _calculate(reference_with_river, settings)
    assert r60.lifetime_years == 60
    assert r60.breakdown.use_phase.carbon == pytest.approx(r50.breakdown.use_phase.carbon * 1.2)
    assert r60.breakdown.embodied.to_dict() == r50.breakdown.embodied.to_dict()
    assert r60.targets.to_dict() == r50.targets.to_dict()


def test_all_zero_use_phase_warns():
    config = load_config(RIVER_CONFIG)
    up = config.stv.use_phase
    up.grid_kwh = up.onsite_renewable_kwh = up.natural_gas_m3 = 0
    for name in type(up.water).model_fields:
        setattr(up.water, name, 0)
    assert any("all use-phase values are 0" in w
               for w in STVProjectSettings.from_config(config).warnings)


# ── second config changes exactly the expected outputs ──────────────────────

def test_river_config_changes_team_targets_and_use_phase(reference_with_river):
    island = _calculate(reference_with_river, STVProjectSettings(
        team=TEAM, lifetime_years=50, use_phase={}, use_phase_modeled=False))
    river = _calculate(reference_with_river,
                       STVProjectSettings.from_config(load_config(RIVER_CONFIG)))

    assert river.team == "River"
    assert river.targets.carbon == pytest.approx(6.38e6 * 0.3)
    assert river.targets.energy == pytest.approx(1.51e8 * 0.4)
    assert river.targets.water == 999.0
    # Embodied impacts do not depend on the project config.
    assert river.breakdown.embodied.to_dict() == island.breakdown.embodied.to_dict()
    assert [i.to_dict() for i in river.construction_items] == [
        i.to_dict() for i in island.construction_items]
    # Use phase: River grid factors x 100,000 kWh x 50 years (+ gas and water).
    assert island.breakdown.use_phase.carbon == 0.0
    assert river.breakdown.use_electricity.carbon == pytest.approx(0.2 * 100_000 * 50)
    assert river.breakdown.use_heating.energy == pytest.approx(37 * 500 * 50)
    assert river.breakdown.use_water.water > 0


# ── custom materials (format: tests/stv/test_stv_custom_materials.py) ────────

def _write_materials(path: Path, rows: list[dict]) -> Path:
    lines = [",".join(COLUMNS)]
    for row in rows:
        lines.append(",".join(str(row.get(c, "")) for c in COLUMNS))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _material(**overrides) -> dict:
    row = {c: 1.0 for c in COLUMNS}
    row.update({c: 3.0 for c in COLUMNS if c.startswith("embodied_")})
    row.update(assembly="Floor", material_type="Engineered Bamboo (cf)",
               source="Invented EPD 123", is_course_data="false", life_units=1)
    row.update(overrides)
    return row


def test_custom_materials_load(tmp_path):
    path = _write_materials(tmp_path / "custom.csv", [_material()])
    loaded = load_custom_materials(path)
    (record,) = loaded.records
    assert record.material_type == "Engineered Bamboo (cf)"
    assert record.embodied_total.carbon == 3.0 and record.materials.carbon == 1.0


def test_custom_materials_errors(tmp_path):
    path = _write_materials(tmp_path / "custom.csv", [_material(assembly="Spaceship")])
    with pytest.raises(CustomMaterialsError, match="unknown assembly 'Spaceship'"):
        load_custom_materials(path)


def test_custom_materials_from_config(tmp_path, reference_with_river):
    _write_materials(tmp_path / "custom.csv", [_material()])
    data = json.loads(RIVER_CONFIG.read_text(encoding="utf-8"))
    data.pop("$schema")
    data["files"] = {}
    data["stv"]["custom_materials_file"] = "custom.csv"
    config_path = tmp_path / "project_config.json"
    config_path.write_text(json.dumps(data), encoding="utf-8")

    settings = STVProjectSettings.from_config(load_config(config_path), tmp_path)
    assert len(settings.custom_materials.records) == 1
    assert settings.custom_materials.path == tmp_path / "custom.csv"


# ── CLI ─────────────────────────────────────────────────────────────────────

def _cli(monkeypatch, tmp_path, reference, *args: str) -> dict:
    template = tmp_path / "course.xlsx"
    template.write_bytes(b"")
    monkeypatch.setattr(STVReferenceData, "from_workbook",
                        staticmethod(lambda path=None: reference))
    monkeypatch.setenv("COURSE_STV_XLSX", str(template))
    inputs = tmp_path / "inputs.json"
    inputs.write_text(json.dumps({"team": TEAM, "construction_items": ITEMS}))
    out = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["concho-stv", "--input", str(inputs),
                                      "--output-dir", str(out), *args])
    cli.main()
    return json.loads((out / "stv_results.json").read_text())


def test_cli_config(monkeypatch, tmp_path, reference_with_river, capsys):
    results = _cli(monkeypatch, tmp_path, reference_with_river, "--config", str(RIVER_CONFIG))
    assert results["team"] == "River"
    assert results["lifetime_years"] == 50
    assert results["breakdown"]["use_electricity"]["carbon"] == pytest.approx(0.2 * 100_000 * 50)


def test_cli_team_overrides_config(monkeypatch, tmp_path, reference_with_river):
    results = _cli(monkeypatch, tmp_path, reference_with_river,
                   "--config", str(RIVER_CONFIG), "--team", TEAM)
    assert results["team"] == TEAM
    assert results["targets"]["water"] == 1234.5


def test_cli_no_use_phase(monkeypatch, tmp_path, reference_with_river):
    results = _cli(monkeypatch, tmp_path, reference_with_river,
                   "--config", str(RIVER_CONFIG), "--no-use-phase")
    assert results["team"] == "River"
    assert results["breakdown"]["use_phase"]["carbon"] == 0.0


def test_cli_not_modeled_warns(monkeypatch, tmp_path, reference_with_river, capsys):
    results = _cli(monkeypatch, tmp_path, reference_with_river,
                   "--config", str(ISLAND_CONFIG), "--team", TEAM)
    assert results["breakdown"]["use_phase"]["carbon"] == 0.0
    assert "not_modeled" in capsys.readouterr().err


def test_cli_invalid_config(monkeypatch, tmp_path, reference, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit):
        _cli(monkeypatch, tmp_path, reference, "--config", str(bad))
    assert "invalid project_config" in capsys.readouterr().err


# ── P3.8: use_phase_status in the results ───────────────────────────────────

def test_status_from_inputs(reference):
    engine = STVEngine(reference)
    empty = engine.calculate(STVInputs.from_dict({"team": TEAM, "construction_items": ITEMS}))
    assert empty.to_dict()["use_phase_status"] == {
        **empty.use_phase_status, "modeled": False, "source": "input", "all_zero": True,
        "not_modeled_reason": "no use-phase inputs given"}
    # A stated urinal flow rate is an input, even 0 (decision D11).
    urinal = engine.calculate(STVInputs.from_dict({
        "team": TEAM, "construction_items": [], "use_phase": {"water_use": {"urinal_gpf": 0}}}))
    assert urinal.use_phase_status["modeled"] is True
    grid = engine.calculate(STVInputs.from_dict({
        "team": TEAM, "construction_items": [],
        "use_phase": {"electricity_from_grid_kwh": 10.0}}))
    assert grid.use_phase_status["inputs"]["electricity_from_grid_kwh"] == 10.0
    assert grid.use_phase_status["all_zero"] is False


def test_cli_status_config(monkeypatch, tmp_path, reference_with_river):
    river = _cli(monkeypatch, tmp_path, reference_with_river, "--config", str(RIVER_CONFIG))
    status = river["use_phase_status"]
    assert (status["modeled"], status["source"], status["not_modeled_reason"],
            status["all_zero"]) == (True, "project_config", None, False)
    assert status["inputs"]["electricity_from_grid_kwh"] == 100_000


def test_cli_status_not_modeled(monkeypatch, tmp_path, reference_with_river):
    island = _cli(monkeypatch, tmp_path, reference_with_river,
                  "--config", str(ISLAND_CONFIG), "--team", TEAM)
    status = island["use_phase_status"]
    assert (status["modeled"], status["source"]) == (False, "project_config")
    assert status["not_modeled_reason"].startswith("Island 2026 reference result C")


def test_cli_status_all_zero_warns(monkeypatch, tmp_path, reference_with_river, capsys):
    data = json.loads(RIVER_CONFIG.read_text(encoding="utf-8"))
    data.pop("$schema")
    data["files"] = {}
    up = data["stv"]["use_phase"]
    up.update(grid_kwh=0, onsite_renewable_kwh=0, natural_gas_m3=0, cogeneration=None)
    up["water"] = {k: (None if k == "urinal_gpf" else 0) for k in up["water"]}
    config = tmp_path / "zero.json"
    config.write_text(json.dumps(data), encoding="utf-8")
    result = _cli(monkeypatch, tmp_path, reference_with_river, "--config", str(config))
    assert result["use_phase_status"]["modeled"] is True
    assert result["use_phase_status"]["all_zero"] is True
    assert "all use-phase values are 0" in capsys.readouterr().err


# ── P3.8: stv.construction_items (e.g. PV as an Energy item) ─────────────────

def _config_with_items(tmp_path, items) -> Path:
    data = json.loads(RIVER_CONFIG.read_text(encoding="utf-8"))
    data.pop("$schema")
    data["files"] = {}
    data["stv"]["construction_items"] = items
    path = tmp_path / "items.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_config_construction_items(monkeypatch, tmp_path, reference_with_river):
    reference_with_river.materials[("Energy", "Test PV (sf)")] = (
        reference_with_river.materials[("Floor", "Test Slab (sf)")])
    reference_with_river.valid_materials["Energy"] = {"Test PV (sf)"}
    config = _config_with_items(tmp_path, [{"assembly": "Energy", "material_type": "Test PV (sf)",
                                            "amount": 500, "note": "invented PV area"}])
    settings = STVProjectSettings.from_config(load_config(config), tmp_path)
    assert settings.construction_items == [{"assembly": "Energy", "material_type": "Test PV (sf)",
                                            "amount": 500.0, "origin": "project_config"}]
    result = _cli(monkeypatch, tmp_path, reference_with_river, "--config", str(config))
    pv = result["construction_items"][-1]
    assert (pv["assembly"], pv["material_type"], pv["amount"], pv["origin"]) == (
        "Energy", "Test PV (sf)", 500.0, "project_config")
    assert result["construction_items"][0]["origin"] == "input"
    assert pv["embodied_total"]["carbon"] == pytest.approx(500 * 2.75)


def test_config_construction_items_checked(monkeypatch, tmp_path, reference_with_river, capsys):
    config = _config_with_items(tmp_path, [{"assembly": "Energy", "material_type": "Nope (sf)",
                                            "amount": 1, "note": "x"}])
    with pytest.raises(SystemExit):
        _cli(monkeypatch, tmp_path, reference_with_river, "--config", str(config))
    assert "stv.construction_items[0] of --config: Unknown assembly 'Energy'" in (
        capsys.readouterr().err)


@pytest.mark.parametrize("item, message", [
    ({"assembly": "Energy", "material_type": "PV (sf)", "amount": 1}, "note"),
    ({"assembly": "Energy", "material_type": "PV (sf)", "amount": -1, "note": "x"}, "amount"),
    ({"assembly": "", "material_type": "PV (sf)", "amount": 1, "note": "x"}, "assembly"),
])
def test_config_construction_items_validation(tmp_path, item, message):
    from engines.common.config import ConfigError

    with pytest.raises(ConfigError, match=message):
        load_config(_config_with_items(tmp_path, [item]))
