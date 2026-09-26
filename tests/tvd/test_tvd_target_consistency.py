"""P3.3: the TVD engine checks the cluster targets against the total target.

Gap = course clusters A-H + ``carved_out`` custom clusters − total target; ``on_top`` custom
clusters are outside the total and reported separately. Outside ``tvd.target_sum_tolerance``
the engine fails unless ``tvd.target_sum_override`` is set (status ``override``).

Runs on the invented fixture (tests/fixtures/tvd_synthetic) with variants of the Island
example config; the full Island run is pinned in ``test_tvd_equivalence.py``.
"""

import json
from pathlib import Path

import pytest

from engines.common.config import validate_config_data
from engines.tvd.cli import main
from engines.tvd.engine import run_files
from engines.tvd.targets import ProjectTargets

REPO_ROOT = Path(__file__).resolve().parents[2]
ISLAND_CONFIG = REPO_ROOT / "engines" / "common" / "examples" / "island_2026.project_config.json"
OVERRIDE = "targets from an older worksheet, reconciled later (test)"


def _run(paths, config):
    return run_files(paths["arch"], paths["struct"], paths["cost"], config)


def _variant(config, *, tolerance=None, override=None, total=None, mode=None):
    cfg = config.model_copy(deep=True)
    if tolerance is not None:
        cfg.tvd.target_sum_tolerance = tolerance
    if override is not None:
        cfg.tvd.target_sum_override = override
    if total is not None:
        cfg.tvd.total_target = total
    if mode is not None:
        cfg.tvd.custom_clusters[0].mode = mode
    return cfg


def _island_data() -> dict:
    return json.loads(ISLAND_CONFIG.read_text(encoding="utf-8"))


# ── Island: within tolerance, Equipment Rental on top ──────────────────────

def test_island_block(synthetic_paths, island_config):
    payload = _run(synthetic_paths, island_config).results_payload()
    tc = payload["target_consistency"]
    assert tc == {
        "total_target": 16_700_000,
        "sum_a_to_h": 16_705_852,
        "sum_carved_out": 0,
        "sum_on_top": 400_000,
        "gap": 5_852,
        "gap_pct": 0.035,
        "gap_incl_on_top": 405_852,
        "tolerance": 0.001,
        "tolerance_amount": 16_700,
        "status": "within_tolerance",
        "override_reason": None,
        "carved_out_clusters": {},
        "on_top_clusters": {"Equipment Rental": 400_000},
    }
    # The block does not touch the other outputs.
    assert payload["financials"]["tvd_target"] == 16_700_000
    assert payload["cluster_targets"]["Equipment Rental"] == 400_000


def test_exact_split_is_ok(synthetic_paths, river_config):
    tc = _run(synthetic_paths, river_config).results_payload()["target_consistency"]
    assert tc["status"] == "ok"
    assert tc["gap"] == 0
    assert tc["sum_carved_out"] == 200_000 and tc["sum_on_top"] == 0
    assert tc["carved_out_clusters"] == {"Crane Rental": 200_000}
    assert tc["sum_a_to_h"] + tc["sum_carved_out"] == pytest.approx(tc["total_target"])


# ── sum mismatch fails ──────────────────────────────────────────────────────

def test_mismatch_fails_with_gap_in_dollars_and_pct(synthetic_paths, island_config):
    bad = _variant(island_config, tolerance=0.0001)  # 5,852 > 1,670
    assert ProjectTargets.from_config(bad).consistency_status == "failed"
    assert ProjectTargets.from_config(bad).target_consistency()["status"] == "failed"
    with pytest.raises(ValueError) as exc:
        _run(synthetic_paths, bad)
    msg = str(exc.value)
    assert "gap +5,852.00 (+0.0350 %)" in msg
    assert "total target 16,700,000.00" in msg
    assert "tolerance 0.0001 = 1,670.00" in msg
    assert "target_sum_override" in msg


def test_mismatch_below_total_fails(synthetic_paths, island_config):
    bad = _variant(island_config, total=17_000_000)  # A-H 294,148 below, tolerance 17,000
    with pytest.raises(ValueError, match=r"gap -294,148.00 \(-1.7303 %\)"):
        _run(synthetic_paths, bad)


def test_cli_fails_on_mismatch(tmp_path, synthetic_paths, capsys):
    data = _island_data()
    data["tvd"]["total_target"] = 17_000_000
    del data["$schema"]
    config = tmp_path / "config.json"
    config.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["--ci", "--arch", synthetic_paths["arch"], "--struct", synthetic_paths["struct"],
              "--cost", synthetic_paths["cost"], "--config", str(config),
              "--out", str(tmp_path / "out")])
    err = capsys.readouterr().err
    assert "294,148" in err
    assert not (tmp_path / "out" / "results").exists()


# ── override passes with status "override" ─────────────────────────────────

def test_override_passes(synthetic_paths, island_config):
    cfg = _variant(island_config, tolerance=0.0001, override=OVERRIDE)
    run = _run(synthetic_paths, cfg)
    tc = run.results_payload()["target_consistency"]
    assert tc["status"] == "override"
    assert tc["override_reason"] == OVERRIDE
    assert tc["gap"] == 5_852 and tc["tolerance_amount"] == 1_670
    assert any("target_sum_override" in n and "+5,852.00" in n for n in run.notes)


def test_override_not_used_within_tolerance(synthetic_paths, island_config):
    cfg = _variant(island_config, override=OVERRIDE)
    tc = _run(synthetic_paths, cfg).results_payload()["target_consistency"]
    assert tc["status"] == "within_tolerance"
    assert tc["override_reason"] == OVERRIDE


def test_config_validation_accepts_override():
    data = _island_data()
    data["tvd"]["target_sum_tolerance"] = 0.0001
    report = validate_config_data(data, base_dir=ISLAND_CONFIG.parent)
    assert not report.ok
    assert "target_sum_override" in "\n".join(report.errors)

    data["tvd"]["target_sum_override"] = OVERRIDE
    report = validate_config_data(data, base_dir=ISLAND_CONFIG.parent)
    assert report.ok, report.errors
    assert any("accepted by target_sum_override" in w for w in report.warnings)


def test_cli_override_writes_block(tmp_path, synthetic_paths, monkeypatch):
    monkeypatch.delenv("CONCHO_ALERT_WEBHOOK_URL", raising=False)
    data = _island_data()
    data["tvd"]["total_target"] = 17_000_000
    data["tvd"]["target_sum_override"] = OVERRIDE
    del data["$schema"]
    config = tmp_path / "config.json"
    config.write_text(json.dumps(data), encoding="utf-8")
    out = tmp_path / "out"
    assert main(["--ci", "--arch", synthetic_paths["arch"], "--struct", synthetic_paths["struct"],
                 "--cost", synthetic_paths["cost"], "--config", str(config),
                 "--out", str(out)]) == 0
    latest = json.loads((out / "results" / "latest.json").read_text(encoding="utf-8"))
    tc = latest["target_consistency"]
    assert tc["status"] == "override" and tc["gap"] == -294_148
    assert tc["gap_incl_on_top"] == 105_852


# ── carved_out vs. on_top ───────────────────────────────────────────────────

def test_carved_out_counts_against_total(synthetic_paths, island_config):
    # Total 17,100,000 = A-H 16,705,852 + Equipment Rental 400,000 − 5,852.
    cfg = _variant(island_config, total=17_100_000, mode="carved_out")
    run = _run(synthetic_paths, cfg)
    tc = run.results_payload()["target_consistency"]
    assert tc["status"] == "within_tolerance"
    assert tc["sum_carved_out"] == 400_000 and tc["sum_on_top"] == 0
    assert tc["carved_out_clusters"] == {"Equipment Rental": 400_000}
    assert tc["on_top_clusters"] == {}
    assert tc["gap"] == tc["gap_incl_on_top"] == 5_852
    assert not any("on top" in n for n in run.notes)


def test_on_top_is_outside_total(synthetic_paths, island_config):
    # Same total, but on top: A-H alone is 394,148 below it.
    cfg = _variant(island_config, total=17_100_000, mode="on_top")
    targets = ProjectTargets.from_config(cfg)
    tc = targets.target_consistency()
    assert tc["status"] == "failed"
    assert tc["gap"] == -394_148 and tc["gap_incl_on_top"] == 5_852
    assert tc["sum_on_top"] == 400_000 and tc["sum_carved_out"] == 0
    with pytest.raises(ValueError, match="gap -394,148.00"):
        _run(synthetic_paths, cfg)


def test_island_on_top_is_reported_separately(island_config):
    notes = ProjectTargets.from_config(island_config).check()
    assert any("'Equipment Rental' (400,000.00) is on top" in n for n in notes)
    assert any("incl. on-top clusters sum to 17,105,852.00, +405,852.00" in n for n in notes)


def test_carved_out_above_total_fails(island_config):
    cfg = _variant(island_config, mode="carved_out")
    cfg.tvd.custom_clusters[0].target = 20_000_000
    with pytest.raises(ValueError, match="carved-out custom clusters .* exceed the total"):
        ProjectTargets.from_config(cfg).check()
