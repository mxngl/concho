"""P3.9 (D15): STV with the shared duplicate / Parts rule, Parts mapped via Original Category.

Invented exports, mapping rules and reference data only (tests/stv/conftest.py); no course
or project data.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest
from conftest import TEAM

from engines.stv import cli
from engines.stv.mapping import Element, load_stv_mapping, map_exports, stv_mapping_from_dicts
from engines.stv.models import COMBINE_DEDUP_NOTE
from engines.stv.reference import STVReferenceData

# Columns the STV importers read, new layout (add-in since concho #18) and old layout (no
# Original Category / Part Source Id), in the order of docs/model-requirements.md.
NEW_COLUMNS = ["ElementId", "Category", "Family", "Type", "Original Category", "Mark",
               "Assembly Code", "Assembly Description", "Area", "Volume", "Material",
               "Comments", "Part Source Id"]
OLD_COLUMNS = [c for c in NEW_COLUMNS if c not in ("Original Category", "Part Source Id")]

RULES = [
    {"discipline": "structural", "category": "Floors", "keyword": "invented slab",
     "stv_assembly": "Floor", "stv_material_type": "Test Slab (sf)", "quantity_field": "area"},
    {"discipline": "architecture", "category": "Floors", "stv_assembly": "Floor",
     "stv_material_type": "Test Slab (sf)", "quantity_field": "area"},
]


def _write(path: Path, rows: list[dict[str, str]], columns=NEW_COLUMNS) -> Path:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in columns})
    return path


def _floor(element_id: str, area: str, **extra) -> dict[str, str]:
    return {"ElementId": element_id, "Category": "Floors", "Type": "Floor",
            "Material": "Invented slab", "Assembly Code": "B1010", "Area": area, **extra}


def _part(element_id: str, source: str, area: str, original: str = "Floors") -> dict[str, str]:
    return {"ElementId": element_id, "Category": "Parts", "Original Category": original,
            "Material": "Invented slab", "Assembly Code": "B1010", "Area": area,
            "Part Source Id": source}


@pytest.fixture
def mapping():
    return stv_mapping_from_dicts(RULES)


@pytest.fixture
def new_pair(tmp_path) -> dict[str, Path]:
    """Floor 500 as Parts in the structural export and whole in the architecture export."""
    return {
        "structural": _write(tmp_path / "S_Structural_Schedule.csv", [
            _part("501", "500", "400"), _part("502", "500", "600"),
        ]),
        "architecture": _write(tmp_path / "A_Architecture_TakeOff.csv", [
            _floor("500", "1000"), _floor("700", "50", Type='Slab DNC'),
        ]),
    }


def _amounts(reports) -> float:
    return sum(item.amount for r in reports for item in r.construction_items)


def test_parts_match_rules_of_their_original_category(mapping):
    part = Element("structural", _part("501", "500", "400"))
    assert part.category == "Parts" and part.match_category == "Floors"
    assert mapping.match(part).rule.stv_material_type == "Test Slab (sf)"
    # Old exports: no Original Category -> matched as "Parts", unmapped as before.
    old = Element("structural", {"ElementId": "9", "Category": "Parts",
                                 "Material": "Invented slab", "Area": "10"})
    assert old.match_category == "Parts" and mapping.match(old).rule is None


def test_new_format_pair_counts_only_the_parts(new_pair, mapping):
    reports, dedup = map_exports([("structural", new_pair["structural"]),
                                  ("architecture", new_pair["architecture"])], mapping)
    assert [[e.element.element_id for e in r.elements] for r in reports] == [
        ["501", "502"], ["700"]]
    assert _amounts(reports) == 400 + 600 + 50
    assert [(d.element_id, d.reason, d.kept_export) for d in dedup.dropped] == [
        ("500", "host_of_parts", "S_Structural_Schedule.csv")]


def test_mapped_row_wins_when_both_have_a_code(tmp_path, mapping):
    """Step b (STV only): the structural rule needs 'invented slab', so the structural row of
    800 is unmapped and the architecture row is kept although Floors are structural."""
    struct = _write(tmp_path / "S.csv", [_floor("800", "70", Material="Other")])
    arch = _write(tmp_path / "A.csv", [_floor("800", "70", Material="Other")])
    reports, dedup = map_exports([("structural", struct), ("architecture", arch)], mapping)
    assert [(d.element_id, d.reason, d.kept_export) for d in dedup.dropped] == [
        ("800", "duplicate_unmapped", "A.csv")]
    assert _amounts(reports) == 70
    # Both mapped: the structural export owns Floors.
    struct = _write(tmp_path / "S2.csv", [_floor("801", "70")])
    arch = _write(tmp_path / "A2.csv", [_floor("801", "90")])
    reports, dedup = map_exports([("structural", struct), ("architecture", arch)], mapping)
    assert [(d.element_id, d.reason, d.kept_export) for d in dedup.dropped] == [
        ("801", "duplicate_other_discipline", "S2.csv")]
    assert _amounts(reports) == 70


def test_row_with_code_wins(tmp_path, mapping):
    struct = _write(tmp_path / "S.csv", [_floor("802", "70", **{"Assembly Code": ""})])
    arch = _write(tmp_path / "A.csv", [_floor("802", "90")])
    reports, dedup = map_exports([("structural", struct), ("architecture", arch)], mapping)
    assert [(d.element_id, d.reason, d.kept_export) for d in dedup.dropped] == [
        ("802", "duplicate_without_code", "A.csv")]
    assert _amounts(reports) == 90


def test_old_layout_still_maps(tmp_path, mapping):
    """44-column style: no Original Category, no Part Source Id; Parts stay unmapped."""
    struct = _write(tmp_path / "S.csv", [
        {"ElementId": "1", "Category": "Parts", "Material": "Invented slab", "Area": "5"},
        _floor("2", "40"),
    ], columns=OLD_COLUMNS)
    reports, dedup = map_exports([("structural", struct)], mapping)
    assert dedup.dropped == [] and dedup.parts == {"rows": 1, "with_part_source_id": 0,
                                                   "hosts": 0}
    assert [e.status for e in reports[0].elements] == ["unmapped", "mapped"]
    assert _amounts(reports) == 40


def _main(monkeypatch, reference, tmp_path, *args: str) -> None:
    template = tmp_path / "course.xlsx"
    template.write_bytes(b"")
    monkeypatch.setattr(STVReferenceData, "from_workbook",
                        staticmethod(lambda path=None: reference))
    monkeypatch.setattr(sys, "argv", ["concho-stv", "--template", str(template), *args])
    cli.main()


def test_cli_writes_deduplication_and_dnc_rows(monkeypatch, tmp_path, reference, new_pair,
                                               capsys):
    mapping_csv = tmp_path / "stv_mapping.csv"
    with mapping_csv.open("w", newline="", encoding="utf-8") as handle:
        columns = ["discipline", "assembly_code", "category", "keyword", "stv_assembly",
                   "stv_material_type", "quantity_field", "conversion", "note"]
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for rule in RULES:
            writer.writerow({c: rule.get(c, "") for c in columns})
    out = tmp_path / "out"
    _main(monkeypatch, reference, tmp_path, "--team", TEAM, "--output-dir", str(out),
          "--stv-mapping", str(mapping_csv),
          "--structural-schedule", str(new_pair["structural"]),
          "--architecture-schedule", str(new_pair["architecture"]))
    err = capsys.readouterr().err
    assert "dropped 1 host_of_parts row(s)" in err
    assert "1 counted row(s) carry the DNC marker" in err
    result = json.loads((out / "stv_results.json").read_text())
    assert [(i["material_type"], i["amount"]) for i in result["construction_items"]] == [
        ("Test Slab (sf)", 1000), ("Test Slab (sf)", 50)]  # structural Parts, architecture
    dedup = result["deduplication"]
    assert dedup["by_reason"]["host_of_parts"] == 1 and dedup["rows_kept"] == 3
    assert "duplicate_unmapped" in dedup["by_reason"]
    assert result["dnc_rows"] == [{"element_id": "700", "category": "Floors",
                                   "type": "Slab DNC", "discipline": "architecture",
                                   "status": "mapped"}]
    assert result["mapping_coverage"]["cross_discipline_elements"] == []

    # --combine-results cannot deduplicate: warning and a note in the results JSON.
    combined = tmp_path / "combined"
    _main(monkeypatch, reference, tmp_path, "--output-dir", str(combined),
          "--combine-results", str(out / "stv_results.json"))
    assert COMBINE_DEDUP_NOTE in capsys.readouterr().err
    block = json.loads((combined / "stv_results.json").read_text())["deduplication"]
    assert block["deduplicated_across_inputs"] is False
    assert block["note"] == COMBINE_DEDUP_NOTE
    assert block["inputs"] == [{"dropped": 1, "by_reason": dedup["by_reason"]}]


def test_island_mapping_takes_structural_bamboo_floor_parts():
    """The Island rule added in P3.9: a structural floor Part of bamboo (new export: Original
    Category Floors, code B1010 from its floor) is booked like the whole bamboo floors."""
    island = load_stv_mapping(Path(__file__).resolve().parents[2] / "engines" / "stv"
                              / "examples" / "island" / "stv_mapping.csv")
    part = Element("structural", {"ElementId": "1", "Category": "Parts",
                                  "Original Category": "Floors", "Assembly Code": "B1010",
                                  "Material": "Structural Bamboo (CLB)", "Area": "100"})
    rule = island.match(part).rule
    assert (rule.stv_assembly, rule.stv_material_type, rule.is_proxy) == (
        "Floor", "Concrete (sf)", True)
    old = Element("structural", {"ElementId": "1", "Category": "Parts",
                                 "Material": "Structural Bamboo (CLB)", "Area": "100"})
    assert island.match(old).rule is None  # old exports: Parts stay unmapped
