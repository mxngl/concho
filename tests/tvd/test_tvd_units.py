"""Unit tests for the TVD engine on the invented fixture in tests/fixtures/tvd_synthetic."""

import json

import pytest

from engines.tvd import alert
from engines.tvd.cli import main
from engines.tvd.cost_db import CostDbRow, cost_db_from_dicts, load_cost_db
from engines.tvd.engine import run_files
from engines.tvd.history import load_history, save_snapshot
from engines.tvd.loading import load_csv_file, merge_takeoffs, parse_qty_str
from engines.tvd.quantities import aggregate_quantities, calculate_costs, pick_quantity


@pytest.fixture
def run(synthetic_paths, island_config):
    return run_files(synthetic_paths["arch"], synthetic_paths["struct"], synthetic_paths["cost"],
                     island_config)


@pytest.fixture
def items(run):
    return {r["ac"]: r for r in run.results}


# ── parsing ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("val, expected", [
    ("6590 SF", 6590.0),
    ("1,000 SF", 1000.0),
    ("42.75 CF", 42.75),
    ("10' - 6\"", 10.5),
    ("", 0.0),
])
def test_parse_qty_str(val, expected):
    assert parse_qty_str(val) == expected


def test_bom_is_stripped(synthetic_paths):
    rows = load_csv_file(synthetic_paths["arch"])
    assert "ElementId" in rows[0]


def test_cost_db_parsing(synthetic_paths):
    db = load_cost_db(synthetic_paths["cost"])
    assert len(db.lines) == 17  # comment line skipped
    by_ac = {line.code: line for line in db.lines}
    assert by_ac["B2010.CW"].unit_cost == 1200.50
    assert by_ac["B1020"].quantity_value == 500.0
    assert by_ac["B1010"].unit_cost is None
    assert by_ac["A1030"].description == "Invented slab"
    assert by_ac["A1030"].unit == "SF"
    assert by_ac["A1030"].row == 4  # file row (comment = 1, header = 2)


# ── dedup ────────────────────────────────────────────────────────────────────

def test_merge_takeoffs_dedups_struct_wins(synthetic_paths):
    arch = load_csv_file(synthetic_paths["arch"])
    struct = load_csv_file(synthetic_paths["struct"])
    merged = merge_takeoffs(arch, struct)
    assert len(merged) == len(arch) + len(struct) - 1
    (row,) = [r for r in merged if r["ElementId"] == "1020"]
    assert row["Area"] == "80 SF"


def test_run_counts(run):
    assert run.total_elements == 20
    assert run.duplicates_removed == 1
    assert run.dnc_count == 2          # Mark "DNC" and Comments "... dnc"
    assert run.unmapped_count == 2     # the Furniture row without AC is excluded
    assert {r["ElementId"] for r in run.unmapped_rows} == {"1015", "1016"}


# ── quantity rules ───────────────────────────────────────────────────────────

def test_fixed_quantity(items):
    assert items["B1020"]["qty"] == 500 and items["B1020"]["qty_src"] == "Fixed"
    assert items["H4000"]["total"] == 12345.67
    assert items["D5010"]["total"] == 2000.0  # fixed qty in a non-takeoff cluster


def test_toilet_count_includes_excluded_categories(items):
    # One D2010 in Plumbing Fixtures, one in Furniture (excluded from quantities).
    assert items["C1030"]["qty"] == 2
    assert items["C1030"]["qty_src"] == "Count of codes (D2010)"
    assert items["C1030"]["total"] == 2000.0


def test_quantity_mirrors(items):
    assert items["C3010"]["qty"] == 280            # mirrors C1010 area (200 + 80)
    assert items["C3010"]["qty_src"] == "Mirror: C1010 area"
    assert items["B3010"]["qty"] == 500            # source B1020 only has a fixed qty
    assert items["B3010"]["qty_src"] == "Mirror: B1020 (Fixed)"
    assert items["C3020"]["qty"] == 0
    assert items["C3020"]["qty_src"] == "Mirror source B1010 not in takeoff"
    assert items["C3020"]["notes"] == ""


@pytest.mark.parametrize("ac, qty, src, total", [
    ("A1030", 1100, "Area (SF)", 11000.0),
    ("A1010", 2, "Volume (CY)", 200.0),
    ("C2010", 12.5, "Length (LF)", 500.0),
    ("C1020", 2, "Count (EA)", 1600.0),
    ("C1010", 280, "Area (SF)", 4200.0),
])
def test_takeoff_lookup(items, ac, qty, src, total):
    assert (items[ac]["qty"], items[ac]["qty_src"], items[ac]["total"]) == (qty, src, total)


def test_takeoff_lookup_units():
    q = {"B1010": {"area_sf": 2000.0, "length_lf": 0.0, "volume_cf": 54.0, "count": 3}}

    def line(unit):
        return CostDbRow(cluster="Shell", assembly_code="B1010", unit=unit,
                         quantity_rule="takeoff")

    assert pick_quantity(line("MSF"), q, {}) == (2.0, "Area/1000 (MSF)")
    assert pick_quantity(line("CF"), q, {}) == (54.0, "Volume (CF)")
    assert pick_quantity(line("Flight"), q, {}) == (3.0, "Count (EA)")
    assert pick_quantity(line("LS"), q, {}) == (0.0, "Unknown unit: LS")


def test_keyword_split(items):
    assert items["B2010.CW"]["qty"] == 200     # "curtain wall" family + "glazing" type
    assert items["B2010.PW"]["qty"] == 300     # fallback
    assert items["B2010.CW"]["total"] == 240100.0


def test_dnc_elements_are_not_counted(items):
    assert items["C1010"]["qty"] == 280  # 999 SF (DNC mark) and 888 SF (dnc comment) skipped


def test_excluded_categories():
    rows = [
        {"ElementId": "1", "Category": "Furniture", "Assembly Code": "E2010", "Area": "20 SF"},
        {"ElementId": "2", "Category": "Furniture", "Assembly Code": ""},
    ]
    code_qtys, unmapped, all_counts, _, _ = aggregate_quantities(rows, {"Furniture"})
    assert code_qtys == {} and unmapped == 0 and all_counts == {"E2010": 1}


def test_non_takeoff_cluster_without_fixed_qty(items):
    assert items["D2010"]["qty"] == 0
    assert items["D2010"]["qty_src"] == "Fixed (no quantity set)"


def test_notes(items):
    assert items["A2020"]["qty_src"] == "No takeoff match"
    assert items["A2020"]["notes"] == "Zero qty from takeoff | AC not in takeoff"
    assert items["B1010"]["notes"] == "No unit cost | Zero qty from takeoff | AC not in takeoff"


def test_rules_come_from_the_cost_db():
    db = cost_db_from_dicts([{"cluster": "Interiors", "assembly_code": "C1030",
                              "description": "x", "unit": "EA", "unit_cost": "10",
                              "quantity_rule": "count_codes:D2010,E2010"}])
    (row,) = calculate_costs(db.lines, {}, {"D2010": 3, "E2010": 1, "C1010": 7})
    assert row["qty"] == 4 and row["total"] == 40.0
    assert row["qty_src"] == "Count of codes (D2010, E2010)"


# ── summary + results JSON ───────────────────────────────────────────────────

def test_cluster_summary_and_payload(run):
    summary = {r["cluster"]: r["total"] for r in run.summary}
    assert list(summary) == [
        "Substructure", "Shell", "Interiors", "Services", "General Conditions", "GRAND TOTAL",
    ]
    assert summary["Shell"] == pytest.approx(272675.0)
    assert summary["GRAND TOTAL"] == pytest.approx(307080.67)

    payload = run.results_payload()
    assert set(payload) == {
        "meta", "financials", "cluster_targets", "cluster_summary", "target_derivation",
        "target_consistency", "cost_db_validation", "reliability", "line_items",
    }
    assert list(payload)[-3:] == ["cost_db_validation", "reliability", "line_items"]
    assert payload["cost_db_validation"]["error_count"] == 0
    assert payload["cost_db_validation"]["unpriced"] == [
        {"row": 6, "cluster": "Shell", "assembly_code": "B1010"}
    ]
    fin = payload["financials"]
    assert fin["grand_total"] == 307080.67
    assert fin["status"] == "under_target"
    assert fin["cost_per_sf"] == round(307080.67 / 30_000, 2)
    assert payload["meta"]["unmapped_count"] == 2
    assert payload["meta"]["dnc_count"] == 2
    assert "Special Construction" in payload["cluster_targets"]
    assert payload["meta"]["project_name"] == "Island 2026 university building"
    shell = next(c for c in payload["cluster_summary"] if c["cluster"] == "Shell")
    assert shell["target"] == 3_826_446
    assert [li["ac"] for li in payload["line_items"]["Interiors"]][:2] == ["C1010", "C1020"]


def test_data_source_has_no_absolute_paths(run):
    labels = run.source.removeprefix("Custom files — ").split(", ")
    assert [lbl.split("=")[0] for lbl in labels] == ["arch", "struct", "cost"]
    for lbl in labels:
        path = lbl.split("=", 1)[1]
        assert not path.startswith("/") and ":" not in path and "\\" not in path


# ── history ──────────────────────────────────────────────────────────────────

def test_history_roundtrip(tmp_path, run):
    path = save_snapshot(str(tmp_path), "Scheme A – Week 12", run.results, run.summary, 2)
    assert path.endswith("_scheme_a_week_12.json")
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    (tmp_path / "other.json").write_text("{}", encoding="utf-8")
    versions = load_history(str(tmp_path))
    assert [v["label"] for v in versions] == ["Scheme A – Week 12"]
    assert load_history(str(tmp_path / "missing")) == []


# ── budget alert ─────────────────────────────────────────────────────────────

def test_alert_disabled_without_url(monkeypatch):
    monkeypatch.delenv("CONCHO_ALERT_WEBHOOK_URL", raising=False)
    monkeypatch.setattr(alert.urllib.request, "urlopen", pytest.fail)
    alert.fire_budget_webhook([], 2.0, 1.0)


def test_alert_posts_with_token(monkeypatch):
    sent = {}

    class Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(req, timeout):
        sent["url"] = req.full_url
        sent["headers"] = dict(req.header_items())
        sent["body"] = json.loads(req.data)
        return Resp()

    monkeypatch.setenv("CONCHO_ALERT_WEBHOOK_URL", "https://example.invalid/hook")
    monkeypatch.setenv("CONCHO_ALERT_WEBHOOK_TOKEN", "secret")
    monkeypatch.delenv("CONCHO_ALERT_WEBHOOK_HEADER", raising=False)
    monkeypatch.setattr(alert.urllib.request, "urlopen", fake_urlopen)
    alert.fire_budget_webhook([{"cluster": "Shell", "total": 3.0}], 3.0, 2.0)
    assert sent["url"] == "https://example.invalid/hook"
    assert sent["headers"]["X-concho-token"] == "secret"
    assert sent["body"]["event"] == "budget_overrun"
    assert sent["body"]["delta"] == 1.0


# ── CLI ──────────────────────────────────────────────────────────────────────

def test_cli_ci_mode(tmp_path, synthetic_paths, monkeypatch):
    monkeypatch.delenv("CONCHO_ALERT_WEBHOOK_URL", raising=False)
    out = tmp_path / "out"
    rc = main([
        "--ci", "--snapshot", "Week 1",
        "--arch", synthetic_paths["arch"],
        "--struct", synthetic_paths["struct"],
        "--cost", synthetic_paths["cost"],
        "--config", synthetic_paths["config"],
        "--out", str(out),
    ])
    assert rc == 0
    latest = json.loads((out / "results" / "latest.json").read_text(encoding="utf-8"))
    assert latest["financials"]["grand_total"] == 307080.67
    assert len(list((out / "results").glob("*.json"))) == 2
    assert len(list((out / "history").glob("*_week_1.json"))) == 1
    html = (out / "docs" / "index.html").read_text(encoding="utf-8")
    assert html.startswith("<!DOCTYPE html>") or "<html" in html[:500]


def test_cli_requires_inputs(capsys):
    with pytest.raises(SystemExit):
        main(["--out", "x"])
