"""CLI tests: template resolution and an end-to-end run on invented reference data."""

from __future__ import annotations

import json
import os
import sys

import pytest
from conftest import TEAM

from engines.stv import cli
from engines.stv.reference import STVReferenceData


def _main(monkeypatch, *args: str) -> None:
    monkeypatch.setattr(sys, "argv", ["concho-stv", *args])
    cli.main()


def test_missing_workbook_fails_with_clear_message(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("COURSE_STV_XLSX", raising=False)
    out = tmp_path / "out"
    with pytest.raises(SystemExit) as exc:
        _main(monkeypatch, "--team", TEAM, "--output-dir", str(out))
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "COURSE_STV_XLSX" in err
    assert "--template" in err
    assert not out.exists()


def test_nonexistent_template_fails(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("COURSE_STV_XLSX", str(tmp_path / "missing.xlsx"))
    with pytest.raises(SystemExit):
        _main(monkeypatch, "--team", TEAM, "--output-dir", str(tmp_path / "out"))
    assert "not found" in capsys.readouterr().err


def test_output_dir_is_required(monkeypatch, tmp_path):
    monkeypatch.setenv("COURSE_STV_XLSX", str(tmp_path / "missing.xlsx"))
    with pytest.raises(SystemExit):
        _main(monkeypatch, "--team", TEAM)


def test_end_to_end_run(monkeypatch, tmp_path, reference, capsys):
    template = tmp_path / "course.xlsx"
    template.write_bytes(b"")  # only has to exist; loading is replaced below
    seen = {}

    def fake_from_workbook(path=None):
        seen["path"] = path
        return reference

    monkeypatch.setattr(STVReferenceData, "from_workbook", staticmethod(fake_from_workbook))
    monkeypatch.setenv("COURSE_STV_XLSX", str(template))
    inputs = tmp_path / "inputs.json"
    inputs.write_text(
        json.dumps(
            {
                "team": TEAM,
                "construction_items": [
                    {"assembly": "Floor", "material_type": "Test Slab (sf)", "amount": 10}
                ],
            }
        )
    )
    out = tmp_path / "out"
    _main(monkeypatch, "--input", str(inputs), "--output-dir", str(out))

    assert seen["path"] == str(template)
    response = json.loads(capsys.readouterr().out)
    results = json.loads((out / "stv_results.json").read_text())
    assert response["results_json"] == str(out / "stv_results.json")
    assert results["team"] == TEAM
    assert results["breakdown"]["embodied"]["carbon"] == pytest.approx(10 * 2.75)
    assert (out / "history.json").exists()
    assert response["charts"]
    assert all(os.path.exists(path) for path in response["charts"].values())
