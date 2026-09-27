"""P3.7: custom materials (custom_materials.csv) and the custom material / proxy flags.

All materials and values here are invented test data: no course data, no EPD data. The
reference data is the invented catalog of conftest.py ("Test Slab (sf)", "Test Column (kg)").
"""

from __future__ import annotations

import json
import sys

import pytest
from conftest import TEAM

from engines import cli as concho_cli
from engines.stv import STVEngine, STVInputs, cli
from engines.stv.custom_materials import (
    COLUMNS,
    CustomMaterialsError,
    json_schema,
    load_custom_materials,
    validate_custom_materials_text,
)
from engines.stv.mapping import Element, map_elements, stv_mapping_from_dicts
from engines.stv.models import STVResults
from engines.stv.reference import STVReferenceData

BAMBOO = "Invented Bamboo Beam (kg)"
# Per kg, invented: materials, transport, construction (GWP, MJ, kg water, kg CFC-11e).
PARTS = {
    "materials": (-0.4, 12.0, 30.0, 1e-8),  # negative GWP allowed (biogenic carbon)
    "transport": (0.1, 1.5, 0.5, 2e-9),
    "construction": (0.05, 0.5, 2.0, 1e-9),
}
INDICATORS = ("gwp_kgco2e", "energy_mj", "water_kg", "odp_kgcfc11e")


def material_row(**overrides) -> dict[str, str]:
    row = {"assembly": "Beams", "material_type": BAMBOO, "life_units": "2",
           "source": "Invented EPD X-1, p. 7, declared unit 1 m3, / 600 kg/m3",
           "is_course_data": "false"}
    for phase, values in PARTS.items():
        row.update({f"{phase}_{i}": repr(v) for i, v in zip(INDICATORS, values, strict=True)})
    row.update({f"embodied_{i}": repr(sum(v[n] for v in PARTS.values()))
                for n, i in enumerate(INDICATORS)})
    row.update({k: str(v) for k, v in overrides.items()})
    return row


def csv_text(*rows: dict[str, str], columns=COLUMNS) -> str:
    lines = ["# invented test materials", ",".join(columns)]
    lines += [",".join(f'"{r.get(c, "")}"' for c in columns) for r in rows]
    return "\n".join(lines) + "\n"


def errors(*rows, catalog=None, columns=COLUMNS) -> str:
    result = validate_custom_materials_text(csv_text(*rows, columns=columns), catalog=catalog)
    assert not result.ok, "expected errors"
    return "\n".join(result.errors)


@pytest.fixture
def custom_path(tmp_path):
    path = tmp_path / "custom_materials.csv"
    path.write_text(csv_text(material_row()), encoding="utf-8")
    return path


@pytest.fixture
def with_bamboo(reference, custom_path) -> STVReferenceData:
    reference.add_custom_materials(load_custom_materials(custom_path, catalog=reference))
    return reference


# --- format and validation ------------------------------------------------------------


def test_valid_file(reference, custom_path):
    result = load_custom_materials(custom_path, catalog=reference)
    assert result.warnings == []
    (m,) = result.materials
    assert m.record.assembly == "Beam"  # 'LCA Data' writes Columns / Beams as Column / Beam
    assert m.record.unit_multiplier == 2.0
    assert m.record.materials.carbon == -0.4
    assert m.record.embodied_total.energy == pytest.approx(14.0)
    assert m.source.startswith("Invented EPD X-1")


def test_warnings_without_catalog_and_without_rows():
    result = validate_custom_materials_text(csv_text())
    assert result.ok
    assert result.warnings == [
        "no materials in the file",
        "no course workbook given: custom material names were not checked against the "
        "course catalog",
    ]


@pytest.mark.parametrize("overrides, message", [
    ({"assembly": "Spaceship"}, "unknown assembly 'Spaceship'"),
    ({"material_type": ""}, "material_type is empty"),
    ({"material_type": "Bamboo Beam"}, "has no unit"),
    ({"source": ""}, "source is empty"),
    ({"is_course_data": "true"}, "is_course_data must be false"),
    ({"is_course_data": ""}, "is_course_data must be false"),
    ({"materials_energy_mj": "12 MJ"}, "materials_energy_mj is not a plain number"),
    ({"transport_water_kg": "nan"}, "transport_water_kg is not a plain number"),
    ({"construction_odp_kgcfc11e": "-1e-9", "embodied_odp_kgcfc11e": "1.1e-8"},
     "construction_odp_kgcfc11e must be >= 0"),
    ({"life_units": "0"}, "life_units must be > 0"),
    ({"embodied_water_kg": "40"}, "embodied_water_kg (40) is not materials + transport"),
])
def test_row_errors(overrides, message):
    assert message in errors(material_row(**overrides))


def test_course_catalog_name_is_rejected(reference):
    text = errors(material_row(material_type="test  slab (SF)", assembly="Floor"),
                  catalog=reference)
    assert "is a course catalog name (Floor / Test Slab (sf))" in text


def test_duplicate_name_and_line_numbers():
    text = errors(material_row(), material_row(material_type=BAMBOO.upper()))
    assert f"line 4: duplicate material_type '{BAMBOO.upper()}' (first on line 3)" in text


def test_header_errors():
    columns = [c for c in COLUMNS if c != "source"] + ["colour", "colour"]
    text = errors(material_row(), columns=columns)
    assert "unknown column(s): colour, colour" in text
    assert "duplicated column(s): colour" in text
    assert "missing column(s): source" in text
    empty = validate_custom_materials_text("# only a comment\n")
    assert empty.errors == ["empty file (no header row)"]


def test_more_cells_than_columns():
    text = csv_text(material_row()).rstrip("\n") + ',"extra"\n'
    assert "cells but" in "\n".join(validate_custom_materials_text(text).errors)


def test_load_raises(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text(csv_text(material_row(source="")), encoding="utf-8")
    with pytest.raises(CustomMaterialsError, match="source is empty"):
        load_custom_materials(path)
    with pytest.raises(CustomMaterialsError, match="cannot read file"):
        load_custom_materials(tmp_path / "missing.csv")


def test_json_schema_matches_columns():
    jsonschema = pytest.importorskip("jsonschema")
    schema = json_schema()
    assert list(schema["properties"]) == COLUMNS
    assert schema["required"] == COLUMNS
    row = {k: (float(v) if k.split("_", 1)[0] in (*PARTS, "embodied") or k == "life_units"
               else v) for k, v in material_row().items()}
    row["is_course_data"] = False
    jsonschema.validate(row, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**row, "is_course_data": True}, schema)


def test_add_rejects_catalog_name(reference, tmp_path):
    path = tmp_path / "c.csv"
    path.write_text(csv_text(material_row(assembly="Floor", material_type="Test Slab (sf)")),
                    encoding="utf-8")
    custom = load_custom_materials(path)  # no catalog: not checked here ...
    with pytest.raises(ValueError, match="may not reuse a catalog name"):
        reference.add_custom_materials(custom)  # ... but when added


# --- engine: custom material like a catalog entry, flags and totals --------------------


def _calculate(reference, items, use_phase=None):
    return STVEngine(reference).calculate(STVInputs.from_dict({
        "team": TEAM, "construction_items": items, "use_phase": use_phase or {}}))


def test_engine_uses_custom_material(with_bamboo):
    result = _calculate(with_bamboo, [
        {"assembly": "Beams", "material_type": BAMBOO, "amount": 1000.0},
        {"assembly": "Floor", "material_type": "Test Slab (sf)", "amount": 100.0},
    ])
    bamboo, slab = result.construction_items
    # amount x value x life_units, per phase
    for n, key in enumerate(("carbon", "energy", "water", "ozone")):
        for phase, values in PARTS.items():
            assert getattr(bamboo, phase).get(key) == pytest.approx(1000 * 2 * values[n])
    assert bamboo.embodied_total.carbon == pytest.approx(1000 * 2 * (-0.25))
    assert bamboo.custom_material and not slab.custom_material
    assert bamboo.to_dict()["custom_material_source"].startswith("Invented EPD X-1")
    assert slab.to_dict()["custom_material_source"] is None

    flags = result.to_dict()["data_flags"]
    assert flags["custom_material"] is True and flags["proxy"] is False
    block = flags["custom_materials"]
    assert block["embodied"]["energy"] == pytest.approx(1000 * 2 * 14.0)
    embodied = result.breakdown.embodied
    assert block["share_of_embodied"]["energy"] == pytest.approx(28_000 / embodied.energy)
    assert block["share_of_life_cycle"]["water"] == pytest.approx(
        bamboo.embodied_total.water / result.breakdown.life_cycle.water)
    (used,) = block["materials"]
    assert (used["assembly"], used["material_type"], used["amount"]) == ("Beams", BAMBOO, 1000)
    assert flags["by_assembly"]["Beams"]["custom_material"] is True
    assert flags["by_assembly"]["Floor"]["custom_material"] is False
    assert flags["by_assembly"]["Beams"]["custom_material_embodied"]["water"] == pytest.approx(
        1000 * 2 * 32.5)


def test_no_flags_without_custom_or_proxy(reference):
    flags = _calculate(reference, [
        {"assembly": "Floor", "material_type": "Test Slab (sf)", "amount": 10.0}
    ]).to_dict()["data_flags"]
    assert (flags["custom_material"], flags["proxy"]) == (False, False)
    assert flags["custom_materials"]["embodied"]["carbon"] == 0.0
    assert flags["proxies"]["items"] == []


def _proxy_mapping(catalog):
    return stv_mapping_from_dicts([
        {"category": "Floors", "keyword": "", "stv_assembly": "Floor",
         "stv_material_type": "Test Slab (sf)", "quantity_field": "area", "note": "slabs"},
        {"category": "Floors", "keyword": "bamboo", "stv_assembly": "Floor",
         "stv_material_type": "Test Slab (sf)", "quantity_field": "area",
         "note": "Proxy: bamboo floors booked as slab"},
        {"category": "Structural Framing", "keyword": "bamboo", "stv_assembly": "Beams",
         "stv_material_type": BAMBOO, "quantity_field": "weight", "note": "custom material"},
    ], catalog=catalog)


def _element(line, **cells) -> Element:
    row = {"ElementId": str(line), "Category": "Floors", "Family": "", "Type": "",
           "Material": "", "Area": "100 SF"}
    row.update(cells)
    return Element(discipline="architecture", row=row, source="test.csv", line=line)


def test_proxy_rules_and_custom_material_through_the_mapping(with_bamboo):
    mapping = _proxy_mapping(with_bamboo)  # validated against the catalog incl. BAMBOO
    assert [r.is_proxy for r in mapping.rules] == [False, True, False]
    report = map_elements([
        _element(2, Area="300 SF"),
        _element(3, Material="Bamboo panel", Area="100 SF"),
        _element(4, Category="Structural Framing", Material="bamboo", Weight="50 kg"),
    ], mapping, discipline="architecture")
    items = {i.material_type: i for i in report.construction_items}
    assert (items["Test Slab (sf)"].amount, items["Test Slab (sf)"].proxy_amount) == (400, 100)
    assert items[BAMBOO].proxy_amount == 0.0
    assert report.to_dict()["construction_items"][1]["proxy_amount"] == 100

    result = _calculate(with_bamboo, [
        {"assembly": i.assembly, "material_type": i.material_type, "amount": i.amount,
         "proxy_amount": i.proxy_amount} for i in report.construction_items])
    slab = next(i for i in result.construction_items if i.material_type == "Test Slab (sf)")
    assert slab.to_dict()["proxy"] is True and slab.proxy_share == pytest.approx(0.25)
    flags = result.to_dict()["data_flags"]
    assert flags["proxy"] and flags["custom_material"]
    assert flags["proxies"]["embodied"]["carbon"] == pytest.approx(
        0.25 * slab.embodied_total.carbon)
    (proxy_item,) = flags["proxies"]["items"]
    assert (proxy_item["amount"], proxy_item["proxy_amount"]) == (400, 100)
    assert flags["by_assembly"]["Floor"]["proxy"] is True
    assert flags["by_assembly"]["Beams"] == {**flags["by_assembly"]["Beams"],
                                             "proxy": False, "custom_material": True}
    total = flags["custom_materials"]["embodied"]["carbon"] + flags["proxies"]["embodied"][
        "carbon"]
    assert total == pytest.approx(flags["by_assembly"]["Floor"]["proxy_embodied"]["carbon"]
                                  + flags["by_assembly"]["Beams"]["embodied"]["carbon"])


def test_flags_survive_json_and_combine(with_bamboo):
    a = _calculate(with_bamboo, [{"assembly": "Beams", "material_type": BAMBOO,
                                  "amount": 10.0}])
    b = _calculate(with_bamboo, [{"assembly": "Floor", "material_type": "Test Slab (sf)",
                                  "amount": 40.0, "proxy_amount": 40.0}])
    reloaded = [STVResults.from_dict(json.loads(json.dumps(r.to_dict()))) for r in (a, b)]
    combined = STVResults.combine(reloaded).to_dict()["data_flags"]
    assert combined["custom_material"] and combined["proxy"]
    assert combined["custom_materials"]["embodied"]["carbon"] == pytest.approx(
        a.breakdown.embodied.carbon)
    assert combined["proxies"]["embodied"]["carbon"] == pytest.approx(
        b.breakdown.embodied.carbon)


def test_unknown_material_still_fails(reference):
    with pytest.raises(ValueError, match="Unknown assembly 'Beams'"):
        _calculate(reference, [{"assembly": "Beams", "material_type": BAMBOO, "amount": 1.0}])


# --- CLIs ------------------------------------------------------------------------------


def _stv_cli(monkeypatch, tmp_path, reference, items, *args):
    template = tmp_path / "course.xlsx"
    template.write_bytes(b"")
    monkeypatch.setattr(STVReferenceData, "from_workbook",
                        staticmethod(lambda path=None: reference))
    monkeypatch.setenv("COURSE_STV_XLSX", str(template))
    inputs = tmp_path / "inputs.json"
    inputs.write_text(json.dumps({"team": TEAM, "construction_items": items}))
    out = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["concho-stv", "--input", str(inputs),
                                      "--output-dir", str(out), *args])
    cli.main()
    return json.loads((out / "stv_results.json").read_text())


def test_stv_cli_custom_materials(monkeypatch, tmp_path, reference, custom_path, capsys):
    result = _stv_cli(monkeypatch, tmp_path, reference,
                      [{"assembly": "Beams", "material_type": BAMBOO, "amount": 5.0}],
                      "--custom-materials", str(custom_path))
    assert result["construction_items"][0]["custom_material"] is True
    assert result["data_flags"]["custom_material"] is True
    assert "team data, not course data" in capsys.readouterr().err


def test_stv_cli_rejects_invalid_custom_materials(monkeypatch, tmp_path, reference, capsys):
    bad = tmp_path / "bad.csv"
    bad.write_text(csv_text(material_row(material_type="Test Column (kg)")), encoding="utf-8")
    with pytest.raises(SystemExit):
        _stv_cli(monkeypatch, tmp_path, reference, [], "--custom-materials", str(bad))
    assert "is a course catalog name" in capsys.readouterr().err


def test_concho_custmat_cli(monkeypatch, tmp_path, custom_path, capsys):
    monkeypatch.delenv("COURSE_STV_XLSX", raising=False)
    assert concho_cli.main(["custmat", "validate", str(custom_path)]) == 0
    assert "not checked against the course catalog" in capsys.readouterr().out
    bad = tmp_path / "bad.csv"
    bad.write_text(csv_text(material_row(is_course_data="true")), encoding="utf-8")
    assert concho_cli.main(["custmat", "validate", str(bad)]) == 1
    assert "INVALID" in capsys.readouterr().out
    assert concho_cli.main(["custmat", "validate", str(custom_path),
                            "--template", str(tmp_path / "missing.xlsx")]) == 1
    capsys.readouterr()
    assert concho_cli.main(["custmat", "schema"]) == 0
    assert json.loads(capsys.readouterr().out)["title"] == "custom_materials.csv row"
