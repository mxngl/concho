"""Golden test: the Island 2026 "Current" STV project result (P2.2 STV part, P2.3).

Re-runs the migrated engine on the inputs that produced the reference result (see
``docs/engines/stv.md``, "Island 2026 reference result") and compares with the stored
outputs within 1e-6 relative:

- inputs: IPD_Challenge@989a6b7 ``revit_schedules/Current/*`` (two CSVs per trade),
  reference data from ``STV_Template/STV_ConceptA_Bambo.xlsx`` (a team copy of the course
  workbook; read in place, never copied into this repo);
- expected: AutoSTV@island-2026-final ``outputs/Current-.../Current/project/stv_results.json``
  (2,517,183.14 kgCO2e, shown as "Current" on the STV dashboard) and the per-trade results in
  IPD_Challenge ``outputs/stv_versions/Current/{trade}/``.

The original batch script (not committed in IPD_Challenge) ran each trade on its CSVs, summed
the construction items per (assembly, material type) and combined the trade results in the
order architecture, mep, structural. This test repeats exactly that.

Skipped unless the fixtures are present (``python scripts/fetch_fixtures.py``).
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pytest

from engines.stv import STVEngine, STVInputs
from engines.stv.models import ConstructionItem, STVResults
from engines.stv.reference import STVReferenceData
from engines.stv.revit_architecture import load_architecture_schedule
from engines.stv.revit_mep import load_mep_schedule
from engines.stv.revit_structural import load_structural_schedule

REL = 1e-6
TEAM = "Island"
WORKBOOK = "STV_Template/STV_ConceptA_Bambo.xlsx"
SCHEDULES = "revit_schedules/Current"

# Order matters for the item order in the combined result: architecture, mep, structural.
TRADES = {
    "architecture": (
        load_architecture_schedule,
        [
            "04_Island_ARCH_Concept2_Architecture_TakeOff.csv",
            "STR_Wall_Bamboo_Concept2_amd03_Architecture_TakeOff.csv",
        ],
    ),
    "mep": (
        load_mep_schedule,
        [
            "01_Island_MEP_Concept2_MEP_TakeOff.csv",
            "04_Island_ARCH_Concept2_MEP_TakeOff.csv",
        ],
    ),
    "structural": (
        load_structural_schedule,
        [
            "04_Island_ARCH_Concept2_Structural_Schedule.csv",
            "STR_Wall_Bamboo_Concept2_amd03_Structural_Schedule.csv",
        ],
    ),
}

EXPECTED_PROJECT = "outputs/Current-20260515T191939Z-3-001/Current/project/stv_results.json"
EXPECTED_TRADE = "outputs/stv_versions/Current/{trade}/stv_results.json"

# Roadmap §1 reference numbers.
TARGETS = {"carbon": 7_396_873.85, "energy": 155_969_076.59, "water": 271_387_397.26}
PROJECT = {"carbon": 2_517_183.14, "energy": 28_396_923.44, "water": 30_026_557.14}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _trade_items(loader, paths: list[Path]) -> list[ConstructionItem]:
    totals: dict[tuple[str, str], float] = defaultdict(float)
    for path in paths:
        for item in loader(path).construction_items:
            totals[(item.assembly, item.material_type)] += item.amount
    return [
        ConstructionItem(assembly=assembly, material_type=material_type, amount=amount)
        for (assembly, material_type), amount in sorted(totals.items())
        if amount > 0
    ]


def _assert_close(actual, expected, path: str = "") -> None:
    """Recursive comparison: numbers within REL, everything else exactly."""
    if isinstance(expected, dict):
        assert set(actual) == set(expected), path
        for key in expected:
            _assert_close(actual[key], expected[key], f"{path}.{key}")
    elif isinstance(expected, list):
        assert len(actual) == len(expected), path
        for index, (a, e) in enumerate(zip(actual, expected, strict=True)):
            _assert_close(a, e, f"{path}[{index}]")
    elif isinstance(expected, float) or isinstance(actual, float):
        assert actual == pytest.approx(expected, rel=REL, abs=1e-12), path
    else:
        assert actual == expected, path


@pytest.fixture(scope="module")
def trade_results(ipd_challenge_dir) -> dict[str, STVResults]:
    engine = STVEngine(STVReferenceData.from_workbook(ipd_challenge_dir / WORKBOOK))
    results = {}
    for trade, (loader, files) in TRADES.items():
        items = _trade_items(loader, [ipd_challenge_dir / SCHEDULES / f for f in files])
        payload = {
            "team": TEAM,
            "construction_items": [
                {"assembly": i.assembly, "material_type": i.material_type, "amount": i.amount}
                for i in items
            ],
        }
        results[trade] = engine.calculate(STVInputs.from_dict(payload))
    return results


@pytest.fixture(scope="module")
def project(trade_results) -> dict:
    return STVResults.combine(list(trade_results.values()), team=TEAM).to_dict()


@pytest.fixture(scope="module")
def expected_project(autostv_dir) -> dict:
    return _load(autostv_dir / EXPECTED_PROJECT)


def test_targets(project):
    for metric, value in TARGETS.items():
        assert project["targets"][metric] == pytest.approx(value, rel=REL)


def test_project_totals(project):
    for metric, value in PROJECT.items():
        assert project["metric_summary"][metric]["project"] == pytest.approx(value, rel=REL)
    # Use phase is not modelled in the reference result (docs/engines/stv.md).
    assert project["breakdown"]["use_phase"]["carbon"] == 0.0


def test_project_matches_reference_file(project, expected_project):
    _assert_close(project["metric_summary"], expected_project["metric_summary"], "metrics")
    _assert_close(project["breakdown"], expected_project["breakdown"], "breakdown")
    _assert_close(project, expected_project)


@pytest.mark.parametrize("trade", list(TRADES))
def test_trade_matches_reference_file(trade, trade_results, ipd_challenge_dir):
    expected = _load(ipd_challenge_dir / EXPECTED_TRADE.format(trade=trade))
    _assert_close(trade_results[trade].to_dict(), expected, trade)


def test_ipd_copy_of_project_file_is_identical(autostv_dir, ipd_challenge_dir):
    # The AutoSTV dashboard file is a byte-identical copy of IPD_Challenge's version.
    ipd = ipd_challenge_dir / "outputs/stv_versions/Current/project/stv_results.json"
    assert ipd.read_bytes() == (autostv_dir / EXPECTED_PROJECT).read_bytes()
