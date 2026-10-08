"""P3.9 (D15): the shared duplicate / Parts rule (engines/common/dedup.py).

All rows invented (ElementIds, categories and codes only; no project data).
"""

from engines.common.dedup import (
    Export,
    deduplicate,
    effective_category,
    owner_discipline,
)


def _row(element_id, category, code="", **extra) -> dict[str, str]:
    return {"ElementId": element_id, "Category": category, "Assembly Code": code, **extra}


def _part(element_id, source, original="Floors", code="B1010", **extra) -> dict[str, str]:
    return _row(element_id, "Parts", code, **{"Part Source Id": source,
                                              "Original Category": original, **extra})


def _ids(rows) -> list[str]:
    return [r["ElementId"] for r in rows]


def _dropped(result) -> list[tuple[str, str, str, str]]:
    return [(d.element_id, d.reason, d.kept_export, d.dropped_export) for d in result.dropped]


# ── rule 1: Parts over their host ────────────────────────────────────────────

def test_new_format_pair_counts_parts_not_host():
    """Floor 500 is split into Parts in the structural export and whole in the architecture
    export (add-in since concho #18): only the Parts count."""
    struct = Export("S.csv", "structural", [_part("501", "500"), _part("502", "500"),
                                            _row("600", "Structural Columns", "B1010")])
    arch = Export("A.csv", "architecture", [_row("500", "Floors", "B1010"),
                                            _row("700", "Walls", "B2010")])
    result = deduplicate([arch, struct])
    assert _ids(result.kept[0]) == ["700"]
    assert _ids(result.kept[1]) == ["501", "502", "600"]
    assert _dropped(result) == [("500", "host_of_parts", "S.csv", "A.csv")]
    assert result.parts == {"rows": 2, "with_part_source_id": 2, "hosts": 1}
    assert result.counts()["host_of_parts"] == 1


def test_host_in_the_same_export_is_dropped():
    only = Export("A.csv", "architecture", [_row("900", "Ceilings", ""),
                                            _part("901", "900", "Ceilings", "")])
    result = deduplicate([only])
    assert _ids(result.kept_rows) == ["901"]
    assert _dropped(result) == [("900", "host_of_parts", "A.csv", "A.csv")]


def test_old_layout_parts_without_source_id_change_nothing():
    """Old exports (44 columns): no Part Source Id / Original Category column."""
    struct = Export("S.csv", "structural", [_row("1", "Parts"), _row("2", "Parts"),
                                            _row("3", "Floors", "B1010")])
    arch = Export("A.csv", "architecture", [_row("4", "Walls", "B2010")])
    result = deduplicate([arch, struct])
    assert result.dropped == []
    assert _ids(result.kept_rows) == ["4", "1", "2", "3"]
    assert result.parts == {"rows": 2, "with_part_source_id": 0, "hosts": 0}
    assert effective_category(_row("1", "Parts")) == "Parts"


# ── rule 2: one row per ElementId ────────────────────────────────────────────

def test_row_with_code_wins():
    arch = Export("A.csv", "architecture", [_row("10", "Floors", "B1010")])
    struct = Export("S.csv", "structural", [_row("10", "Floors", "")])
    result = deduplicate([arch, struct])
    assert _ids(result.kept[0]) == ["10"] and result.kept[1] == []
    assert _dropped(result) == [("10", "duplicate_without_code", "A.csv", "S.csv")]


def test_both_with_code_structural_category_goes_to_structural():
    arch = Export("A.csv", "architecture", [_row("11", "Floors", "B1010", Area="99")])
    struct = Export("S.csv", "structural", [_row("11", "Floors", "B1010", Area="80")])
    result = deduplicate([arch, struct])
    assert [r["Area"] for r in result.kept_rows] == ["80"]
    assert _dropped(result) == [("11", "duplicate_other_discipline", "S.csv", "A.csv")]


def test_both_with_code_other_category_goes_to_architecture():
    """Before P3.9 TVD kept the structural row here ("structural always wins")."""
    arch = Export("A.csv", "architecture", [_row("12", "Walls", "C1010", Area="50")])
    struct = Export("S.csv", "structural", [_row("12", "Walls", "C1010", Area="80")])
    result = deduplicate([arch, struct])
    assert [r["Area"] for r in result.kept_rows] == ["50"]
    assert _dropped(result) == [("12", "duplicate_other_discipline", "A.csv", "S.csv")]


def test_parts_in_two_exports_follow_their_original_category():
    arch = Export("A.csv", "architecture", [_part("13", "", "Structural Framing")])
    struct = Export("S.csv", "structural", [_part("13", "", "Structural Framing")])
    result = deduplicate([arch, struct])
    assert _dropped(result) == [("13", "duplicate_other_discipline", "S.csv", "A.csv")]
    assert result.dropped[0].category == "Structural Framing"


def test_mep_rows_code_first_then_owner():
    arch = Export("A.csv", "architecture", [_row("20", "Plumbing Fixtures"),
                                            _row("21", "Plumbing Fixtures", "D2010")])
    mep = Export("M.csv", "mep", [_row("20", "Plumbing Fixtures"),
                                  _row("21", "Plumbing Fixtures")])
    result = deduplicate([arch, mep])
    assert _dropped(result) == [
        ("21", "duplicate_without_code", "A.csv", "M.csv"),
        ("20", "duplicate_other_discipline", "M.csv", "A.csv"),
    ]


def test_mapping_step_only_when_given():
    """STV passes is_mapped (step b); TVD does not and goes on to the discipline."""
    arch = Export("A.csv", "architecture", [_row("30", "Floors", "A1010")])
    struct = Export("S.csv", "structural", [_row("30", "Floors", "A1010")])

    def mapped(row, discipline):
        return discipline == "architecture"

    stv = deduplicate([arch, struct], is_mapped=mapped)
    assert _dropped(stv) == [("30", "duplicate_unmapped", "A.csv", "S.csv")]
    assert "duplicate_unmapped" in stv.counts()
    tvd = deduplicate([arch, struct])
    assert _dropped(tvd) == [("30", "duplicate_other_discipline", "S.csv", "A.csv")]
    assert "duplicate_unmapped" not in tvd.counts()


def test_same_discipline_keeps_first_export():
    first = Export("A1.csv", "architecture", [_row("40", "Walls", "B2010")])
    second = Export("A2.csv", "architecture", [_row("40", "Walls", "B2010")])
    result = deduplicate([first, second])
    assert _dropped(result) == [("40", "duplicate_same_discipline", "A1.csv", "A2.csv")]


def test_rows_without_element_id_are_kept():
    arch = Export("A.csv", "architecture", [_row("", "Walls", "B2010")])
    struct = Export("S.csv", "structural", [_row("", "Walls", "B2010")])
    result = deduplicate([arch, struct])
    assert result.dropped == [] and len(result.kept_rows) == 2


def test_block_lists_ids_and_categories_only():
    arch = Export("A.csv", "architecture", [_row("500", "Floors", "B1010", Area="1000")])
    struct = Export("S.csv", "structural", [_part("501", "500", Area="600")])
    block = deduplicate([arch, struct]).block()
    assert (block["rows_in"], block["rows_kept"], block["dropped"]) == (2, 1, 1)
    assert block["by_reason"] == {"host_of_parts": 1, "duplicate_without_code": 0,
                                  "duplicate_other_discipline": 0,
                                  "duplicate_same_discipline": 0}
    assert block["dropped_rows"] == [{
        "element_id": "500", "category": "Floors", "kept_export": "S.csv",
        "kept_discipline": "structural", "dropped_export": "A.csv",
        "dropped_discipline": "architecture", "reason": "host_of_parts",
    }]
    assert "1000" not in str(block) and "600" not in str(block)


def test_owner_discipline_table():
    assert owner_discipline("Floors") == owner_discipline("structural columns") == "structural"
    assert owner_discipline("Structural Foundations") == "structural"
    assert owner_discipline("Ducts") == owner_discipline("Plumbing Fixtures") == "mep"
    assert owner_discipline("Walls") == owner_discipline("Ceilings") == "architecture"
    assert owner_discipline("Parts") == "architecture"  # Parts without Original Category
