"""P3.1: ``concho config validate`` / ``concho config schema`` exit codes and output."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from engines.cli import main

REPO_ROOT = Path(__file__).resolve().parents[2]
ISLAND = REPO_ROOT / "engines" / "common" / "examples" / "island_2026.project_config.json"
TEMPLATE = REPO_ROOT / "template" / "project_config.example.json"
SCHEMA_FILE = REPO_ROOT / "docs" / "schema" / "project_config.schema.json"


@pytest.mark.parametrize("path", [ISLAND, TEMPLATE])
def test_validate_examples_exit_0(capsys, path):
    assert main(["config", "validate", str(path)]) == 0
    out = capsys.readouterr().out
    assert "OK:" in out
    assert "error:" not in out


def test_validate_island_prints_on_top_warning(capsys):
    main(["config", "validate", str(ISLAND)])
    out = capsys.readouterr().out
    assert "warning: tvd.custom_clusters: on-top cluster(s) Equipment Rental" in out
    assert "405,852 USD above the total target" in out


def test_validate_invalid_exit_1(tmp_path, capsys):
    data = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    del data["stv"]["use_phase"]["grid_kwh"]
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(data), encoding="utf-8")
    assert main(["config", "validate", str(bad)]) == 1
    out = capsys.readouterr().out
    assert "error: stv.use_phase: use phase is incomplete; missing: grid_kwh" in out
    assert "INVALID:" in out


def test_validate_bad_json_exit_1(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    assert main(["config", "validate", str(bad)]) == 1
    assert "invalid JSON" in capsys.readouterr().out


def test_validate_missing_file_exit_1(tmp_path, capsys):
    assert main(["config", "validate", str(tmp_path / "nope.json")]) == 1
    assert "cannot read file" in capsys.readouterr().out


def test_schema_prints_checked_in_schema(capsys):
    assert main(["config", "schema"]) == 0
    assert capsys.readouterr().out == SCHEMA_FILE.read_text(encoding="utf-8")


def test_usage_error_exit_1(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["config"])
    assert exc.value.code == 1


def test_module_entry_point():
    proc = subprocess.run(
        [sys.executable, "-m", "engines.cli", "config", "validate", str(ISLAND)],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
