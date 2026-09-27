"""P2.4: STV engine vs. the course workbook, same inputs on both sides.

Skipped unless ``COURSE_STV_XLSX`` points to the course workbook (``CEE_222_STV_V12.xlsx``).
The workbook is course data and is never committed (roadmap §0, hard rule 2).

Each case writes construction items (sheet "Construction and Materials", rows 18-58,
columns B/C/D) and use-phase inputs (sheet "Use Phase") into a temporary copy of the
workbook, recalculates the copy with LibreOffice headless (``soffice --convert-to xlsx``),
and compares the course results with ``engines.stv`` for the same inputs:

- embodied: "Construction and Materials"!E11:H11 vs. ``breakdown.embodied``
- use phase: "Use Phase"!F13:I13 vs. ``breakdown.use_phase``

All amounts and use-phase values below are invented test inputs, not team or course data.
Material and fuel names are the course catalog names; no LCA values appear in this file.

The embodied equivalence uses reference data read from a recalculated copy of the
template: the workbook as supplied carries stale cached values in some LCA component
cells (see ``test_embodied_odp_from_supplied_workbook_differs``).

P3.7 / P3.8 (``test_config_use_phase_with_pv_matches_course``,
``test_custom_material_matches_course``): a use phase with every field filled, incl. PV as an
Energy construction item, taken through ``project_config`` (``STVProjectSettings``), and a
custom material from a ``custom_materials.csv`` text, which the workbook expresses as an extra
``LCA Data`` row (written over the unreferenced catalog row ``CUSTOM_LCA_ROW`` of the copy; the
course sheet looks materials up by name). Both inputs are invented.

Known differences between the engine and the course (engine left unchanged, see the
``test_*_differs`` test): the stale cached LCA component values of the supplied workbook.
Fixed in P3.10 and now compared like the main cases: the cogeneration water/ODP columns
(``test_cogen_matches_course``), the rainwater cap (``test_rainwater_cap_matches_course``)
and the toilet factor with a urinal cell of 0 (``test_toilet_factor_matches_course``).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("COURSE_STV_XLSX"),
    reason="COURSE_STV_XLSX not set (course workbook must be supplied locally)",
)

openpyxl = pytest.importorskip("openpyxl")

from engines.common.config import load_config  # noqa: E402
from engines.stv import STVEngine, STVInputs  # noqa: E402
from engines.stv.custom_materials import COLUMNS as CUSTOM_COLUMNS  # noqa: E402
from engines.stv.custom_materials import validate_custom_materials_text  # noqa: E402
from engines.stv.project import STVProjectSettings  # noqa: E402
from engines.stv.reference import STVReferenceData  # noqa: E402

REL = 1e-6
CM = "Construction and Materials"
UP = "Use Phase"
FIRST_ITEM_ROW, LAST_ITEM_ROW = 18, 58  # 41 item rows in the course sheet
METRICS = ("carbon", "energy", "water", "ozone")
EMBODIED_CELLS = ("E11", "F11", "G11", "H11")
USE_PHASE_CELLS = ("F13", "G13", "H13", "I13")
TARGET_CELLS = ("E10", "F10", "G10")
TEMPLATE_ID = "template_unchanged"

# Use Phase input cells (column D) for the engine's use_phase payload keys.
USE_PHASE_INPUT_CELLS = {
    "electricity_from_grid_kwh": "D19",
    "onsite_renewable_kwh": "D20",
    "natural_gas_m3": "D29",
}
COGEN_INPUT_CELLS = {
    "electricity_kwh": "D23",
    "electricity_split": "D24",
    "heating_mj": "D25",
    "heating_split": "D26",
    "cooling_kwh": "D27",
    "cooling_split": "D28",
}
WATER_INPUT_CELLS = {
    "toilet_gpf": "D32",
    "urinal_gpf": "D33",
    "wc_sink_gpm": "D34",
    "lab_sink_gpm": "D35",
    "kitchen_sink_gpm": "D36",
    "shower_gpm": "D37",
    "landscaping_gal": "D38",
    "rainwater_collection_gal": "D40",
}


@dataclass
class Case:
    id: str
    team: str
    items: list[tuple[str, str, float]] = field(default_factory=list)
    use_phase: dict = field(default_factory=dict)
    # True: leave the urinal cell D33 blank (the template ships it as 0).
    urinal_blank: bool = False
    # P3.7: a custom material (custom_materials.csv row) written into 'LCA Data'.
    custom_row: dict | None = None

    def engine_inputs(self) -> STVInputs:
        # The engine gets what the course sheet holds in D33 (decision D11): blank -> None
        # (no urinals, toilet factor 1.0), otherwise the number, 0 by default (factor 0.75).
        water = dict(self.use_phase.get("water_use", {}))
        water["urinal_gpf"] = None if self.urinal_blank else water.get("urinal_gpf", 0.0)
        return STVInputs.from_dict(
            {
                "team": self.team,
                "construction_items": [
                    {"assembly": a, "material_type": m, "amount": x} for a, m, x in self.items
                ],
                "use_phase": {**self.use_phase, "water_use": water},
            }
        )


# --- invented inputs ------------------------------------------------------------------

ISLAND_ITEMS = [
    ("Foundation", "Concrete Slab (cy)", 812.5),
    ("Foundation", "Novacem Strip Foundation (cy)", 143.0),
    ("Interior Wall", "Timber Studs and Painted Gypsum (sf)", 18_450.0),
    ("Exterior Wall", "Recycled Brick (sf)", 9_120.0),
    ("Exterior Wall", "Curtain Wall Double Pane (sf)", 4_300.0),
    ("Floor", "Carpet (sf)", 21_000.0),  # unit multiplier 2 in the course catalog
    ("Floor", "Wood System (sf)", 30_000.0),
    ("Roof", "Noxite Membrane (sf)", 11_250.0),  # unit multiplier 3
    ("Roof", "Green Roof (sf)", 2_400.0),
    ("Window", "Triple Pane Plastic Frame (sf)", 3_150.0),
    ("Columns", "Glulam Column (kg)", 96_500.0),  # alias Columns -> Column
    ("Beams", "Glulam Beam (kg)", 143_200.0),  # alias Beams -> Beam
    ("Beams", "Steel Beam (kg)", 22_750.0),
    ("MEP", "Copper Pipe (kg)", 1_830.0),
    ("MEP", "Air Filters (m^3/s)", 12.5),  # unit multiplier 50
    ("Energy", "Photovoltaics (sf)", 6_800.0),
    ("Misc", "C.R. Laurence Shading System (sf)", 1_275.0),
]

RIVER_ITEMS = [
    ("Foundation", "Mat and Pile (cy)", 1_960.0),
    ("Interior Wall", "Steel Studs and Painted Gypsum (sf)", 25_600.0),
    ("Exterior Wall", "EIFS on Metal Stud (sf)", 14_880.0),
    ("Floor", "Concrete and Ceramic (sf)", 41_000.0),
    ("Roof", "Steel Structure (sf)", 13_700.0),
    ("Roof", "EPDM Membrane (sf)", 13_700.0),
    ("Window", "Double Pane Aluminum Frame (sf)", 5_600.0),
    ("Columns", "Steel Column (kg)", 58_300.0),
    ("Columns", "Reinforced Concrete Column (cy)", 212.0),
    ("Beams", "Reinforced Concrete Beam (cy)", 305.5),
    ("MEP", "Heat Pump (nominal tons)", 64.0),
    ("Energy", "EV Battery (kWh)", 250.0),
]

# 41 rows: the full item table, repeated materials across all assemblies.
_FULL_CYCLE = [
    ("Foundation", "Strip Foundation (cy)"),
    ("Interior Wall", "Painted Concrete (sf)"),
    ("Exterior Wall", "Brick on Metal Stud (sf)"),
    ("Floor", "Bubble Deck (sf)"),
    ("Roof", "Wood Structure (sf)"),
    ("Window", "Single Pane Plastic Frame (sf)"),
    ("Columns", "Wood Column (kg)"),
    ("Beams", "Wood Beam (kg)"),
    ("MEP", "HDPE Pipe (kg)"),
    ("Energy", "Flat Plate Solar Thermal (sf)"),
    ("Misc", "Smart Glass (sf)"),
]
FULL_TABLE_ITEMS = [
    (*_FULL_CYCLE[i % len(_FULL_CYCLE)], 100.0 + 37.25 * i)
    for i in range(LAST_ITEM_ROW - FIRST_ITEM_ROW + 1)
]

CASES = [
    Case(
        id="island_no_cogen",
        team="Island",
        items=ISLAND_ITEMS,
        use_phase={
            "electricity_from_grid_kwh": 162_500.0,
            "onsite_renewable_kwh": 40_000.0,
            "natural_gas_m3": 3_200.0,
            "water_use": {
                "toilet_gpf": 1.28,
                "urinal_gpf": 0.125,  # > 0: toilet factor 0.75 in both
                "wc_sink_gpm": 0.5,
                "lab_sink_gpm": 1.5,
                "kitchen_sink_gpm": 1.8,
                "shower_gpm": 1.75,
                "landscaping_gal": 55_000.0,
                "rainwater_collection_gal": 20_000.0,  # below both caps
            },
        },
    ),
    Case(
        id="river_cogen_carbon_energy",
        team="River",
        items=RIVER_ITEMS,
        use_phase={
            "electricity_from_grid_kwh": 98_000.0,
            "cogeneration": {
                "fuel_type": "Natural Gas",
                "electricity_kwh": 120_000.0,
                "electricity_split": 0.5,
                "heating_mj": 310_000.0,
                "heating_split": 0.3,
                "cooling_kwh": 45_000.0,
                "cooling_split": 0.2,
            },
            "water_use": {"toilet_gpf": 1.6, "wc_sink_gpm": 2.2},
        },
        urinal_blank=True,  # no urinals: toilet factor 1.0 in both
    ),
    Case(
        id="pacific_full_table",
        team="Pacific",
        items=FULL_TABLE_ITEMS,
        use_phase={
            "electricity_from_grid_kwh": 250_000.0,
            "water_use": {"toilet_gpf": 1.1, "urinal_gpf": 0.5, "shower_gpm": 2.0},
        },
    ),
]

# Edge cases (formerly course-vs-engine differences, fixed in P3.10).
TOILET_ONLY = {"water_use": {"toilet_gpf": 1.28}}
# Urinal cell D33 = 0 / engine urinal_gpf = 0 (explicit): toilet factor 0.75 in both.
TOILET_URINAL_ZERO = Case(
    id="toilet_urinal_cell_zero",
    team="Island",
    use_phase={"water_use": {"toilet_gpf": 1.28, "urinal_gpf": 0.0}},
)
# Urinal cell D33 blank / engine urinal_gpf = None: toilet factor 1.0 in both.
TOILET_URINAL_BLANK = Case(
    id="toilet_urinal_cell_blank", team="Island", use_phase=TOILET_ONLY, urinal_blank=True
)
# Rainwater above toilet + urinal + landscaping (course cap, P3.10) but below total water
# (the engine's cap before P3.10).
RAINWATER_ABOVE_COURSE_CAP = Case(
    id="rainwater_above_course_cap",
    team="Island",
    use_phase={
        "water_use": {
            "toilet_gpf": 1.28,
            "urinal_gpf": 0.125,
            "wc_sink_gpm": 2.2,
            "shower_gpm": 2.0,
            "landscaping_gal": 10_000.0,
            "rainwater_collection_gal": 1_500_000.0,
        }
    },
)
COGEN_ONLY = Case(
    id="cogen_only",
    team="Island",
    use_phase={
        "cogeneration": {
            "fuel_type": "Natural Gas",
            "electricity_kwh": 120_000.0,
            "electricity_split": 0.5,
            "heating_mj": 310_000.0,
            "heating_split": 0.3,
            "cooling_kwh": 45_000.0,
            "cooling_split": 0.2,
        }
    },
    urinal_blank=True,
)
EDGE_CASES = [TOILET_URINAL_ZERO, TOILET_URINAL_BLANK, RAINWATER_ABOVE_COURSE_CAP, COGEN_ONLY]

# --- P3.8: filled use phase incl. PV, through project_config ---------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_CONFIG = REPO_ROOT / "template" / "project_config.example.json"
FILLED_USE_PHASE = {  # every field stated and non-zero (invented)
    "not_modeled": False,
    "grid_kwh": 85_000,
    "onsite_renewable_kwh": 120_000,
    "natural_gas_m3": 1_500,
    "cogeneration": {"fuel_type": "Natural Gas", "electricity_kwh": 40_000,
                     "heating_mj": 90_000, "cooling_kwh": 15_000,
                     "splits": {"electricity": 0.5, "heating": 0.3, "cooling": 0.2}},
    "water": {"toilet_gpf": 1.1, "urinal_gpf": 0.125, "wc_sink_gpm": 0.5,
              "lab_sink_gpm": 0.8, "kitchen_sink_gpm": 1.5, "shower_gpm": 1.8,
              "landscaping_gal": 30_000, "rainwater_gal": 250_000},
}
CONFIG_ITEMS = [  # PV panels and an EV battery as config construction items (invented)
    {"assembly": "Energy", "material_type": "Photovoltaics (sf)", "amount": 4_200,
     "note": "invented PV area"},
    {"assembly": "Energy", "material_type": "EV Battery (kWh)", "amount": 300,
     "note": "invented battery"},
]


def _config_case(tmp_dir: Path) -> Case:
    """The case as concho-stv --config builds it: STVProjectSettings of a project_config."""
    data = json.loads(TEMPLATE_CONFIG.read_text(encoding="utf-8"))
    data.pop("$schema")
    data["files"] = {}
    data["stv"].update(course_team="Island", use_phase=FILLED_USE_PHASE,
                       construction_items=CONFIG_ITEMS)
    path = tmp_dir / "project_config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    settings = STVProjectSettings.from_config(load_config(path), tmp_dir)
    items = [("Floor", "Wood System (sf)", 12_000.0)] + [
        (i["assembly"], i["material_type"], i["amount"]) for i in settings.construction_items]
    return Case(id="config_use_phase_pv", team=settings.team, items=items,
                use_phase=settings.use_phase)


# --- P3.7: a custom material path ------------------------------------------------------

# 'LCA Data' row of the copy that takes the custom material: QR5 (Turbine), which no formula
# references and no case uses.
CUSTOM_LCA_ROW = 102
CUSTOM_NAME = "Invented Bamboo Beam (kg)"
_CUSTOM_PARTS = {"materials": (-0.35, 11.0, 28.0, 1.2e-8), "transport": (0.12, 1.6, 0.6, 2e-9),
                 "construction": (0.04, 0.45, 1.8, 7e-10)}
_IND = ("gwp_kgco2e", "energy_mj", "water_kg", "odp_kgcfc11e")
CUSTOM_ROW = {
    "assembly": "Beams", "material_type": CUSTOM_NAME, "life_units": "1",
    "source": "invented test EPD, not real data", "is_course_data": "false",
    **{f"{p}_{i}": repr(v[n]) for p, v in _CUSTOM_PARTS.items() for n, i in enumerate(_IND)},
    **{f"embodied_{i}": repr(sum(v[n] for v in _CUSTOM_PARTS.values()))
       for n, i in enumerate(_IND)},
}
CUSTOM_CASE = Case(
    id="custom_material",
    team="Island",
    items=[("Beams", CUSTOM_NAME, 25_000.0), ("Beams", "Glulam Beam (kg)", 10_000.0),
           ("Floor", "Concrete (sf)", 8_000.0)],
    custom_row=CUSTOM_ROW,
)


def _custom_csv() -> str:
    return (",".join(CUSTOM_COLUMNS) + "\n"
            + ",".join(f'"{CUSTOM_ROW[c]}"' for c in CUSTOM_COLUMNS) + "\n")


# --- workbook helpers -----------------------------------------------------------------


def _write_case(template: Path, case: Case, dest: Path) -> None:
    wb = openpyxl.load_workbook(template)
    cm, up = wb[CM], wb[UP]
    cm["C5"] = case.team
    up["C5"] = case.team

    assert len(case.items) <= LAST_ITEM_ROW - FIRST_ITEM_ROW + 1
    for row in range(FIRST_ITEM_ROW, LAST_ITEM_ROW + 1):
        cm[f"B{row}"], cm[f"C{row}"], cm[f"D{row}"] = "Pick Assembly", "Pick Type", None
    for row, (assembly, material, amount) in enumerate(case.items, start=FIRST_ITEM_ROW):
        cm[f"B{row}"], cm[f"C{row}"], cm[f"D{row}"] = assembly, material, amount

    payload = case.use_phase
    for key, cell in USE_PHASE_INPUT_CELLS.items():
        up[cell] = float(payload.get(key, 0.0))
    cogen = payload.get("cogeneration", {})
    up["D22"] = cogen.get("fuel_type") or "Select Fuel"
    for key, cell in COGEN_INPUT_CELLS.items():
        up[cell] = float(cogen.get(key, 0.0))
    water = payload.get("water_use", {})
    for key, cell in WATER_INPUT_CELLS.items():
        up[cell] = float(water.get(key) or 0.0)
    if case.urinal_blank:
        up["D33"] = None
    if case.custom_row is not None:
        lca, r, row = wb["LCA Data"], CUSTOM_LCA_ROW, case.custom_row
        lca[f"B{r}"] = {"Beams": "Beam", "Columns": "Column"}.get(row["assembly"],
                                                                 row["assembly"])
        lca[f"C{r}"] = row["material_type"]
        columns = [f"{p}_{i}" for p in ("embodied", "materials", "transport", "construction")
                   for i in _IND]
        for letter, column in zip("DEFGHIJKLMNOPQRS", columns, strict=True):
            lca[f"{letter}{r}"] = float(row[column])
        lca[f"T{r}"] = float(row["life_units"])
    wb.save(dest)


def _recalculate(sources: list[Path], out_dir: Path, profile_dir: Path) -> None:
    """Recalculate xlsx files with LibreOffice headless (one soffice call for all)."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        pytest.skip("LibreOffice (soffice) not found; needed to recalculate the course workbook")
    cmd = [
        soffice,
        f"-env:UserInstallation={profile_dir.as_uri()}",
        "--headless",
        "--calc",
        "--convert-to",
        "xlsx",
        "--outdir",
        str(out_dir),
        *map(str, sources),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    missing = [p.name for p in sources if not (out_dir / p.name).is_file()]
    assert not missing, (
        f"LibreOffice did not produce {missing} (is the Calc component installed?)\n"
        f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    )


def _cells(ws, cells) -> tuple[float, ...]:
    return tuple(float(ws[c].value) for c in cells)


def _max_rel_err(course: tuple[float, ...], engine: tuple[float, ...]) -> float:
    return max((abs(c - e) / abs(c) if c else abs(e)) for c, e in zip(course, engine, strict=True))


def p37_p38_cases(base: Path) -> list[Case]:
    return [CUSTOM_CASE, _config_case(base)]


@pytest.fixture(scope="module")
def template() -> Path:
    return Path(os.environ["COURSE_STV_XLSX"])


@pytest.fixture(scope="module")
def engine(template) -> STVEngine:
    """Engine on the workbook as supplied (what ``concho-stv`` uses)."""
    return STVEngine(STVReferenceData.from_workbook(template))


@pytest.fixture(scope="module")
def recalculated(template, tmp_path_factory) -> Path:
    """Directory with all case copies, plus the unchanged template, recalculated."""
    base = tmp_path_factory.mktemp("stv_course")
    src_dir, out_dir = base / "in", base / "out"
    src_dir.mkdir()
    out_dir.mkdir()
    # openpyxl drops all cached formula values on save, so LibreOffice recomputes every cell.
    openpyxl.load_workbook(template).save(src_dir / f"{TEMPLATE_ID}.xlsx")
    sources = [src_dir / f"{TEMPLATE_ID}.xlsx"]
    for case in [*CASES, *EDGE_CASES, *p37_p38_cases(base)]:
        path = src_dir / f"{case.id}.xlsx"
        _write_case(template, case, path)
        sources.append(path)
    _recalculate(sources, out_dir, base / "lo_profile")
    return out_dir


@pytest.fixture(scope="module")
def engine_recalculated(recalculated) -> STVEngine:
    """Engine on reference data read from the recalculated, otherwise unchanged template."""
    return STVEngine(STVReferenceData.from_workbook(recalculated / f"{TEMPLATE_ID}.xlsx"))


@pytest.fixture(scope="module")
def course(recalculated) -> dict[str, dict]:
    """Course results per case id, read from the recalculated copies."""
    results = {}
    for case in [*CASES, *EDGE_CASES, CUSTOM_CASE, _config_case(recalculated.parent)]:
        wb = openpyxl.load_workbook(recalculated / f"{case.id}.xlsx", data_only=True)
        results[case.id] = {
            "targets": _cells(wb[CM], TARGET_CELLS),
            "embodied": _cells(wb[CM], EMBODIED_CELLS),
            "use_phase": _cells(wb[UP], USE_PHASE_CELLS),
            "use_rows": {
                row: _cells(wb[UP], [f"{col}{row}" for col in "FGHI"])
                for row in (32, 33, 38, 39, 40)
            },
        }
    return results


def _vector(v) -> tuple[float, ...]:
    return tuple(v.get(m) for m in METRICS)


# --- equivalence ----------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_embodied_matches_course(case, engine_recalculated, course):
    got = engine_recalculated.calculate(case.engine_inputs())
    expected = course[case.id]["embodied"]
    actual = _vector(got.breakdown.embodied)
    print(f"{case.id} embodied max rel err {_max_rel_err(expected, actual):.3e}")
    assert actual == pytest.approx(expected, rel=REL)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_targets_match_course(case, engine, course):
    # Also proves the copy was recalculated for this case's team.
    got = engine.calculate(case.engine_inputs())
    assert _vector(got.targets)[:3] == pytest.approx(course[case.id]["targets"], rel=REL)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_use_phase_matches_course(case, engine, course):
    # All four metrics, incl. cogeneration water/ODP (fixed in P3.10).
    got = engine.calculate(case.engine_inputs())
    expected = course[case.id]["use_phase"]
    actual = _vector(got.breakdown.use_phase)
    print(f"{case.id} use phase max rel err {_max_rel_err(expected, actual):.3e}")
    assert actual == pytest.approx(expected, rel=REL)


def test_cogen_matches_course(engine, course):
    """P3.10 item 1: course cogeneration water/ODP use 'Cogen Data' columns G (H2O) and H
    (ODP) divided by I (MJ/kg); the engine read F and G before. Cogeneration only, so the
    comparison isolates it; all four metrics match now.
    """
    got = engine.calculate(COGEN_ONLY.engine_inputs())
    course_use = course[COGEN_ONLY.id]["use_phase"]
    engine_use = _vector(got.breakdown.use_phase)

    print(
        f"cogen only: use-phase water course {course_use[2]:.6g} vs engine {engine_use[2]:.6g}, "
        f"ODP course {course_use[3]:.6g} vs engine {engine_use[3]:.6g}"
    )
    assert engine_use[2] > 0 and engine_use[3] > 0
    assert engine_use == pytest.approx(course_use, rel=REL)


# --- documented differences (engine unchanged) -----------------------------------------


@pytest.mark.parametrize("case", [TOILET_URINAL_ZERO, TOILET_URINAL_BLANK], ids=lambda c: c.id)
def test_toilet_factor_matches_course(case, engine, course):
    """P3.10 item 3 (decision D11): the course applies the 0.75 toilet factor whenever the
    urinal cell D33 is non-blank, even 0. Engine: ``urinal_gpf`` 0 -> 0.75, None -> 1.0.
    With only a toilet flow rate, D33 = 0 gives 0.75 x the blank-cell use phase.
    """
    engine_use = _vector(engine.calculate(case.engine_inputs()).breakdown.use_phase)
    course_use = course[case.id]["use_phase"]
    print(f"{case.id}: use-phase water course {course_use[2]:,.0f} kg, "
          f"engine {engine_use[2]:,.0f} kg")
    assert engine_use == pytest.approx(course_use, rel=REL)


def test_toilet_factor_zero_vs_blank(course):
    zero = course[TOILET_URINAL_ZERO.id]["use_phase"]
    blank = course[TOILET_URINAL_BLANK.id]["use_phase"]
    assert zero == pytest.approx(tuple(0.75 * v for v in blank), rel=REL)


def test_rainwater_cap_matches_course(engine, course):
    """P3.10 item 2 (decision D12, follow the course): the rainwater credit is capped at
    toilet + urinal + landscaping water (``H40 = -MIN(D40*..., H32+H33+H38)``), not at the
    total water use. With rainwater above that cap the sink/shower water remains.
    """
    case = RAINWATER_ABOVE_COURSE_CAP
    engine_use = _vector(engine.calculate(case.engine_inputs()).breakdown.use_phase)
    course_use = course[case.id]["use_phase"]
    water = {row: v[2] for row, v in course[case.id]["use_rows"].items()}

    print(
        f"rainwater above course cap: use-phase water course {course_use[2]:,.0f} kg, "
        f"engine {engine_use[2]:,.0f} kg"
    )
    capped = water[32] + water[33] + water[38]
    assert water[40] == pytest.approx(-capped, rel=REL)
    assert course_use[2] == pytest.approx(50 * (water[39] - capped), rel=REL)
    assert course_use[2] > 0
    assert engine_use == pytest.approx(course_use, rel=REL)


def test_embodied_odp_from_supplied_workbook_differs(engine, engine_recalculated, course):
    """The supplied workbook caches stale values for some LCA component cells ('LCA Data'
    K/O/S: small constants such as ``=x*10^-11`` are cached as 0), while the totals D-G
    that the course formulas use are cached correctly. The engine sums the components, so
    on the supplied file its embodied ODP is slightly low. GWP, energy and water are not
    affected; a recalculated template matches (``test_embodied_matches_course``).
    """
    for case in CASES:
        supplied = _vector(engine.calculate(case.engine_inputs()).breakdown.embodied)
        fresh = _vector(engine_recalculated.calculate(case.engine_inputs()).breakdown.embodied)
        expected = course[case.id]["embodied"]
        print(
            f"{case.id} embodied, supplied workbook: max rel err "
            f"GWP/energy/water {_max_rel_err(expected[:3], supplied[:3]):.3e}, "
            f"ODP {_max_rel_err(expected[3:], supplied[3:]):.3e}"
        )
        assert supplied[:3] == pytest.approx(expected[:3], rel=REL)
        assert fresh[3] == pytest.approx(expected[3], rel=REL)
        assert supplied[3] < expected[3]


# --- P3.7 / P3.8 ----------------------------------------------------------------------


def test_config_use_phase_with_pv_matches_course(engine_recalculated, course, recalculated):
    """P3.8: every use-phase field filled (cogeneration, gas, all water incl. rainwater) and
    PV + EV battery as Energy construction items, all through project_config: embodied, use
    phase and targets match the course sheets."""
    case = _config_case(recalculated.parent)
    got = engine_recalculated.calculate(case.engine_inputs())
    expected = course[case.id]
    assert _vector(got.breakdown.embodied) == pytest.approx(expected["embodied"], rel=REL)
    assert _vector(got.breakdown.use_phase) == pytest.approx(expected["use_phase"], rel=REL)
    assert _vector(got.targets)[:3] == pytest.approx(expected["targets"], rel=REL)
    assert all(v != 0 for v in expected["use_phase"])
    print(f"config use phase + PV: use phase max rel err "
          f"{_max_rel_err(expected['use_phase'], _vector(got.breakdown.use_phase)):.3e}")


def test_custom_material_matches_course(recalculated, course):
    """P3.7: a custom material from custom_materials.csv, used like a catalog entry, gives
    the embodied impacts the course sheet computes for the same values in 'LCA Data'."""
    reference = STVReferenceData.from_workbook(recalculated / f"{TEMPLATE_ID}.xlsx")
    custom = validate_custom_materials_text(_custom_csv(), catalog=reference)
    assert custom.ok, custom.errors
    reference.add_custom_materials(custom)
    got = STVEngine(reference).calculate(CUSTOM_CASE.engine_inputs())
    expected = course[CUSTOM_CASE.id]["embodied"]
    print(f"custom material: embodied max rel err "
          f"{_max_rel_err(expected, _vector(got.breakdown.embodied)):.3e}")
    assert _vector(got.breakdown.embodied) == pytest.approx(expected, rel=REL)
    flags = got.to_dict()["data_flags"]
    assert flags["custom_material"] and flags["by_assembly"]["Beams"]["custom_material"]
    assert not flags["by_assembly"]["Floor"]["custom_material"]


@pytest.mark.parametrize("path", [
    TEMPLATE_CONFIG,
    REPO_ROOT / "engines/common/examples/island_2026_use_phase.project_config.json",
], ids=["template", "island_use_phase"])
def test_config_construction_items_are_course_catalog_entries(engine, path):
    """P3.8: the shipped configs' construction items (PV) name course catalog entries."""
    settings = STVProjectSettings.from_config(load_config(path), path.parent)
    assert settings.construction_items
    for item in settings.construction_items:
        engine.reference_data.validate_item(item["assembly"], item["material_type"])
