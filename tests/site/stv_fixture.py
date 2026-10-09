"""Invented STV results for the dashboard tests (P7.2).

The course STV workbook is licensed and never committed, so the STV engine cannot run in CI.
This builds a results JSON the same way ``concho-stv`` does (mapping table, duplicate / Parts
rule, mapping coverage, DNC rows, ``STVEngine``, ``STVResults.to_dict``) from INVENTED exports,
an INVENTED mapping table and an INVENTED catalog stand-in (the same idea as
``tests/stv/conftest.py``). No number here is course data.
"""

from __future__ import annotations

from pathlib import Path

from engines.stv.cli import _item_dicts
from engines.stv.coverage import build_mapping_coverage, dnc_rows
from engines.stv.engine import STVEngine
from engines.stv.mapping import map_exports, stv_mapping_from_dicts
from engines.stv.models import ImpactVector, STVInputs
from engines.stv.reference import FuelRecord, MaterialRecord, STVReferenceData, TeamFactors

TEAM = "Example Team"

# fmt: off
# (assembly, material type, unit multiplier, materials / transport / construction factors:
#  carbon, energy, water, ozone per unit): all invented.
CATALOG = [
    ("Floor", "Test Slab (sf)", 1.0, (9.0, 90.0, 800.0, 1e-6), (1.0, 10.0, 60.0, 1e-7), (0.8, 8.0, 40.0, 1e-7)),
    ("Exterior Wall", "Test Cladding (sf)", 1.0, (6.0, 70.0, 500.0, 1e-6), (0.9, 9.0, 50.0, 1e-7), (0.5, 5.0, 30.0, 1e-7)),
    ("Column", "Test Column (kg)", 1.0, (1.1, 12.0, 90.0, 1e-7), (0.1, 1.0, 5.0, 1e-8), (0.05, 0.5, 3.0, 1e-8)),
    ("Beam", "Test Beam (kg)", 1.0, (0.7, 9.0, 60.0, 1e-7), (0.1, 1.0, 5.0, 1e-8), (0.05, 0.5, 3.0, 1e-8)),
    ("Beam", "Test Timber Beam (kg)", 1.0, (0.4, 7.0, 40.0, 1e-7), (0.1, 1.0, 5.0, 1e-8), (0.05, 0.5, 3.0, 1e-8)),
    ("MEP", "Test Pipe (ft)", 1.0, (2.0, 25.0, 180.0, 1e-7), (0.2, 2.0, 10.0, 1e-8), (0.1, 1.0, 6.0, 1e-8)),
]
# fmt: on
CUSTOM_SOURCE = "EPD-TEST-0001 (invented)"

MAPPING = [
    {"assembly_code": "", "category": "Floors", "keyword": "", "stv_assembly": "Floor",
     "stv_material_type": "Test Slab (sf)", "quantity_field": "area", "conversion": "",
     "note": "Concrete slab"},
    {"assembly_code": "", "category": "Floors", "keyword": "timber", "stv_assembly": "Floor",
     "stv_material_type": "Test Slab (sf)", "quantity_field": "area", "conversion": "",
     "note": "proxy: timber floor booked as concrete slab (catalog has no timber floor)"},
    {"assembly_code": "", "category": "Walls", "keyword": "", "stv_assembly": "Exterior Wall",
     "stv_material_type": "Test Cladding (sf)", "quantity_field": "area", "conversion": "",
     "note": ""},
    {"assembly_code": "", "category": "Structural Columns", "keyword": "",
     "stv_assembly": "Columns", "stv_material_type": "Test Column (kg)",
     "quantity_field": "weight", "conversion": "", "note": ""},
    {"assembly_code": "", "category": "Structural Framing", "keyword": "",
     "stv_assembly": "Beams", "stv_material_type": "Test Timber Beam (kg)",
     "quantity_field": "weight", "conversion": "", "note": ""},
    {"assembly_code": "", "category": "Pipes", "keyword": "", "stv_assembly": "MEP",
     "stv_material_type": "Test Pipe (ft)", "quantity_field": "length", "conversion": "",
     "note": ""},
]

HEADER = ("ElementId,Category,Family,Type,Level,Material,Assembly Code,Area,Volume,Length,"
          "Weight,Comments,Part Source Id\n")
ARCH = [
    "1001,Walls,,Facade panel,L1,Metal,B2010,800,40,40,,,",
    "1002,Walls,,Facade panel DNC,L1,Metal,B2010,150,8,15,,,",
    "1003,Floors,,Timber floor,L1,Timber,B1010,1200,60,,,,",
    "1004,Floors,,Slab,L2,Concrete,B1010,2000,200,,,,",
    "1005,Furniture,,Desk,L1,Wood,E2010,,,,,,",
    "1006,Doors,,Single door,L1,Wood,C1020,,,,,,",
]
STRUCT = [
    "1004,Floors,,Slab,L2,Concrete,B1010,2000,200,,,,",
    "2001,Structural Columns,,Steel column,L1,Steel,B1010,,,12,5200,,",
    "2002,Structural Framing,,Timber beam,L2,Timber,B1010,,,30,18000,,",
]
MEP = ["3001,Pipes,,Copper,L1,Copper,D2000,,,300,,,"]


def _reference(with_custom: bool = True) -> STVReferenceData:
    records, valid = [], {}
    for assembly, name, mult, mat, tra, con in CATALOG:
        records.append(MaterialRecord(
            assembly=assembly, material_type=name,
            embodied_total=ImpactVector(*mat) + ImpactVector(*tra) + ImpactVector(*con),
            materials=ImpactVector(*mat), transport=ImpactVector(*tra),
            construction=ImpactVector(*con), unit_multiplier=mult))
        valid.setdefault({"Column": "Columns", "Beam": "Beams"}.get(assembly, assembly),
                         set()).add(name)
    by_name: dict[str, list[MaterialRecord]] = {}
    for r in records:
        by_name.setdefault(r.material_type, []).append(r)
    ref = STVReferenceData(
        {(r.assembly, r.material_type): r for r in records}, by_name, valid,
        {TEAM: TeamFactors(TEAM, ImpactVector(carbon=0.35, energy=6.0, water=2.0, ozone=1e-8),
                           target_carbon_factor=1.7, target_water_factor=6.0e7,
                           target_energy_factor=1.3)},
        {"Test Gas": FuelRecord("Test Gas", 2.0, 1e-6, 40.0, 0.05)})
    if with_custom:
        ref.custom_sources[("Beam", "Test Timber Beam (kg)")] = CUSTOM_SOURCE
    return ref


def build_stv_results(tmp: Path, *, use_phase: bool = True, scale: float = 1.0) -> dict:
    """``stv_results.json`` content for the invented exports (``scale`` multiplies the use
    phase, to make a second, different snapshot)."""
    tmp.mkdir(parents=True, exist_ok=True)
    paths = []
    for discipline, kind, rows in (("architecture", "Architecture_TakeOff", ARCH),
                                   ("structural", "Structural_Schedule", STRUCT),
                                   ("mep", "MEP_TakeOff", MEP)):
        path = tmp / f"Demo_{discipline.upper()}_{kind}.csv"
        path.write_text(HEADER + "\n".join(rows) + "\n", encoding="utf-8")
        paths.append((discipline, path))
    mapping = stv_mapping_from_dicts(MAPPING)
    reports, dedup = map_exports(paths, mapping)
    items = [i for r in reports for i in _item_dicts(r.construction_items)]
    payload = {"team": TEAM, "construction_items": items}
    if use_phase:
        payload["use_phase"] = {"electricity_from_grid_kwh": 400_000 * scale,
                                "natural_gas_m3": 30_000 * scale}
    results = STVEngine(_reference()).calculate(STVInputs.from_dict(payload))
    if use_phase:
        results.use_phase_status.update(source="project_config", modeled=True,
                                        not_modeled_reason=None, all_zero=False)
    else:
        results.use_phase_status.update(
            source="project_config", modeled=False, all_zero=True,
            not_modeled_reason="invented: the team has not modeled the building services yet")
    results.mapping_coverage = build_mapping_coverage(reports, mapping, results)
    results.dnc_rows = dnc_rows(reports)
    results.deduplication = dedup.block()
    return results.to_dict()
