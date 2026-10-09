"""P6.3: ``scripts/render_agent.py`` fills prompts and webhook path from config / env."""

from __future__ import annotations

import json
import sys

import agent_helpers as h
import pytest

sys.path.insert(0, str(h.REPO_ROOT / "scripts"))
import render_agent as ra  # noqa: E402

PATH = "a" * 12 + "-" + "B" * 12  # 25 characters
TEMPLATE_CONFIG = h.REPO_ROOT / "template" / "project_config.example.json"


def env(**kw):
    base = {"CONCHO_PROJECT_NAME": "Maple Court", "CONCHO_LOCATION": "Springfield",
            "CONCHO_COMPLETION_DATE": "2031-05-01", "CONCHO_TEAM": "Fictional Team",
            "CONCHO_WEBHOOK_PATH": PATH}
    base.update(kw)
    return base


def test_values_from_config_and_env_overrides(tmp_path):
    cfg = tmp_path / "project_config.json"
    cfg.write_text(json.dumps({"project": {
        "name": "Config Name", "team_name": "Config Team", "location": "Config City",
        "completion_date": "2030-08-31"}}), encoding="utf-8")
    assert ra.resolve_values(cfg, {}) == {
        "PROJECT_NAME": "Config Name", "TEAM": "Config Team", "LOCATION": "Config City",
        "COMPLETION_DATE": "2030-08-31"}
    got = ra.resolve_values(cfg, {"CONCHO_TEAM": "From Env"})
    assert got["TEAM"] == "From Env" and got["PROJECT_NAME"] == "Config Name"


def test_template_example_config_renders():
    values = ra.resolve_values(TEMPLATE_CONFIG, {})
    assert set(values) == set(ra.PLACEHOLDERS)
    assert values["COMPLETION_DATE"] == "2030-08-31"


def test_missing_values_are_listed():
    with pytest.raises(ra.RenderError) as exc:
        ra.resolve_values(None, {"CONCHO_TEAM": "T"})
    for name in ("PROJECT_NAME", "LOCATION", "COMPLETION_DATE"):
        assert name in str(exc.value)
    assert "TEAM (" not in str(exc.value)


@pytest.mark.parametrize("bad", ["{{ $env.X }}", "two\nlines", "@@PROMPT:cost@@", "x" * 300, " "])
def test_unsafe_values_are_refused(bad):
    with pytest.raises(ra.RenderError):
        ra.resolve_values(None, env(CONCHO_TEAM=bad))


def test_render_workflow_expands_prompts_and_webhook_path():
    wf = h.load("concho.json")
    values = ra.resolve_values(None, env())
    out = ra.render_workflow(wf, values, PATH)
    text = json.dumps(out)
    assert "@@" not in text and ra.WEBHOOK_PLACEHOLDER not in text
    assert PATH in text and "Maple Court" in text and "Fictional Team" in text
    assert wf == h.load("concho.json"), "the input workflow is not modified"
    # still the same graph
    assert [n["name"] for n in out["nodes"]] == [n["name"] for n in wf["nodes"]]
    assert out["connections"] == wf["connections"]
    # n8n expressions are left alone
    assert "={{ $json.message }}" in text


def test_webhook_path_must_be_long_and_plain():
    wf = h.load("concho.json")
    values = ra.resolve_values(None, env())
    with pytest.raises(ra.RenderError):
        ra.render_workflow(wf, values, None)
    for bad in ("short", "has/slash" + "x" * 20, "has space" + "x" * 20):
        with pytest.raises(ra.RenderError):
            ra.render_workflow(wf, values, bad)


def test_unknown_prompt_marker_and_placeholder(tmp_path):
    (tmp_path / "a.md").write_text("Hello {{NOPE}}", encoding="utf-8")
    with pytest.raises(ra.RenderError, match="NOPE"):
        ra.render_prompt("a", {}, tmp_path)
    with pytest.raises(ra.RenderError, match="not found"):
        ra.render_prompt("missing", {}, tmp_path)
    (tmp_path / "loop.md").write_text("@@INCLUDE:loop@@", encoding="utf-8")
    with pytest.raises(ra.RenderError, match="loop"):
        ra.load_prompt("loop", tmp_path)


def test_render_all_writes_every_workflow_but_not_legacy(tmp_path):
    written = ra.render_all(tmp_path / "build", None, env())
    assert {p.name for p in written} == {"concho.json", "error-handler.json"}
    for path in written:
        json.loads(path.read_text(encoding="utf-8"))
    assert not (tmp_path / "build" / "legacy").exists()


def test_cli_reports_errors_and_models(tmp_path, capsys, monkeypatch):
    for k in list(env()):
        monkeypatch.delenv(k, raising=False)
    assert ra.main(["--out", str(tmp_path / "o")]) == 1
    assert "missing values" in capsys.readouterr().err
    for k, v in env().items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("CONCHO_MODEL_SUBAGENT", "other-model")
    assert ra.main(["--out", str(tmp_path / "o")]) == 0
    out = capsys.readouterr().out
    assert "subagent=other-model" in out and "router=gpt-4o-mini" in out
