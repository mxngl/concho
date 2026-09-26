"""Equivalence test: new engine vs. the original AutoTVD ``tvd_analysis.py``.

Uses the AutoTVD checkout from ``AUTOTVD_DIR`` if set, else ``AutoTVD`` in the shared
fixture root (``CONCHO_FIXTURES_DIR`` or ``.fixtures/``, see ``tests/conftest.py`` and
``scripts/fetch_fixtures.py``); skipped if neither exists. Nothing from that checkout is
copied into this repo: ``cost_data.csv`` is RSMeans-derived.

Both implementations run in CI mode on ``AUTOTVD_DIR/qto/*.csv`` +
``AUTOTVD_DIR/cost_data.csv`` inside ``tmp_path``; the new engine reads the project values
from the Island example config (``engines/common/examples/island_2026.project_config.json``).
Compared: the results JSON (all fields except run timestamps, run label, input paths, the
project/team names added in P3.2 and the ``target_consistency`` block added in P3.3), the
history snapshot (except its date) and the dashboard HTML (with timestamps and data source
masked).

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
    # P3.3: new block, not in the original; tested in test_island_target_consistency.
    payload.pop("target_consistency", None)
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

    new = tmp_path_factory.mktemp("new")
    _run([sys.executable, "-m", "engines.tvd", "--ci", "--snapshot", SNAPSHOT_LABEL, *flags,
          "--config", str(ISLAND_CONFIG), "--out", str(new)], new)
    return {"orig": orig, "new": new}


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


def test_island_golden_numbers(outputs, autotvd_dir):
    base = autotvd_dir
    for rel, digest in REFERENCE_SHA256.items():
        if hashlib.sha256((base / rel).read_bytes()).hexdigest() != digest:
            pytest.skip(f"{rel} differs from the island-2026-final reference input")
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
