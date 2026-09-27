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
import sys
from collections import defaultdict
from pathlib import Path

import pytest

from engines.common.config import load_config
from engines.stv import STVEngine, STVInputs, cli
from engines.stv.coverage import build_mapping_coverage
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
# Keys added after the stored reference files: P3.6 (estimates), P3.7 (custom materials,
# proxies), P3.8 (use-phase status).
ADDED_ITEM_KEYS = ("estimated", "estimated_amount", "custom_material", "custom_material_source",
                   "proxy", "proxy_amount", "origin")
ADDED_RESULT_KEYS = ("data_flags", "use_phase_status")
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
    proxy: dict[tuple[str, str], float] = defaultdict(float)
    for path in paths:
        for item in loader(path, mapping).construction_items:
            totals[(item.assembly, item.material_type)] += item.amount
            estimated[(item.assembly, item.material_type)] += item.estimated_amount
            proxy[(item.assembly, item.material_type)] += item.proxy_amount
    return [
        ConstructionItem(assembly=assembly, material_type=material_type, amount=amount,
                         estimated_amount=estimated[(assembly, material_type)],
                         proxy_amount=proxy[(assembly, material_type)])
        for (assembly, material_type), amount in sorted(totals.items())
        if amount > 0
    ]


def _without_added(result: dict) -> dict:
    """The result without the keys added since P3.6 (for the comparison with stored files)."""
    items = [{k: v for k, v in item.items() if k not in ADDED_ITEM_KEYS}
             for item in result["construction_items"]]
    rest = {k: v for k, v in result.items() if k not in ADDED_RESULT_KEYS}
    return {**rest, "construction_items": items}


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
                 "estimated_amount": i.estimated_amount, "proxy_amount": i.proxy_amount}
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
    _assert_close(_without_added(project), expected_project)


@pytest.mark.parametrize("trade", list(TRADES))
def test_trade_matches_reference_file(trade, trade_results, ipd_challenge_dir):
    expected = _load(ipd_challenge_dir / EXPECTED_TRADE.format(trade=trade))
    _assert_close(_without_added(trade_results[trade].to_dict()), expected, trade)


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


# --- P3.6: mapping coverage of the Island exports -----------------------------------------

# Rows skipped before P3.6: architecture 655, structural 167 (166 Parts + 1 floor), MEP 170
# (docs/engines/stv.md, "Unmapped Parts"); now split into unmapped and zero quantity.
ELEMENTS = {
    "architecture": {"total": 1986, "mapped": 1331, "zero_quantity": 3, "unmapped": 652},
    "structural": {"total": 505, "mapped": 338, "zero_quantity": 0, "unmapped": 167},
    "mep": {"total": 1516, "mapped": 1346, "zero_quantity": 74, "unmapped": 96},
}
# Floor elements in both the architecture and the structural export (P2.3, P3.9).
DOUBLE_FLOORS = {"1241457", "1789623", "1789655"}


@pytest.fixture(scope="module")
def island_coverage(ipd_challenge_dir, island_mapping, project) -> dict:
    reports = [loader(ipd_challenge_dir / SCHEDULES / f, island_mapping)
               for loader, files in TRADES.values() for f in files]
    return build_mapping_coverage(reports, island_mapping, STVResults.from_dict(project))


def test_island_mapping_coverage_counts(island_coverage):
    for discipline, counts in ELEMENTS.items():
        block = island_coverage["disciplines"][discipline]
        assert {k: block["elements"][k] for k in counts} == counts, discipline
    assert island_coverage["total"]["kgco2e"] == pytest.approx(PROJECT["carbon"], rel=REL)


def test_island_parts_stay_unmapped_and_are_listed(island_coverage):
    unmapped = island_coverage["disciplines"]["structural"]["unmapped_types"]
    parts = next(t for t in unmapped if t["category"] == "Parts")
    assert parts["count"] == 166
    assert parts["materials"] == ["Structural Bamboo (CLB)"]
    assert parts["volume_cf"] > 0
    arch_parts = next(t for t in island_coverage["disciplines"]["architecture"]["unmapped_types"]
                      if t["category"] == "Parts")
    assert arch_parts["count"] == 96


def test_island_cross_discipline_elements(island_coverage):
    cross = {x["element_id"]: x for x in island_coverage["cross_discipline_elements"]}
    assert DOUBLE_FLOORS <= set(cross)
    outcome = {o["discipline"]: o for o in cross["1241457"]["occurrences"]}
    assert outcome["structural"]["status"] == "unmapped"
    assert (outcome["architecture"]["stv_material_type"], outcome["architecture"]["amount"]) == (
        "Concrete (sf)", 6848.0)


def test_island_bamboo_proxy_rules(island_coverage):
    proxies = {r["category"]: r for r in island_coverage["rules"]
               if r["keyword"] == "structural bamboo" and r["discipline"] == "structural"}
    assert proxies["Structural Columns"]["won"] == 99
    assert proxies["Structural Framing"]["won"] == 113
    assert proxies["Structural Columns"]["stv_material_type"] == "Glulam Column (kg)"


def test_island_estimates(island_coverage, project):
    estimated = {d: b["estimated"] for d, b in island_coverage["disciplines"].items()}
    assert estimated["architecture"]["elements"] == estimated["structural"]["elements"] == 0
    assert estimated["mep"]["elements"] > 0
    assert 0 < estimated["mep"]["kgco2e"] < island_coverage["disciplines"]["mep"]["kgco2e"]
    flagged = {(i["assembly"], i["material_type"]) for i in project["construction_items"]
               if i["estimated"]}
    assert flagged and all(assembly == "MEP" for assembly, _ in flagged)


def test_island_cli_single_run(monkeypatch, tmp_path, ipd_challenge_dir):
    """All six exports in one concho-stv call: same total, full coverage block."""
    schedules = ipd_challenge_dir / SCHEDULES
    args = ["--config", str(ISLAND_CONFIG), "--template", str(ipd_challenge_dir / WORKBOOK),
            "--output-dir", str(tmp_path)]
    for trade, (_loader, files) in TRADES.items():
        args += [f"--{trade}-schedule", *(str(schedules / f) for f in files)]
    monkeypatch.setattr(sys, "argv", ["concho-stv", *args])
    cli.main()
    result = _load(tmp_path / "stv_results.json")
    assert result["metric_summary"]["carbon"]["project"] == pytest.approx(PROJECT["carbon"],
                                                                          rel=REL)
    coverage = result["mapping_coverage"]
    assert coverage["mapping_file"].endswith("engines/stv/examples/island/stv_mapping.csv")
    assert DOUBLE_FLOORS <= {x["element_id"] for x in coverage["cross_discipline_elements"]}


# --- P3.7: bamboo proxies flagged, no custom material ------------------------------------

# kgCO2e of the proxy rules of the Island mapping file (bamboo as concrete floor,
# steel-stud walls, glulam columns and beams); docs/engines/stv.md.
PROXY_KGCO2E = {"Floor": 349_607.170808, "Interior Wall": 123_625.979178,
                "Beams": 72_139.4414088, "Columns": 25_239.9219634}


def test_island_proxy_flags(project):
    flags = project["data_flags"]
    assert flags["custom_material"] is False and flags["proxy"] is True
    assert flags["custom_materials"]["embodied"]["carbon"] == 0.0
    for assembly, kgco2e in PROXY_KGCO2E.items():
        block = flags["by_assembly"][assembly]
        assert block["proxy"] is True
        assert block["proxy_embodied"]["carbon"] == pytest.approx(kgco2e, rel=REL)
    assert flags["proxies"]["embodied"]["carbon"] == pytest.approx(
        sum(PROXY_KGCO2E.values()), rel=REL)
    assert flags["proxies"]["share_of_embodied"]["carbon"] == pytest.approx(
        sum(PROXY_KGCO2E.values()) / PROJECT["carbon"], rel=REL)
    assert not any(flags["by_assembly"][a]["proxy"] for a in ("Foundation", "MEP", "Roof",
                                                               "Exterior Wall"))
