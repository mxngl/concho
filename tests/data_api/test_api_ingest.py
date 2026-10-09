"""P5.3: ingest of a team repo's results into SQLite, on INVENTED data (api_synthetic.py)."""

from __future__ import annotations

import json
import sqlite3

import api_synthetic as syn
import pytest

from engines.api import schema, summaries
from engines.api.ingest import IngestError, ingest_repo


@pytest.fixture
def repo(tmp_path):
    return syn.make_repo(tmp_path / "team")


def _db(result) -> sqlite3.Connection:
    return schema.connect(result["db"], readonly=True)


def test_tables_and_totals(repo):
    result = ingest_repo(repo)
    assert result["ingested"] == ["20270117T093000Z"] and result["latest"] == result["ingested"][0]
    conn = _db(result)
    assert {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")} >= set(
        schema.TABLES)
    snap = conn.execute("SELECT * FROM snapshots").fetchone()
    assert snap["tvd_grand_total"] == syn.GRAND_TOTAL and snap["tvd_target"] == syn.TARGET
    assert snap["project_name"] == "Demo Hall" and snap["stv_present"] == 1
    assert conn.execute("SELECT COUNT(*) FROM tvd_line_items").fetchone()[0] == 7
    assert conn.execute("SELECT SUM(total) FROM tvd_line_items").fetchone()[0] == syn.GRAND_TOTAL
    assert conn.execute("SELECT COUNT(*) FROM tvd_clusters").fetchone()[0] == 4
    assert conn.execute("SELECT COUNT(*) FROM stv_items").fetchone()[0] == 5
    carbon = conn.execute("SELECT * FROM stv_summary WHERE metric='carbon'").fetchone()
    assert carbon["project"] == pytest.approx(11300.0) and carbon["use_phase"] == 0.0
    item = conn.execute("SELECT * FROM stv_items WHERE material_type='Brick (sf)'").fetchone()
    assert item["unit"] == "sf" and item["carbon_per_unit"] == pytest.approx(8.0)


def test_elements_use_the_d15_rows(repo):
    conn = _db(ingest_repo(repo))
    # 17 rows in three exports; dropped: host of the Part (12), floor 5 in the architecture
    # export (structural owns Floors), plumbing fixture 9 in the architecture export (MEP owns).
    assert conn.execute("SELECT COUNT(*) FROM elements").fetchone()[0] == syn.ELEMENT_ROWS
    exports = {r["element_id"]: r["export"] for r in conn.execute("SELECT * FROM elements")}
    assert exports["5"].endswith("Structural_Schedule.csv")
    assert exports["9"].endswith("MEP_TakeOff.csv")
    assert "12" not in exports
    part = conn.execute("SELECT * FROM elements WHERE element_id='11'").fetchone()
    assert part["is_part"] == 1 and part["category"] == "Floors"  # Original Category
    assert conn.execute("SELECT dnc FROM elements WHERE element_id='8'").fetchone()[0] == 1
    # imperial length string of the MEP export is parsed by the shared tolerant parser
    pipe = conn.execute("SELECT length_lf FROM elements WHERE element_id='13'").fetchone()
    assert pipe[0] == 20.0


def test_quantity_summary_precomputed(repo):
    conn = _db(ingest_repo(repo))
    rows = {(r["category"], r["level"], r["ac"]): r for r in conn.execute(
        "SELECT * FROM quantity_summary")}
    assert rows[("Walls", "L1", "C1010")]["area_sf"] == 400.0  # the DNC wall (100 SF) is left out
    assert rows[("Floors", "L2", "B1010")]["area_sf"] == 500.0  # the Part counts, not its host
    assert rows[("Doors", "L1", "")]["elements"] == 1
    assert ("Furniture", "L1", "") in rows
    assert sum(r["elements"] for r in rows.values()) == syn.ELEMENT_ROWS - 1  # minus DNC


def test_data_quality(repo):
    conn = _db(ingest_repo(repo))
    q = {(r["scope"], r["metric"]): r for r in conn.execute("SELECT * FROM data_quality")}
    assert q[("tvd", "unmapped_elements")]["value"] == 1
    assert q[("tvd", "unmapped_elements")]["pct"] == 10.0  # 1 of 11 - 1 DNC
    assert q[("tvd", "unpriced_line_items")]["value"] == 1
    assert q[("stv", "mapped_elements")]["pct"] == 80.0
    assert q[("stv", "use_phase_modeled")]["value"] == 0
    assert q[("elements", "missing_assembly_code")]["value"] == 1  # the door
    assert json.loads(q[("elements", "missing_assembly_code")]["detail"])["top_categories"] == {
        "Doors": 1}
    assert q[("elements", "no_quantity")]["value"] == 1  # the plumbing fixture has no quantity


def test_ingest_is_incremental_and_force_replaces(repo):
    first = ingest_repo(repo)
    again = ingest_repo(repo)
    assert again["ingested"] == [] and again["existing"] == first["ingested"]
    syn.add_snapshot(repo, "20270201T080000Z", label="Second")
    third = ingest_repo(repo)
    assert third["ingested"] == ["20270201T080000Z"] and third["latest"] == "20270201T080000Z"
    forced = ingest_repo(repo, snapshot="20270117T093000Z", force=True)
    assert forced["ingested"] == ["20270117T093000Z"]
    conn = _db(forced)
    assert conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM tvd_line_items").fetchone()[0] == 14  # not doubled


def test_changed_exports_make_a_snapshot_stale(repo):
    ingest_repo(repo)
    path = repo / "exports" / "Demo_ARCH_Architecture_TakeOff.csv"
    path.write_text(path.read_text(encoding="utf-8")
                    + "99,Walls,Basic Wall,New,L1,,C1010,Partitions,1,1,1,1,1,x,,,\n",
                    encoding="utf-8")
    syn.add_snapshot(repo, "20270301T080000Z")  # same TVD numbers: its run saw other exports
    conn = _db(ingest_repo(repo))
    rows = {r["snapshot_id"]: r for r in conn.execute("SELECT * FROM snapshots")}
    assert rows["20270117T093000Z"]["elements_status"] == "loaded"  # ingested before the change
    assert rows["20270301T080000Z"]["elements_status"] == "stale"
    assert "changed after this snapshot" in rows["20270301T080000Z"]["elements_note"]
    assert conn.execute("SELECT COUNT(*) FROM elements WHERE snapshot_id='20270301T080000Z'"
                        ).fetchone()[0] == 0


def test_snapshot_without_stv_and_exports(repo):
    syn.add_snapshot(repo, "20270201T080000Z", stv=None, exports=[])
    conn = _db(ingest_repo(repo, snapshot="20270201T080000Z"))
    snap = conn.execute("SELECT * FROM snapshots").fetchone()
    assert snap["stv_present"] == 0 and snap["stv_carbon_life_cycle"] is None
    assert snap["elements_status"] == "no_exports"
    assert json.loads(snap["summary_json"])["carbon"]["available"] is False
    assert conn.execute("SELECT COUNT(*) FROM stv_items").fetchone()[0] == 0


def test_errors(tmp_path):
    with pytest.raises(IngestError, match="not found"):
        ingest_repo(tmp_path)
    repo = syn.make_repo(tmp_path / "t")
    with pytest.raises(IngestError, match="not in results"):
        ingest_repo(repo, snapshot="nope")
    (repo / "results" / "20270117T093000Z" / "tvd" / "tvd_results.json").unlink()
    with pytest.raises(IngestError, match="missing"):
        ingest_repo(repo)


def test_foreign_schema_version_is_refused(repo):
    result = ingest_repo(repo)
    conn = sqlite3.connect(result["db"])
    conn.execute("UPDATE meta SET value='999' WHERE key='schema_version'")
    conn.commit()
    conn.close()
    with pytest.raises(ValueError, match="schema version"):
        ingest_repo(repo)


# ---------------------------------------------------------------------------- summary size


def test_summary_json_stays_under_10_kb_even_for_big_projects(tmp_path):
    repo = tmp_path / "big"
    syn.write_exports(repo)
    # 300 line items in one cluster... and 400 STV items over 7 assemblies
    syn.add_snapshot(repo, "20270117T093000Z", tvd=syn.big_tvd(300), stv=syn.big_stv(400))
    conn = _db(ingest_repo(repo))
    text = conn.execute("SELECT summary_json FROM snapshots").fetchone()[0]
    assert len(text.encode()) < summaries.MAX_BYTES
    summary = json.loads(text)
    assert summary["cost"]["grand_total"] > 0 and summary["carbon"]["life_cycle"] > 0


def test_summary_is_trimmed_when_lists_are_long():
    clusters = [("s", f"Cluster {i:03d} " + "x" * 40, 1000.0 + i, 900.0, 100.0, 5.0, 1.0, 0.01, 3)
                for i in range(400)]
    items = [("s", i, f"Assembly {i:03d} " + "y" * 40, "m", "sf", 1.0, 100.0 + i)
             for i in range(400)]
    qsum = [("s", f"Cat {i:03d} " + "z" * 30, f"Level {i:03d}", "B1010", 1, 1.0, 1.0, 1.0)
            for i in range(400)]
    out = summaries.build("s", {"timestamp": "t"}, syn.tvd_payload(), syn.stv_payload(), clusters,
                          items, qsum, [], "loaded")
    size = len(json.dumps(out, separators=(",", ":")).encode())
    assert size < summaries.MAX_BYTES
    assert out["cost"]["clusters"][0][1] >= out["cost"]["clusters"][-1][1]  # largest kept
