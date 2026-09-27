"""P3.1: project_config schema, validation rules and examples.

Every validation rule has a passing and a failing case. The base config is the neutral
template example (invented values, no course data).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import export_config_schema
from engines.common.config import (
    ConfigError,
    find_secrets,
    json_schema_text,
    load_config,
    validate_config_data,
    validate_config_file,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "template" / "project_config.example.json"
ISLAND = REPO_ROOT / "engines" / "common" / "examples" / "island_2026.project_config.json"
SCHEMA_FILE = REPO_ROOT / "docs" / "schema" / "project_config.schema.json"

ISLAND_VALUES = {"A": 1781276, "B": 3826446, "C": 2005842, "D": 4041448,
                 "E": 1319286, "F": 1001839, "G": 1435258, "H": 1294457}  # fmt: skip


@pytest.fixture
def base() -> dict:
    return json.loads(TEMPLATE.read_text(encoding="utf-8"))


def _validate(data: dict, base_dir: Path = TEMPLATE.parent):
    return validate_config_data(data, base_dir=base_dir)


def _errors(data: dict, base_dir: Path = TEMPLATE.parent) -> str:
    report = _validate(data, base_dir)
    assert not report.ok, "expected validation errors"
    return "\n".join(report.errors)


def _ok(data: dict, base_dir: Path = TEMPLATE.parent):
    report = _validate(data, base_dir)
    assert report.ok, report.errors
    return report


def _amount_split(values: dict | None = None) -> dict:
    return {"method": "explicit", "basis": "amount", "values": dict(values or ISLAND_VALUES)}


def _fixed_total(data: dict, total: float, split: dict) -> dict:
    tvd = data["tvd"]
    tvd.pop("budget", None)
    tvd.pop("target", None)
    tvd["total_target"] = total
    tvd["cluster_split"] = split
    tvd["custom_clusters"] = []
    return data


# --- examples -------------------------------------------------------------------------


def test_template_example_validates():
    report = validate_config_file(TEMPLATE)
    assert report.ok, report.errors
    assert report.config.stv.use_phase.water.urinal_gpf == 0.125


def test_island_example_validates_with_on_top_warning():
    report = validate_config_file(ISLAND)
    assert report.ok, report.errors
    cfg = report.config
    assert cfg.tvd.total_target == 16_700_000
    assert cfg.project.gross_sf == 30_000
    assert cfg.stv.course_team.value == "Island"
    assert cfg.stv.use_phase.not_modeled is True
    assert cfg.schedule.rooms_per_zone == 2
    assert [c.name for c in cfg.tvd.custom_clusters] == ["Equipment Rental"]
    on_top = [w for w in report.warnings if "on_top" in w]
    assert len(on_top) == 1
    assert "405,852" in on_top[0] and "17,105,852" in on_top[0]
    assert any("not_modeled" in w for w in report.warnings)


def test_island_on_top_gap_is_an_error_when_carved_out():
    data = json.loads(ISLAND.read_text(encoding="utf-8"))
    data["tvd"]["custom_clusters"][0]["mode"] = "carved_out"
    assert "405,852 above the total target" in _errors(data, ISLAND.parent)


def test_load_config_returns_model_and_raises_on_errors(tmp_path, base):
    assert load_config(ISLAND).project.team_name == "Island Team 2026"
    del base["project"]["name"]
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(base), encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(bad)
    assert "project.name: required field is missing" in str(exc.value)


# --- required / unknown fields ---------------------------------------------------------


def test_missing_required_field_is_named(base):
    del base["project"]["gross_sf"]
    del base["stv"]["course_team"]
    msg = _errors(base)
    assert "project.gross_sf: required field is missing" in msg
    assert "stv.course_team: required field is missing" in msg


def test_unknown_field_is_rejected(base):
    base["project"]["gross_sqft"] = 1
    assert "project.gross_sqft: unknown field" in _errors(base)


def test_invalid_enum_value(base):
    base["stv"]["course_team"] = "Lagoon"
    assert "stv.course_team" in _errors(base)


# --- tvd: total vs budget --------------------------------------------------------------


def test_total_target_and_budget_are_exclusive(base):
    base["tvd"]["total_target"] = 1_000_000
    assert "either total_target" in _errors(base)


def test_neither_total_nor_budget(base):
    del base["tvd"]["budget"]
    del base["tvd"]["target"]
    assert "either total_target" in _errors(base)


def test_budget_requires_target(base):
    del base["tvd"]["target"]
    assert "target (the team's target amount) is required" in _errors(base)


def test_target_without_budget_is_rejected(base):
    _fixed_total(base, 16_705_852, _amount_split())
    base["tvd"]["target"] = 1
    assert "target is only used with budget" in _errors(base)


def test_budget_formula_and_target_above_budget_warns(base):
    report = _ok(base)
    budget = report.config.tvd.budget
    assert budget.amount == pytest.approx(20_000_000 * (1 - 0.03 + 0.02) ** 3)
    assert not any("above the budget" in w for w in report.warnings)
    base["tvd"]["target"] = 25_000_000
    assert any("above the budget" in w for w in _ok(base).warnings)


def test_budget_years_in_order(base):
    base["tvd"]["budget"]["construction_year"] = 2025
    assert "construction_year (2025) is before grant_year (2026)" in _errors(base)


# --- tvd: cluster targets sum to the total ---------------------------------------------


def test_amount_split_exact_sum_passes_without_warning(base):
    _fixed_total(base, sum(ISLAND_VALUES.values()), _amount_split())
    report = _ok(base)
    assert not any("tvd." in w for w in report.warnings)


def test_amount_split_within_tolerance_warns(base):
    _fixed_total(base, 16_700_000, _amount_split())  # 5,852 over, tolerance 0.1 %
    report = _ok(base)
    assert any("5,852 above the total target" in w for w in report.warnings)


def test_amount_split_outside_tolerance_fails(base):
    _fixed_total(base, 16_700_000, _amount_split())
    base["tvd"]["target_sum_tolerance"] = 0.0001
    msg = _errors(base)
    assert "tvd: course cluster targets (16,705,852)" in msg
    assert "5,852 above the total target 16,700,000" in msg
    assert "raise target_sum_tolerance" in msg


def test_carved_out_custom_cluster_counts_against_total(base):
    total = sum(ISLAND_VALUES.values()) + 400_000
    _fixed_total(base, total, _amount_split())
    base["tvd"]["custom_clusters"] = [
        {"name": "Equipment Rental", "target": 400_000, "mode": "carved_out"}
    ]
    report = _ok(base)
    assert not any("on_top" in w for w in report.warnings)
    base["tvd"]["custom_clusters"] = []
    assert "400,000 below the total target" in _errors(base)


def test_on_top_custom_cluster_warns_with_gap(base):
    _fixed_total(base, sum(ISLAND_VALUES.values()), _amount_split())
    base["tvd"]["custom_clusters"] = [{"name": "Extras", "target": 1_000, "mode": "on_top"}]
    report = _ok(base)
    assert any("1,000 USD above the total target" in w for w in report.warnings)


def test_carved_out_larger_than_total_fails(base):
    base["tvd"]["custom_clusters"][0]["target"] = 99_000_000
    assert "carved-out custom clusters (99,000,000) exceed the total target" in _errors(base)


def test_custom_cluster_names(base):
    base["tvd"]["custom_clusters"].append(
        {"name": "Owner Allowance", "target": 1, "mode": "on_top"}
    )
    assert "must be unique" in _errors(base)
    base["tvd"]["custom_clusters"] = [{"name": "Shell", "target": 1, "mode": "on_top"}]
    assert "uses a course cluster letter or name" in _errors(base)


def test_custom_cluster_cannot_be_course_data(base):
    base["tvd"]["custom_clusters"][0]["is_course_data"] = True
    assert "tvd.custom_clusters[0].is_course_data" in _errors(base)


def test_explicit_values_need_all_clusters(base):
    values = dict(ISLAND_VALUES)
    del values["F"]
    _fixed_total(base, 16_700_000, _amount_split(values))
    assert "missing: F" in _errors(base)


def test_unknown_split_method(base):
    base["tvd"]["cluster_split"]["method"] = "average"
    assert "method must be 'explicit' or 'derive_from_references'" in _errors(base)


# --- shares sum to 1.0 -----------------------------------------------------------------


def test_pct_split_sums_to_one(base):
    shares = {"A": 0.1, "B": 0.25, "C": 0.15, "D": 0.25, "E": 0.05, "F": 0.03, "G": 0.07,
              "H": 0.1}  # fmt: skip
    _fixed_total(base, 1_000_000, {"method": "explicit", "basis": "pct", "values": shares})
    _ok(base)
    base["tvd"]["cluster_split"]["values"]["H"] = 10
    assert "pct values must sum to 1.0, but they sum to 10.900000" in _errors(base)


def test_reference_column_shares_sum_to_one(base):
    _ok(base)
    base["tvd"]["cluster_split"]["reference_columns"][1]["shares"]["A"] = 0.5
    msg = _errors(base)
    assert "reference column 'Previous project 1' must sum to 1.0" in msg


def test_owner_ratings_cover_all_clusters(base):
    del base["tvd"]["cluster_split"]["owner_ratings"]["items"]["D"]
    assert "items must list all clusters A-H; missing: D" in _errors(base)


def test_owner_ratings_by_known_owners_in_range(base):
    items = base["tvd"]["cluster_split"]["owner_ratings"]["items"]
    items["A"][0]["ratings"]["Owner 3"] = 5
    assert "items.A 'Foundation durability': ratings by unknown owner(s) ['Owner 3']" in (
        _errors(base))
    del items["A"][0]["ratings"]["Owner 3"]
    items["B"][0]["ratings"]["Owner 1"] = 11
    assert "less than or equal to 10" in _errors(base)


def test_owner_ratings_all_blank_or_zero(base):
    split = base["tvd"]["cluster_split"]
    for items in split["owner_ratings"]["items"].values():
        for it in items:
            it["ratings"] = {o: 0 for o in it["ratings"]}
    assert "owner_ratings has no rating above 0" in _errors(base)
    split["reallocation_pct"] = 0
    _ok(base)


def test_unrated_cluster_warns(base):
    base["tvd"]["cluster_split"]["owner_ratings"]["items"]["E"] = []
    report = _validate(base)
    assert report.ok
    assert any("no owner rating for cluster(s) E" in w for w in report.warnings)


def test_team_adjustment_sums_to_zero(base):
    base["tvd"]["cluster_split"]["team_adjustment"] = {"B": 0.02, "G": -0.01}
    assert "team_adjustment must sum to 0" in _errors(base)
    base["tvd"]["cluster_split"]["team_adjustment"] = {"A": -0.2, "B": 0.2}
    assert "team_adjustment makes target shares negative: A (" in _errors(base)


def test_target_shares_sum_to_one(base):
    shares = {"A": 0.1, "B": 0.25, "C": 0.15, "D": 0.25, "E": 0.05, "F": 0.03, "G": 0.07,
              "H": 0.1}
    base["tvd"]["cluster_split"]["target_shares"] = shares
    _ok(base)
    shares["H"] = 0.2
    assert "target_shares must sum to 1.0" in _errors(base)


def test_cogeneration_splits_sum_to_one(base):
    cogen = {
        "fuel_type": "Natural Gas",
        "electricity_kwh": 1000,
        "heating_mj": 500,
        "cooling_kwh": 0,
        "splits": {"electricity": 0.6, "heating": 0.4, "cooling": 0},
    }
    base["stv"]["use_phase"]["cogeneration"] = cogen
    _ok(base)
    cogen["splits"]["cooling"] = 0.2
    assert "cogeneration splits must sum to 1.0, but they sum to 1.200000" in _errors(base)


# --- use phase complete or not_modeled -------------------------------------------------


def test_use_phase_incomplete_fails(base):
    up = base["stv"]["use_phase"]
    del up["grid_kwh"]
    del up["cogeneration"]
    del up["water"]["shower_gpm"]
    msg = _errors(base)
    assert "use phase is incomplete; missing: grid_kwh, cogeneration, water.shower_gpm" in msg
    assert "set not_modeled: true" in msg


def test_use_phase_not_modeled_passes_with_warning(base):
    base["stv"]["use_phase"] = {"not_modeled": True, "not_modeled_reason": "no energy model"}
    report = _ok(base)
    assert any("not_modeled is true" in w for w in report.warnings)
    assert report.config.stv.use_phase.not_modeled_reason == "no energy model"


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_use_phase_not_modeled_needs_reason(base, reason):
    """P3.8: not modeled is an explicit statement with a reason."""
    base["stv"]["use_phase"] = {"not_modeled": True, "not_modeled_reason": reason}
    assert "not_modeled_reason is missing" in _errors(base)
    base["stv"]["use_phase"] = {"not_modeled": True}
    assert "not_modeled_reason is missing" in _errors(base)


def test_use_phase_reason_without_not_modeled_warns(base):
    base["stv"]["use_phase"]["not_modeled_reason"] = "stale"
    report = _ok(base)
    assert any("not_modeled_reason is set but ignored" in w for w in report.warnings)


def test_use_phase_not_modeled_with_values_warns(base):
    base["stv"]["use_phase"]["not_modeled"] = True
    base["stv"]["use_phase"]["not_modeled_reason"] = "values kept for later"
    report = _ok(base)
    assert any("ignored because not_modeled" in w for w in report.warnings)


def test_urinal_null_vs_missing(base):
    water = base["stv"]["use_phase"]["water"]
    water["urinal_gpf"] = None  # no urinals: allowed
    assert _ok(base).config.stv.use_phase.water.urinal_gpf is None
    water["urinal_gpf"] = 0  # course behaviour: allowed
    assert _ok(base).config.stv.use_phase.water.urinal_gpf == 0
    del water["urinal_gpf"]  # not stated: error
    assert "water.urinal_gpf" in _errors(base)


def test_use_phase_all_zero_warns(base):
    up = base["stv"]["use_phase"]
    for key in ("grid_kwh", "onsite_renewable_kwh", "natural_gas_m3"):
        up[key] = 0
    up["water"] = {k: 0 for k in up["water"]}
    report = _ok(base)
    assert any("all use-phase values are 0" in w for w in report.warnings)


# --- dates in order --------------------------------------------------------------------


def test_schedule_dates_in_order(base):
    base["schedule"]["target_completion"] = "2029-01-01"
    assert "target_completion (2029-01-01) must be after start_date (2029-03-01)" in _errors(
        base
    )


def test_schedule_completion_not_after_project_completion(base):
    base["schedule"]["target_completion"] = "2031-01-01"
    assert "is after project.completion_date (2030-08-31)" in _errors(base)


def test_blocked_window_order(base):
    base["schedule"]["blocked_windows"][0]["end"] = "2029-12-01"
    assert "blocked window 'Winter shutdown' ends (2029-12-01) before it starts" in _errors(base)


def test_blocked_window_outside_schedule_warns(base):
    base["schedule"]["blocked_windows"].append(
        {"name": "Old", "start": "2020-01-01", "end": "2020-02-01"}
    )
    assert any("'Old'" in w and "outside" in w for w in _ok(base).warnings)


def test_invalid_date(base):
    base["project"]["completion_date"] = "30/09/2030"
    assert "project.completion_date" in _errors(base)


# --- referenced files ------------------------------------------------------------------


def test_files_exist(tmp_path, base):
    (tmp_path / "cost_db.csv").write_text("x\n", encoding="utf-8")
    (tmp_path / "macro.csv").write_text("x\n", encoding="utf-8")
    base["files"].update(cost_db="cost_db.csv", macro_schedule="macro.csv")
    report = _ok(base, tmp_path)
    assert not any(w.startswith("files.") for w in report.warnings)


def test_required_file_missing_fails(tmp_path, base):
    base["files"]["cost_db"] = "missing.csv"
    msg = _errors(base, tmp_path)
    assert "files.cost_db: file not found: missing.csv" in msg


def test_required_file_unset_warns(base):
    report = _ok(base)
    assert any("files.cost_db is not set" in w for w in report.warnings)


def test_optional_file_missing_warns(tmp_path, base):
    base["files"]["stv_mapping"] = "stv_mapping.csv"
    base["stv"]["custom_materials_file"] = "custom.csv"
    report = _ok(base, tmp_path)
    assert any("files.stv_mapping: optional file not found" in w for w in report.warnings)
    assert any("stv.custom_materials_file: optional file" in w for w in report.warnings)


def test_exports_must_be_a_directory(tmp_path, base):
    (tmp_path / "exports").write_text("", encoding="utf-8")
    assert "files.exports" in _errors(base, tmp_path)


def test_custom_materials_paths_must_agree(base):
    base["stv"]["custom_materials_file"] = "a.csv"
    base["files"]["custom_materials"] = "b.csv"
    assert "differ" in _errors(base)
    base["files"]["custom_materials"] = "a.csv"
    _ok(base)


# --- no secrets ------------------------------------------------------------------------

# Built at runtime so the repo never contains token-shaped strings.
_FAKE_SECRETS = {
    "URL with credentials": "https://user:" + "hunter2" + "@example.com/db",
    "URL with a token/key parameter": "https://example.com/data.json?" + "token=abc123",
    "Discord webhook URL": "https://discord.com/api/" + "webhooks/123/abc",
    "webhook URL with UUID": "https://n8n.example.com/" + "webhook/"
    + "12345678-1234-1234-1234-123456789abc",
    "GitHub token": "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4",
    "API key (sk-...)": "s" + "k-" + "test0000000000000000abcd",
    "JSON web token": "ey" + "J0eXAiOiJKV1QifQ.ey" + "JzdWIiOiIxMjM0NTY3ODkwIn0.x",
    "Discord ID": "1" * 18,
    "token-like string": "Ab1" * 12,
}


@pytest.mark.parametrize("label", sorted(_FAKE_SECRETS))
def test_secrets_are_rejected(base, label):
    value = _FAKE_SECRETS[label]
    base["project"]["location"] = value
    msg = _errors(base)
    assert f"project.location: value looks like a secret ({label})" in msg
    assert value not in msg  # never echoed


def test_numeric_discord_id_is_rejected(base):
    base["agent"]["discord"]["guild"] = int("1" * 18)
    assert "agent.discord.guild: value looks like a secret (Discord ID)" in _errors(base)


def test_discord_channels_take_env_var_names(base):
    base["agent"]["discord"]["channels"]["ask"] = "discord-channel"
    assert "agent.discord.channels.ask" in _errors(base)
    base["agent"]["discord"]["channels"]["ask"] = "DISCORD_CHANNEL_ID_ASK"
    _ok(base)


def test_clean_values_are_not_flagged(base):
    assert find_secrets(base) == []
    island = json.loads(ISLAND.read_text(encoding="utf-8"))
    assert find_secrets(island) == []
    clean = {"u": "https://example.com/page", "p": "../../a/b.json", "n": 16700000}
    assert find_secrets(clean) == []


# --- schema ---------------------------------------------------------------------------


def test_schema_file_is_up_to_date():
    assert SCHEMA_FILE.read_text(encoding="utf-8") == json_schema_text(), (
        "docs/schema/project_config.schema.json is stale: "
        "run python scripts/export_config_schema.py"
    )


def test_field_reference_is_up_to_date():
    assert export_config_schema.main(["--check"]) == 0


def test_examples_validate_against_json_schema():
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    for path in (TEMPLATE, ISLAND):
        jsonschema.validate(json.loads(path.read_text(encoding="utf-8")), schema)

