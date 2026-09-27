"""P3.4: every cost DB quantity_rule on a small synthetic project (invented numbers).

Project: the Island example config (gross floor area 30,000 SF) and a handful of invented
takeoff elements. Each rule is checked through :func:`engines.tvd.engine.compute`, i.e. with
the cost DB validated first, the keyword split from ``split_keywords`` and the
``cost_db_validation`` block in the results.
"""

import pytest

from engines.tvd.cli import main
from engines.tvd.cost_db import CostDbError, cost_db_from_dicts
from engines.tvd.engine import compute, run_files

TAKEOFF = [
    # ElementId, Category, Family, Type, Assembly Code, Area, Length, Volume
    ("1", "Walls", "Basic Wall", "Interior 5in", "C1010", "100 SF", "20", ""),
    ("2", "Walls", "Basic Wall", "Interior 5in", "C1010", "50 SF", "10", ""),
    ("3", "Walls", "Curtain Wall", "Storefront", "B2010", "300 SF", "30", ""),
    ("4", "Walls", "Basic Wall", "Exterior Plaster", "B2010", "700 SF", "70", ""),
    ("5", "Walls", "Basic Wall", "Glazing band", "B2010", "40 SF", "4", ""),
    ("6", "Plumbing Fixtures", "WC", "Standard", "D2010", "", "", ""),
    ("7", "Furniture", "WC", "Accessible", "D2010", "", "", ""),  # excluded, still counted
    ("8", "Floors", "Slab", "6in", "B1010", "1000 SF", "", "500 CF"),
]


def _elements() -> list[dict]:
    keys = ("ElementId", "Category", "Family", "Type", "Assembly Code", "Area", "Length",
            "Volume")
    return [dict(zip(keys, row, strict=True)) for row in TAKEOFF]


def _line(cluster, code, unit, cost, rule, value="", **kw) -> dict:
    return {"cluster": cluster, "assembly_code": code, "group": kw.pop("group", "g"),
            "description": kw.pop("description", f"invented {code} {rule}"), "unit": unit,
            "unit_cost": cost, "quantity_rule": rule, "quantity_value": value,
            "qty_reliability": "2", "cost_reliability": "2", "source": "invented", **kw}


def _run(rows, island_config, custom=None):
    db = cost_db_from_dicts(rows, custom_clusters=custom)
    run = compute(_elements(), [], db, island_config)
    return run, run.results


def test_takeoff_by_unit_and_several_lines_per_code(island_config):
    # Two SF lines and one LF line under C1010: each gets the full C1010 quantity of its unit.
    rows = [
        _line("C", "C1010", "SF", "10", "takeoff", description="board"),
        _line("C", "C1010", "SF", "2", "takeoff", description="insulation"),
        _line("C", "C1010", "LF", "5", "takeoff", description="base"),
        _line("B", "B1010", "CY", "100", "takeoff"),
        _line("B", "B1010", "MSF", "1000", "takeoff", description="msf"),
        _line("B", "B1020", "SF", "10", "takeoff"),  # not in the takeoff
    ]
    _, res = _run(rows, island_config)
    assert [(r["qty"], r["qty_src"], r["total"]) for r in res] == [
        (150, "Area (SF)", 1500.0),
        (150, "Area (SF)", 300.0),
        (30, "Length (LF)", 150.0),
        (pytest.approx(18.52), "Volume (CY)", pytest.approx(1851.85)),
        (1.0, "Area/1000 (MSF)", 1000.0),
        (0, "No takeoff match", 0.0),
    ]
    assert res[-1]["notes"] == "Zero qty from takeoff | AC not in takeoff"


def test_fixed(island_config):
    rows = [_line("H", "H4000", "LS", "250000.00", "fixed", "1"),
            _line("D", "D1010", "EA", "1000", "fixed", "")]
    _, res = _run(rows, island_config)
    assert [(r["qty"], r["qty_src"], r["total"]) for r in res] == [
        (1, "Fixed", 250000.0), (0, "Fixed (no quantity set)", 0.0)]


def test_per_gsf(island_config):
    rows = [_line("D", "D5010", "GSF", "10", "per_gsf"),
            _line("D", "D5020", "SF", "2", "per_gsf", "0.5")]
    _, res = _run(rows, island_config)
    assert [(r["qty"], r["qty_src"], r["total"]) for r in res] == [
        (30000, "GSF × 1", 300000.0), (15000, "GSF × 0.5", 30000.0)]


def test_pct_of_subtotal(island_config):
    rows = [
        _line("H", "H5000", "%", "", "pct_of_subtotal", "5", description="contingency"),
        _line("H", "H4000", "LS", "100000.00", "fixed", "1"),
        _line("C", "C1010", "SF", "10", "takeoff"),
        _line("H", "H3000", "%", "", "pct_of_subtotal", "10", description="fee"),
    ]
    run, res = _run(rows, island_config)
    subtotal = 100000.0 + 1500.0  # the other lines, not the pct lines
    assert [r["ac"] for r in res] == ["H5000", "H4000", "C1010", "H3000"]  # file order
    assert (res[0]["qty"], res[0]["unit_cost"], res[0]["total"]) == (5, subtotal / 100, 5075.0)
    assert res[0]["qty_src"] == "5 % of subtotal"
    assert res[3]["total"] == 10150.0
    grand = next(r["total"] for r in run.summary if r["cluster"] == "GRAND TOTAL")
    assert grand == pytest.approx(subtotal * 1.15)


def test_mirror(island_config):
    rows = [
        _line("C", "C1010", "SF", "10", "takeoff"),
        _line("C", "C3010", "SF", "2", "mirror:C1010"),
        _line("C", "C3010", "LF", "1", "mirror:C1010", description="trim"),  # by unit
        _line("B", "B1020", "SF", "10", "fixed", "400"),
        _line("B", "B3010", "SF", "3", "mirror:B1020"),      # source only fixed
        _line("C", "C3020", "SF", "4", "mirror:C1020"),      # source missing
    ]
    _, res = _run(rows, island_config)
    assert [(r["qty"], r["qty_src"]) for r in res[1:]] == [
        (150, "Mirror: C1010 area"),
        (30, "Mirror: C1010 length"),
        (400, "Fixed"),
        (400, "Mirror: B1020 (Fixed)"),
        (0, "Mirror source C1020 not in takeoff"),
    ]
    assert res[-1]["notes"] == ""  # no takeoff notes for mirrors


def test_count_codes_counts_excluded_categories(island_config):
    rows = [_line("C", "C1030", "EA", "500", "count_codes:D2010"),
            _line("C", "C1030", "EA", "50", "count_codes:D2010,C1010,D2010",
                  description="accessories")]
    run, res = _run(rows, island_config)
    assert [(r["qty"], r["qty_src"]) for r in res] == [
        (2, "Count of codes (D2010)"),  # one fixture is in the excluded Furniture category
        (4, "Count of codes (D2010, C1010)"),
    ]
    assert "D2010" not in {r["ac"] for r in run.results}


def test_split_keywords(island_config):
    rows = [
        _line("B", "B2010.CW", "SF", "100", "takeoff", split_keywords="storefront|glazing"),
        _line("B", "B2010.PW", "SF", "10", "takeoff", split_keywords="*"),
    ]
    _, res = _run(rows, island_config)
    assert [(r["ac"], r["qty"]) for r in res] == [("B2010.CW", 340), ("B2010.PW", 700)]


def test_without_fallback_unmatched_elements_keep_the_base_code(island_config):
    rows = [_line("B", "B2010.CW", "SF", "100", "takeoff", split_keywords="storefront"),
            _line("B", "B2010", "SF", "10", "takeoff")]
    _, res = _run(rows, island_config)
    assert [(r["ac"], r["qty"]) for r in res] == [("B2010.CW", 300), ("B2010", 740)]


def test_qty_label_overrides_the_generic_label(island_config):
    rows = [_line("C", "C1030", "EA", "500", "count_codes:D2010", qty_label="Toilet stalls")]
    _, (res,) = _run(rows, island_config)
    assert res["qty_src"] == "Toilet stalls"


def test_custom_cluster(island_config):
    rows = [_line("Equipment Rental", "I1000", "LS", "400000", "fixed", "1")]
    run, (res,) = _run(rows, island_config, custom=["Equipment Rental"])
    assert res["cluster"] == "Equipment Rental" and res["total"] == 400000.0


def test_validation_block_in_the_results(island_config):
    rows = [_line("C", "C1010", "SF", "", "takeoff", qty_reliability="")]
    run, _ = _run(rows, island_config)
    block = run.results_payload()["cost_db_validation"]
    assert block["warning_count"] == 2
    assert block["unpriced"] == [{"row": 2, "cluster": "Interiors", "assembly_code": "C1010"}]
    assert block["not_rated"] == {"qty_reliability": 1}


# ── invalid cost DB stops the run ────────────────────────────────────────────────────────


def test_invalid_cost_db_stops_the_engine(tmp_path, synthetic_paths, island_config, capsys):
    bad = tmp_path / "cost_db.csv"
    text = open(synthetic_paths["cost"], encoding="utf-8").read()
    bad.write_text(text.replace("Invented slab,SF,10.00", "Invented slab,SF,$10,00"),
                   encoding="utf-8")
    with pytest.raises(CostDbError, match="unit_cost"):
        run_files(synthetic_paths["arch"], synthetic_paths["struct"], str(bad), island_config)
    with pytest.raises(SystemExit):
        main(["--ci", "--config", synthetic_paths["config"], "--arch", synthetic_paths["arch"],
              "--struct", synthetic_paths["struct"], "--cost", str(bad),
              "--out", str(tmp_path / "out")])
    err = capsys.readouterr().err
    assert "not a plain decimal" in err and "concho costdb validate" in err
    assert not (tmp_path / "out" / "results").exists()


def test_old_cost_data_format_is_rejected(tmp_path, synthetic_paths, island_config):
    old = tmp_path / "cost_data.csv"
    old.write_text("Cluster Name,Assembly Code,Assembly Group Name,Description             ,"
                   "Unit             ,Total O&P,Fixed Quantity\n"
                   "Shell,B1020,Roof,Invented,SF,\"$1,00\",10\n", encoding="utf-8")
    with pytest.raises(CostDbError, match="migrate_cost_data.py"):
        run_files(synthetic_paths["arch"], synthetic_paths["struct"], str(old), island_config)


def test_unknown_cluster_with_config_is_an_error(synthetic_paths, river_config, tmp_path):
    # River has the custom cluster "Crane Rental"; "Equipment Rental" is not in its config.
    path = tmp_path / "cost_db.csv"
    text = open(synthetic_paths["cost"], encoding="utf-8").read()
    path.write_text(text + "Equipment Rental,I1000,Rental,Invented crane,LS,1.00,fixed,1,,,,,\n",
                    encoding="utf-8")
    with pytest.raises(CostDbError, match="unknown cluster 'Equipment Rental'"):
        run_files(synthetic_paths["arch"], synthetic_paths["struct"], str(path), river_config)
    path.write_text(text + "Crane Rental,I1000,Rental,Invented crane,LS,1.00,fixed,1,,,,,\n",
                    encoding="utf-8")
    run = run_files(synthetic_paths["arch"], synthetic_paths["struct"], str(path), river_config)
    assert run.results[-1]["cluster"] == "Crane Rental"
