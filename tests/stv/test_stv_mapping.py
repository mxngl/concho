"""P3.6: STV mapping table: validator, matching order, ties, conversions (invented rows).

All catalog names and rows here are invented (no course data); the catalog is a stand-in
with the only attribute the validator uses (``valid_materials``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from engines import cli as concho_cli
from engines.stv import conversions
from engines.stv.mapping import (
    COLUMNS,
    Element,
    StvMappingError,
    StvMappingTieError,
    check_exports,
    json_schema,
    map_elements,
    parse_keyword,
    stv_mapping_from_dicts,
    validate_stv_mapping_dicts,
    validate_stv_mapping_text,
)


@dataclass
class FakeCatalog:
    valid_materials: dict[str, set[str]] = field(default_factory=lambda: {
        "Floor": {"Test Slab (sf)", "Test Deck (sf)"},
        "Columns": {"Test Column (kg)", "Test Concrete Column (cy)"},
        "MEP": {"Test Duct (ft)", "Test Fan (m^3/s)", "Test Sheet Duct (kg)"},
        "Energy": {"Test Turbine (Turbine)"},
    })


CATALOG = FakeCatalog()


def rule(**kw) -> dict[str, str]:
    base = {"assembly_code": "", "category": "Floors", "keyword": "", "stv_assembly": "Floor",
            "stv_material_type": "Test Slab (sf)", "quantity_field": "area", "conversion": "",
            "note": ""}
    base.update({k: str(v) for k, v in kw.items()})
    return base


def errors(*rows, catalog=CATALOG) -> str:
    result = validate_stv_mapping_dicts(list(rows), catalog=catalog)
    assert not result.ok, "expected errors"
    return "\n".join(result.errors)


def element(discipline="architecture", **cells) -> Element:
    row = {"ElementId": "1", "Category": "Floors", "Family": "", "Type": "", "Material": "",
           "Assembly Code": "", "Assembly Description": "", "Area": "100 SF"}
    row.update(cells)
    return Element(discipline=discipline, row=row, source="test.csv", line=2)


# --- valid tables ---------------------------------------------------------------------


def test_valid_table_with_catalog_has_no_warnings():
    result = validate_stv_mapping_dicts([rule(), rule(category="", assembly_code="B1010")],
                                        catalog=CATALOG)
    assert result.ok, result.errors
    assert result.warnings == []
    assert [r.row for r in result.mapping.rules] == [2, 3]


def test_without_catalog_warns():
    result = validate_stv_mapping_dicts([rule()], catalog=None)
    assert result.ok
    assert any("not checked against the course LCA catalog" in w for w in result.warnings)


def test_comments_blank_lines_and_optional_columns():
    text = ("# invented\n" + ",".join(COLUMNS) + "\n\n"
            ",Floors,,Floor,Test Slab (sf),area,,\n")
    result = validate_stv_mapping_text(text, catalog=CATALOG)
    assert result.ok, result.errors
    (only,) = result.mapping.rules
    assert (only.row, only.priority, only.discipline) == (4, 100, "")


def test_json_schema():
    schema = json_schema()
    assert schema["title"] == "stv_mapping.csv row"
    assert set(schema["x-csv-columns"]) == set(COLUMNS) | {"discipline", "priority"}
    assert set(schema["required"]) == {"stv_assembly", "stv_material_type", "quantity_field"}


# --- every error type -----------------------------------------------------------------


def test_header_errors():
    msg = "\n".join(validate_stv_mapping_text(
        "assembly_code,category,keyword,stv_assembly,stv_material_typ,quantity_field,"
        "conversion,note,note\n").errors)
    assert "missing column(s): stv_material_type" in msg
    assert "unknown column 'stv_material_typ'" in msg and "Did you mean" in msg
    assert "column 'note' appears more than once" in msg
    assert "file is empty" in validate_stv_mapping_text("").errors[0]


def test_too_many_cells():
    text = ",".join(COLUMNS) + "\n,Floors,,Floor,Test Slab (sf),area,,,extra\n"
    assert "unquoted comma" in "\n".join(validate_stv_mapping_text(text).errors)


def test_discipline_error():
    assert "is not one of architecture, structural, mep" in errors(rule(discipline="civil"))


@pytest.mark.parametrize("code, expected", [
    ("B2019", "not in the Uniformat reference list"),
    ("B20", "not in the Uniformat reference list"),
    ("B2010.CW", "sub-codes are not used"),
])
def test_assembly_code_errors(code, expected):
    msg = errors(rule(assembly_code=code))
    assert expected in msg
    if code == "B2019":
        assert "Did you mean B2020 / B2010" in msg


def test_code_level2_form_and_extension_are_valid():
    result = validate_stv_mapping_dicts(
        [rule(assembly_code="B2000"), rule(assembly_code="H1000", priority=1)], catalog=CATALOG)
    assert result.ok, result.errors


def test_rule_needs_category_or_code():
    assert "needs a category or an assembly_code" in errors(rule(category=""))


def test_keyword_needs_category():
    assert "a keyword needs a category" in errors(rule(category="", assembly_code="B1010",
                                                       keyword="wood"))


@pytest.mark.parametrize("keyword, expected", [
    ("wood||timber", "empty term"),
    ("wood&", "empty term"),
    ("width_in<=15", "unknown numeric test 'width_in'"),
    ("diameter_in=15", "looks like a numeric test"),
])
def test_keyword_errors(keyword, expected):
    assert expected in errors(rule(keyword=keyword))


def test_priority_error():
    assert "is not a whole number" in errors(rule(priority="high"))
    assert "is not a whole number" in errors(rule(priority="-1"))


def test_empty_catalog_fields():
    msg = errors(rule(stv_assembly="", stv_material_type=""))
    assert "stv_assembly: empty" in msg and "stv_material_type: empty" in msg


def test_catalog_errors():
    assert "'Flor' is not an assembly of the course LCA catalog" in errors(
        rule(stv_assembly="Flor"))
    msg = errors(rule(stv_material_type="Test Slap (sf)"))
    assert "not in the course LCA catalog for 'Floor'" in msg
    assert "Did you mean 'Test Slab (sf)'" in msg


def test_quantity_field_error():
    assert "is not one of area | volume" in errors(rule(quantity_field="mass"))


@pytest.mark.parametrize("conversion, expected", [
    ("cf_to_m3", "unknown conversion 'cf_to_m3'"),
    ("density_kg_per_cf", "missing parameter(s) density_kg_per_cf"),
    ("density_kg_per_cf=abc", "not a plain positive decimal"),
    ("density_kg_per_cf=0", "must be > 0"),
    ("door_area(thickness=1.75)", "unknown parameter(s) thickness"),
    ("duct_weight_estimate=1.3", "takes 4 parameters"),
    ("duct_weight_estimate(surface_factor=1.3;density_kg_per_m3=8000;gauge_m=0.0005/0.0006;"
     "gauge_limits_m=0.3/0.6)", "one value more than gauge_limits_m"),
    ("cf_to_cy=2", "takes no parameters"),
    ("door_area(thickness_in)", "is not key=value"),
    ("cf to cy!", "is not a conversion"),
])
def test_conversion_errors(conversion, expected):
    assert expected in errors(rule(conversion=conversion))


def test_conversion_needs_its_quantity_field():
    assert "cf_to_cy converts quantity_field 'volume', not 'area'" in errors(
        rule(conversion="cf_to_cy"))


@pytest.mark.parametrize("kw, expected", [
    ({"quantity_field": "volume"}, "volume gives 'cf', but 'Test Slab (sf)' is measured in 'sf'"),
    ({"stv_assembly": "Columns", "stv_material_type": "Test Column (kg)",
      "quantity_field": "volume", "conversion": "cf_to_cy"}, "volume + cf_to_cy gives 'cy'"),
    ({"quantity_field": "count"}, "count gives 'count'"),
    ({"stv_assembly": "MEP", "stv_material_type": "Test Fan (m^3/s)", "quantity_field": "length"},
     "length gives 'ft'"),
])
def test_unit_mismatch(kw, expected):
    msg = errors(rule(**kw))
    assert "unit mismatch" in msg and expected in msg


def test_units_that_match():
    result = validate_stv_mapping_dicts([
        rule(stv_assembly="Columns", stv_material_type="Test Column (kg)",
             quantity_field="volume", conversion="density_kg_per_cf=19.5"),
        rule(category="Structural Columns", stv_assembly="Columns",
             stv_material_type="Test Concrete Column (cy)", quantity_field="volume",
             conversion="cf_to_cy"),
        rule(category="Generic Models", stv_assembly="Energy",
             stv_material_type="Test Turbine (Turbine)", quantity_field="count"),
        rule(category="Air Terminals", stv_assembly="MEP", stv_material_type="Test Fan (m^3/s)",
             quantity_field="airflow"),
        rule(category="Ducts", stv_assembly="MEP", stv_material_type="Test Duct (ft)",
             quantity_field="length", conversion="duct_equivalent_length"),
    ], catalog=CATALOG)
    assert result.ok, result.errors


# --- ties (static) --------------------------------------------------------------------


def test_static_tie_same_key_and_priority():
    msg = errors(rule(keyword="Wood | timber"), rule(keyword="timber|wood",
                                                     stv_material_type="Test Deck (sf)"))
    assert "rows 2 and 3: tie" in msg


def test_static_tie_overlapping_disciplines():
    assert "tie" in errors(rule(discipline="structural"), rule())


def test_no_static_tie_for_other_priority_or_discipline():
    result = validate_stv_mapping_dicts([
        rule(), rule(priority=50), rule(discipline="structural", priority=7),
        rule(discipline="mep", priority=7),
    ], catalog=CATALOG)
    assert result.ok, result.errors


# --- matching -------------------------------------------------------------------------


SPECIFICITY_ROWS = [
    rule(category="Floors", stv_material_type="Test Slab (sf)", note="category"),
    rule(category="Floors", keyword="wood", note="category + keyword"),
    rule(category="", assembly_code="B1010", note="code"),
    rule(category="Floors", assembly_code="B1010", note="code + category"),
    rule(category="Floors", assembly_code="B1010", keyword="wood", note="code+category+kw"),
]


@pytest.mark.parametrize("n_rules", range(1, 6))
def test_most_specific_rule_wins(n_rules):
    mapping = stv_mapping_from_dicts(SPECIFICITY_ROWS[:n_rules], catalog=CATALOG)
    e = element(**{"Assembly Code": "B1010", "Type": "Wood floor"})
    match = mapping.match(e)
    assert match.rule.row == n_rules + 1  # the last (most specific) row given
    assert len(match.lost_to_specificity) == n_rules - 1


def test_priority_orders_rules_of_the_same_specificity():
    mapping = stv_mapping_from_dicts([
        rule(keyword="concrete", stv_material_type="Test Deck (sf)", priority=20),
        rule(keyword="wood", priority=10),
    ], catalog=CATALOG)
    match = mapping.match(element(Type="Wood on concrete"))
    assert match.rule.row == 3
    assert [r.row for r in match.lost_to_priority] == [2]


def test_runtime_tie_names_both_rules_and_the_element(tmp_path):
    mapping = stv_mapping_from_dicts([
        rule(keyword="concrete", stv_material_type="Test Deck (sf)"),
        rule(keyword="wood"),
    ], catalog=CATALOG)
    e = element(ElementId="4711", Type="Wood on concrete")
    with pytest.raises(StvMappingTieError) as exc:
        map_elements([e], mapping, discipline="architecture")
    msg = str(exc.value)
    assert "element 4711" in msg and "row 2" in msg and "row 3" in msg
    assert "priority 100" in msg
    # The validator finds the same tie on an export.
    export = tmp_path / "arch.csv"
    export.write_text("ElementId,Category,Type,Area\n4711,Floors,Wood on concrete,10 SF\n",
                      encoding="utf-8")
    (tie,) = check_exports(mapping, [("architecture", export)])
    assert "element 4711" in tie and "row 2" in tie and "row 3" in tie


def test_discipline_filters_rules():
    mapping = stv_mapping_from_dicts([
        rule(discipline="structural", stv_material_type="Test Deck (sf)"),
    ], catalog=CATALOG)
    assert mapping.match(element("structural")).rule is not None
    assert mapping.match(element("architecture")).rule is None
    assert mapping.match(element("unknown")).rule is None


@pytest.mark.parametrize("rule_code, element_code, matches", [
    ("B2000", "B2030100", True),
    ("B2000", "b2010", True),
    ("B2010", "B2010100", True),
    ("B2010", "B2020", False),
    ("B2010", "", False),
    ("B1000", "B10", True),
])
def test_code_prefix(rule_code, element_code, matches):
    mapping = stv_mapping_from_dicts([rule(category="", assembly_code=rule_code)],
                                     catalog=CATALOG)
    e = element(**{"Assembly Code": element_code})
    assert (mapping.match(e).rule is not None) == matches


@pytest.mark.parametrize("keyword, text, matches", [
    ("wood|timber", "Timber joist", True),
    ("exterior & concrete", "EXTERIOR wall", False),
    ("exterior & concrete", "Exterior concrete wall", True),
    ("exterior|curtain & glass|glazing", "curtain wall glazing", True),
    ("exterior|curtain & glass|glazing", "exterior brick", False),
])
def test_keyword_logic(keyword, text, matches):
    assert parse_keyword(keyword).matches(text.lower(), {}) == matches


def test_keyword_fields_and_category_case():
    mapping = stv_mapping_from_dicts([rule(category="floors", keyword="standard foundations")],
                                     catalog=CATALOG)
    assert mapping.match(element(**{"Assembly Description": "Standard Foundations"})).rule
    assert mapping.match(element(Material="Standard foundations mix")).rule
    assert not mapping.match(element(Comments="standard foundations")).rule


def test_numeric_test():
    kw = parse_keyword("diameter_in<=15")
    assert kw.matches("", {"Size": '12"x12"'})
    assert not kw.matches("", {"Size": '18"x12"'})
    assert not kw.matches("", {})  # unknown diameter: no match
    assert parse_keyword("diameter_in>15").matches("", {"Diameter": '16"'})


# --- conversions and estimates ----------------------------------------------------------


def q(conversion: str, field_: str, row: dict[str, str]) -> conversions.Quantity:
    return conversions.quantity(row, field_, conversions.parse_conversion(conversion))


def test_plain_quantity_fields():
    row = {"Area": "1,200 SF", "Volume": "54 CF", "Length": "3' - 6\"", "Weight": "12.5 kg",
           "Airflow": "360 m³/h"}
    assert q("", "area", row).amount == 1200
    assert q("", "volume", row).amount == 54
    assert q("", "length", row).amount == 3.5
    assert q("", "count", row).amount == 1
    assert q("", "weight", row).amount == 12.5
    assert q("", "airflow", row).amount == pytest.approx(0.1)
    assert q("", "weight", {"Unit Weight": "3 kg"}).amount == 3


def test_volume_conversions():
    assert q("cf_to_cy", "volume", {"Volume": "54 CF"}).amount == pytest.approx(2)
    assert q("density_kg_per_cf=10", "volume", {"Volume": "5 CF"}).amount == 50


def test_door_area_fallbacks_are_estimates():
    conv = "door_area(thickness_in=2)"
    assert q(conv, "area", {"Area": "20 SF"}) == conversions.Quantity(20, False)
    assert q(conv, "area", {"Width": "3' - 0\"", "Height": "7' - 0\""}) == \
        conversions.Quantity(21, True)
    got = q(conv, "area", {"Width": "3' - 0\"", "Volume": "4 CF"})
    assert got.estimated and got.amount == pytest.approx(24)
    assert q(conv, "area", {}).amount == 0


def test_duct_equivalent_length_fallbacks_are_estimates():
    conv = "duct_equivalent_length"
    assert q(conv, "length", {"Length": "10' - 0\""}) == conversions.Quantity(10, False)
    assert q(conv, "length", {"Area": "4 SF", "Volume": "8 CF"}) == conversions.Quantity(2, True)
    assert q(conv, "length", {"Volume": "27 CF"}).amount == pytest.approx(3)


def test_duct_weight_estimate():
    conv = ("duct_weight_estimate(surface_factor=2;density_kg_per_m3=1000;gauge_m=0.001/0.002;"
            "gauge_limits_m=0.3)")
    assert q(conv, "weight", {"Weight": "7 kg"}) == conversions.Quantity(7, False)
    # 0.254 m x 0.254 m, 1 m long: 2 x perimeter 1.016 m x 1 m x 0.001 m x 1000 kg/m3
    got = q(conv, "weight", {"Size": '10"x10"', "Length": "3' - 3.370079\""})
    assert got.estimated
    assert got.amount == pytest.approx(2 * 1.016 * 1.0 * 0.001 * 1000, rel=1e-6)
    # larger side > 0.3 m: the last gauge
    got = q(conv, "weight", {"Size": '20"x10"', "Length": "3' - 3.370079\""})
    assert got.amount == pytest.approx(2 * 2 * (0.508 + 0.254) * 0.002 * 1000, rel=1e-6)


def test_map_elements_flags_estimates_and_zero_quantity():
    mapping = stv_mapping_from_dicts([
        rule(category="Ducts", stv_assembly="MEP", stv_material_type="Test Duct (ft)",
             quantity_field="length", conversion="duct_equivalent_length"),
    ], catalog=CATALOG)
    elements = [
        element("mep", Category="Ducts", Length="10' - 0\""),
        element("mep", Category="Ducts", Area="4 SF", Volume="8 CF"),
        element("mep", Category="Ducts", Area=""),
        element("mep", Category="Pipes"),
    ]
    report = map_elements(elements, mapping, discipline="mep")
    (item,) = report.construction_items
    assert (item.amount, item.estimated_amount) == (12, 2)
    assert [e.status for e in report.elements] == ["mapped", "mapped", "zero_quantity",
                                                   "unmapped"]
    assert report.mapped_rows == 2
    assert [r["reason"][:4] for r in report.skipped_rows] == ["Rule", "No S"]


def test_load_errors_raise():
    with pytest.raises(StvMappingError) as exc:
        stv_mapping_from_dicts([rule(category="")])
    assert "needs a category" in str(exc.value)


# --- concho stvmap ----------------------------------------------------------------------


def test_cli_validate_and_schema(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("COURSE_STV_XLSX", raising=False)
    good = tmp_path / "good.csv"
    good.write_text(",".join(COLUMNS) + "\n,Floors,,Floor,Test Slab (sf),area,,\n",
                    encoding="utf-8")
    assert concho_cli.main(["stvmap", "validate", str(good)]) == 0
    assert "OK:" in capsys.readouterr().out

    bad = tmp_path / "bad.csv"
    bad.write_text(",".join(COLUMNS) + "\n,Floors,,Floor,Test Slab (sf),volume,,\n",
                   encoding="utf-8")
    assert concho_cli.main(["stvmap", "validate", str(bad)]) == 1
    assert "unit mismatch" in capsys.readouterr().out

    tie = tmp_path / "tie.csv"
    tie.write_text(",".join(COLUMNS) + "\n,Floors,wood,Floor,A (sf),area,,\n"
                   ",Floors,oak,Floor,B (sf),area,,\n", encoding="utf-8")
    export = tmp_path / "arch.csv"
    export.write_text("ElementId,Category,Type,Area\n9,Floors,Oak wood,10 SF\n", encoding="utf-8")
    assert concho_cli.main(["stvmap", "validate", str(tie)]) == 0
    capsys.readouterr()
    assert concho_cli.main(["stvmap", "validate", str(tie), "--architecture", str(export)]) == 1
    assert "tie: element 9" in capsys.readouterr().out

    assert concho_cli.main(["stvmap", "validate", str(good), "--template",
                            str(tmp_path / "missing.xlsx")]) == 1
    capsys.readouterr()
    assert concho_cli.main(["stvmap", "schema"]) == 0
    assert json.loads(capsys.readouterr().out)["title"] == "stv_mapping.csv row"
