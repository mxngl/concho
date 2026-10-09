"""P6.2/P6.7: offline checks of ``agent/workflows/concho.json`` and ``error-handler.json``.

No n8n and no LLM here: the checks are on the JSON (valid references, no hard-coded URLs, IDs
or tokens, no node references downstream of the input normalizer, the router and the tools
match the data API, models come from the env). What only a running n8n can show is listed in
``docs/agent.md``.
"""

from __future__ import annotations

import re
import sys
from collections import deque

import agent_helpers as h
import pytest

sys.path.insert(0, str(h.REPO_ROOT / "scripts"))
import render_agent  # noqa: E402

import check_forbidden  # noqa: E402

WORKFLOW_FILES = ["concho.json", "error-handler.json"]
CATEGORIES = ["COST", "CARBON", "QUANTITY", "SCHEDULE", "GENERAL", "OTHER"]
SUBAGENTS = ["Cost Agent", "Carbon Agent", "Quantity Agent", "General Agent", "Fallback Agent"]
TOOL_NODES = {
    "Cost Agent": {"get_cost_summary", "get_cost_items", "cost_what_if"},
    "Carbon Agent": {"get_carbon_summary", "get_carbon_items", "carbon_what_if"},
    "Quantity Agent": {"get_quantities", "count_elements"},
    "General Agent": {"get_cost_overview", "get_carbon_overview", "get_quality",
                      "list_snapshots", "compare_snapshots"},
    "Fallback Agent": set(),
}


@pytest.fixture(scope="module")
def wf():
    return h.load("concho.json")


@pytest.fixture(scope="module")
def err():
    return h.load("error-handler.json")


# ------------------------------------------------------------------ structure


@pytest.mark.parametrize("name", WORKFLOW_FILES)
def test_nodes_and_connections_are_consistent(name):
    wf = h.load(name)
    nodes = wf["nodes"]
    names = [n["name"] for n in nodes]
    ids = [n["id"] for n in nodes]
    assert len(set(names)) == len(names), "node names must be unique"
    assert len(set(ids)) == len(ids), "node ids must be unique"
    for n in nodes:
        assert n["type"] and isinstance(n["typeVersion"], (int, float))
        assert len(n["position"]) == 2
    for src, dst, kind, _out in h.edges(wf):
        assert src in names, f"connection from unknown node {src!r}"
        assert dst in names, f"connection to unknown node {dst!r}"
        assert kind in ("main", "ai_languageModel", "ai_tool", "ai_outputParser", "ai_memory")


def test_every_node_is_reachable_from_a_trigger(wf, err):
    for workflow, trigger in ((wf, "Webhook"), (err, "Error Trigger")):
        # sub-nodes (model, tools, parser) point at their agent: follow edges both ways for
        # ai_* connections, forwards for main ones.
        nodes = h.by_name(workflow)
        fwd: dict[str, set[str]] = {n: set() for n in nodes}
        for src, dst, kind, _ in h.edges(workflow):
            fwd[src].add(dst)
            if kind != "main":
                fwd[dst].add(src)
        seen, queue = {trigger}, deque([trigger])
        while queue:
            for nxt in fwd[queue.popleft()]:
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        assert set(nodes) == seen, f"unreachable nodes: {sorted(set(nodes) - seen)}"


def test_agents_have_one_model_and_only_the_data_tools(wf):
    nodes = h.by_name(wf)
    models: dict[str, list[str]] = {}
    tools: dict[str, set[str]] = {}
    for src, dst, kind, _ in h.edges(wf):
        if kind == "ai_languageModel":
            models.setdefault(dst, []).append(src)
        if kind == "ai_tool":
            tools.setdefault(dst, set()).add(src)
    agents = [n for n, v in nodes.items() if v["type"].endswith(".agent")]
    assert sorted(agents) == sorted(["Router", *SUBAGENTS])
    for agent in agents:
        assert len(models.get(agent, [])) == 1, f"{agent}: exactly one chat model"
        assert nodes[models[agent][0]]["type"].endswith(".lmChatOpenAi")
    for agent, expected in TOOL_NODES.items():
        assert tools.get(agent, set()) == expected, agent
    assert "Router" not in tools
    # a tool node belongs to one agent only (n8n sub-nodes are not shared)
    all_tools = [t for ts in tools.values() for t in ts]
    assert len(all_tools) == len(set(all_tools))
    for t in all_tools:
        assert nodes[t]["type"] == "n8n-nodes-base.httpRequestTool", f"{t}: only HTTP tools"


def test_tool_nodes_are_unique_and_fully_connected(wf):
    nodes = h.by_name(wf)
    tool_nodes = {n for n, v in nodes.items() if v["type"].endswith("Tool")}
    wired = {src for src, _dst, kind, _ in h.edges(wf) if kind == "ai_tool"}
    assert tool_nodes == wired, "every tool node must be attached to an agent"


def test_no_node_references_downstream_of_the_normalizer(wf):
    """Expressions use $json of the previous item (carried through merges), never $('Node')."""
    pattern = re.compile(r"\$\(\s*['\"`]|\$node\s*\[|\$items\(|\$prevNode|\$input\.|\.item\.json")
    for n in wf["nodes"]:
        for s in h.strings(n["parameters"]):
            assert not pattern.search(s), f"{n['name']}: node reference in {s[:80]!r}"
    # the only nodes that read the webhook body are the normalizer's expressions
    for n in wf["nodes"]:
        if n["name"] == "Normalize input":
            continue
        for s in h.strings(n["parameters"]):
            assert "$json.body" not in s, f"{n['name']} reads the raw webhook body"


def test_normalizer_is_one_set_node_with_the_agreed_fields(wf):
    nodes = h.by_name(wf)
    norm = nodes["Normalize input"]
    assert norm["type"] == "n8n-nodes-base.set"
    fields = {a["name"] for a in norm["parameters"]["assignments"]["assignments"]}
    assert fields == {"message", "user_id", "user_name", "channel_id", "guild_id", "message_id",
                      "session_id", "source", "attachments"}
    assert norm["parameters"]["includeOtherFields"] is False
    feeds = {s for s, d, k, _ in h.edges(wf) if d == "Normalize input" and k == "main"}
    assert feeds == {"Webhook"}
    # a thread is a channel in Discord: the thread id wins so the reply lands in the thread
    channel = next(a for a in norm["parameters"]["assignments"]["assignments"]
                   if a["name"] == "channel_id")["value"]
    assert channel.index("thread_id") < channel.index("channel_id")


# ------------------------------------------------------------------ router


def test_router_uses_structured_output_with_the_category_enum(wf):
    import json
    nodes = h.by_name(wf)
    router = nodes["Router"]
    assert router["parameters"]["hasOutputParser"] is True
    parser = nodes["Router Output"]
    assert parser["type"].endswith("outputParserStructured")
    schema = json.loads(parser["parameters"]["inputSchema"])
    assert schema["properties"]["category"]["enum"] == CATEGORIES
    assert "category" in schema["required"]
    assert ("Router Output", "Router", "ai_outputParser", 0) in set(h.edges(wf))


def test_switch_covers_every_category_and_has_a_fallback(wf):
    switch = h.by_name(wf)["Route"]
    rules = switch["parameters"]["rules"]["values"]
    keys = [r["outputKey"] for r in rules]
    assert keys == ["COST", "CARBON", "QUANTITY", "GENERAL", "SCHEDULE"]
    opts = switch["parameters"]["options"]
    assert opts["fallbackOutput"] == "extra" and opts["renameFallbackOutput"] == "OTHER"
    # case-insensitive match on the normalized category
    for r in rules:
        assert r["conditions"]["options"]["caseSensitive"] is False
    wired = {out: dst for src, dst, _k, out in h.edges(wf) if src == "Route"}
    assert wired == {0: "Cost Agent", 1: "Carbon Agent", 2: "Quantity Agent", 3: "General Agent",
                     4: "Fallback Agent", 5: "Fallback Agent"}, "all 6 outputs wired"


def test_schedule_and_other_reach_no_data_tool(wf):
    assert TOOL_NODES["Fallback Agent"] == set()
    tools = {s for s, d, k, _ in h.edges(wf) if d == "Fallback Agent" and k == "ai_tool"}
    assert tools == set()


# ------------------------------------------------------------------ errors and reply


def test_every_llm_node_has_an_error_branch_to_the_user_message(wf):
    nodes = h.by_name(wf)
    for agent in ["Router", *SUBAGENTS]:
        assert nodes[agent].get("onError") == "continueErrorOutput", agent
        assert (agent, "Error reply", "main", 1) in set(h.edges(wf)), agent
    assert nodes["Router"].get("retryOnFail") is True


def test_global_error_workflow_exists_and_posts_to_the_debug_channel(wf, err):
    assert wf["settings"]["errorWorkflow"] == err["id"]
    types = {n["type"] for n in err["nodes"]}
    assert "n8n-nodes-base.errorTrigger" in types
    debug = next(n for n in err["nodes"] if n["type"].endswith(".discord"))
    assert "$env.DISCORD_CHANNEL_ID_DEBUG" in debug["parameters"]["channelId"]["value"]
    # details go to the debug channel; the message of the user is not in the error payload
    assert "message" not in debug["parameters"]["content"].replace("error?.message", "")


def test_reply_goes_to_the_originating_channel_and_mentions_the_user(wf):
    nodes = h.by_name(wf)
    send = nodes["Send reply"]
    assert send["type"] == "n8n-nodes-base.discord"
    assert send["parameters"]["channelId"]["value"] == "={{ $json.channel_id }}"
    assert "<@{{ $json.user_id }}>" in send["parameters"]["content"]
    assert "$json.reply" in send["parameters"]["content"]
    gate = [s for s in h.strings(nodes["Reply on Discord?"]["parameters"])]
    assert "discord" in gate
    # the webhook answers the caller (bot / eval) before Discord is posted to
    order = [(s, d) for s, d, k, _ in h.edges(wf) if k == "main"]
    assert ("Attach answer", "Compose reply") in order
    assert ("Error reply", "Compose reply") in order, "errors are answered like any reply"
    assert ("Compose reply", "Respond to caller") in order
    assert ("Respond to caller", "Reply on Discord?") in order
    assert nodes["Webhook"]["parameters"]["responseMode"] == "responseNode"
    assert nodes["Webhook"]["parameters"]["authentication"] == "headerAuth"


def test_agents_cap_tool_calls(wf):
    nodes = h.by_name(wf)
    for agent in SUBAGENTS:
        # 2 tool calls + the answer
        assert nodes[agent]["parameters"]["options"]["maxIterations"] <= 3
        assert nodes[agent]["parameters"]["options"]["returnIntermediateSteps"] is True


# ------------------------------------------------------------------ hard-coded values


@pytest.mark.parametrize("name", WORKFLOW_FILES)
def test_no_hard_coded_urls_ids_or_tokens(name):
    wf = h.load(name)
    text = (h.WORKFLOWS / name).read_text(encoding="utf-8")
    assert not check_forbidden.check_text(text, f"agent/workflows/{name}")
    for s in h.strings(wf):
        assert not re.search(r"https?://", s), f"hard-coded URL: {s[:80]!r}"
        assert not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", s), f"hard-coded IP: {s[:80]!r}"
        assert not re.search(r"\bsk-[A-Za-z0-9]{8,}|\bBearer\s+(?!\{\{)", s), \
            f"token in {s[:60]!r}"
    # credentials are referenced by id and name only, never stored
    for n in wf["nodes"]:
        for cred in n.get("credentials", {}).values():
            assert set(cred) == {"id", "name"}


def test_discord_ids_come_from_the_env_or_the_input(wf, err):
    for workflow in (wf, err):
        for n in workflow["nodes"]:
            if not n["type"].endswith(".discord"):
                continue
            for key in ("guildId", "channelId"):
                value = n["parameters"][key]["value"]
                assert value.startswith("={{") and ("$env." in value or "$json." in value)


def test_tools_call_only_the_data_api_through_the_env_url(wf):
    for n in wf["nodes"]:
        if n["type"] != "n8n-nodes-base.httpRequestTool":
            continue
        assert n["parameters"]["url"].startswith("={{ $env.CONCHO_API_URL }}/"), n["name"]
        headers = {p["name"]: p["value"] for p in n["parameters"]["headerParameters"]["parameters"]}
        assert headers == {"Authorization": "=Bearer {{ $env.CONCHO_API_TOKEN }}"}
        # the API's 4xx answers ({"error": ..., "hint": ...}) must reach the model
        assert n["parameters"]["options"]["response"]["response"]["neverError"] is True
        assert n["parameters"]["toolDescription"].strip()


def test_tools_match_the_data_api(wf, api_routes):
    """Path, method and every query parameter of each tool exist in the API's OpenAPI schema."""
    seen = set()
    for n in wf["nodes"]:
        if n["type"] != "n8n-nodes-base.httpRequestTool":
            continue
        path = n["parameters"]["url"].split("}}", 1)[1]
        assert path in api_routes, f"{n['name']}: {path} is not an endpoint of the data API"
        assert path != "/sql"
        seen.add(path)
        route_params = api_routes[path]
        sent = [p["name"] for p in n["parameters"].get("queryParameters", {}).get("parameters", [])]
        for name in sent:
            assert name in route_params["all"], f"{n['name']}: unknown parameter {name}"
        for required in route_params["required"]:
            assert required in sent, f"{n['name']}: required parameter {required} not offered"
        for p in n["parameters"].get("queryParameters", {}).get("parameters", []):
            assert "$fromAI(" in p["value"]
    # every Tier-1 endpoint except the health check and the optional SQL one has a tool
    assert seen == set(api_routes) - {"/health", "/sql"}


# ------------------------------------------------------------------ models and env


def test_models_come_from_the_env_with_the_default(wf):
    role = {"Router Model": "CONCHO_MODEL_ROUTER"}
    role.update({f"{a.replace(' Agent', '')} Model": "CONCHO_MODEL_SUBAGENT" for a in SUBAGENTS})
    models = [n for n in wf["nodes"] if n["type"].endswith(".lmChatOpenAi")]
    assert {n["name"] for n in models} == set(role)
    for n in models:
        value = n["parameters"]["model"]["value"]
        assert value == "={{ $env." + role[n["name"]] + f" || '{render_agent.DEFAULT_MODEL}' }}}}"
    assert render_agent.DEFAULT_MODEL == "gpt-4o-mini"
    assert render_agent.model_settings({}) == {"router": "gpt-4o-mini", "subagent": "gpt-4o-mini",
                                              "tts": "gpt-4o-mini-tts"}
    assert render_agent.model_settings({"CONCHO_MODEL_ROUTER": "x"})["router"] == "x"


def test_every_env_var_used_is_in_env_example(wf, err):
    documented = h.env_vars_in_example()
    used = set()
    for workflow in (wf, err):
        for s in h.strings(workflow):
            used.update(re.findall(r"\$env\.([A-Z][A-Z0-9_]*)", s))
    assert used, "the workflows read the env"
    assert used <= documented, f"not in agent/.env.example: {sorted(used - documented)}"
    # the model variables and the render script's own variables are documented too
    needed = set(render_agent.MODEL_ENV.values()) | {e for e, _ in render_agent.SOURCES.values()}
    assert needed | {render_agent.WEBHOOK_ENV} <= documented


def test_env_example_has_no_values_that_look_like_secrets():
    for line in h.ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            if key.endswith(("TOKEN", "KEY", "PATH")):
                assert value.strip() == "", f"{key} must be empty in .env.example"
    assert not check_forbidden.check_text(h.ENV_EXAMPLE.read_text(encoding="utf-8"),
                                          "agent/.env.example")
