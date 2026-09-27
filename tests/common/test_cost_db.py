"""P3.4: cost DB validator (engines/tvd/cost_db.py) and Uniformat reference, on invented rows.

Every error type has a case below; all rows are invented (no RSMeans, no course data).
"""

import json
from pathlib import Path

import pytest

from engines.cli import main
from engines.common import uniformat
from engines.tvd.cost_db import (
    COLUMNS,
    CostDbError,
    json_schema,
    load_cost_db,
    validate_cost_db_dicts,
    validate_cost_db_text,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "template"
ISLAND_CONFIG = REPO_ROOT / "engines" / "common" / "examples" / "island_2026.project_config.json"

OK_ROW = {
    "cluster": "Shell", "assembly_code": "B2020", "group": "Exterior Windows",
    "description": "Invented window", "unit": "EA", "unit_cost": "100.00",
    "quantity_rule": "takeoff", "quantity_value": "", "qty_reliability": "2",
    "cost_reliability": "3", "source": "invented", "split_keywords": "",
}


def _row(**kw) -> dict:
    return {**OK_ROW, **kw}


def _check(*rows, custom=None):
    return validate_cost_db_dicts(list(rows), custom_clusters=custom)


def _one_error(*rows, custom=None) -> str:
    db = _check(*rows, custom=custom)
    assert len(db.errors) == 1, db.errors
    return db.errors[0]


def _csv(*lines: str) -> str:
    return "\n".join([",".join(COLUMNS), *lines]) + "\n"


# ── valid input ────────────────────────────────────────────────────────────────────────


def test_valid_row():
    db = _check(_row())
    assert db.ok and db.warnings == [] and len(db.lines) == 1
    line = db.lines[0]
    assert (line.unit_cost, line.qty_reliability, line.cost_reliability) == (100.0, 2, 3)
    assert line.row == 2


@pytest.mark.parametrize("code, cluster", [
    ("B2010", "Shell"),        # NIST level 3
    ("B2000", "B"),            # course form of NIST level 2 (B20), accepted by rule
    ("F1000", "Special Construction"),
    ("H4000", "General Conditions"),  # uniformat_extensions.csv
    ("B2010.CW", "shell"),     # sub-code, checked through B2010; cluster case-insensitive
])
def test_accepted_codes(code, cluster):
    assert _check(_row(assembly_code=code, cluster=cluster)).ok


def test_row_numbers_skip_comments_and_blank_lines():
    text = "# comment\n" + _csv(
        "", "# another comment",
        "Shell,B2020,g,d,EA,1.00,takeoff,,1,1,,",
        "Shell,B9999,g,d,EA,1.00,takeoff,,1,1,,",
    )
    db = validate_cost_db_text(text)
    assert [line.row for line in db.lines] == [5]
    assert db.errors[0].startswith("row 6 (B9999): assembly_code:")


# ── header errors ──────────────────────────────────────────────────────────────────────


def test_old_format_is_rejected():
    text = "Cluster Name,Assembly Code,Assembly Group Name,Total O&P\nShell,B2020,x,$1,00\n"
    (err,) = validate_cost_db_text(text).errors
    assert "old AutoTVD cost_data.csv format" in err and "migrate_cost_data.py" in err


def test_header_missing_unknown_duplicated():
    header = [c for c in COLUMNS if c != "source"] + ["unit_costs", "unit"]
    errors = validate_cost_db_text(",".join(header) + "\n").errors
    assert errors == [
        "header: missing column(s): source.",
        "header: unknown column 'unit_costs'. Did you mean unit_cost?",
        "header: duplicated column(s): unit.",
    ]


def test_empty_file():
    assert validate_cost_db_text("# only a comment\n").errors == [
        "header: the file is empty (no header row)."
    ]


def test_too_many_cells():
    db = validate_cost_db_text(_csv("Shell,B2020,g,d,EA,1,000.00,takeoff,,1,1,,x"))
    assert db.errors == [
        "row 2: 13 cells, but the header has 12 columns (unquoted comma?)."
    ]


# ── cluster + code ─────────────────────────────────────────────────────────────────────


def test_cluster_required():
    assert _one_error(_row(cluster=" ")) == "row 2 (B2020): cluster: required."


def test_unknown_cluster_with_config():
    err = _one_error(_row(cluster="Equipment Rentals", assembly_code="I1000"),
                     custom=["Equipment Rental"])
    assert err.startswith("row 2 (I1000): cluster: unknown cluster 'Equipment Rentals': ")
    assert err.endswith("Did you mean Equipment Rental?")


def test_custom_cluster_skips_code_check_with_one_warning():
    rows = [_row(cluster="Equipment Rental", assembly_code=f"I{n}000", description=f"d{n}",
                 unit="LS", quantity_rule="fixed", quantity_value="1") for n in (1, 2)]
    for custom in (None, ["Equipment Rental"]):
        db = _check(*rows, custom=custom)
        assert db.ok
        assert db.warnings == [
            "rows 2-3: cluster 'Equipment Rental' is a custom cluster (not a course cluster "
            "A-H): Uniformat code check skipped."
        ]


def test_code_required():
    assert _one_error(_row(assembly_code="")) == "row 2: assembly_code: required."


def test_malformed_code_suggests():
    err = _one_error(_row(assembly_code="B201"))
    assert err.startswith("row 2 (B201): assembly_code: 'B201' is not a code of the form")
    assert "Did you mean" in err


def test_unknown_code_suggests_closest():
    err = _one_error(_row(assembly_code="B2040"))
    assert err == (
        "row 2 (B2040): assembly_code: 'B2040' is not in the Uniformat reference list "
        "(engines/common/uniformat.csv, uniformat_extensions.csv). "
        "Did you mean B2030 / B2020 / B2010?"
    )


def test_level1_and_bare_level2_codes_are_not_valid():
    assert not _check(_row(assembly_code="B0000")).ok
    assert uniformat.lookup("B20") is None  # not 4-digit form


def test_cluster_code_mismatch():
    err = _one_error(_row(cluster="Interiors"))
    assert err == ("row 2 (B2020): cluster: 'Interiors' is cluster C, but B2020 belongs to "
                   "group B (Shell).")


def test_legacy_cluster_spelling_warns():
    db = _check(_row(cluster="Special Contruction", assembly_code="F1010"))
    assert db.ok
    assert db.warnings == ["row 2 (F1010): cluster: legacy spelling 'Special Contruction', "
                           "read as 'Special Construction'."]


# ── description, unit, numbers ─────────────────────────────────────────────────────────


def test_description_required_unless_placeholder():
    assert _one_error(_row(description="")).startswith("row 2 (B2020): description: required")
    db = _check(_row(description="", unit="", unit_cost=""))
    assert db.ok
    assert db.warnings == [
        "row 2 (B2020): placeholder row (no description, unit or unit cost): priced 0."
    ]
    assert db.unpriced == [{"row": 2, "cluster": "Shell", "assembly_code": "B2020"}]


def test_unit_required_and_known():
    assert _one_error(_row(unit="")).startswith("row 2 (B2020): unit: required.")
    err = _one_error(_row(unit="SQF"))
    assert err.startswith("row 2 (B2020): unit: unknown unit 'SQF'. Did you mean")


@pytest.mark.parametrize("value", ["$25,00", "1,000.00", "1.670.000,00", "12 EA", "1e3"])
def test_unit_cost_must_be_plain_decimal(value):
    err = _one_error(_row(unit_cost=value))
    assert err == (f"row 2 (B2020): unit_cost: '{value}' is not a plain decimal: no currency "
                   "symbol, no thousands separator, '.' as decimal point (e.g. 1670000.00).")


def test_negative_numbers():
    err = _one_error(_row(unit_cost="-5"))
    assert err == "row 2 (B2020): unit_cost: '-5' must not be negative."
    err = _one_error(_row(quantity_rule="fixed", unit="LS", quantity_value="-1"))
    assert err == "row 2 (B2020): quantity_value: '-1' must not be negative."


def test_quantity_value_must_be_plain_decimal():
    err = _one_error(_row(quantity_rule="fixed", unit="LS", quantity_value="1,5"))
    assert err.startswith("row 2 (B2020): quantity_value: '1,5' is not a plain decimal")


def test_empty_unit_cost_warns():
    db = _check(_row(unit_cost=""))
    assert db.ok and db.warnings == ["row 2 (B2020): unit_cost: empty: line priced 0."]


@pytest.mark.parametrize("value", ["0", "4", "high", "2.0"])
def test_reliability_1_to_3(value):
    err = _one_error(_row(cost_reliability=value))
    assert err == (f"row 2 (B2020): cost_reliability: '{value}' must be 1, 2 or 3 (low, "
                   "medium, high), or empty.")


def test_blank_reliability_warns_once_per_column():
    rows = [_row(description=f"d{i}", qty_reliability="", cost_reliability="")
            for i in range(3)]
    db = _check(*rows, _row(description="rated"))
    assert db.ok
    assert db.warnings == [
        "rows 2-4: qty_reliability: not rated (3 rows); needed for the reliability summary "
        "(P3.5).",
        "rows 2-4: cost_reliability: not rated (3 rows); needed for the reliability summary "
        "(P3.5).",
    ]
    assert db.not_rated == {"qty_reliability": [2, 3, 4], "cost_reliability": [2, 3, 4]}
    assert db.validation_block()["not_rated"] == {"qty_reliability": 3, "cost_reliability": 3}


# ── duplicates ────────────────────────────────────────────────────────────────────────


def test_duplicate_key_case_and_whitespace_insensitive():
    dup = _row(cluster=" shell ", group="exterior  windows", description="INVENTED window")
    err = _one_error(_row(), dup)
    assert err == ("row 3 (B2020): duplicate of row 2 (same cluster, assembly_code, group and "
                   "description).")


def test_same_code_and_group_with_other_description_is_fine():
    assert _check(_row(), _row(description="Invented window, large")).ok


def test_duplicate_placeholders():
    ph = _row(description="", unit="", unit_cost="")
    assert "duplicate of row 2" in _one_error(ph, ph)


def test_legacy_and_canonical_cluster_name_are_the_same_cluster():
    row = _row(assembly_code="F1010", cluster="Special Construction")
    assert "duplicate of row 2" in _one_error(row, {**row, "cluster": "Special Contruction"})


# ── quantity rules ─────────────────────────────────────────────────────────────────────


def test_rule_required():
    assert _one_error(_row(quantity_rule="")).startswith("row 2 (B2020): quantity_rule: required")


def test_unknown_rule_suggests():
    err = _one_error(_row(quantity_rule="takeof"))
    assert err.startswith("row 2 (B2020): quantity_rule: unknown rule 'takeof'. Did you mean "
                          "takeoff?")


@pytest.mark.parametrize("rule, message", [
    ("mirror:", "'mirror:' needs target code(s), e.g. mirror:C1010."),
    ("count_codes:", "'count_codes:' needs target code(s), e.g. count_codes:D2010."),
    ("takeoff:B2010", "'takeoff' takes no target ('takeoff:B2010')."),
    ("mirror:B2010,B2030", "mirror takes exactly one code (mirror:<AC>)."),
    ("mirror:B2020", "a row cannot mirror its own code."),
])
def test_rule_syntax(rule, message):
    assert _one_error(_row(quantity_rule=rule)) == f"row 2 (B2020): quantity_rule: {message}"


def test_malformed_rule_target():
    err = _one_error(_row(quantity_rule="count_codes:D2010,d20"))
    assert err.startswith("row 2 (B2020): quantity_rule: target 'd20' is not a code")


def test_rule_targets_must_exist():
    err = _one_error(_row(quantity_rule="mirror:B2040"))
    assert err.startswith("row 2 (B2020): quantity_rule: target B2040 is neither in the "
                          "Uniformat reference list nor a code of this cost DB.")
    err = _one_error(_row(unit="EA", quantity_rule="count_codes:D2010,D2099"))
    assert "target D2099 is neither" in err
    # a sub-code of this cost DB is a valid target
    sub = _row(assembly_code="B2010.CW", unit="SF", split_keywords="glass")
    assert _check(sub, _row(unit="SF", quantity_rule="mirror:B2010.CW")).ok


def test_mirror_chain():
    a = _row(assembly_code="C3010", cluster="Interiors", unit="SF",
             quantity_rule="mirror:C1010")
    b = _row(assembly_code="C3020", cluster="Interiors", unit="SF",
             quantity_rule="mirror:C3010")
    assert _one_error(a, b) == ("row 3 (C3020): quantity_rule: mirror target C3010 is itself "
                                "a mirror (no chains).")


def test_quantity_value_only_for_value_rules():
    err = _one_error(_row(quantity_value="3"))
    assert err.startswith("row 2 (B2020): quantity_value: must be empty for rule takeoff")


def test_takeoff_needs_a_takeoff_unit():
    err = _one_error(_row(unit="LS"))
    assert err.startswith("row 2 (B2020): unit: 'LS' cannot be measured from the takeoff")


@pytest.mark.parametrize("kw, message", [
    ({"quantity_value": ""}, "quantity_value: pct_of_subtotal needs a percent in (0, 100]"),
    ({"quantity_value": "120"}, "quantity_value: pct_of_subtotal needs a percent in (0, 100]"),
    ({"unit": "LS"}, "unit: pct_of_subtotal needs unit '%'."),
    ({"unit_cost": "10"}, "unit_cost: must be empty for pct_of_subtotal"),
])
def test_pct_of_subtotal_errors(kw, message):
    row = _row(assembly_code="H5000", cluster="H", unit="%", unit_cost="",
               quantity_rule="pct_of_subtotal", quantity_value="5", **{})
    assert _check(row).ok
    assert message in _one_error({**row, **kw})


def test_percent_unit_only_for_pct_rule():
    err = _one_error(_row(unit="%", quantity_rule="fixed", quantity_value="1"))
    assert err == "row 2 (B2020): unit: unit '%' is only for pct_of_subtotal."


def test_rule_warnings():
    db = _check(
        _row(quantity_rule="fixed", unit="LS", quantity_value=""),
        _row(description="count", unit="SF", quantity_rule="count_codes:D2010,D2010"),
        _row(description="label", qty_label="Custom"),
    )
    assert db.ok
    assert db.warnings == [
        "row 2 (B2020): quantity_value: fixed without quantity: quantity 0.",
        "row 3 (B2020): quantity_rule: a code is listed twice (counted once).",
        "row 3 (B2020): unit: count_codes gives a count; unit 'SF' (expected EA).",
        "row 4 (B2020): qty_label: 'Custom' replaces the outcome label of a takeoff rule "
        "(e.g. 'No takeoff match').",
    ]


# ── split keywords ─────────────────────────────────────────────────────────────────────


def _wall(sub: str, spec: str, **kw) -> dict:
    return _row(assembly_code=f"B2010.{sub}", unit="SF", description=f"wall {sub}",
                split_keywords=spec, **kw)


def test_split_keywords_only_on_sub_codes():
    err = _one_error(_row(split_keywords="glass"))
    assert err == ("row 2 (B2020): split_keywords: only sub-code rows (e.g. B2010.CW) can "
                   "have split keywords.")


def test_split_fallback_not_mixed():
    err = _one_error(_wall("CW", "glass|*"))
    assert err.endswith("'*' (everything else) cannot be combined with keywords.")


def test_split_keywords_consistent_per_sub_code():
    err = _one_error(_wall("CW", "glass"), _wall("CW", "curtain", group="other"))
    assert err == ("row 3 (B2010.CW): split_keywords: differs from row 2 for the same "
                   "sub-code.")


def test_one_fallback_per_base_code():
    err = _one_error(_wall("A", "*"), _wall("B", "*"))
    assert err == ("row 3 (B2010.B): split_keywords: more than one '*' sub-code for B2010: "
                   "B2010.A, B2010.B.")


def test_split_warnings():
    db = _check(_wall("CW", "glass"), _wall("XX", ""), _wall("PW", "*"),
                _row(assembly_code="B2010", unit="SF", description="base"))
    assert db.ok
    assert db.warnings == [
        "row 3 (B2010.XX): split_keywords: empty: no B2010 element is routed to this "
        "sub-code (takeoff quantity 0).",
        "row 5 (B2010): quantity_rule: all B2010 elements go to its sub-codes (B2010.CW, "
        "B2010.XX, B2010.PW); this row gets no takeoff quantity.",
    ]


# ── mislabels ────────────────────────────────────────────────────────────────────────


def test_d_group_mislabels_warn_and_keep_the_code():
    rows = [
        _row(cluster="Services", assembly_code="D5030", description="Invented fire protection",
             unit="GSF", quantity_rule="fixed", quantity_value="10"),
        _row(cluster="Services", assembly_code="D5090", description="Invented HVAC system",
             unit="GSF", quantity_rule="fixed", quantity_value="10"),
        _row(cluster="Services", assembly_code="D3050", description="Invented HVAC units",
             unit="GSF", quantity_rule="fixed", quantity_value="10"),
    ]
    db = _check(*rows)
    assert db.ok
    assert [(m["assembly_code"], m["suggested_group"]) for m in db.mislabels] == [
        ("D5030", "D40"), ("D5090", "D30"),
    ]
    assert db.warnings[0] == (
        "row 2 (D5030): description: 'Invented fire protection' suggests D40 (Fire "
        "Protection), but D5030 is 'Communications & Security' (D50); code kept."
    )
    assert [line.code for line in db.lines] == ["D5030", "D5090", "D3050"]


# ── load_cost_db, validation block ─────────────────────────────────────────────────────


def test_load_cost_db_raises_with_all_errors(tmp_path):
    path = tmp_path / "cost_db.csv"
    path.write_text(_csv("Shell,B2040,g,d,EA,$1,takeoff,,1,1,,"), encoding="utf-8")
    with pytest.raises(CostDbError) as exc:
        load_cost_db(path)
    assert len(exc.value.errors) == 2


def test_missing_file(tmp_path):
    with pytest.raises(CostDbError, match="cannot read file"):
        load_cost_db(tmp_path / "nope.csv")


def test_validation_block():
    db = _check(_row(), _row(description="no price", unit_cost=""))
    assert db.validation_block() == {
        "status": "warnings",
        "rows": 2,
        "error_count": 0,
        "warning_count": 1,
        "warnings": ["row 3 (B2020): unit_cost: empty: line priced 0."],
        "unpriced": [{"row": 3, "cluster": "Shell", "assembly_code": "B2020"}],
        "not_rated": {},
    }


# ── Uniformat reference ────────────────────────────────────────────────────────────────


def test_uniformat_reference():
    ref = uniformat.reference()
    assert ref["D5030"].title == "Communications & Security" and ref["D5030"].level == 3
    assert ref["D40"].level == 2 and ref["D"].level == 1
    assert {e.code for e in ref.values() if e.origin != "nist"} == {
        "H1000", "H2000", "H3000", "H4000", "H5000"
    }
    assert all(e.origin == "course" for e in ref.values() if e.origin != "nist")
    assert not any(c.startswith(("H", "Z")) for c, e in ref.items() if e.origin == "nist")
    assert uniformat.lookup("F1000").code == "F10"  # course level-2 form by rule
    assert uniformat.lookup("B2010.CW").code == "B2010"
    assert uniformat.lookup("A1040") is None
    assert "F1000" in uniformat.valid_codes() and "B20" not in uniformat.valid_codes()


def test_uniformat_file_cites_its_source():
    head = (REPO_ROOT / "engines" / "common" / "uniformat.csv").read_text(encoding="utf-8")
    assert "NISTIR 6389" in head.split("code,level,title")[0]
    ext = (REPO_ROOT / "engines" / "common" / "uniformat_extensions.csv").read_text("utf-8")
    assert "not NIST, NOT COPIED FROM COURSE DATA".lower() in ext.lower()


# ── schema + template ──────────────────────────────────────────────────────────────────


def test_json_schema_matches_columns():
    schema = json_schema()
    assert list(schema["properties"]) == [*COLUMNS, "qty_label"]
    assert set(schema["required"]) == {"cluster", "assembly_code", "quantity_rule"}
    exported = json.loads((REPO_ROOT / "docs" / "schema" / "cost_db.schema.json").read_text())
    assert exported == schema


def test_template_is_header_only():
    lines = (TEMPLATE / "cost_db.csv").read_text(encoding="utf-8").splitlines()
    assert lines == [",".join([*COLUMNS, "qty_label"])]


def test_template_example_validates():
    db = load_cost_db(TEMPLATE / "examples" / "cost_db.example.csv")
    assert 3 <= len(db.lines) <= 5
    assert all("invented" in line.source.lower() for line in db.lines)


# ── CLI ───────────────────────────────────────────────────────────────────────────────


def test_cli_validate_ok(tmp_path, capsys):
    path = tmp_path / "cost_db.csv"
    path.write_text(_csv("Shell,B2020,g,d,EA,1.00,takeoff,,,,,"), encoding="utf-8")
    assert main(["costdb", "validate", str(path)]) == 0
    out = capsys.readouterr().out
    assert out.count("warning: ") == 2 and f"OK: {path} is valid (2 warnings)." in out


def test_cli_validate_errors(tmp_path, capsys):
    path = tmp_path / "cost_db.csv"
    path.write_text(_csv("Rental,I1000,g,d,LS,1.00,fixed,1,1,1,,"), encoding="utf-8")
    assert main(["costdb", "validate", str(path)]) == 0  # custom cluster: warning only
    assert main(["costdb", "validate", str(path), "--config", str(ISLAND_CONFIG)]) == 1
    out = capsys.readouterr().out
    assert "error: row 2 (I1000): cluster: unknown cluster 'Rental'" in out
    assert f"INVALID: {path} has 1 error." in out


def test_cli_schema(capsys):
    assert main(["costdb", "schema"]) == 0
    assert json.loads(capsys.readouterr().out)["title"] == "cost_db.csv row"
