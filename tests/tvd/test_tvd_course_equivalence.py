"""P2.5: TVD line items vs. the course workbook, same line items on both sides.

Skipped unless ``COURSE_TVD_XLSX`` points to the course workbook
(``PBL_Lab_TVD-collaboration_tool.xlsx``). The workbook is course data and is never
committed (roadmap §0, hard rule 2).

Each case writes line items (Total O&P and Quantity per Uniformat subcode) into the line
rows of the cluster sheets ("A Substructure" ... "H Gen. Cond.") of a temporary copy of the
workbook, after clearing the sample line items there, and recalculates the copy with
LibreOffice headless (``soffice --convert-to xlsx``). The course results are compared with
``engines.tvd.engine.compute`` for the same items, at four levels:

- line totals (cluster sheet column T of each line row),
- subcode sums (cluster sheet column T of each subcode row),
- cluster sums (cluster sheet ``T14``),
- "TVD Summary" subcode, cluster and total rows (column C).

Quantities reach the engine either through takeoff elements (clusters A-C) or through the
cost DB's Fixed Quantity (all other clusters), as in the Island cost DB. The engine rounds
quantities and line totals to cents (the A1020 line below: 240.75 x 215.5 = 51,881.625), so
lines are kept large enough for that to stay within the 1e-6 tolerance. All unit costs,
quantities and descriptions are invented; they are not RSMeans or course data.

Not compared, because ``engines/tvd`` does not implement them yet (P3.5): target
derivation ("TVD Targets"), owner reallocation ("TVD Owners"), reliability ratings
(columns N-P and "TVD Reliability") and "TVD Tracking".
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("COURSE_TVD_XLSX"),
    reason="COURSE_TVD_XLSX not set (course workbook must be supplied locally)",
)

openpyxl = pytest.importorskip("openpyxl")

from engines.tvd.engine import compute  # noqa: E402
from engines.tvd.summary import grand_total_of  # noqa: E402

REL = 1e-6
SUMMARY = "TVD Summary"

# Cluster letter -> (course sheet, engine cluster name). Engine names follow the Island
# cost DB; clusters A-C use takeoff quantities (engines/tvd/island_defaults.py).
CLUSTERS = {
    "A": ("A Substructure", "Substructure"),
    "B": ("B Shell", "Shell"),
    "C": ("C Interiors", "Interiors"),
    "D": ("D Services", "Services"),
    "E": ("E Equip. and Furn.", "Equipment and Furnishings"),
    "F": ("F Special Const.", "Special Construction"),
    "G": ("G Bldg. Sitework", "Building Sitework"),
    "H": ("H Gen. Cond.", "General Conditions"),
}
# "TVD Summary" column C rows: cluster rows and subcode rows (codes as in the cluster
# sheets; the H rows are labelled without codes in the summary).
SUMMARY_TOTAL_ROW = 6
SUMMARY_CLUSTER_ROWS = {"A": 7, "B": 11, "C": 18, "D": 26, "E": 38, "F": 41, "G": 44, "H": 50}
SUMMARY_SUBCODE_ROWS = {
    "A1020": 8, "A1030": 9, "A2020": 10,
    "B1010": 12, "B1020": 13, "B2010": 14, "B2020": 15, "B2030": 16, "B3010": 17,
    "C1010": 19, "C1020": 20, "C1030": 21, "C2010": 22, "C3010": 23, "C3020": 24, "C3030": 25,
    "D1010": 27, "D2010": 28, "D2020": 29, "D2040": 30, "D3050": 31, "D4010": 32,
    "D4020": 33, "D5010": 34, "D5020": 35, "D5030": 36, "D5090": 37,
    "E1020": 39, "E2010": 40,
    "F1000": 42, "F2000": 43,
    "G1030": 45, "G2050": 46, "G3010": 47, "G3020": 48, "G4010": 49,
    "H1000": 51, "H2000": 52, "H3000": 53, "H4000": 54, "H5000": 55,
}  # fmt: skip


@dataclass
class Item:
    """One line item. ``elements`` are takeoff quantity strings (clusters A-C); without
    them the quantity goes to the engine as Fixed Quantity."""

    ac: str
    unit: str
    total_op: float
    qty: float
    elements: list[dict] = field(default_factory=list)

    @property
    def cluster(self) -> str:
        return self.ac[0]


def _areas(*sf: float) -> list[dict]:
    return [{"Area": f"{a} SF"} for a in sf]


def _lengths(*lf: float) -> list[dict]:
    return [{"Length": f"{x}"} for x in lf]


def _volumes_cf(*cf: float) -> list[dict]:
    return [{"Volume": f"{v} CF"} for v in cf]


def _count(n: int) -> list[dict]:
    return [{} for _ in range(n)]


# --- invented line items ------------------------------------------------------------------

ALL_CLUSTERS = [
    Item("A1020", "LF", 240.75, 215.5, _lengths(120.0, 95.5)),
    Item("A1030", "SF", 7.43, 10_000.0, _areas(4_200, 5_800)),
    Item("A2020", "CY", 512.30, 100.0, _volumes_cf(1_350, 1_350)),
    Item("B1010", "SF", 18.65, 30_000.0, _areas(12_000, 9_500, 8_500)),
    Item("B1010", "SF", 2.50, 4_000.0),  # second line in the same subcode (fixed qty)
    Item("B2020", "EA", 1_450.00, 36.0, _count(36)),
    Item("B2030", "EA", 3_875.50, 6.0, _count(6)),
    Item("C1010", "SF", 11.20, 18_400.0, _areas(10_000, 8_400)),
    Item("C1020", "EA", 1_245.00, 42.0, _count(42)),
    Item("C2010", "FLIGHT", 18_250.00, 4.0, _count(4)),
    Item("D1010", "EA", 145_000.00, 2.0),
    Item("D2010", "EA", 2_860.00, 48.0),
    Item("D3050", "SF", 26.40, 30_000.0),
    Item("D5020", "SF", 14.75, 30_000.0),
    Item("E1020", "LS", 85_000.00, 1.0),
    Item("F1000", "LS", 240_000.00, 1.0),
    Item("G1030", "CY", 18.90, 6_500.0),
    Item("G2050", "SF", 6.25, 12_000.0),
    Item("H1000", "LS", 320_000.00, 1.0),
    Item("H4000", "LS", 501_000.00, 1.0),
]

# B3010 and C3030 both filled: exposes the "TVD Summary"!C25 reference (see test below).
CEILING_AND_ROOF_COVERINGS = [
    Item("B3010", "SF", 9.80, 11_000.0),
    Item("C3030", "SF", 7.35, 24_000.0),
    Item("C1010", "SF", 11.20, 5_000.0, _areas(5_000)),
    Item("D2010", "EA", 2_860.00, 10.0),
]

CASES = {"all_clusters": ALL_CLUSTERS, "ceiling_and_roof_coverings": CEILING_AND_ROOF_COVERINGS}


# --- engine side ----------------------------------------------------------------------------


def _engine_rows(items: list[Item]) -> tuple[list[dict], list[dict]]:
    """Takeoff rows and cost DB rows (AutoTVD CSV column names) for the items."""
    takeoff, cost = [], []
    for i, item in enumerate(items):
        fixed = "" if item.elements else f"{item.qty}"
        cost.append(
            {
                "Cluster Name": CLUSTERS[item.cluster][1],
                "Assembly Code": item.ac,
                "Assembly Group Name": "",
                "Description             ": f"Invented item {i}",
                "Unit             ": item.unit,
                "Total O&P": f"{item.total_op}",
                "Fixed Quantity": fixed,
            }
        )
        for j, element in enumerate(item.elements):
            takeoff.append(
                {
                    "ElementId": f"{i}-{j}",
                    "Category": "Generic Models",
                    "Family": "Invented",
                    "Type": "Invented",
                    "Mark": "",
                    "Comments": "",
                    "Assembly Code": item.ac,
                    **element,
                }
            )
    return takeoff, cost


def _engine(items: list[Item]):
    takeoff, cost = _engine_rows(items)
    run = compute(takeoff, [], cost)
    assert len(run.results) == len(items)
    subcodes: dict[str, float] = defaultdict(float)
    for r in run.results:
        subcodes[r["ac"]] += r["total"]
    clusters = {r["cluster"]: r["total"] for r in run.summary if r["cluster"] != "GRAND TOTAL"}
    return run, dict(subcodes), clusters, grand_total_of(run.summary)


# --- workbook side --------------------------------------------------------------------------


def _layout(ws) -> dict[str, tuple[int, list[int]]]:
    """Subcode -> (subcode row, line rows), read from the cluster sheet formulas."""
    layout = {}
    for ref in re.findall(r"T(\d+)", ws["T14"].value):
        row = int(ref)
        code = str(ws[f"C{row}"].value).split()[0]
        m = re.fullmatch(r"=SUM\(T(\d+)(?::T(\d+))?\)", ws[f"T{row}"].value)
        first, last = int(m.group(1)), int(m.group(2) or m.group(1))
        layout[code] = (row, list(range(first, last + 1)))
    return layout


def _write_case(template: Path, items: list[Item], dest: Path) -> dict[int, tuple[str, int]]:
    """Write items into a copy; return item index -> (sheet, line row)."""
    wb = openpyxl.load_workbook(template)
    placed = {}
    for letter, (sheet, _) in CLUSTERS.items():
        ws = wb[sheet]
        layout = _layout(ws)
        for _, lines in layout.values():
            for row in lines:  # clear the sample line items shipped with the workbook
                for col in "DEFGHIKNO":
                    ws[f"{col}{row}"] = None
        free = {code: list(lines) for code, (_, lines) in layout.items()}
        for i, item in enumerate(items):
            if item.cluster != letter:
                continue
            row = free[item.ac].pop(0)
            ws[f"D{row}"] = f"INVENTED-{i}"
            ws[f"E{row}"] = f"Invented item {i}"
            ws[f"F{row}"] = item.unit
            ws[f"I{row}"] = item.total_op
            ws[f"K{row}"] = item.qty
            placed[i] = (sheet, row)
    wb.save(dest)
    return placed


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


@pytest.fixture(scope="module")
def template() -> Path:
    return Path(os.environ["COURSE_TVD_XLSX"])


@pytest.fixture(scope="module")
def course(template, tmp_path_factory) -> dict[str, dict]:
    """Per case: recalculated workbook (values) plus where each item was placed."""
    base = tmp_path_factory.mktemp("tvd_course")
    src_dir, out_dir = base / "in", base / "out"
    src_dir.mkdir()
    out_dir.mkdir()
    placed = {}
    for case_id, items in CASES.items():
        placed[case_id] = _write_case(template, items, src_dir / f"{case_id}.xlsx")
    _recalculate([src_dir / f"{c}.xlsx" for c in CASES], out_dir, base / "lo_profile")

    layouts = {}
    wb_formulas = openpyxl.load_workbook(template)
    for sheet, _ in CLUSTERS.values():
        layouts[sheet] = _layout(wb_formulas[sheet])
    return {
        case_id: {
            "wb": openpyxl.load_workbook(out_dir / f"{case_id}.xlsx", data_only=True),
            "placed": placed[case_id],
            "layouts": layouts,
        }
        for case_id in CASES
    }


def _num(value) -> float:
    return 0.0 if value in (None, "") else float(value)


def _rel_err(course_value: float, engine_value: float) -> float:
    if not course_value:
        return abs(engine_value)
    return abs(course_value - engine_value) / abs(course_value)


# --- equivalence ----------------------------------------------------------------------------


@pytest.mark.parametrize("case_id", CASES)
def test_line_totals_match_course(case_id, course):
    items, c = CASES[case_id], course[case_id]
    run, _, _, _ = _engine(items)
    errs = []
    for i, (item, line) in enumerate(zip(items, run.results, strict=True)):
        assert line["qty"] == pytest.approx(item.qty, rel=REL), f"engine qty, item {i}"
        sheet, row = c["placed"][i]
        expected = _num(c["wb"][sheet][f"T{row}"].value)
        errs.append(_rel_err(expected, line["total"]))
        assert line["total"] == pytest.approx(expected, rel=REL), f"{item.ac} line {i}"
    print(f"{case_id} line totals max rel err {max(errs):.3e}")


@pytest.mark.parametrize("case_id", CASES)
def test_subcode_and_cluster_sums_match_course(case_id, course):
    items, c = CASES[case_id], course[case_id]
    _, subcodes, clusters, _ = _engine(items)
    errs = []
    for sheet, engine_cluster in CLUSTERS.values():
        ws = c["wb"][sheet]
        for code, (row, _) in c["layouts"][sheet].items():
            expected = _num(ws[f"T{row}"].value)
            actual = subcodes.get(code, 0.0)
            errs.append(_rel_err(expected, actual))
            assert actual == pytest.approx(expected, rel=REL), f"{sheet} {code}"
        expected = _num(ws["T14"].value)
        actual = clusters.get(engine_cluster, 0.0)
        errs.append(_rel_err(expected, actual))
        assert actual == pytest.approx(expected, rel=REL), f"{sheet} T14"
    print(f"{case_id} subcode/cluster sums max rel err {max(errs):.3e}")


@pytest.mark.parametrize("case_id", ["all_clusters"])
def test_tvd_summary_matches_course(case_id, course):
    """All "TVD Summary" subcode, cluster and total rows (case without B3010/C3030)."""
    items, c = CASES[case_id], course[case_id]
    _, subcodes, clusters, grand_total = _engine(items)
    ws = c["wb"][SUMMARY]
    errs = []
    checks = [(f"C{row}", subcodes.get(code, 0.0)) for code, row in SUMMARY_SUBCODE_ROWS.items()]
    checks += [
        (f"C{row}", clusters.get(CLUSTERS[letter][1], 0.0))
        for letter, row in SUMMARY_CLUSTER_ROWS.items()
    ]
    checks.append((f"C{SUMMARY_TOTAL_ROW}", grand_total))
    for cell, actual in checks:
        expected = _num(ws[cell].value)
        errs.append(_rel_err(expected, actual))
        assert actual == pytest.approx(expected, rel=REL), f"{SUMMARY}!{cell}"
    assert grand_total > 0
    print(f"{case_id} TVD Summary max rel err {max(errs):.3e}, grand total {grand_total:,.2f}")


# --- documented course-workbook quirk ---------------------------------------------------------


def test_summary_ceiling_finishes_row_references_roof_coverings(template, course):
    """The "TVD Summary"!C25 ("C3030 Ceiling Finishes") is ``='B Shell'!T30`` (B3010 Roof
    Coverings), not ``='C Interiors'!T27``. So the summary counts B3010 twice (in B Shell and
    in C Interiors) and drops C3030. The cluster sheets themselves are right and match the
    engine; only the summary's C Interiors row and total are off by B3010 - C3030.
    """
    assert openpyxl.load_workbook(template)[SUMMARY]["C25"].value == "='B Shell'!T30"

    case_id = "ceiling_and_roof_coverings"
    _, subcodes, clusters, grand_total = _engine(CASES[case_id])
    ws = course[case_id]["wb"][SUMMARY]
    shift = subcodes["B3010"] - subcodes["C3030"]
    assert shift != 0

    assert _num(ws["C25"].value) == pytest.approx(subcodes["B3010"], rel=REL)
    assert _num(ws["C18"].value) == pytest.approx(clusters["Interiors"] + shift, rel=REL)
    assert _num(ws["C6"].value) == pytest.approx(grand_total + shift, rel=REL)
    # The cluster sheet itself matches the engine.
    assert _num(course[case_id]["wb"]["C Interiors"]["T14"].value) == pytest.approx(
        clusters["Interiors"], rel=REL
    )
