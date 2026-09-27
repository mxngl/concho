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

Since P3.2 the team, lifetime and use phase come from the Island example config
(``engines/common/examples/island_2026.project_config.json``); the numbers are unchanged. A
second, invented config (course team "River", modeled use phase) must change exactly the
targets and the use phase.

Since P3.6 the Revit rows are mapped with the Island mapping table
(``engines/stv/examples/island/stv_mapping.csv``) instead of the hardcoded importers; the
results are identical. The line items now also carry ``estimated`` / ``estimated_amount``
(P3.6), which the stored reference files do not have; they are left out of the file
comparison and checked separately.

Skipped unless the fixtures are present (``python scripts/fetch_fixtures.py``).
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pytest

from engines.common.config import load_config
from engines.stv import STVEngine, STVInputs
from engines.stv.mapping import StvMapping, load_stv_mapping
from engines.stv.models import ConstructionItem, STVResults
from engines.stv.project import STVProjectSettings
from engines.stv.reference import STVReferenceData
from engines.stv.revit_architecture import load_architecture_schedule
from engines.stv.revit_mep import load_mep_schedule
from engines.stv.revit_structural import load_structural_schedule

REL = 1e-6
TEAM = "Island"
REPO_ROOT = Path(__file__).resolve().parents[2]
ISLAND_CONFIG = REPO_ROOT / "engines" / "common" / "examples" / "island_2026.project_config.json"
RIVER_CONFIG = REPO_ROOT / "tests" / "fixtures" / "configs" / "river_test.project_config.json"
ISLAND_MAPPING = REPO_ROOT / "engines" / "stv" / "examples" / "island" / "stv_mapping.csv"
# P3.6 item fields that the stored reference results do not have.
P36_ITEM_KEYS = ("estimated", "estimated_amount")
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


def _trade_items(loader, paths: list[Path], mapping: StvMapping) -> list[ConstructionItem]:
    totals: dict[tuple[str, str], float] = defaultdict(float)
    estimated: dict[tuple[str, str], float] = defaultdict(float)
    for path in paths:
        for item in loader(path, mapping).construction_items:
            totals[(item.assembly, item.material_type)] += item.amount
            estimated[(item.assembly, item.material_type)] += item.estimated_amount
    return [
        ConstructionItem(assembly=assembly, material_type=material_type, amount=amount,
                         estimated_amount=estimated[(assembly, material_type)])
        for (assembly, material_type), amount in sorted(totals.items())
        if amount > 0
    ]


def _without_p36(result: dict) -> dict:
    """The result without the P3.6 item fields (for the comparison with stored files)."""
    items = [{k: v for k, v in item.items() if k not in P36_ITEM_KEYS}
             for item in result["construction_items"]]
    return {**result, "construction_items": items}


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
def reference_data(ipd_challenge_dir) -> STVReferenceData:
    return STVReferenceData.from_workbook(ipd_challenge_dir / WORKBOOK)


@pytest.fixture(scope="module")
def island_mapping(reference_data) -> StvMapping:
    # Validated against the catalog of the reference workbook.
    return load_stv_mapping(ISLAND_MAPPING, catalog=reference_data)


def _run_trades(reference_data, ipd_challenge_dir, settings: STVProjectSettings,
                use_phase_trade: str | None = None, *,
                mapping: StvMapping) -> dict[str, STVResults]:
    """One result per trade; the use phase (if any) goes into ``use_phase_trade`` only."""
    engine = STVEngine(reference_data, lifetime_years=settings.lifetime_years)
    results = {}
    for trade, (loader, files) in TRADES.items():
        items = _trade_items(loader, [ipd_challenge_dir / SCHEDULES / f for f in files],
                             mapping)
        payload = {
            "team": settings.team,
            "construction_items": [
                {"assembly": i.assembly, "material_type": i.material_type, "amount": i.amount,
                 "estimated_amount": i.estimated_amount}
                for i in items
            ],
            "use_phase": settings.use_phase if trade == use_phase_trade else {},
        }
        results[trade] = engine.calculate(STVInputs.from_dict(payload))
    return results


@pytest.fixture(scope="module")
def trade_results(reference_data, ipd_challenge_dir, island_mapping) -> dict[str, STVResults]:
    settings = STVProjectSettings.from_config(load_config(ISLAND_CONFIG))
    assert (settings.team, settings.lifetime_years, settings.use_phase) == (TEAM, 50, {})
    return _run_trades(reference_data, ipd_challenge_dir, settings, "architecture",
                       mapping=island_mapping)


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
    _assert_close(_without_p36(project), expected_project)


@pytest.mark.parametrize("trade", list(TRADES))
def test_trade_matches_reference_file(trade, trade_results, ipd_challenge_dir):
    expected = _load(ipd_challenge_dir / EXPECTED_TRADE.format(trade=trade))
    _assert_close(_without_p36(trade_results[trade].to_dict()), expected, trade)


def test_ipd_copy_of_project_file_is_identical(autostv_dir, ipd_challenge_dir):
    # The AutoSTV dashboard file is a byte-identical copy of IPD_Challenge's version.
    ipd = ipd_challenge_dir / "outputs/stv_versions/Current/project/stv_results.json"
    assert ipd.read_bytes() == (autostv_dir / EXPECTED_PROJECT).read_bytes()


def test_river_config_changes_targets_and_use_phase(reference_data, ipd_challenge_dir, project,
                                                    island_mapping):
    settings = STVProjectSettings.from_config(load_config(RIVER_CONFIG))
    trades = _run_trades(reference_data, ipd_challenge_dir, settings, "architecture",
                         mapping=island_mapping)
    river = STVResults.combine(list(trades.values()), team=settings.team).to_dict()
    team = reference_data.get_team("River")

    assert river["team"] == "River"
    assert river["targets"]["carbon"] == pytest.approx(6.38e6 * team.target_carbon_factor)
    assert river["targets"]["energy"] == pytest.approx(1.51e8 * team.target_energy_factor)
    assert river["targets"]["water"] == pytest.approx(team.target_water_factor)
    assert river["targets"] != project["targets"]
    # Embodied impacts and construction items are independent of the project config.
    for key in ("embodied_materials", "embodied_transport", "embodied_construction",
                "embodied"):
        assert river["breakdown"][key] == project["breakdown"][key]
    assert river["construction_items"] == project["construction_items"]
    # Use phase from the config: River grid factors x 100,000 kWh x 50 years (+ gas, water).
    assert river["breakdown"]["use_electricity"]["carbon"] == pytest.approx(
        team.grid_electricity.carbon * 100_000 * 50, rel=REL
    )
    assert river["breakdown"]["use_heating"]["energy"] == pytest.approx(37 * 500 * 50, rel=REL)
    assert river["breakdown"]["use_water"]["water"] > 0
    assert project["breakdown"]["use_phase"]["carbon"] == 0.0

