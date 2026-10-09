"""Equivalence test: new engine vs. the original AutoTVD ``tvd_analysis.py``.

Uses the AutoTVD checkout from ``AUTOTVD_DIR`` if set, else ``AutoTVD`` in the shared
fixture root (``CONCHO_FIXTURES_DIR`` or ``.fixtures/``, see ``tests/conftest.py`` and
``scripts/fetch_fixtures.py``); skipped if neither exists. Nothing from that checkout is
copied into this repo: ``cost_data.csv`` is RSMeans-derived.

Both implementations run in CI mode on ``AUTOTVD_DIR/qto/*.csv`` inside ``tmp_path``; the
original reads ``AUTOTVD_DIR/cost_data.csv``, the new engine (P3.4) the same file converted
to ``cost_db.csv`` by ``scripts/migrate_cost_data.py`` into ``tmp_path`` (never committed:
RSMeans-derived). The new engine reads the project values from the Island example config
(``engines/common/examples/island_2026.project_config.json``).
Compared: the results JSON (all fields except run timestamps, run label, input paths, the
project/team names added in P3.2, the ``target_consistency`` block added in P3.3, the
``cost_db_validation`` block added in P3.4, the ``target_derivation``, ``reliability`` and
``tracking`` blocks added in P3.5 and the ``deduplication`` block added in P3.9; each new block
has its own Island test below), the
history snapshot (except its date) and the dashboard HTML (with timestamps and data source
masked).

P3.11: the new engine runs with the hidden flag ``--legacy-length-parsing`` (AutoTVD's quantity
parser, which reads ``9' - 7 3/4"`` as 9 ft), so this test still proves the byte-identical
migration. The engine default is the tolerant parser (``engines/common/quantities.py``); its
Island run is pinned separately in ``test_island_corrected_golden`` (the submitted Island value
16,065,644.29 is now the *legacy* reference).

Intended differences since P3.2, normalised/masked here:

- the cluster name "Special Contruction" (typo in the AutoTVD cost DB, kept by the original)
  is "Special Construction" in the new engine; the original outputs are normalised to it;
- the dashboard takes the team name and the gross floor area from the config instead of
  hardcoded strings: the team name is masked in both HTML files, and the GSF expressions in
  the PDF export (``30000`` / ``30,000 GSF`` in the original, ``GROSS_SF_JS`` in the new
  renderer) are masked.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from migrate_cost_data import migrate

SNAPSHOT_LABEL = "Equivalence check"
REPO_ROOT = Path(__file__).resolve().parents[2]
ISLAND_CONFIG = REPO_ROOT / "engines" / "common" / "examples" / "island_2026.project_config.json"
TEAM_NAME = "Island Team 2026"  # project.team_name in ISLAND_CONFIG

# P3.2: canonical cluster name (the original keeps the cost DB typo).
LEGACY_NAME, CANONICAL_NAME = "Special Contruction", "Special Construction"

# P3.2: GSF expressions of the PDF export, hardcoded in the original.
_GSF_MASKS = {
    "sub: '30,000 GSF',     col: cMuted": "sub: <gsf>, col: cMuted",
    "sub: GROSS_SF_JS.toLocaleString('en-US') + ' GSF', col: cMuted": "sub: <gsf>, col: cMuted",
    "Math.round(grandTotal / 30000)": "Math.round(grandTotal / <gsf>)",
    "Math.round(grandTotal / GROSS_SF_JS)": "Math.round(grandTotal / <gsf>)",
}

# sha256 of the Island reference inputs (docs/ROADMAP.md §1, P0.4).
REFERENCE_SHA256 = {
    "cost_data.csv": "65538af77d051625c493995246e69f51a3203b0278940491bdef57eda92d6358",
    "qto/Architecture_TakeOff.csv":
        "67ea680db1f30cfde05b677658b471ca6e06fe2370e117e027789bb43f35a9d6",
    "qto/Structural_Schedule.csv":
        "1583cfe473d9142cbec67e7e78639874181ac2e26ae1349aabadfb3dc55fa641",
}

# Masks for values that legitimately differ between two runs.
_TS = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}")


def _inputs(base: Path) -> dict[str, Path]:
    return {
        "arch": base / "qto" / "Architecture_TakeOff.csv",
        "struct": base / "qto" / "Structural_Schedule.csv",
        "cost": base / "cost_data.csv",
    }


def _env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("CONCHO_ALERT_")}
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _run(cmd: list[str], cwd: Path) -> None:
    proc = subprocess.run(cmd, cwd=cwd, env=_env(), capture_output=True, text=True,
                          encoding="utf-8")
    assert proc.returncode == 0, proc.stdout + proc.stderr


def _canonical(obj):
    """Replace the legacy cluster name in all keys and string values (original outputs)."""
    text = json.dumps(obj, ensure_ascii=False).replace(LEGACY_NAME, CANONICAL_NAME)
    return json.loads(text)


def _strip_meta(payload: dict) -> dict:
    payload = json.loads(json.dumps(payload))
    # P3.5: new block, not in the original; tested in test_island_target_derivation.
    payload.pop("target_derivation", None)
    # P3.5: new blocks, not in the original; tested in test_island_reliability and
    # test_island_tracking.
    payload.pop("reliability", None)
    payload.pop("tracking", None)
    # P3.3: new block, not in the original; tested in test_island_target_consistency.
    payload.pop("target_consistency", None)
    # P3.4: new block, not in the original; tested in test_island_cost_db_validation.
    payload.pop("cost_db_validation", None)
    # P3.11: new block, not in the original; tested in test_island_legacy_parser_block.
    payload.pop("quantity_parse_warnings", None)
    # P3.9: new block, not in the original; tested in test_island_deduplication.
    payload.pop("deduplication", None)
    # P7 follow-up: new block, not in the original; tested in test_island_unmapped_rows.
    payload.pop("unmapped_rows", None)
    for key in ("generated_at", "date", "label", "data_source", "project_name", "team_name"):
        payload["meta"].pop(key, None)
    return payload


def _single(folder: Path, pattern: str) -> Path:
    (path,) = folder.glob(pattern)
    return path


@pytest.fixture(scope="module")
def outputs(tmp_path_factory, autotvd_dir) -> dict[str, Path]:
    # autotvd_dir is absolute: both implementations run as subprocesses in tmp folders.
    base = autotvd_dir
    inputs = _inputs(base)
    flags = ["--arch", str(inputs["arch"]), "--struct", str(inputs["struct"]),
             "--cost", str(inputs["cost"])]

    # Original: a copy of tvd_analysis.py writes next to itself (results/, history/, docs/).
    orig = tmp_path_factory.mktemp("orig")
    shutil.copy(base / "tvd_analysis.py", orig / "tvd_analysis.py")
    _run([sys.executable, "tvd_analysis.py", "--ci", "--snapshot", SNAPSHOT_LABEL, *flags], orig)

    # P3.4: the new engine reads the converted cost DB (tmp only, never committed).
    new = tmp_path_factory.mktemp("new")
    cost_db = new / "cost_db.csv"
    migration, db = migrate(inputs["cost"], cost_db, custom_clusters=["Equipment Rental"])
    assert db is not None and db.ok, migration.errors + (db.errors if db else [])
    flags[flags.index("--cost") + 1] = str(cost_db)
    _run([sys.executable, "-m", "engines.tvd", "--ci", "--snapshot", SNAPSHOT_LABEL, *flags,
          "--config", str(ISLAND_CONFIG), "--out", str(new), "--legacy-length-parsing"], new)

    # P3.11: the engine default (tolerant parser) on the same inputs.
    corrected = tmp_path_factory.mktemp("corrected")
    _run([sys.executable, "-m", "engines.tvd", "--ci", *flags,
          "--config", str(ISLAND_CONFIG), "--out", str(corrected)], corrected)
    return {"orig": orig, "new": new, "corrected": corrected}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_results_json_identical(outputs):
    orig = _load(outputs["orig"] / "results" / "latest.json")
    new = _load(outputs["new"] / "results" / "latest.json")
    assert _strip_meta(new) == _canonical(_strip_meta(orig))
    assert new["meta"]["project_name"] == "Island 2026 university building"
    assert new["meta"]["team_name"] == TEAM_NAME
    # The timestamped copy equals latest.json in both implementations.
    new_ts = _single(outputs["new"] / "results", "2*.json")
    assert _load(new_ts) == new


def test_history_snapshot_identical(outputs):
    orig = _load(_single(outputs["orig"] / "history", "*_equivalence_check.json"))
    new = _load(_single(outputs["new"] / "history", "*_equivalence_check.json"))
    orig.pop("date")
    new.pop("date")
    assert new == _canonical(orig)


def test_dashboard_html_identical(outputs):
    def normalise(folder: Path) -> str:
        html = (folder / "docs" / "index.html").read_text(encoding="utf-8")
        source = _load(folder / "results" / "latest.json")["meta"]["data_source"]
        html = html.replace(source, "<source>").replace(LEGACY_NAME, CANONICAL_NAME)
        html = html.replace("cl-special-contruction", "cl-special-construction")  # anchor id
        html = html.replace(TEAM_NAME, "<team>")
        for old, mask in _GSF_MASKS.items():
            html = html.replace(old, mask)
        return _TS.sub("<ts>", html)

    new_html = (outputs["new"] / "docs" / "index.html").read_text(encoding="utf-8")
    assert "grandTotal / 30000" not in new_html  # GSF only via GROSS_SF_JS (from config)
    assert "'30,000 GSF'" not in new_html
    assert normalise(outputs["new"]) == normalise(outputs["orig"])


def _skip_unless_reference_inputs(base: Path) -> None:
    for rel, digest in REFERENCE_SHA256.items():
        if hashlib.sha256((base / rel).read_bytes()).hexdigest() != digest:
            pytest.skip(f"{rel} differs from the island-2026-final reference input")


def test_island_golden_numbers(outputs, autotvd_dir):
    """Legacy reference: the submitted Island value (AutoTVD parser, P3.11)."""
    _skip_unless_reference_inputs(autotvd_dir)
    new = _load(outputs["new"] / "results" / "latest.json")
    assert new["financials"]["grand_total"] == 16_065_644.29
    assert new["meta"]["unmapped_count"] == 1693
    assert new["meta"]["dnc_count"] == 75


# P3.3: A-H 16,705,852 vs. 16,700,000 (+5,852, within 0.1 %); Equipment Rental on top.
ISLAND_TARGET_CONSISTENCY = {
    "total_target": 16_700_000,
    "sum_a_to_h": 16_705_852,
    "sum_carved_out": 0,
    "sum_on_top": 400_000,
    "gap": 5_852,
    "gap_pct": 0.035,
    "gap_incl_on_top": 405_852,
    "tolerance": 0.001,
    "tolerance_amount": 16_700,
    "status": "within_tolerance",
    "override_reason": None,
    "carved_out_clusters": {},
    "on_top_clusters": {"Equipment Rental": 400_000},
}


def test_island_target_consistency(outputs):
    new = _load(outputs["new"] / "results" / "latest.json")
    assert new["target_consistency"] == ISLAND_TARGET_CONSISTENCY
    orig = _load(outputs["orig"] / "results" / "latest.json")
    assert "target_consistency" not in orig


# P3.4: the converted Island cost DB validates with 0 errors; the placeholder rows are
# listed as unpriced, the D5030/D5090 mislabels as warnings (codes kept).
def test_island_cost_db_validation(outputs):
    block = _load(outputs["new"] / "results" / "latest.json")["cost_db_validation"]
    assert block["error_count"] == 0 and block["status"] == "warnings"
    assert block["rows"] == 48
    assert block["not_rated"] == {"qty_reliability": 48, "cost_reliability": 48}
    assert [(u["cluster"], u["assembly_code"]) for u in block["unpriced"]] == [
        ("Substructure", "A1020"), ("Interiors", "C3030"), ("Special Construction", "F1000"),
    ]
    warnings = "\n".join(block["warnings"])
    assert "(D5030): description: 'Fire Protection Systems' suggests D40" in warnings
    assert "(D5090): description: 'HVAC Systems' suggests D30" in warnings
    assert "cluster 'Equipment Rental' is a custom cluster" in warnings
    assert block["warning_count"] == len(block["warnings"]) == 8


# P3.5: explicit amount split, no budget (total_target); the shares of the 16.7M total sum
# to 1.00035 (the 5,852 gap above).
def test_island_target_derivation(outputs):
    block = _load(outputs["new"] / "results" / "latest.json")["target_derivation"]
    assert block["method"] == "explicit" and block["budget"] is None
    assert block["target_above_budget"] is None and block["warnings"] == []
    assert block["total_target"] == block["course_cluster_base"] == 16_700_000
    targets = {x: c["target"] for x, c in block["clusters"].items()}
    assert targets == {"A": 1_781_276, "B": 3_826_446, "C": 2_005_842, "D": 4_041_448,
                       "E": 1_319_286, "F": 1_001_839, "G": 1_435_258, "H": 1_294_457}
    assert block["sums"]["target"] == 16_705_852
    assert block["sums"]["final_share"] == pytest.approx(16_705_852 / 16_700_000, abs=1e-9)
    assert "owner_share" not in block["clusters"]["A"]


# P3.5: the Island cost DB is not rated, so every $ is not_rated.
def test_island_reliability(outputs):
    new = _load(outputs["new"] / "results" / "latest.json")
    rel = new["reliability"]
    grand_total = new["financials"]["grand_total"]
    assert grand_total == 16_065_644.29
    for cat in ("quantity", "cost", "overall"):
        assert rel["totals"][cat] == {"high": 0, "medium": 0, "low": 0,
                                      "not_rated": grand_total}
    assert rel["totals"]["estimate"] == grand_total
    by_cluster = {r["cluster"]: r["estimate"] for r in new["cluster_summary"]}
    assert {n: c["estimate"] for n, c in rel["clusters"].items()} == by_cluster
    assert rel["totals_a_to_h"]["estimate"] == pytest.approx(
        grand_total - by_cluster["Equipment Rental"], abs=0.005)


# P3.5: the equivalence snapshot is the current run (no --event/--note given).
def test_island_tracking(outputs):
    new = _load(outputs["new"] / "results" / "latest.json")
    assert new["tracking"] == {
        "target": 16_700_000,
        "rows": [{
            "date": new["meta"]["date"], "label": SNAPSHOT_LABEL, "event": None, "note": None,
            "estimate": 16_065_644.29, "delta": 634_355.71, "current": True,
        }],
    }


# P3.11: the legacy run says so in its results JSON; AutoTVD's parser reports no issues.
def test_island_legacy_parser_block(outputs):
    new = _load(outputs["new"] / "results" / "latest.json")
    assert new["quantity_parse_warnings"] == {"parser": "legacy", "total": 0, "columns": {}}
    assert "quantity_parse_warnings" not in _load(outputs["orig"] / "results" / "latest.json")


# P3.11: Island with the tolerant parser (engine default). Only C1010 (interior partitions,
# priced per LF) changes: its length was read without the fractional inches. Before/after
# table: docs/engines/tvd.md, "Quantity parsing".
ISLAND_CORRECTED_CLUSTERS = {
    "Substructure": 466_690.00,
    "Shell": 4_430_372.01,
    "Interiors": 1_553_243.15,  # legacy 1,537,403.04
    "Services": 5_175_000.00,
    "Equipment and Furnishings": 234_080.72,
    "Special Construction": 217_825.00,
    "Building Sitework": 598_273.52,
    "General Conditions": 3_006_000.00,
    "Equipment Rental": 400_000.00,
}


def test_island_corrected_golden(outputs, autotvd_dir):
    _skip_unless_reference_inputs(autotvd_dir)
    corrected = _load(outputs["corrected"] / "results" / "latest.json")
    legacy = _load(outputs["new"] / "results" / "latest.json")
    assert corrected["financials"]["grand_total"] == 16_081_484.40
    assert corrected["meta"]["unmapped_count"] == 1693
    assert corrected["meta"]["dnc_count"] == 75
    assert {r["cluster"]: r["estimate"] for r in corrected["cluster_summary"]} == (
        ISLAND_CORRECTED_CLUSTERS)
    assert corrected["quantity_parse_warnings"] == {
        "parser": "tolerant", "total": 0, "columns": {}}

    # Exactly one line differs from the legacy run: C1010, 782.58 → 820.63 LF.
    changed = [
        (new_line["ac"], new_line["unit"], old_line["qty"], new_line["qty"])
        for cluster, lines in corrected["line_items"].items()
        for new_line, old_line in zip(lines, legacy["line_items"][cluster], strict=True)
        if new_line != old_line
    ]
    assert changed == [("C1010", "LF", 782.58, 820.63)]
    delta = corrected["financials"]["grand_total"] - legacy["financials"]["grand_total"]
    assert delta == pytest.approx(15_840.11, abs=0.005)


# P3.9 (D15): the AutoTVD reference exports share no ElementId and have no Parts, so the
# duplicate / Parts rule drops nothing (the old "structural always wins" merge didn't either);
# no legacy merge switch is needed. docs/engines/tvd.md, "Duplicates and Parts".
@pytest.mark.parametrize("run", ["new", "corrected"])
def test_island_deduplication(outputs, run):
    new = _load(outputs[run] / "results" / "latest.json")
    block = new["deduplication"]
    assert block["dropped"] == 0 and block["dropped_rows"] == []
    assert block["rows_in"] == block["rows_kept"] == new["meta"]["total_elements"] == 2608
    assert block["parts"] == {"rows": 0, "with_part_source_id": 0, "hosts": 0}
    assert [(e["discipline"], e["rows"]) for e in block["exports"]] == [
        ("architecture", 2321), ("structural", 287)]
    assert new["meta"]["duplicates_removed"] == 0


# P7 follow-up: the unmapped rows are listed (capped), the totals are unchanged.
@pytest.mark.parametrize("run", ["new", "corrected"])
def test_island_unmapped_rows(outputs, run):
    new = _load(outputs[run] / "results" / "latest.json")
    block = new["unmapped_rows"]
    assert block["total"] == new["meta"]["unmapped_count"]
    assert block["listed"] == len(block["rows"]) == min(block["total"], block["cap"])
    areas = [(r["area_sf"], r["volume_cf"], r["length_lf"]) for r in block["rows"]]
    assert areas == sorted(areas, reverse=True)
    assert {r["reason"] for r in block["rows"]} == {"no Assembly Code"}
