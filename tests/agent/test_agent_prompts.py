"""P6.3/P6.7: the prompt files are project-neutral, complete, and render for any team."""

from __future__ import annotations

import json
import re
import sys

import agent_helpers as h
import pytest

sys.path.insert(0, str(h.REPO_ROOT / "scripts"))
import render_agent as ra  # noqa: E402

PROMPT_FILES = sorted(h.PROMPTS.glob("*.md"))
# prompts a workflow agent uses (common.md is only included by the others)
AGENT_PROMPTS = ["router", "cost", "carbon", "quantity", "general", "fallback"]
CONFIG_GLOBS = ["engines/**/*.json", "template/*.json", "tests/fixtures/**/*.json"]

FICTIONAL = {"PROJECT_NAME": "Maple Court", "LOCATION": "Springfield, Exampleland",
             "COMPLETION_DATE": "2031-05-01", "TEAM": "Fictional Team"}


def forbidden_strings() -> set[str]:
    """Names that belong to one project: the Island reference, and every team / project /
    location name in any config under the repo (examples, template, fixtures)."""
    words = {"Island", "San Juan", "Puerto Rico", "Island Team 2026", "Hostinger"}
    words.update(t.value for t in __import__("engines.common.config", fromlist=["CourseTeam"])
                 .CourseTeam)
    for pattern in CONFIG_GLOBS:
        for path in h.REPO_ROOT.glob(pattern):
            try:
                project = json.loads(path.read_text(encoding="utf-8")).get("project")
            except (ValueError, AttributeError):
                continue
            if isinstance(project, dict):
                for key in ("name", "team_name", "location"):
                    value = project.get(key)
                    if isinstance(value, str) and value.strip():
                        words.add(value.strip())
    return words


def test_there_is_a_prompt_per_agent():
    assert {p.stem for p in PROMPT_FILES} == set(AGENT_PROMPTS) | {"common"}


@pytest.mark.parametrize("path", PROMPT_FILES, ids=lambda p: p.name)
def test_no_project_specific_string_in_any_prompt(path):
    text = path.read_text(encoding="utf-8")
    for word in sorted(forbidden_strings()):
        # whole words, case-sensitive: "river" in prose is fine, the team "River" is not
        assert not re.search(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", text), \
            f"{path.name} contains project-specific text {word!r}"
    assert not re.search(r"20[2-9]\d-\d\d-\d\d", text.replace("2027-01-17", "")), \
        "no concrete dates in prompts (use the placeholder)"


@pytest.mark.parametrize("path", PROMPT_FILES, ids=lambda p: p.name)
def test_only_known_placeholders(path):
    used = set(re.findall(r"\{\{([A-Za-z_ ]+)\}\}", path.read_text(encoding="utf-8")))
    assert used <= set(ra.PLACEHOLDERS), f"unknown placeholders in {path.name}: {used}"


def test_every_placeholder_is_used_by_the_shared_context():
    assert set(re.findall(r"\{\{([A-Z_]+)\}\}", (h.PROMPTS / "common.md").read_text())) == \
        set(ra.PLACEHOLDERS)


def test_rendered_prompts_are_filled_and_free_of_braces():
    for name in AGENT_PROMPTS:
        text = ra.render_prompt(name, FICTIONAL)
        assert "{{" not in text and "@@" not in text
        # braces break the prompt template of the n8n agent node
        assert "{" not in text and "}" not in text, name
        if name != "router":
            for value in FICTIONAL.values():
                assert value in text, f"{name}: {value} missing"
        assert text.strip() == text and len(text) < 6000


def test_rendered_workflow_text_contains_no_project_string_from_the_repo():
    values = ra.resolve_values(env={f"CONCHO_{k}": v for k, v in FICTIONAL.items()})
    for name in AGENT_PROMPTS:
        text = ra.render_prompt(name, values)
        for word in forbidden_strings():
            assert not re.search(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", text)


def test_workflow_prompt_markers_match_the_prompt_files():
    wf = h.load("concho.json")
    markers = set()
    for s in h.strings(wf):
        markers.update(re.findall(r"@@PROMPT:([a-z_]+)@@", s))
    assert markers == set(AGENT_PROMPTS)
    for node in wf["nodes"]:
        if node["type"].endswith(".agent"):
            message = node["parameters"]["options"]["systemMessage"]
            assert re.fullmatch(r"@@PROMPT:[a-z_]+@@", message)


@pytest.mark.parametrize("name", ["cost", "carbon", "quantity", "general"])
def test_subagent_prompts_carry_the_shared_rules(name):
    text = ra.render_prompt(name, FICTIONAL)
    low = text.lower()
    assert "at most 2 tool calls" in low
    assert "language of the user's latest message" in low
    assert "snapshot" in low and "labels" in low
    assert "custom_material" in text and "proxy" in low and "what-if" in low
    assert "too_many_results" in text and "narrow" in low
    assert "never guess" in low


def test_stv_units_are_mj_and_kg_never_kwh_or_litres():
    carbon = ra.render_prompt("carbon", FICTIONAL)
    assert "kgCO2e" in carbon and "MJ" in carbon and "water in kg" in carbon
    for name in AGENT_PROMPTS:
        text = ra.render_prompt(name, FICTIONAL).lower()
        assert "kwh" not in text, name
        assert not re.search(r"\b(litres?|liters?|gallons?)\b", text), name
        assert not re.search(r"\d\s?l\b", text), name


def test_schedule_is_not_available_in_this_version():
    fb = ra.render_prompt("fallback", FICTIONAL)
    assert "not available in this version" in fb
    assert "SCHEDULE" in ra.render_prompt("router", FICTIONAL)
    assert "not available in this version" in ra.render_prompt("general", FICTIONAL)


def test_router_prompt_lists_the_enum_and_the_follow_up_rule():
    text = ra.render_prompt("router", FICTIONAL)
    for category in ("COST", "CARBON", "QUANTITY", "GENERAL", "SCHEDULE", "OTHER"):
        assert f"- {category}:" in text
    assert "follow-up" in text and "ISO 639-1" in text


def test_prompts_name_exactly_the_tools_of_their_agent():
    tools = {"cost": {"get_cost_summary", "get_cost_items", "cost_what_if"},
             "carbon": {"get_carbon_summary", "get_carbon_items", "carbon_what_if"},
             "quantity": {"get_quantities", "count_elements"},
             "general": {"get_cost_overview", "get_carbon_overview", "get_quality",
                         "list_snapshots", "compare_snapshots"}}
    every = set().union(*tools.values())
    for name, expected in tools.items():
        text = ra.render_prompt(name, FICTIONAL)
        named = {t for t in every if re.search(rf"\b{t}\b", text)}
        assert named == expected, f"{name}: {sorted(named ^ expected)}"
