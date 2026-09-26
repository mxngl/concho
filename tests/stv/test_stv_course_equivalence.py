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

Known differences between the engine and the course (engine left unchanged, see the
``test_*_differs`` test): the stale cached LCA component values of the supplied workbook.
Fixed in P3.10 and now compared like the main cases: the cogeneration water/ODP columns
(``test_cogen_matches_course``), the rainwater cap (``test_rainwater_cap_matches_course``)
and the toilet factor with a urinal cell of 0 (``test_toilet_factor_matches_course``).
"""

from __future__ import annotations

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

from engines.stv import STVEngine, STVInputs  # noqa: E402
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
    for case in [*CASES, *EDGE_CASES]:
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
    for case in [*CASES, *EDGE_CASES]:
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
