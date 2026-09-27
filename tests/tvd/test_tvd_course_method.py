"""P3.5: target derivation and reliability summary vs. the course TVD workbook.

Skipped unless ``COURSE_TVD_XLSX`` points to the course workbook
(``PBL_Lab_TVD-collaboration_tool.xlsx``). The workbook is course data and is never
committed (roadmap §0, hard rule 2): every input below is read from it at runtime, nothing
from it is copied into the repo.

Target derivation (sheets "TVD Targets" and "TVD Owners", the workbook's sample inputs and
its cached results): the sample budget inputs (C5:C9), team target (C11), reference shares
(G5:J12), owner value items and ratings (TVD Owners B6:E20), reallocation % (TVD Owners
C22) and target shares (N5:N12) become a ``tvd`` config section; the engine must reproduce
the budget C10, the reference average K5:K12, the owner-adjusted split L5:L12 and the $
rows G16:J23, L16:L23 and N16:N23 (K16:K23 are empty in the course sheet). A second check
sets C22 to 25 % in a copy (recalculated with LibreOffice) and pins the course's
``G / C22 / 100`` owner term, which no longer sums to 100 % (the engine does).

Reliability (cluster sheets, rows with ratings 1/2/3 in column M and ``SUMIF`` in N:P, e.g.
``'A Substructure'!M26:P28``, and "TVD Reliability"): the sample line items of all eight
cluster sheets (Total O&P, quantity, quantity and cost reliability) become ``fixed`` cost DB
rows; the engine's per-cluster sums by High/Medium/Low must match N:P. A second case with
invented line items (partly rated, unrated) is written into a copy and recalculated. The
"TVD Reliability" sheet's reference errors (E14 -> W30, LOW totals without H) are pinned.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("COURSE_TVD_XLSX"),
    reason="COURSE_TVD_XLSX not set (course workbook must be supplied locally)",
)

openpyxl = pytest.importorskip("openpyxl")

from test_tvd_course_equivalence import CLUSTERS, _layout, _num, _recalculate  # noqa: E402

from engines.common.config import CourseCluster, TVDSection, load_config  # noqa: E402
from engines.tvd.cost_db import cost_db_from_dicts  # noqa: E402
from engines.tvd.derivation import course_owner_term, derive_targets  # noqa: E402
from engines.tvd.engine import compute  # noqa: E402

REL = 1e-9  # target derivation: plain float arithmetic on both sides
REL_COST = 1e-6  # reliability: the engine rounds line totals to cents
TARGETS, OWNERS, RELIABILITY = "TVD Targets", "TVD Owners", "TVD Reliability"
LETTERS = [c.value for c in CourseCluster]
TARGET_ROWS = dict(zip(LETTERS, range(5, 13), strict=True))  # share rows 5-12
AMOUNT_ROWS = dict(zip(LETTERS, range(16, 24), strict=True))  # $ rows 16-23
REF_COLS = "GHIJ"
LEVEL_OF = {1: "high", 2: "medium", 3: "low"}
ISLAND_CONFIG = (
    Path(__file__).resolve().parents[2]
    / "engines" / "common" / "examples" / "island_2026.project_config.json"
)


@pytest.fixture(scope="module")
def template() -> Path:
    return Path(os.environ["COURSE_TVD_XLSX"])


@pytest.fixture(scope="module")
def values(template):
    """The workbook with its cached values (as last calculated by the course's Excel)."""
    return openpyxl.load_workbook(template, data_only=True)


@pytest.fixture(scope="module")
def formulas(template):
    return openpyxl.load_workbook(template)


# --- target derivation: workbook inputs -> tvd config -------------------------------------


def _owner_ratings(ws) -> dict:
    """TVD Owners: owners from the header row (D5, E5, ...), value items grouped by the
    cluster labels in column B (``A Substructure`` ... ``H General Conditions``)."""
    owner_cols = []
    for col in "DEFGH":
        head = ws[f"{col}5"].value
        if head and "Owner" in str(head) and "Average" not in str(head):
            owner_cols.append(col)
    owners = [str(ws[f"{c}5"].value) for c in owner_cols]
    items: dict[str, list] = {x: [] for x in LETTERS}
    cluster = None
    for row in range(6, 21):
        label = ws[f"B{row}"].value
        if label:
            cluster = str(label).strip()[0]
        name = ws[f"C{row}"].value
        if not name:
            continue
        ratings = {o: (None if ws[f"{c}{row}"].value in (None, "") else ws[f"{c}{row}"].value)
                   for o, c in zip(owners, owner_cols, strict=True)}
        items[cluster].append({"item": str(name), "ratings": ratings})
    return {"owners": owners, "items": items}


def _tvd_section(wb, *, target_shares: bool) -> TVDSection:
    t, o = wb[TARGETS], wb[OWNERS]
    data = {
        "budget": {
            "grant": t["C5"].value,
            "grant_year": int(t["C6"].value),
            "construction_year": int(t["C7"].value),
            "inflation": t["C8"].value,
            "roi": t["C9"].value,
        },
        "target": t["C11"].value,
        "cluster_split": {
            "method": "derive_from_references",
            "reference_columns": [
                {"name": str(t[f"{col}4"].value),
                 "shares": {x: _num(t[f"{col}{TARGET_ROWS[x]}"].value) for x in LETTERS}}
                for col in REF_COLS
            ],
            "owner_ratings": _owner_ratings(o),
            "reallocation_pct": o["C22"].value,
            "team_adjustment": {x: _num(t[f"M{TARGET_ROWS[x]}"].value) for x in LETTERS},
            "target_shares": (
                {x: _num(t[f"N{TARGET_ROWS[x]}"].value) for x in LETTERS}
                if target_shares else None
            ),
        },
    }
    return TVDSection.model_validate(data)


def test_budget_matches_course_c10(values):
    d = derive_targets(_tvd_section(values, target_shares=True))
    assert d.budget_amount == pytest.approx(values[TARGETS]["C10"].value, rel=REL)
    assert d.total_target == values[TARGETS]["C11"].value
    assert d.target_above_budget is (values[TARGETS]["C11"].value > values[TARGETS]["C10"].value)


def test_reference_average_and_owner_split_match_course(values, formulas):
    # The engine's formulas are the intended ones; the course's L uses G / C22 / 100, which
    # equals G x C22 at the workbook's 10 %.
    assert values[OWNERS]["C22"].value == pytest.approx(0.10)
    assert formulas[OWNERS]["H6"].value == "=G6/$C$22/100"
    d = derive_targets(_tvd_section(values, target_shares=True))
    t = values[TARGETS]
    for x in LETTERS:
        row = TARGET_ROWS[x]
        assert d.course.reference_average[x] == pytest.approx(t[f"K{row}"].value, rel=REL), x
        assert d.course.owner_adjusted[x] == pytest.approx(t[f"L{row}"].value, rel=REL), x
    assert sum(d.course.owner_adjusted.values()) == pytest.approx(1.0, abs=1e-12)


def test_owner_shares_match_course(values, formulas):
    """TVD Owners G per cluster (the cluster label rows)."""
    d = derive_targets(_tvd_section(values, target_shares=True))
    o = values[OWNERS]
    for row in range(6, 21):
        label = o[f"B{row}"].value
        if not label:
            continue
        x = str(label).strip()[0]
        assert d.course.owner_value[x] == pytest.approx(o[f"F{row}"].value, rel=REL), x
        assert d.course.owner_share[x] == pytest.approx(o[f"G{row}"].value, rel=REL), x


@pytest.mark.parametrize("target_shares", [True, False], ids=["course_N", "L_plus_M"])
def test_amount_rows_match_course(values, target_shares):
    """$ rows G16:J23 (references), L16:L23 (owner-adjusted), M16:M23 (team, 0 in the
    sample) and N16:N23 (targets; with target_shares = N5:N12, else L + M = L here)."""
    d = derive_targets(_tvd_section(values, target_shares=target_shares))
    t = values[TARGETS]
    names = [str(t[f"{col}4"].value) for col in REF_COLS]
    block = d.block()
    for x in LETTERS:
        row = AMOUNT_ROWS[x]
        c = block["clusters"][x]
        for col, name in zip(REF_COLS, names, strict=True):
            assert d.amount(d.course.references[name][x]) == pytest.approx(
                t[f"{col}{row}"].value, rel=REL), f"{col}{row}"
            assert c["amounts"]["references"][name] == round(t[f"{col}{row}"].value, 2)
        assert d.amount(d.course.owner_adjusted[x]) == pytest.approx(t[f"L{row}"].value, rel=REL)
        assert d.amount(d.course.team_adjustment[x]) == pytest.approx(_num(t[f"M{row}"].value))
        expected = t[f"N{row}"].value if target_shares else t[f"L{row}"].value
        assert d.final_amount[CourseCluster(x)] == pytest.approx(expected, rel=REL), f"N{row}"
    assert t["K24"].value == 0  # the course's K $ row is empty (K16:K23 not filled)
    assert sum(d.final_amount.values()) == pytest.approx(t["N24"].value, rel=REL)


def test_course_owner_term_breaks_shares_for_other_reallocation(template, tmp_path):
    """With C22 = 25 % the course's H = G / C22 / 100 sums to 0.04 and L to 0.79; the
    engine's L = K x 0.75 + G x 0.25 sums to 1."""
    wb = openpyxl.load_workbook(template)
    wb[OWNERS]["C22"] = 0.25
    src, out = tmp_path / "in", tmp_path / "out"
    src.mkdir()
    out.mkdir()
    wb.save(src / "realloc25.xlsx")
    _recalculate([src / "realloc25.xlsx"], out, tmp_path / "lo_profile")
    course = openpyxl.load_workbook(out / "realloc25.xlsx", data_only=True)

    t, o = course[TARGETS], course[OWNERS]
    assert o["H21"].value == pytest.approx(0.04, rel=1e-9)
    assert t["L13"].value == pytest.approx(0.79, rel=1e-9)

    d = derive_targets(_tvd_section(course, target_shares=False))
    assert d.course.reallocation_pct == 0.25
    assert sum(d.course.owner_adjusted.values()) == pytest.approx(1.0, abs=1e-12)
    for x in LETTERS:
        k, g = d.course.reference_average[x], d.course.owner_share[x]
        assert d.course.owner_adjusted[x] == pytest.approx(k * 0.75 + g * 0.25, rel=REL)
        # The course's own L for this cluster, rebuilt from the engine's K and G:
        assert t[f"L{TARGET_ROWS[x]}"].value == pytest.approx(
            k * 0.75 + course_owner_term(g, 0.25), rel=REL), x


# --- reliability ------------------------------------------------------------------------


def _unit(value) -> str:
    unit = re.sub(r"[^A-Za-z]", "", str(value or "")).upper()
    return {"": "LS", "EA": "EA", "SF": "SF", "LF": "LF", "CY": "CY", "CF": "CF",
            "SY": "SY", "LS": "LS"}.get(unit, "EA")


def _rating(value) -> str:
    return "" if value in (None, "") else str(int(value))


def _sample_rows(values_wb, formulas_wb) -> list[dict]:
    """Cost DB rows (fixed quantities) from the line items of all cluster sheets."""
    rows = []
    for letter, (sheet, engine_cluster) in CLUSTERS.items():
        ws, wf = values_wb[sheet], formulas_wb[sheet]
        for code, (_, line_rows) in _layout(wf).items():
            for r in line_rows:
                cost, qty = ws[f"I{r}"].value, ws[f"K{r}"].value
                if cost in (None, "") and qty in (None, ""):
                    continue
                rows.append({
                    "cluster": engine_cluster, "assembly_code": code,
                    "description": f"Course line {letter}{r}", "unit": _unit(ws[f"F{r}"].value),
                    "unit_cost": f"{_num(cost)}", "quantity_rule": "fixed",
                    "quantity_value": f"{_num(qty)}",
                    "qty_reliability": _rating(ws[f"N{r}"].value),
                    "cost_reliability": _rating(ws[f"O{r}"].value),
                    "source": "course workbook (runtime only)",
                })
    return rows


def _reliability_rows(ws_formulas) -> dict[int, int]:
    """Rating (1/2/3 in column M) -> row of the SUMIF block of a cluster sheet."""
    out = {}
    for r in range(15, 80):
        m, n = ws_formulas[f"M{r}"].value, ws_formulas[f"N{r}"].value
        if isinstance(m, int | float) and str(n).startswith("=SUMIF("):
            out[int(m)] = r
    assert sorted(out) == [1, 2, 3], ws_formulas.title
    return out


def _engine_reliability(rows: list[dict]) -> dict:
    db = cost_db_from_dicts(rows)
    assert db.ok, db.errors
    run = compute([], [], db, load_config(ISLAND_CONFIG))
    return run.reliability


def _assert_cluster_sheets(rel: dict, values_wb, formulas_wb) -> list[float]:
    errs = []
    for sheet, engine_cluster in CLUSTERS.values():
        rows = _reliability_rows(formulas_wb[sheet])
        cl = rel["clusters"].get(engine_cluster)
        for rating, row in rows.items():
            for col, cat in zip("NOP", ("quantity", "cost", "overall"), strict=True):
                expected = _num(values_wb[sheet][f"{col}{row}"].value)
                actual = cl[cat][LEVEL_OF[rating]] if cl else 0.0
                errs.append(abs(expected - actual) / expected if expected else abs(actual))
                assert actual == pytest.approx(expected, rel=REL_COST), f"{sheet}!{col}{row}"
    return errs


def test_reliability_matches_cluster_sheets_sample(values, formulas):
    rel = _engine_reliability(_sample_rows(values, formulas))
    errs = _assert_cluster_sheets(rel, values, formulas)
    assert rel["totals"]["quantity"]["not_rated"] == 0
    print(f"sample reliability max rel err {max(errs):.3e}")


# Invented line items: (cluster letter, code, Total O&P, quantity, qty rating, cost rating).
INVENTED = [
    ("A", "A1030", 12.50, 4_000.0, 1, 3),
    ("A", "A2020", 410.00, 120.0, None, 2),  # only cost rated -> overall 2 (MAX ignores blank)
    ("B", "B2020", 1_150.00, 40.0, 2, None),  # only quantity rated -> overall 2
    ("C", "C1010", 9.75, 8_000.0, None, None),  # not rated
    ("D", "D3050", 22.00, 10_000.0, 3, 1),
    ("E", "E1020", 60_000.00, 1.0, 2, 2),
    ("F", "F1000", 90_000.00, 1.0, 3, 3),
    ("G", "G2050", 5.50, 6_000.0, 1, 1),
    ("H", "H1000", 150_000.00, 1.0, 1, 3),
    ("H", "H4000", 200_000.00, 1.0, 2, 1),
]


@pytest.fixture(scope="module")
def invented_course(template, tmp_path_factory):
    """Copy with the sample lines cleared and INVENTED written in, recalculated."""
    base = tmp_path_factory.mktemp("tvd_rel")
    src, out = base / "in", base / "out"
    src.mkdir()
    out.mkdir()
    wb = openpyxl.load_workbook(template)
    for letter, (sheet, _) in CLUSTERS.items():
        ws = wb[sheet]
        layout = _layout(ws)
        for _, lines in layout.values():
            for row in lines:
                for col in "DEFGHIKNO":
                    ws[f"{col}{row}"] = None
        free = {code: list(lines) for code, (_, lines) in layout.items()}
        for i, (x, code, cost, qty, qr, cr) in enumerate(INVENTED):
            if x != letter:
                continue
            row = free[code].pop(0)
            ws[f"D{row}"], ws[f"E{row}"], ws[f"F{row}"] = f"INVENTED-{i}", f"Invented {i}", "EA"
            ws[f"I{row}"], ws[f"K{row}"], ws[f"N{row}"], ws[f"O{row}"] = cost, qty, qr, cr
    wb.save(src / "reliability.xlsx")
    _recalculate([src / "reliability.xlsx"], out, base / "lo_profile")
    return openpyxl.load_workbook(out / "reliability.xlsx", data_only=True)


def _invented_rows() -> list[dict]:
    return [
        {"cluster": CLUSTERS[x][1], "assembly_code": code, "description": f"Invented {i}",
         "unit": "EA", "unit_cost": f"{cost}", "quantity_rule": "fixed",
         "quantity_value": f"{qty}", "qty_reliability": _rating(qr),
         "cost_reliability": _rating(cr), "source": "invented"}
        for i, (x, code, cost, qty, qr, cr) in enumerate(INVENTED)
    ]


def test_reliability_matches_cluster_sheets_invented(invented_course, formulas):
    rel = _engine_reliability(_invented_rows())
    _assert_cluster_sheets(rel, invented_course, formulas)
    # The unrated C1010 line is only in not_rated; the course's SUMIF leaves it out.
    assert rel["clusters"]["Interiors"]["overall"]["not_rated"] == pytest.approx(78_000.0)


def test_reliability_sheet_errors_are_not_copied(invented_course, formulas):
    """TVD Reliability: E14 -> 'H Gen. Cond.'!W30 (not N30), LOW totals C6/C18 without H.
    The engine's A-H totals include H in every level."""
    f = formulas[RELIABILITY]
    assert f["E14"].value == "='H Gen. Cond.'!W30"
    assert f["C6"].value == "=SUM(C7:C13)" and f["C18"].value == "=SUM(C19:C25)"
    assert f["C14"].value == "='H Gen. Cond.'!N32" and f["C26"].value == "='H Gen. Cond.'!O32"

    rel = _engine_reliability(_invented_rows())
    tot = rel["totals_a_to_h"]
    ws = invented_course[RELIABILITY]
    h = rel["clusters"]["General Conditions"]
    # Rows where the course sheet is right match the engine.
    for cat, total_row in (("quantity", 6), ("cost", 18), ("overall", 30)):
        for col, level in (("D", "medium"),) + ((("E", "high"),) if cat != "quantity" else ()):
            assert _num(ws[f"{col}{total_row}"].value) == pytest.approx(
                tot[cat][level], rel=REL_COST), f"{cat} {col}{total_row}"
    assert _num(ws["C30"].value) == pytest.approx(tot["overall"]["low"], rel=REL_COST)
    # The errors: LOW without H, quantity HIGH of H = the target column.
    assert h["quantity"]["low"] == 0 and h["cost"]["low"] == pytest.approx(150_000.0)
    assert _num(ws["C18"].value) == pytest.approx(
        tot["cost"]["low"] - h["cost"]["low"], rel=REL_COST)
    assert _num(ws["E14"].value) != pytest.approx(h["quantity"]["high"])
    assert _num(ws["E6"].value) == pytest.approx(
        tot["quantity"]["high"] - h["quantity"]["high"] + _num(ws["E14"].value), rel=REL_COST)
