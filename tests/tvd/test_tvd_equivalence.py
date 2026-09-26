"""Equivalence test: new engine vs. the original AutoTVD ``tvd_analysis.py``.

Skipped unless ``AUTOTVD_DIR`` points to a local AutoTVD checkout (ideally tag
``island-2026-final``). Nothing from that checkout is copied into this repo:
``cost_data.csv`` is RSMeans-derived.

Both implementations run in CI mode on ``AUTOTVD_DIR/qto/*.csv`` +
``AUTOTVD_DIR/cost_data.csv`` inside ``tmp_path``. Compared: the results JSON (all
fields except run timestamps, run label and input paths), the history snapshot
(except its date) and the dashboard HTML (with timestamps and data source masked).
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

AUTOTVD_DIR = os.environ.get("AUTOTVD_DIR")

pytestmark = pytest.mark.skipif(not AUTOTVD_DIR, reason="AUTOTVD_DIR not set")

SNAPSHOT_LABEL = "Equivalence check"

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


def _strip_meta(payload: dict) -> dict:
    payload = json.loads(json.dumps(payload))
    for key in ("generated_at", "date", "label", "data_source"):
        payload["meta"].pop(key)
    return payload


def _single(folder: Path, pattern: str) -> Path:
    (path,) = folder.glob(pattern)
    return path


@pytest.fixture(scope="module")
def outputs(tmp_path_factory) -> dict[str, Path]:
    base = Path(AUTOTVD_DIR)
    inputs = _inputs(base)
    flags = ["--arch", str(inputs["arch"]), "--struct", str(inputs["struct"]),
             "--cost", str(inputs["cost"])]

    # Original: a copy of tvd_analysis.py writes next to itself (results/, history/, docs/).
    orig = tmp_path_factory.mktemp("orig")
    shutil.copy(base / "tvd_analysis.py", orig / "tvd_analysis.py")
    _run([sys.executable, "tvd_analysis.py", "--ci", "--snapshot", SNAPSHOT_LABEL, *flags], orig)

    new = tmp_path_factory.mktemp("new")
    _run([sys.executable, "-m", "engines.tvd", "--ci", "--snapshot", SNAPSHOT_LABEL, *flags,
          "--out", str(new)], new)
    return {"orig": orig, "new": new}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_results_json_identical(outputs):
    orig = _load(outputs["orig"] / "results" / "latest.json")
    new = _load(outputs["new"] / "results" / "latest.json")
    assert _strip_meta(new) == _strip_meta(orig)
    # The timestamped copy equals latest.json in both implementations.
    new_ts = _single(outputs["new"] / "results", "2*.json")
    assert _load(new_ts) == new


def test_history_snapshot_identical(outputs):
    orig = _load(_single(outputs["orig"] / "history", "*_equivalence_check.json"))
    new = _load(_single(outputs["new"] / "history", "*_equivalence_check.json"))
    orig.pop("date")
    new.pop("date")
    assert new == orig


def test_dashboard_html_identical(outputs):
    def normalise(folder: Path) -> str:
        html = (folder / "docs" / "index.html").read_text(encoding="utf-8")
        source = _load(folder / "results" / "latest.json")["meta"]["data_source"]
        return _TS.sub("<ts>", html.replace(source, "<source>"))

    assert normalise(outputs["new"]) == normalise(outputs["orig"])


def test_island_golden_numbers(outputs):
    base = Path(AUTOTVD_DIR)
    for rel, digest in REFERENCE_SHA256.items():
        if hashlib.sha256((base / rel).read_bytes()).hexdigest() != digest:
            pytest.skip(f"{rel} differs from the island-2026-final reference input")
    new = _load(outputs["new"] / "results" / "latest.json")
    assert new["financials"]["grand_total"] == 16_065_644.29
    assert new["meta"]["unmapped_count"] == 1693
    assert new["meta"]["dnc_count"] == 75
