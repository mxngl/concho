"""P5.4: the data API on INVENTED data: endpoints, auth, snapshot naming, labels, what-if,
POST /sql, and the hard caps."""

from __future__ import annotations

import api_synthetic as syn
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from engines.api import caps  # noqa: E402
from engines.api.app import create_app  # noqa: E402
from engines.api.ingest import ingest_repo  # noqa: E402

TOKEN = "test-token-not-a-secret"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
SID = "20270117T093000Z"


def client_for(repo, *, enable_sql=False) -> TestClient:
    db = ingest_repo(repo)["db"]
    return TestClient(create_app(db, TOKEN, enable_sql=enable_sql), headers=AUTH)


@pytest.fixture
def repo(tmp_path):
    return syn.make_repo(tmp_path / "team")


@pytest.fixture
def api(repo):
    return client_for(repo)


# ---------------------------------------------------------------------------- auth


def test_auth_is_required(repo):
    db = ingest_repo(repo)["db"]
    anon = TestClient(create_app(db, TOKEN))
    assert anon.get("/health").json() == {"status": "ok"}
    for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": TOKEN},
                    {"Authorization": "Basic " + TOKEN}):
        response = anon.get("/cost/summary", headers=headers)
        assert response.status_code == 401 and response.json()["error"] == "unauthorized"


def test_no_token_no_app(repo, monkeypatch):
    db = ingest_repo(repo)["db"]
    monkeypatch.delenv("CONCHO_API_TOKEN", raising=False)
    with pytest.raises(ValueError, match="CONCHO_API_TOKEN"):
        create_app(db)
    monkeypatch.setenv("CONCHO_API_TOKEN", TOKEN)
    assert create_app(db)  # the token comes from the environment
    with pytest.raises(ValueError, match="not found"):
        create_app(db + ".missing", TOKEN)


# ---------------------------------------------------------------------------- cost


def test_cost_summary(api):
    body = api.get("/cost/summary").json()
    assert body["snapshot"]["id"] == SID and body["snapshot"]["label"] == "Run"
    assert body["grand_total"] == syn.GRAND_TOTAL and body["target"] == syn.TARGET
    assert body["status"] == "under_target" and body["currency"] == "USD"
    assert {r["cluster"] for r in body["rows"]} == set(syn.LINE_ITEMS)
    assert body["unmapped_elements"]["count"] == 1


def test_cost_filters(api):
    body = api.get("/cost", params={"cluster": "shell"}).json()  # case-insensitive
    assert body["matched_lines"] == 3 and body["matched_total"] == 63000.0
    assert body["rows"][0]["ac"] == "B3010"  # largest first
    body = api.get("/cost", params={"ac": "B2010"}).json()
    assert [r["desc"] for r in body["rows"]] == ["Facade"]
    # the course's 4-digit form of a level-2 code means the whole group
    assert api.get("/cost", params={"ac": "B2000"}).json()["matched_total"] == 12000.0
    assert api.get("/cost", params={"ac": "B"}).json()["matched_total"] == 63000.0
    both = api.get("/cost", params={"cluster": "Shell", "ac": "B30"}).json()
    assert both["matched_total"] == 30000.0
    unknown = api.get("/cost", params={"cluster": "Nope"})
    assert unknown.status_code == 404 and unknown.json()["error"] == "unknown_cluster"
    assert "Shell" in unknown.json()["clusters"]
    assert api.get("/cost", params={"ac": "Z9999"}).json()["error"] == "no_match"


def test_cost_what_if_roof_plus_10_percent(api):
    body = api.get("/cost/what_if", params={"ac": "B30", "change_pct": 10}).json()
    # roof 30,000 -> +3,000; the 10 % contingency follows the subtotal: 7,200 -> 7,500
    assert body["scenario"]["matched_lines"] == 1
    assert body["change"]["direct"] == 3000.0
    assert body["change"]["indirect_percent_lines"] == pytest.approx(300.0)
    assert body["grand_total_before"] == syn.GRAND_TOTAL
    assert body["grand_total_after"] == pytest.approx(syn.GRAND_TOTAL + 3300.0)
    assert body["delta_to_target_after"] == pytest.approx(syn.GRAND_TOTAL + 3300 - syn.TARGET)
    assert body["status_after"] == "over_target"  # 82,500 > 80,000
    assert "what_if" in body["labels"][0] and body["snapshot"]["id"] == SID
    changed = {r["cluster"]: r for r in body["rows"]}
    assert changed["Shell"]["after"] == pytest.approx(66000.0)
    assert changed["General Conditions"]["change"] == pytest.approx(300.0)
    assert "Interiors" not in changed


def test_cost_what_if_negative_and_errors(api):
    body = api.get("/cost/what_if", params={"ac": "C1010", "change_pct": -50}).json()
    assert body["change"]["direct"] == -3000.0 and body["status_after"] == "under_target"
    assert api.get("/cost/what_if", params={"ac": "Z", "change_pct": 5}).status_code == 404
    bad = api.get("/cost/what_if", params={"ac": "B30", "change_pct": -150})
    assert bad.status_code == 422 and bad.json()["error"] == "bad_change_pct"
    missing = api.get("/cost/what_if", params={"ac": "B30"})
    assert missing.status_code == 422 and missing.json()["error"] == "bad_parameter"


# ---------------------------------------------------------------------------- carbon


def test_carbon_summary_labels_custom_and_proxy(api):
    body = api.get("/carbon/summary").json()
    assert body["snapshot"]["id"] == SID
    assert body["metrics"]["carbon"]["life_cycle"] == 11300.0
    assert body["metrics"]["carbon"]["percent_of_target"] == pytest.approx(0.226)
    assert body["use_phase_modeled"] is False and body["warnings"]
    text = " ".join(body["labels"])
    assert "custom_material" in text and "proxy" in text
    by_name = {r["stv_assembly"]: r for r in body["rows"]}
    assert by_name["Roof"]["proxy"] is True and by_name["Columns"]["custom_material"] is True
    assert by_name["Floor"]["custom_material"] is False
    assert body["units"]["energy"] == "MJ" and body["units"]["water"] == "kg"


def test_carbon_rows_are_labelled_per_row(api):
    body = api.get("/carbon", params={"stv_assembly": "columns"}).json()
    row = body["rows"][0]
    assert row["custom_material"] is True and row["custom_material_source"] == "invented EPD"
    assert any("custom_material" in label for label in body["labels"])
    assert not any("proxy" in label for label in body["labels"])
    body = api.get("/carbon", params={"material": "membrane"}).json()
    assert body["rows"][0]["proxy"] is True and any("proxy" in x for x in body["labels"])
    plain = api.get("/carbon", params={"stv_assembly": "Floor"}).json()
    assert "labels" not in plain and plain["matched_embodied_kgco2e"] == 7200.0
    assert api.get("/carbon", params={"material": "nothing"}).json()["error"] == "no_match"


def test_carbon_what_if(api):
    body = api.get("/carbon/what_if", params={
        "material_from": "Concrete (sf)", "material_to": "Timber (sf)"}).json()
    # 1,400 sf x 5.0 = 7,000 kgCO2e becomes 1,400 x 2.0 = 2,800
    assert body["embodied_before"] == 7000.0 and body["embodied_after"] == 2800.0
    assert body["change_kgco2e"] == -4200.0
    assert body["life_cycle_after"] == pytest.approx(11300.0 - 4200.0)
    assert body["percent_of_target_after"] == pytest.approx((11300.0 - 4200.0) / 50000.0, rel=1e-3)
    assert body["labels"][0].startswith("what_if") and body["snapshot"]["id"] == SID
    # `ac` is accepted as the STV assembly
    same = api.get("/carbon/what_if", params={
        "material_from": "Concrete (sf)", "material_to": "Timber (sf)", "ac": "Floor"}).json()
    assert same["change_kgco2e"] == -4200.0
    flagged = api.get("/carbon/what_if", params={
        "material_from": "Concrete (sf)", "material_to": "Bio Column (kg)"})
    assert flagged.status_code == 422 and flagged.json()["error"] == "unit_mismatch"
    to_custom = api.get("/carbon/what_if", params={
        "material_from": "Bio Column (kg)", "material_to": "Bio Column (kg)"}).json()
    assert any("custom_material" in x for x in to_custom["labels"])


def test_carbon_what_if_needs_a_factor_in_the_project(api):
    unknown = api.get("/carbon/what_if", params={
        "material_from": "Concrete (sf)", "material_to": "Steel (sf)"})
    assert unknown.status_code == 404 and unknown.json()["error"] == "unknown_material_factor"
    nothing = api.get("/carbon/what_if", params={
        "material_from": "Gold (sf)", "material_to": "Timber (sf)"})
    assert nothing.json()["error"] == "no_match"


def test_snapshot_without_stv(repo):
    syn.add_snapshot(repo, "20270201T080000Z", stv=None)
    api = client_for(repo)
    for url in ("/carbon/summary", "/carbon", "/carbon/what_if?material_from=a&material_to=b"):
        response = api.get(url)
        assert response.status_code == 404 and response.json()["error"] == "no_stv"
    # an older snapshot still has it
    assert api.get("/carbon/summary", params={"snapshot": SID}).status_code == 200


# ---------------------------------------------------------------------------- quantities


def test_quantities(api):
    body = api.get("/quantities", params={"category": "walls", "level": "l1"}).json()
    assert body["snapshot"]["id"] == SID
    assert body["totals"]["elements"] == 2 and body["totals"]["area_sf"] == 700.0
    assert {r["ac"] for r in body["rows"]} == {"C1010", "B2010"}
    assert api.get("/quantities", params={"ac": "B1000"}).json()["totals"]["elements"] == 3
    assert api.get("/quantities", params={"level": "L9"}).json()["error"] == "no_match"
    everything = api.get("/quantities").json()
    assert everything["totals"]["elements"] == syn.ELEMENT_ROWS - 1
    assert len(everything["rows"]) == 11


def test_elements_count(api):
    body = api.get("/elements/count").json()
    assert body["count"] == syn.ELEMENT_ROWS - 1 and body["excluded_dnc"] == 1
    assert {r["discipline"]: r["count"] for r in body["rows"]} == {
        "architecture": 6, "structural": 3, "mep": 2}
    assert api.get("/elements/count", params={"level": "L1", "category": "Walls"}
                   ).json()["count"] == 2
    assert api.get("/elements/count", params={"discipline": "mep"}).json()["count"] == 2


def test_quantities_unavailable_for_stale_snapshot(repo):
    path = repo / "exports" / "Demo_STR_Structural_Schedule.csv"
    path.write_text(path.read_text(encoding="utf-8") + "77,Floors,F,S,L1,,B1010,x,,,,1,1,c,,,\n",
                    encoding="utf-8")
    api = client_for(repo)
    for url in ("/quantities", "/elements/count"):
        response = api.get(url)
        assert response.status_code == 404 and response.json()["error"] == "elements_unavailable"
    assert api.get("/cost/summary").status_code == 200  # cost does not depend on the exports
    rows = {r["metric"]: r for r in api.get("/quality").json()["rows"] if r["scope"] == "elements"}
    assert rows["status"]["detail"]["status"] == "stale"


# ---------------------------------------------------------------------------- quality etc.


def test_quality(api):
    body = api.get("/quality").json()
    assert body["snapshot"]["id"] == SID and body["elements_status"] == "loaded"
    rows = {(r["scope"], r["metric"]): r for r in body["rows"]}
    assert rows[("tvd", "unmapped_elements")]["pct"] == 10.0
    assert rows[("elements", "missing_assembly_code")]["detail"]["top_categories"] == {"Doors": 1}


def test_snapshots_compare_and_snapshot_param(repo):
    changed = syn.tvd_payload()
    changed["line_items"]["Shell"][2]["total"] = 33000.0  # roof 30,000 -> 33,000
    changed["cluster_summary"][1]["estimate"] = 66000.0
    changed["financials"]["grand_total"] = syn.GRAND_TOTAL + 3000
    items = list(syn.STV_ITEMS)
    syn.add_snapshot(repo, "20270201T080000Z", label="Second", tvd=changed,
                     stv=syn.stv_payload(items[:3]))
    api = client_for(repo)
    listing = api.get("/snapshots").json()
    assert listing["total"] == 2 and [r["id"] for r in listing["rows"]] == [
        "20270201T080000Z", SID]
    assert listing["snapshot"]["id"] == "20270201T080000Z"  # the latest one
    assert api.get("/cost/summary").json()["snapshot"]["id"] == "20270201T080000Z"
    old = api.get("/cost/summary", params={"snapshot": SID}).json()
    assert old["grand_total"] == syn.GRAND_TOTAL
    unknown = api.get("/cost/summary", params={"snapshot": "nope"})
    assert unknown.status_code == 404 and unknown.json()["error"] == "unknown_snapshot"

    cmp = api.get("/compare", params={"a": SID, "b": "20270201T080000Z"}).json()
    assert cmp["compared"]["a"]["id"] == SID and cmp["compared"]["b"]["label"] == "Second"
    assert cmp["cost"]["change"] == 3000.0
    assert cmp["carbon"]["change"] == pytest.approx(-(500 * 0.4 + 1000 * 1.5))
    shell = next(r for r in cmp["rows"] if r["cluster"] == "Shell")
    assert shell["change"] == 3000.0 and shell["change_pct"] == pytest.approx(4.76, abs=0.01)
    assert api.get("/compare", params={"a": SID}).status_code == 422


def test_every_answer_names_its_snapshot(repo):
    api = client_for(repo)
    urls = ["/cost/summary", "/cost?cluster=Shell", "/cost/what_if?ac=B30&change_pct=5",
            "/carbon/summary", "/carbon?stv_assembly=Floor",
            "/carbon/what_if?material_from=Concrete%20(sf)&material_to=Timber%20(sf)",
            "/quantities", "/elements/count", "/quality", "/snapshots",
            f"/compare?a={SID}&b={SID}"]
    for url in urls:
        body = api.get(url).json()
        assert body["snapshot"]["id"] == SID, url
        assert "timestamp" in body["snapshot"], url


# ---------------------------------------------------------------------------- caps


def test_caps_rows(tmp_path):
    repo = tmp_path / "big"
    syn.write_exports(repo)
    syn.add_snapshot(repo, SID, tvd=syn.big_tvd(80), stv=syn.big_stv(80))
    api = client_for(repo)
    # 80 matching lines: over the row cap -> the documented error, not a truncated list
    response = api.get("/cost", params={"cluster": "Shell"})
    assert response.status_code == 200
    body = response.json()
    assert body["error"] == "too_many_results" and body["hint"] == "filter by level or category"
    assert body["snapshot"]["id"] == SID and body["at_least_rows"] == caps.MAX_ROWS + 1
    assert "rows" not in body
    # narrowed down: within the cap
    narrow = api.get("/cost", params={"cluster": "Shell", "ac": "B000"}).json()
    assert "error" not in narrow and 0 < len(narrow["rows"]) <= caps.MAX_ROWS
    # 80 STV items
    assert api.get("/carbon", params={"stv_assembly": "Assembly 1"}).json().get("error") is None
    assert api.get("/carbon").json()["error"] == "too_many_results"


def test_exactly_50_rows_pass_and_51_do_not(tmp_path):
    repo = tmp_path / "edge"
    syn.write_exports(repo)
    syn.add_snapshot(repo, SID, tvd=syn.big_tvd(50), stv=syn.big_stv(10))
    assert "error" not in client_for(repo).get("/cost").json()
    repo2 = tmp_path / "edge2"
    syn.write_exports(repo2)
    syn.add_snapshot(repo2, SID, tvd=syn.big_tvd(51), stv=syn.big_stv(10))
    assert client_for(repo2).get("/cost").json()["error"] == "too_many_results"


def test_caps_tokens(tmp_path):
    repo = tmp_path / "wide"
    syn.write_exports(repo)
    tvd = syn.big_tvd(20)
    for line in tvd["line_items"]["Shell"]:
        line["notes"] = "n" * 3000  # 20 rows, but ~60,000 characters
    syn.add_snapshot(repo, SID, tvd=tvd)
    body = client_for(repo).get("/cost").json()
    assert body["error"] == "too_many_results" and body["estimated_tokens"] > caps.MAX_TOKENS
    assert body["at_least_rows"] <= caps.MAX_ROWS  # the token cap alone triggered


def test_enforce_unit():
    small = {"snapshot": {"id": "x"}, "rows": [{"a": 1}] * 50}
    assert caps.enforce(small) is small
    big = {"snapshot": {"id": "x"}, "rows": [{"a": 1}] * 51, "labels": ["a", "b"]}
    out = caps.enforce(big)
    assert out["error"] == "too_many_results" and out["hint"] == caps.HINT
    assert out["snapshot"] == {"id": "x"} and out["at_least_rows"] == 51
    # strings in lists are not rows; nested lists are
    assert caps.count_rows({"x": ["a"] * 100}) == 0
    assert caps.count_rows({"rows": [[1, 2]] * 3, "d": {"y": [{}]}}) == 4
    assert caps.estimate_tokens("a" * 30) == 10


def test_all_endpoints_stay_under_the_caps_on_a_realistic_project(tmp_path):
    """Island-like sizes: 48 line items, ~85 STV items, 218 quantity groups."""
    repo = tmp_path / "island_like"
    syn.write_exports(repo)
    syn.add_snapshot(repo, SID, tvd=syn.big_tvd(48), stv=syn.big_stv(40))
    api = client_for(repo)
    for url in ("/cost/summary", "/cost", "/carbon/summary", "/quality", "/snapshots",
                "/cost/what_if?ac=B&change_pct=10", "/quantities?category=Walls&level=L1",
                "/elements/count"):
        body = api.get(url).json()
        assert "error" not in body, (url, body)
        assert caps.count_rows(body) <= caps.MAX_ROWS
        assert caps.estimate_tokens(body) <= caps.MAX_TOKENS


# ---------------------------------------------------------------------------- POST /sql


def test_sql_is_off_by_default(api):
    assert api.post("/sql", json={"query": "SELECT 1"}).status_code == 404


def test_sql_select_only(repo):
    api = client_for(repo, enable_sql=True)
    ok = api.post("/sql", json={"query": "SELECT cluster, estimate FROM tvd_clusters "
                                         "ORDER BY estimate DESC"}).json()
    assert ok["columns"] == ["cluster", "estimate"] and ok["rows"][0] == ["Shell", 63000.0]
    assert ok["snapshot"]["id"] == SID and any("sql" in x for x in ok["labels"])
    cte = api.post("/sql", json={"query": "WITH t AS (SELECT 1 AS a) SELECT a FROM t"}).json()
    assert cte["rows"] == [[1]]
    for bad in ("DELETE FROM snapshots", "INSERT INTO meta VALUES ('a','b')",
                "DROP TABLE elements", "PRAGMA writable_schema=1", "UPDATE meta SET value='1'",
                "ATTACH DATABASE '/tmp/x.db' AS x", "SELECT 1; DELETE FROM meta",
                "SELECT load_extension('x')", "  ", "VACUUM"):
        response = api.post("/sql", json={"query": bad})
        assert response.status_code == 400, bad
        assert response.json()["error"] in ("not_a_select", "sql_error"), bad
    # nothing changed
    assert api.get("/snapshots").json()["total"] == 1
    assert api.get("/cost/summary").json()["grand_total"] == syn.GRAND_TOTAL


def test_sql_row_cap_and_auth(repo):
    api = client_for(repo, enable_sql=True)
    many = api.post("/sql", json={"query": "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL "
                                           "SELECT i+1 FROM n WHERE i < 500) SELECT i FROM n"})
    assert many.json()["error"] == "too_many_results"
    anon = TestClient(api.app)
    assert anon.post("/sql", json={"query": "SELECT 1"}).status_code == 401


def test_sql_stops_runaway_queries(repo, monkeypatch):
    from engines.api import sqlrunner
    monkeypatch.setattr(sqlrunner, "MAX_SECONDS", 0.05)
    api = client_for(repo, enable_sql=True)
    slow = api.post("/sql", json={"query": "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT "
                                           "i+1 FROM n) SELECT count(*) FROM n"})
    assert slow.status_code == 400 and slow.json()["error"] == "query_too_slow"
