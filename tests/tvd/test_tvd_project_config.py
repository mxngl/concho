"""P3.2: the TVD engine and dashboard take the project values from ``project_config``.

Runs the invented fixture (tests/fixtures/tvd_synthetic) with the Island example config and
with an invented second config (tests/fixtures/configs/river_test.project_config.json) and
checks that exactly the project-dependent outputs change.
"""

import json
from pathlib import Path

import pytest

from dashboards.tvd.legacy_render import generate_html
from engines.common.config import CourseCluster, load_config
from engines.tvd.cli import main
from engines.tvd.clusters import course_cluster, display_name
from engines.tvd.cost_db import load_cost_data
from engines.tvd.engine import run_files
from engines.tvd.targets import ProjectTargets

REPO_ROOT = Path(__file__).resolve().parents[2]
RIVER_CONFIG = REPO_ROOT / "tests" / "fixtures" / "configs" / "river_test.project_config.json"
TEMPLATE_CONFIG = REPO_ROOT / "template" / "project_config.example.json"

RIVER_TARGETS = {
    "Substructure": 480_000, "Shell": 1_200_000, "Interiors": 720_000, "Services": 960_000,
    "Equipment and Furnishings": 240_000, "Special Construction": 240_000,
    "Building Sitework": 480_000, "General Conditions": 480_000, "Crane Rental": 200_000,
}


def _run(paths, config):
    return run_files(paths["arch"], paths["struct"], paths["cost"], config)


def _html(run):
    return generate_html(run.results, run.summary, run.unmapped_count, run.source, run.targets,
                         run.total_target, run.gross_sf, run.unmapped_rows, [],
                         team_name=run.project.team_name)


# ── canonical clusters ──────────────────────────────────────────────────────

@pytest.mark.parametrize("label, cluster, name", [
    ("Substructure", CourseCluster.A, "Substructure"),
    ("F", CourseCluster.F, "Special Construction"),
    ("Special Construction", CourseCluster.F, "Special Construction"),
    ("Special Contruction", CourseCluster.F, "Special Construction"),  # AutoTVD typo
    ("special  contruction", CourseCluster.F, "Special Construction"),
    ("general conditions", CourseCluster.H, "General Conditions"),
    ("Equipment Rental", None, "Equipment Rental"),
])
def test_cluster_names(label, cluster, name):
    assert course_cluster(label) == cluster
    assert display_name(label) == name


def test_cost_db_normalises_cluster_names():
    rows = [{"Cluster Name": "Special Contruction", "Assembly Code": "F1010"},
            {"Cluster Name": "Crane Rental", "Assembly Code": "Z9"}]
    assert [r["cluster"] for r in load_cost_data(rows)] == ["Special Construction",
                                                             "Crane Rental"]


# ── targets from config ─────────────────────────────────────────────────────

def test_island_targets(island_config):
    targets = ProjectTargets.from_config(island_config)
    assert targets.total_target == 16_700_000 and targets.gross_sf == 30_000
    assert isinstance(targets.gross_sf, int)  # rendered as 30000, not 30000.0
    assert targets.cluster_targets["Special Construction"] == 1_001_839
    assert list(targets.cluster_targets)[-1] == "Equipment Rental"
    notes = targets.check()
    assert any("+5,852.00" in n for n in notes)            # within the 0.1 % tolerance
    assert any("'Equipment Rental'" in n and "on top" in n for n in notes)


def test_river_targets_pct_split_with_carved_out(river_config):
    targets = ProjectTargets.from_config(river_config)
    assert targets.cluster_targets == pytest.approx(RIVER_TARGETS)
    assert list(targets.cluster_targets) == list(RIVER_TARGETS)
    assert targets.total_target == 5_000_000 and targets.gross_sf == 12_500
    assert targets.check() == []


def test_targets_outside_tolerance_fail(island_config):
    bad = island_config.model_copy(deep=True)
    bad.tvd.target_sum_tolerance = 0.0001  # 5,852 > 1,670
    with pytest.raises(ValueError, match="above the total target"):
        ProjectTargets.from_config(bad).check()


def test_derive_from_references_not_implemented():
    template = load_config(TEMPLATE_CONFIG)
    with pytest.raises(NotImplementedError, match="P3.5"):
        ProjectTargets.from_config(template)


# ── second config changes exactly the project-dependent outputs ─────────────

def test_river_config_changes_only_project_values(synthetic_paths, island_config,
                                                  river_config):
    island = _run(synthetic_paths, island_config).results_payload()
    river = _run(synthetic_paths, river_config).results_payload()

    # Unchanged: everything computed from the QTO and the cost DB.
    assert river["line_items"] == island["line_items"]
    for key in ("total_elements", "duplicates_removed", "unmapped_count", "dnc_count",
                "data_source"):
        assert river["meta"][key] == island["meta"][key]
    assert river["financials"]["grand_total"] == island["financials"]["grand_total"]
    assert [(c["cluster"], c["estimate"]) for c in river["cluster_summary"]] == [
        (c["cluster"], c["estimate"]) for c in island["cluster_summary"]
    ]

    # Changed: project values and everything derived from them.
    grand = river["financials"]["grand_total"]
    assert river["meta"]["project_name"] == "River test pavilion"
    assert river["meta"]["team_name"] == "River Test Team"
    assert river["meta"]["gross_sf"] == 12_500
    assert river["cluster_targets"] == pytest.approx(RIVER_TARGETS)
    assert river["financials"] == {
        "grand_total": grand,
        "tvd_target": 5_000_000,
        "delta": round(grand - 5_000_000, 2),
        "delta_pct": round((grand - 5_000_000) / 5_000_000 * 100, 2),
        "cost_per_sf": round(grand / 12_500, 2),
        "status": "under_target",
    }
    for row in river["cluster_summary"]:
        target = RIVER_TARGETS[row["cluster"]]
        assert row["target"] == target
        assert row["delta"] == round(row["estimate"] - target, 2)
        assert row["per_sf"] == round(row["estimate"] / 12_500, 2)


def test_dashboard_uses_config_values(synthetic_paths, island_config, river_config):
    river_html = _html(_run(synthetic_paths, river_config))
    island_html = _html(_run(synthetic_paths, island_config))

    assert "Island" not in river_html
    assert river_html.count("River Test Team") == 6  # header, footer, image + PDF exports
    assert "const GROSS_SF_JS        = 12500;" in river_html
    assert '"Crane Rental": "#4A7A9B"' in river_html  # first custom-cluster colour
    assert "30000" not in river_html and "30,000" not in river_html
    assert "$/SF (12,500 GSF)" in river_html

    assert island_html.count("Island Team 2026") == 6
    assert "const GROSS_SF_JS        = 30000;" in island_html
    assert '"Equipment Rental": "#4A7A9B"' in island_html


def test_dashboard_escapes_team_name(synthetic_paths, river_config):
    run = _run(synthetic_paths, river_config)
    html = generate_html(run.results, run.summary, 0, "", run.targets, run.total_target,
                         run.gross_sf, team_name="O'Hara </script> Team")
    assert '<div class="header-subtitle">O&#x27;Hara &lt;/script&gt; Team</div>' in html
    assert "'O\\'Hara <\\/script> Team  ·  TVD Dashboard'" in html  # single-quoted JS
    assert html.count("</script>") == html.count("<script")


# ── CLI ─────────────────────────────────────────────────────────────────────

def test_cli_cost_db_from_config(tmp_path, synthetic_paths, monkeypatch, capsys):
    monkeypatch.delenv("CONCHO_ALERT_WEBHOOK_URL", raising=False)
    out = tmp_path / "out"
    rc = main(["--ci", "--arch", synthetic_paths["arch"], "--struct", synthetic_paths["struct"],
               "--config", str(RIVER_CONFIG), "--out", str(out)])
    assert rc == 0
    latest = json.loads((out / "results" / "latest.json").read_text(encoding="utf-8"))
    assert latest["financials"]["tvd_target"] == 5_000_000
    assert "cost=" in latest["meta"]["data_source"]
    assert "River test pavilion (River Test Team)" in capsys.readouterr().out


def test_cli_requires_config(synthetic_paths, capsys):
    with pytest.raises(SystemExit):
        main(["--arch", synthetic_paths["arch"], "--struct", synthetic_paths["struct"],
              "--cost", synthetic_paths["cost"], "--out", "x"])
    assert "--config" in capsys.readouterr().err


def test_cli_needs_cost_db(tmp_path, synthetic_paths, capsys):
    # The Island example leaves files.cost_db unset (RSMeans-derived file).
    with pytest.raises(SystemExit):
        main(["--arch", synthetic_paths["arch"], "--struct", synthetic_paths["struct"],
              "--config", synthetic_paths["config"], "--out", str(tmp_path)])
    assert "files.cost_db" in capsys.readouterr().err


def test_cli_rejects_invalid_config(tmp_path, synthetic_paths, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"project": {}}), encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["--arch", synthetic_paths["arch"], "--struct", synthetic_paths["struct"],
              "--cost", synthetic_paths["cost"], "--config", str(bad), "--out", str(tmp_path)])
    assert "invalid project_config" in capsys.readouterr().err
