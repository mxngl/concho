"""P5.3/P5.4 on the Island 2026 reference fixtures: the totals the API serves must be the
engine results (TVD 16,081,484.40; STV 2,517,183.14 kgCO2e per trade, 2,459,374.64 in one run).

Skipped unless the fixtures are present (``CONCHO_FIXTURES_DIR``, ``python
scripts/fetch_fixtures.py``). Nothing from the fixtures is copied into this repo; the team
repo below lives in a temporary folder. Two snapshots, as a team would have them:

- A: TVD (default parser) + the stored per-trade STV project result of the Island reference;
- B: TVD + one ``concho-stv`` call over the six Current exports (D15 deduplication).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402
from migrate_cost_data import migrate  # noqa: E402

from engines.api.app import create_app  # noqa: E402
from engines.api.ingest import ingest_repo  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
ISLAND_CONFIG = REPO_ROOT / "engines" / "common" / "examples" / "island_2026.project_config.json"
ISLAND_MAPPING = REPO_ROOT / "engines" / "stv" / "examples" / "island" / "stv_mapping.csv"
TOKEN = "island-test-token"

TVD_GRAND_TOTAL = 16_081_484.40  # default (tolerant) parser, docs/engines/tvd.md
STV_PER_TRADE = 2_517_183.14  # kgCO2e, per-trade reference (roadmap §1)
STV_ONE_RUN = 2_459_374.640652  # one run of the six Current exports (D15)
SCHEDULES = "revit_schedules/Current"
WORKBOOK = "STV_Template/STV_ConceptA_Bambo.xlsx"
EXPECTED_PROJECT = "outputs/Current-20260515T191939Z-3-001/Current/project/stv_results.json"
STV_EXPORTS = {
    "--architecture-schedule": ["04_Island_ARCH_Concept2_Architecture_TakeOff.csv",
                                "STR_Wall_Bamboo_Concept2_amd03_Architecture_TakeOff.csv"],
    "--mep-schedule": ["01_Island_MEP_Concept2_MEP_TakeOff.csv",
                       "04_Island_ARCH_Concept2_MEP_TakeOff.csv"],
    "--structural-schedule": ["04_Island_ARCH_Concept2_Structural_Schedule.csv",
                              "STR_Wall_Bamboo_Concept2_amd03_Structural_Schedule.csv"],
}
SNAP_A, SNAP_B = "20260515T191939Z", "20260601T080000Z"


def _run(cmd: list[str], cwd: Path) -> None:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.fixture(scope="module")
def island(tmp_path_factory, autotvd_dir, autostv_dir, ipd_challenge_dir) -> TestClient:
    repo = tmp_path_factory.mktemp("island_team")
    # exports/: the AutoTVD takeoffs under the add-in's file names
    exports = repo / "exports"
    exports.mkdir()
    (exports / "Island_Architecture_TakeOff.csv").write_bytes(
        (autotvd_dir / "qto" / "Architecture_TakeOff.csv").read_bytes())
    (exports / "Island_Structural_Schedule.csv").write_bytes(
        (autotvd_dir / "qto" / "Structural_Schedule.csv").read_bytes())

    # TVD with the engine default parser, cost DB converted into the temp folder only
    work = tmp_path_factory.mktemp("island_tvd")
    cost_db = work / "cost_db.csv"
    migration, db = migrate(autotvd_dir / "cost_data.csv", cost_db,
                            custom_clusters=["Equipment Rental"])
    assert db is not None and db.ok, migration.errors
    _run([sys.executable, "-m", "engines.tvd", "--ci", "--arch",
          str(exports / "Island_Architecture_TakeOff.csv"), "--struct",
          str(exports / "Island_Structural_Schedule.csv"), "--cost", str(cost_db),
          "--config", str(ISLAND_CONFIG), "--out", str(work)], work)
    tvd = json.loads((work / "results" / "latest.json").read_text(encoding="utf-8"))

    # STV: B = one run over the six Current exports; A = the stored per-trade project result
    stv_out = tmp_path_factory.mktemp("island_stv")
    cmd = [sys.executable, "-m", "engines.stv.cli", "--config", str(ISLAND_CONFIG),
           "--template", str(ipd_challenge_dir / WORKBOOK), "--output-dir", str(stv_out)]
    for flag, files in STV_EXPORTS.items():
        cmd += [flag, *(str(ipd_challenge_dir / SCHEDULES / f) for f in files)]
    _run(cmd, stv_out)
    stv_one_run = json.loads((stv_out / "stv_results.json").read_text(encoding="utf-8"))
    stv_per_trade = json.loads((autostv_dir / EXPECTED_PROJECT).read_text(encoding="utf-8"))

    entries = []
    for sid, stv, label in ((SNAP_A, stv_per_trade, "per trade"), (SNAP_B, stv_one_run, "one run")):
        run = repo / "results" / sid
        (run / "tvd").mkdir(parents=True)
        (run / "stv").mkdir()
        (run / "tvd" / "tvd_results.json").write_text(json.dumps(tvd), encoding="utf-8")
        (run / "stv" / "stv_results.json").write_text(json.dumps(stv), encoding="utf-8")
        entries.append({
            "id": sid, "timestamp": f"{sid[:4]}-{sid[4:6]}-{sid[6:8]}T08:00:00Z",
            "commit": "b" * 40, "label": label, "label_source": "manual",
            "exports": ["exports/Island_Architecture_TakeOff.csv",
                        "exports/Island_Structural_Schedule.csv"],
            "paths": {"tvd_results": f"results/{sid}/tvd/tvd_results.json",
                      "tvd_dashboard": None, "stv_results": f"results/{sid}/stv/stv_results.json"},
            "tvd": {}, "stv": {}, "stv_note": None})
    (repo / "results" / "index.json").write_text(
        json.dumps({"schema": 1, "latest": SNAP_B, "snapshots": entries}), encoding="utf-8")

    result = ingest_repo(repo)
    app = create_app(result["db"], TOKEN, enable_sql=True)
    client = TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"})
    client.tvd_results = tvd  # type: ignore[attr-defined]
    return client


def test_tvd_total_is_the_engine_result(island):
    body = island.get("/cost/summary").json()
    assert body["grand_total"] == pytest.approx(TVD_GRAND_TOTAL, abs=0.005)
    assert body["snapshot"]["id"] == SNAP_B and body["currency"] == "USD"
    clusters = sum(r["estimate"] for r in body["rows"])
    assert clusters == pytest.approx(TVD_GRAND_TOTAL, abs=0.5)  # per-cluster values are rounded
    # the line items of the database add up to the same total
    total = island.post("/sql", json={"query": "SELECT ROUND(SUM(total), 2) FROM tvd_line_items "
                                                f"WHERE snapshot_id = '{SNAP_B}'"}).json()
    assert total["rows"][0][0] == pytest.approx(TVD_GRAND_TOTAL, abs=0.5)


def test_stv_per_trade_and_one_run(island):
    a = island.get("/carbon/summary", params={"snapshot": SNAP_A}).json()
    b = island.get("/carbon/summary").json()
    assert a["metrics"]["carbon"]["life_cycle"] == pytest.approx(STV_PER_TRADE, rel=1e-6)
    assert b["metrics"]["carbon"]["life_cycle"] == pytest.approx(STV_ONE_RUN, rel=1e-6)
    assert a["snapshot"]["id"] == SNAP_A and b["snapshot"]["id"] == SNAP_B
    cmp = island.get("/compare", params={"a": SNAP_A, "b": SNAP_B}).json()
    assert cmp["carbon"]["change"] == pytest.approx(STV_ONE_RUN - STV_PER_TRADE, abs=0.01)
    assert cmp["cost"]["change"] == 0


def test_elements_reproduce_the_tvd_run(island):
    tvd = island.tvd_results
    quality = {(r["scope"], r["metric"]): r for r in island.get("/quality").json()["rows"]}
    assert island.get("/quality").json()["elements_status"] == "loaded"
    counted = tvd["meta"]["total_elements"] - tvd["meta"]["dnc_count"]
    assert island.get("/elements/count").json()["count"] == counted
    assert quality[("elements", "missing_assembly_code")]["value"] == tvd["meta"]["unmapped_count"]
    assert quality[("tvd", "unmapped_elements")]["value"] == tvd["meta"]["unmapped_count"]


def test_island_answers_stay_under_the_caps(island):
    from engines.api import caps
    for url in ("/cost/summary", "/carbon/summary", "/quality", "/snapshots",
                "/elements/count"):
        body = island.get(url).json()
        assert "error" not in body, (url, body)
        assert caps.count_rows(body) <= caps.MAX_ROWS
        assert caps.estimate_tokens(body) <= caps.MAX_TOKENS
    # whatever the size of the answer, it is within the caps or the documented error
    for url in ("/quantities", "/carbon", "/cost", "/cost?cluster=Shell"):
        body = island.get(url).json()
        assert body.get("error") in (None, "too_many_results"), (url, body)
        assert caps.count_rows(body) <= caps.MAX_ROWS
        assert caps.estimate_tokens(body) <= caps.MAX_TOKENS
