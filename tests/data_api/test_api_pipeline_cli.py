"""P5.3/P5.4 end to end on the team pipeline's own output (invented data, no course workbook):
``run_pipeline.py run`` on ``template/`` + ``tests/fixtures/pipeline_team/``, then the
``concho-api`` CLI (ingest, summary, serve on localhost)."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from engines.api import cli
from engines.api.ingest import default_db_path, ingest_repo

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "template"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "pipeline_team"
SCRIPT = REPO_ROOT / "scripts" / "run_pipeline.py"
GRAND_TOTAL = 51_880.00  # the fixture README, as in tests/pipeline/test_pipeline.py
TOKEN = "cli-test-token"


@pytest.fixture(scope="module")
def team(tmp_path_factory) -> Path:
    repo = tmp_path_factory.mktemp("pipeline_team") / "team"
    shutil.copytree(TEMPLATE, repo)
    shutil.copytree(FIXTURE / "exports", repo / "exports", dirs_exist_ok=True)
    shutil.copy2(FIXTURE / "cost_db.csv", repo / "cost_db.csv")
    env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_ACTIONS", "COURSE_STV_XLSX")}
    proc = subprocess.run([sys.executable, str(SCRIPT), "run", "--repo", str(repo)], cwd=repo,
                          capture_output=True, text=True, encoding="utf-8", env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return repo


def test_ingest_of_a_pipeline_run(team):
    result = ingest_repo(team)
    assert len(result["ingested"]) == 1 and result["db"] == str(default_db_path(team))
    from engines.api import schema
    conn = schema.connect(result["db"], readonly=True)
    snap = conn.execute("SELECT * FROM snapshots").fetchone()
    assert snap["tvd_grand_total"] == GRAND_TOTAL
    assert snap["stv_present"] == 0 and "STV skipped" in snap["stv_note"]  # no workbook here
    assert snap["elements_status"] == "loaded"  # the exports reproduce the TVD run
    assert conn.execute("SELECT COUNT(*) FROM elements").fetchone()[0] > 0
    assert json.loads(snap["summary_json"])["cost"]["grand_total"] == GRAND_TOTAL


def test_summary_command_prints_a_small_json(team, capsys):
    ingest_repo(team)
    assert cli.main(["summary", "--repo", str(team)]) == 0
    text = capsys.readouterr().out
    assert len(text.encode()) < 10_000 and json.loads(text)["cost"]["grand_total"] == GRAND_TOTAL


def test_ingest_command(team, capsys):
    assert cli.main(["ingest", "--repo", str(team), "--force"]) == 0
    assert json.loads(capsys.readouterr().out)["schema_version"] == 1
    assert cli.main(["ingest", "--repo", str(team / "nope")]) == 1
    assert "error:" in capsys.readouterr().err


def test_serve_needs_a_token(team, monkeypatch, capsys):
    monkeypatch.delenv("CONCHO_API_TOKEN", raising=False)
    assert cli.main(["serve", "--repo", str(team)]) == 1
    assert "CONCHO_API_TOKEN" in capsys.readouterr().err


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_serve_on_localhost(team):
    """The real thing: a `concho-api serve` process answers on 127.0.0.1 with the token."""
    pytest.importorskip("uvicorn")
    port = _free_port()
    env = {**os.environ, "CONCHO_API_TOKEN": TOKEN}
    proc = subprocess.Popen(
        [sys.executable, "-m", "engines.api.cli", "serve", "--repo", str(team), "--port",
         str(port)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        url = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                urllib.request.urlopen(f"{url}/health", timeout=1).read()
                break
            except (urllib.error.URLError, ConnectionError, OSError):
                assert proc.poll() is None, "concho-api serve exited"
                time.sleep(0.1)
        else:
            pytest.fail("concho-api serve did not start")
        with pytest.raises(urllib.error.HTTPError) as denied:
            urllib.request.urlopen(f"{url}/cost/summary", timeout=2)
        assert denied.value.code == 401
        request = urllib.request.Request(f"{url}/cost/summary",
                                         headers={"Authorization": f"Bearer {TOKEN}"})
        body = json.loads(urllib.request.urlopen(request, timeout=5).read())
        assert body["grand_total"] == GRAND_TOTAL and body["snapshot"]["id"]
        sql = urllib.request.Request(f"{url}/sql", data=b'{"query": "SELECT 1"}', method="POST",
                                     headers={"Authorization": f"Bearer {TOKEN}",
                                              "Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as off:  # POST /sql is off without the flag
            urllib.request.urlopen(sql, timeout=2)
        assert off.value.code == 404
    finally:
        proc.terminate()
        proc.wait(timeout=10)
