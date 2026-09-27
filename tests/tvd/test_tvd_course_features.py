"""P3.5 unit tests on invented inputs: target derivation (budget, references, owner
reallocation, team adjustment), reliability summary and tracking. All numbers are
invented; the course-workbook comparison is in ``test_tvd_course_method.py``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from engines.common.config import CourseCluster, TVDSection, validate_config_data
from engines.tvd.cli import main
from engines.tvd.cost_db import RELIABILITY_LEVELS, cost_db_from_dicts
from engines.tvd.derivation import (
    course_owner_term,
    derive_targets,
    owner_shares,
    owner_values,
    reference_average,
)
from engines.tvd.engine import compute
from engines.tvd.history import load_history, save_snapshot, tracking_table
from engines.tvd.reliability import overall_rating, reliability_summary
from engines.tvd.targets import ProjectTargets

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_CONFIG = REPO_ROOT / "template" / "project_config.example.json"
RIVER_CONFIG = REPO_ROOT / "tests" / "fixtures" / "configs" / "river_test.project_config.json"
LETTERS = [c.value for c in CourseCluster]

REF_1 = {"A": 0.10, "B": 0.30, "C": 0.10, "D": 0.30, "E": 0.05, "F": 0.05, "G": 0.05, "H": 0.05}
REF_2 = {"A": 0.20, "B": 0.20, "C": 0.20, "D": 0.20, "E": 0.05, "F": 0.05, "G": 0.05, "H": 0.05}


def _items(**ratings) -> dict:
    """One value item per cluster; ``ratings[letter]`` = (owner 1, owner 2)."""
    return {
        x: [{"item": f"Item {x}", "ratings": {"O1": r[0], "O2": r[1]}}] if r else []
        for x, r in ((x, ratings.get(x, (5, 5))) for x in LETTERS)
    }


def _tvd(*, p=0.10, items=None, team=None, shares=None, target=900_000.0, **extra) -> dict:
    return {
        "budget": {"grant": 1_000_000, "grant_year": 2026, "construction_year": 2028,
                   "inflation": 0.03, "roi": 0.01},
        "target": target,
        "cluster_split": {
            "method": "derive_from_references",
            "reference_columns": [{"name": "Ref 1", "shares": REF_1},
                                  {"name": "Ref 2", "shares": REF_2}],
            "owner_ratings": {"owners": ["O1", "O2"], "items": items or _items()},
            "reallocation_pct": p,
            "team_adjustment": team or {},
            "target_shares": shares,
        },
        **extra,
    }


def _derive(**kw):
    return derive_targets(TVDSection.model_validate(_tvd(**kw)))


# ── budget ──────────────────────────────────────────────────────────────────


def test_budget_formula():
    d = _derive()
    assert d.budget_amount == pytest.approx(1_000_000 * 0.98 ** 2)  # 960,400
    block = d.block()["budget"]
    assert block["years"] == 2 and block["amount"] == 960_400.0
    assert d.target_above_budget is False and d.warnings == []


def test_target_above_budget_warns():
    tvd = TVDSection.model_validate(_tvd(target=1_000_000))
    d = derive_targets(tvd)
    assert d.target_above_budget is True
    assert d.warnings == [
        "tvd.target (1,000,000.00) is above the budget from the course formula "
        "(960,400.00): grant 1,000,000.00 x (1 - 0.03 + 0.01) ^ (2028 - 2026)."
    ]
    assert d.block()["target_above_budget"] is True


def test_target_above_budget_in_engine_notes():
    data = json.loads(TEMPLATE_CONFIG.read_text(encoding="utf-8"))
    data["tvd"]["target"] = 25_000_000  # budget 19,405,980
    report = validate_config_data(data, base_dir=TEMPLATE_CONFIG.parent)
    assert report.ok
    assert any("above the budget" in w for w in report.warnings)
    notes = ProjectTargets.from_config(report.config).check()
    assert any("tvd.target (25,000,000.00) is above the budget" in n for n in notes)


# ── references, owner ratings, reallocation ─────────────────────────────────


def test_reference_average():
    k = reference_average([REF_1, REF_2])
    assert k["A"] == pytest.approx(0.15) and k["B"] == pytest.approx(0.25)
    assert reference_average([dict.fromkeys(LETTERS, 0.0)] * 2) == dict.fromkeys(LETTERS, 0.0)


@pytest.mark.parametrize("p", [0.0, 0.10, 0.25])
def test_reallocation_shares_sum_to_one(p):
    d = _derive(p=p, items=_items(A=(10, 8), B=(2, 3), D=(9, None)))
    m = d.course
    for key in ("reference_average", "owner_share", "owner_adjusted", "derived_share"):
        assert sum(getattr(m, key).values()) == pytest.approx(1.0, abs=1e-12), key
    assert sum(d.final_share.values()) == pytest.approx(1.0, abs=1e-12)
    for x in LETTERS:
        k, g = m.reference_average[x], m.owner_share[x]
        assert m.owner_adjusted[x] == pytest.approx(k * (1 - p) + g * p)
    if p == 0:
        assert m.owner_adjusted == pytest.approx(m.reference_average)
    assert sum(d.final_amount.values()) == pytest.approx(900_000.0)


def test_course_owner_term_only_matches_at_ten_percent():
    assert course_owner_term(0.2, 0.10) == pytest.approx(0.2 * 0.10)
    assert course_owner_term(0.2, 0.25) == pytest.approx(0.2 * 0.04)  # not 0.2 x 0.25


def test_blank_ratings_are_ignored():
    items = {x: [] for x in LETTERS}
    items["A"] = [{"item": "a1", "ratings": {"O1": 5, "O2": None}},
                  {"item": "a2", "ratings": {}},
                  {"item": "a3", "ratings": {"O1": 7, "O2": 9}}]
    items["B"] = [{"item": "b1", "ratings": {"O2": 3}}]
    values = owner_values({x: [[i["ratings"].get(o) for o in ("O1", "O2")] for i in its]
                           for x, its in items.items()})
    assert values["A"] == pytest.approx(7.0)  # mean of 5, 7, 9 (blanks ignored)
    assert values["B"] == 3.0 and values["C"] is None
    shares = owner_shares(values)
    assert shares["A"] == pytest.approx(0.7) and shares["C"] == 0.0

    d = _derive(items=items)
    assert d.course.owner_value["A"] == pytest.approx(7.0)
    assert d.course.item_count["A"] == 3
    assert d.block()["clusters"]["C"]["owner_value"] is None
    assert d.warnings == [
        "owner_ratings: no rating for cluster(s) C, D, E, F, G, H: owner share 0 "
        "(the course sheet would show an error)."
    ]


def test_all_ratings_blank_is_an_error_unless_no_reallocation():
    items = {x: [{"item": "i", "ratings": {"O1": None}}] for x in LETTERS}
    with pytest.raises(ValidationError, match="no rating above 0"):
        TVDSection.model_validate(_tvd(items=items))
    d = _derive(items=items, p=0.0)
    assert d.course.owner_share == dict.fromkeys(LETTERS, 0.0)
    assert d.course.owner_adjusted == pytest.approx(d.course.reference_average)


def test_ratings_outside_0_to_10_or_by_unknown_owner():
    items = _items(A=(11, 5))
    with pytest.raises(ValidationError, match="less than or equal to 10"):
        TVDSection.model_validate(_tvd(items=items))
    items = _items()
    items["B"][0]["ratings"]["Owner X"] = 4
    with pytest.raises(ValidationError, match=r"ratings by unknown owner\(s\) \['Owner X'\]"):
        TVDSection.model_validate(_tvd(items=items))


# ── team adjustment M, target shares N ──────────────────────────────────────


def test_team_adjustment_applied():
    d = _derive(team={"B": 0.02, "H": -0.02})
    m = d.course
    assert m.team_adjustment["B"] == 0.02 and m.team_adjustment["A"] == 0.0
    assert d.final_share[CourseCluster.B] == pytest.approx(m.owner_adjusted["B"] + 0.02)
    assert sum(d.final_share.values()) == pytest.approx(1.0)
    assert m.final_source == "L+M"
    b = d.block()["clusters"]["B"]
    assert b["amounts"]["team_adjustment"] == pytest.approx(18_000.0)
    assert b["target"] == pytest.approx(b["amounts"]["derived"])


def test_team_adjustment_not_summing_to_zero_is_an_error():
    with pytest.raises(ValidationError, match=r"team_adjustment must sum to 0.*\+0\.010000"):
        TVDSection.model_validate(_tvd(team={"B": 0.03, "H": -0.02}))


def test_team_adjustment_making_a_share_negative_is_an_error():
    with pytest.raises(ValidationError, match=r"negative: H \("):
        TVDSection.model_validate(_tvd(team={"B": 0.2, "H": -0.2}))


def test_target_shares_replace_l_plus_m():
    shares = {"A": 0.2, "B": 0.2, "C": 0.1, "D": 0.3, "E": 0.05, "F": 0.05, "G": 0.05,
              "H": 0.05}
    d = _derive(shares=shares, team={"B": 0.01, "C": -0.01})
    assert d.course.final_source == "target_shares"
    assert d.final_amount[CourseCluster.D] == pytest.approx(270_000.0)
    assert d.block()["clusters"]["B"]["derived_share"] != d.block()["clusters"]["B"]["final_share"]
    assert any("team_adjustment is only reported" in w for w in d.warnings)
    bad = dict(shares, H=0.10)
    with pytest.raises(ValidationError, match="target_shares must sum to 1.0"):
        TVDSection.model_validate(_tvd(shares=bad))


def test_carved_out_clusters_reduce_the_base():
    tvd = _tvd(custom_clusters=[{"name": "Allowance", "target": 100_000, "mode": "carved_out"}])
    d = derive_targets(TVDSection.model_validate(tvd))
    assert d.base == 800_000.0
    assert sum(d.final_amount.values()) == pytest.approx(800_000.0)


def test_explicit_split_block_has_no_course_values():
    data = json.loads(RIVER_CONFIG.read_text(encoding="utf-8"))
    d = derive_targets(TVDSection.model_validate(data["tvd"]))
    block = d.block()
    assert block["method"] == "explicit" and block["budget"] is None
    assert "reallocation_pct" not in block and "owner_share" not in block["clusters"]["A"]
    assert block["clusters"]["A"] == {"name": "Substructure", "final_share": 0.1,
                                      "target": 480_000.0}  # 10 % of 5,000,000 - 200,000
    assert block["sums"] == {"final_share": 1.0, "target": 4_800_000.0}


# ── reliability ─────────────────────────────────────────────────────────────


def test_reliability_scale_follows_the_course():
    assert RELIABILITY_LEVELS == {1: "high", 2: "medium", 3: "low"}
    assert overall_rating(1, 3) == 3 and overall_rating(2, 1) == 2
    assert overall_rating(None, 2) == 2 and overall_rating(3, None) == 3
    assert overall_rating(None, None) is None


def _line(cluster, code, cost, qty, qr, cr, desc):
    return {"cluster": cluster, "assembly_code": code, "description": desc, "unit": "LS",
            "unit_cost": cost, "quantity_rule": "fixed", "quantity_value": qty,
            "qty_reliability": qr, "cost_reliability": cr, "source": "invented"}


def test_reliability_summary_per_cluster_and_totals(river_config):
    rows = [
        _line("A", "A1010", "100.00", "10", "1", "3", "a"),     # q high, c low, overall low
        _line("A", "A1030", "50.00", "2", "", "2", "b"),        # q not rated, overall medium
        _line("H", "H4000", "1000.00", "1", "2", "1", "c"),     # overall medium
        _line("H", "H5000", "400.00", "1", "", "", "d"),        # not rated
        _line("Crane Rental", "Z9000", "300.00", "1", "3", "3", "e"),
    ]
    db = cost_db_from_dicts(rows, custom_clusters=["Crane Rental"])
    assert db.ok, db.errors
    run = compute([], [], db, river_config)
    rel = run.reliability
    assert rel["scale"] == {"1": "high", "2": "medium", "3": "low"}
    a = rel["clusters"]["Substructure"]
    assert a["quantity"] == {"high": 1000.0, "medium": 0.0, "low": 0.0, "not_rated": 100.0}
    assert a["cost"] == {"high": 0.0, "medium": 100.0, "low": 1000.0, "not_rated": 0.0}
    assert a["overall"] == {"high": 0.0, "medium": 100.0, "low": 1000.0, "not_rated": 0.0}
    assert a["estimate"] == 1100.0
    h = rel["clusters"]["General Conditions"]
    assert h["overall"] == {"high": 0.0, "medium": 1000.0, "low": 0.0, "not_rated": 400.0}
    # H is part of every A-H total (the course sheet's LOW totals leave it out).
    assert rel["totals_a_to_h"]["overall"] == {"high": 0.0, "medium": 1100.0, "low": 1000.0,
                                               "not_rated": 400.0}
    assert rel["totals"]["overall"]["low"] == 1300.0  # + the custom cluster
    assert rel["totals"]["estimate"] == pytest.approx(2800.0)
    for cat in ("quantity", "cost", "overall"):
        assert sum(rel["totals"][cat].values()) == pytest.approx(2800.0)
    assert run.results_payload()["reliability"] == rel


def test_reliability_summary_needs_matching_lines():
    with pytest.raises(ValueError, match="differ in length"):
        reliability_summary([], [{"cluster": "Shell", "total": 1.0}])


# ── tracking ────────────────────────────────────────────────────────────────


def _summary(total):
    return [{"cluster": "Shell", "total": total}, {"cluster": "GRAND TOTAL", "total": total}]


def test_snapshot_stores_event_and_note(tmp_path):
    path = save_snapshot(str(tmp_path), "Week 3", [], _summary(95.0), 0,
                         event="Design review 1", note="after VE")
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    assert data["event"] == "Design review 1" and data["note"] == "after VE"
    plain = save_snapshot(str(tmp_path / "b"), "Week 4", [], _summary(95.0), 0)
    assert set(json.loads(Path(plain).read_text(encoding="utf-8"))) == {
        "label", "date", "results", "summary", "unmapped_count"}  # format unchanged


def test_old_snapshots_without_event_still_load(tmp_path):
    old = {"label": "Old run", "date": "2026-04-01", "results": [], "summary": _summary(120.0),
           "unmapped_count": 3}
    (tmp_path / "20260401_000000_old_run.json").write_text(json.dumps(old), encoding="utf-8")
    save_snapshot(str(tmp_path), "New run", [], _summary(90.0), 0, event="Owner workshop")
    history = load_history(str(tmp_path))
    assert [v["label"] for v in history] == ["Old run", "New run"]

    table = tracking_table(history, 100.0)
    assert table["target"] == 100.0
    old_row, new_row = table["rows"]
    assert old_row == {"date": "2026-04-01", "label": "Old run", "event": None, "note": None,
                       "estimate": 120.0, "delta": -20.0, "current": False}
    assert new_row["event"] == "Owner workshop" and new_row["delta"] == 10.0
    assert new_row["current"] is True  # no extra row: the run is the last snapshot


def test_cli_event_and_note(tmp_path, synthetic_paths, monkeypatch):
    monkeypatch.delenv("CONCHO_ALERT_WEBHOOK_URL", raising=False)
    out = tmp_path / "out"
    common = ["--ci", "--arch", synthetic_paths["arch"], "--struct", synthetic_paths["struct"],
              "--cost", synthetic_paths["cost"], "--config", str(RIVER_CONFIG),
              "--out", str(out)]
    assert main([*common, "--snapshot", "Week 1", "--event", "Kick-off"]) == 0
    assert main([*common, "--event", "Owner workshop", "--note", "no snapshot"]) == 0
    latest = json.loads((out / "results" / "latest.json").read_text(encoding="utf-8"))
    rows = latest["tracking"]["rows"]
    assert [(r["label"], r["event"], r["note"], r["current"]) for r in rows] == [
        ("Week 1", "Kick-off", None, False),
        (latest["meta"]["label"], "Owner workshop", "no snapshot", True),
    ]
    grand_total = latest["financials"]["grand_total"]
    assert rows[-1]["estimate"] == grand_total
    assert rows[-1]["delta"] == round(5_000_000 - grand_total, 2)
    assert latest["tracking"]["target"] == 5_000_000
    (snap,) = (out / "history").glob("*_week_1.json")
    assert json.loads(snap.read_text(encoding="utf-8"))["event"] == "Kick-off"
