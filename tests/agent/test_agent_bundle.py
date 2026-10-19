"""P6.6: offline checks of the deployment bundle (compose file, credentials, import script, bot).

No Docker daemon, no n8n, no Discord: the compose file is parsed (and, where the ``docker``
CLI is present, validated with ``docker compose config``), the credential builder and the bot
logic are plain functions, and the import script is run with ``--dry-run``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from types import SimpleNamespace

import agent_helpers as h
import pytest
import yaml

COMPOSE = h.AGENT / "docker-compose.yml"
SCRIPTS = h.REPO_ROOT / "scripts"
IMPORT_SH = SCRIPTS / "import_workflows.sh"

sys.path.insert(0, str(SCRIPTS))
import n8n_credentials as creds  # noqa: E402

# a complete, fake .env (values are invented)
FAKE_ENV = {
    "CONCHO_WEBHOOK_PATH": "fake-webhook-path-0123456789abcd",
    "CONCHO_WEBHOOK_TOKEN": "fake-webhook-token",
    "CONCHO_API_TOKEN": "fake-api-token",
    "CONCHO_TEAM_REPO": "/tmp",
    "OPENAI_API_KEY": "sk-fake-openai",
    "DISCORD_BOT_TOKEN": "fake-discord-token",
    "POSTGRES_PASSWORD": "fake-pg-password",
    "N8N_ENCRYPTION_KEY": "fake-encryption-key",
}


@pytest.fixture(scope="module")
def compose():
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def _env_file(tmp_path, values=FAKE_ENV):
    path = tmp_path / ".env"
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
    return path


# --- compose file ---------------------------------------------------------------------------


def test_compose_has_the_agreed_services(compose):
    assert set(compose["services"]) == {"postgres", "memory-purge", "data-api", "n8n", "bot"}
    assert compose["services"]["bot"]["profiles"] == ["discord"]
    for name, svc in compose["services"].items():
        if name != "bot":
            assert "profiles" not in svc


def test_only_n8n_publishes_a_port_and_only_on_localhost_by_default(compose):
    for name, svc in compose["services"].items():
        if name == "n8n":
            assert svc["ports"] == ["${N8N_BIND_ADDRESS:-127.0.0.1}:5678:5678"]
        else:
            assert "ports" not in svc, f"{name} must not publish a port"
    assert not any(s.get("network_mode") == "host" for s in compose["services"].values())


def test_data_api_is_built_from_the_repo_and_gets_the_team_repo_read_only(compose):
    api = compose["services"]["data-api"]
    assert api["build"] == {"context": "..", "dockerfile": "agent/Dockerfile.api"}
    assert any(v.endswith(":/team:ro") for v in api["volumes"])
    docker = (h.AGENT / "Dockerfile.api").read_text(encoding="utf-8")
    assert "concho-api" in docker and '"serve"' in docker and "--host" in docker
    assert "USER concho" in docker  # not root
    assert "--enable-sql" not in docker  # POST /sql stays off


def test_no_secret_is_written_into_the_compose_file(compose):
    def walk(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                yield from walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                yield from walk(v, f"{path}[{i}]")
        elif isinstance(node, str):
            yield path, node

    for path, value in walk(compose["services"]):
        if re.search(r"(PASSWORD|TOKEN|KEY|SECRET)", path):
            assert value.startswith("${"), f"{path} is not read from the env"


def test_every_compose_variable_is_in_env_example(compose):
    used = set(re.findall(r"\$\{([A-Z][A-Z0-9_]*)", COMPOSE.read_text(encoding="utf-8")))
    missing = used - h.env_vars_in_example()
    assert not missing, f"not in agent/.env.example: {sorted(missing)}"


def test_scripts_and_bot_env_vars_are_in_env_example():
    text = "\n".join(p.read_text(encoding="utf-8") for p in
                     [h.AGENT / "bot" / "bot.py", SCRIPTS / "n8n_credentials.py",
                      SCRIPTS / "import_workflows.sh", SCRIPTS / "run_eval.py"]
                     if p.exists())
    used = set(re.findall(r"\b((?:CONCHO|DISCORD|POSTGRES|OPENAI|N8N)_[A-Z0-9_]+)\b", text))
    # not user settings: test-only, a Python constant, or set by the compose file itself
    used -= {"CONCHO_TEST_DATABASE_URL", "CONCHO_FIXTURES_DIR", "DISCORD_PLACEHOLDER",
             "CONCHO_WEBHOOK_URL"}
    missing = {v for v in used if v not in h.env_vars_in_example()}
    assert not missing, f"not in agent/.env.example: {sorted(missing)}"


def test_env_example_has_no_secret_values_filled_in():
    secrets = {"OPENAI_API_KEY", "DISCORD_BOT_TOKEN", "CONCHO_API_TOKEN", "CONCHO_WEBHOOK_TOKEN",
               "CONCHO_WEBHOOK_PATH", "POSTGRES_PASSWORD", "N8N_ENCRYPTION_KEY"}
    for line in h.ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        m = re.match(r"([A-Z0-9_]+)=(.*)", line)
        if m and m.group(1) in secrets:
            assert m.group(2) == "", f"{m.group(1)} has a value in .env.example"


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker CLI not installed")
def test_docker_compose_config_validates(tmp_path):
    (h.AGENT / "build").mkdir(exist_ok=True)
    env = _env_file(tmp_path)
    for profile in ([], ["--profile", "discord"]):
        proc = subprocess.run(["docker", "compose", "-f", str(COMPOSE), "--env-file", str(env),
                               *profile, "config", "--quiet"], capture_output=True, text=True)
        if "is not a docker command" in proc.stderr or "unknown shorthand" in proc.stderr:
            pytest.skip("docker compose plugin not installed")
        assert proc.returncode == 0, proc.stderr
    # the required variables are enforced
    proc = subprocess.run(["docker", "compose", "-f", str(COMPOSE), "--env-file",
                           str(_env_file(tmp_path, {"CONCHO_API_TOKEN": "x"})), "config",
                           "--quiet"], capture_output=True, text=True)
    assert proc.returncode != 0 and "POSTGRES_PASSWORD" in proc.stderr


# --- credentials ------------------------------------------------------------------------------


def test_credentials_cover_exactly_what_the_workflows_reference():
    built = creds.build(FAKE_ENV)
    assert {c["id"] for c in built} == {"concho-openai", "concho-discord",
                                        "concho-webhook-auth", "concho-postgres"}
    by_id = {c["id"]: c for c in built}
    assert by_id["concho-openai"]["type"] == "openAiApi"
    assert by_id["concho-openai"]["data"]["apiKey"] == "sk-fake-openai"
    assert by_id["concho-discord"]["data"] == {"botToken": "fake-discord-token"}
    assert by_id["concho-webhook-auth"]["data"] == {"name": "X-Concho-Token",
                                                    "value": "fake-webhook-token"}
    pg = by_id["concho-postgres"]["data"]
    assert (pg["host"], pg["database"], pg["user"], pg["password"]) == \
        ("postgres", "concho", "concho", "fake-pg-password")
    # every credential a node refers to is built, with the name the node uses
    for fname in ("concho.json", "error-handler.json"):
        for node in h.load(fname)["nodes"]:
            for ctype, ref in node.get("credentials", {}).items():
                assert (by_id[ref["id"]]["name"], by_id[ref["id"]]["type"]) == (ref["name"], ctype)


@pytest.mark.parametrize("name", ["OPENAI_API_KEY", "CONCHO_WEBHOOK_TOKEN", "POSTGRES_PASSWORD"])
def test_credentials_refuse_an_empty_secret(name):
    with pytest.raises(creds.CredentialError, match=name):
        creds.build({**FAKE_ENV, name: " "})


def test_discord_token_may_be_missing_for_an_eval_only_setup():
    built = creds.build({k: v for k, v in FAKE_ENV.items() if k != "DISCORD_BOT_TOKEN"})
    data = next(c["data"] for c in built if c["id"] == "concho-discord")
    assert data == {"botToken": creds.DISCORD_PLACEHOLDER}


def test_credentials_list_prints_no_secret(capsys, monkeypatch):
    for k, v in FAKE_ENV.items():
        monkeypatch.setenv(k, v)
    assert creds.main(["--list"]) == 0
    out = capsys.readouterr().out
    assert "concho-openai" in out
    assert not any(v in out for v in FAKE_ENV.values())


# --- import script (dry run) ----------------------------------------------------------------


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_import_script_syntax_and_dry_run_steps(tmp_path):
    assert subprocess.run(["bash", "-n", str(IMPORT_SH)]).returncode == 0
    proc = subprocess.run(["bash", str(IMPORT_SH), "--dry-run", "--env-file",
                           str(_env_file(tmp_path))], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    order = ["render_agent.py", "up -d --build --wait postgres data-api n8n",
             "concho-discord", "concho-openai", "concho-postgres", "concho-webhook-auth",
             "import:credentials",
             "import:workflow --input=/import/error-handler.json",
             "import:workflow --input=/import/concho.json", "update:workflow", "restart n8n"]
    pos = [out.index(s) for s in order]
    assert pos == sorted(pos)
    assert not any(v in out + proc.stderr for v in FAKE_ENV.values() if len(v) > 4 and v != "/tmp")


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_import_script_stops_on_missing_values(tmp_path):
    env = _env_file(tmp_path, {"CONCHO_WEBHOOK_PATH": "x"})
    proc = subprocess.run(["bash", str(IMPORT_SH), "--dry-run", "--env-file", str(env)],
                          capture_output=True, text=True)
    assert proc.returncode == 1
    assert "OPENAI_API_KEY" in proc.stderr and "POSTGRES_PASSWORD" in proc.stderr


# --- bot --------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def bot():
    spec = importlib.util.spec_from_file_location("concho_bot", h.AGENT / "bot" / "bot.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BOT_ID = 900


def _msg(content="how much is the roof?", author=1, channel=10, parent=None, mentions=(),
         is_bot=False, attachments=()):
    chan = SimpleNamespace(id=channel, parent_id=parent)
    return SimpleNamespace(
        content=content, id=555, author=SimpleNamespace(id=author, bot=is_bot,
                                                        display_name="Ana"),
        channel=chan, guild=SimpleNamespace(id=77),
        mentions=[SimpleNamespace(id=m) for m in mentions],
        attachments=[SimpleNamespace(url=u) for u in attachments])


def test_bot_handles_ask_channels_threads_and_mentions_only(bot):
    ask = bot.parse_ids("10, 11")
    assert ask == {"10", "11"}
    assert bot.should_handle(_msg(channel=10), BOT_ID, ask)
    assert bot.should_handle(_msg(channel=99, parent=11), BOT_ID, ask)  # thread under #ask
    assert not bot.should_handle(_msg(channel=12), BOT_ID, ask)
    assert bot.should_handle(_msg(channel=12, mentions=[BOT_ID]), BOT_ID, ask)
    assert not bot.should_handle(_msg(is_bot=True), BOT_ID, ask)
    assert not bot.should_handle(_msg(author=BOT_ID), BOT_ID, ask)
    assert not bot.should_handle(_msg(content="   "), BOT_ID, ask)


def test_bot_payload_follows_the_input_contract(bot):
    payload = bot.build_payload(_msg(content=f"<@{BOT_ID}> and on Level 2?", channel=10,
                                     attachments=["https://cdn.example/a.png"]), BOT_ID)
    assert payload == {"content": "and on Level 2?", "author_id": "1", "author_name": "Ana",
                       "channel_id": "10", "guild_id": "77", "message_id": "555",
                       "source": "discord", "attachments": ["https://cdn.example/a.png"]}
    thread = bot.build_payload(_msg(channel=99, parent=10), BOT_ID)
    assert thread["thread_id"] == "99" and thread["channel_id"] == "10"
    # the keys the workflow's normalizer reads
    norm = h.by_name(h.load("concho.json"))["Normalize input"]
    text = json.dumps(norm["parameters"])
    for key in ("content", "author_id", "author_name", "thread_id", "channel_id", "guild_id",
                "message_id", "attachments", "source"):
        assert f"body.{key}" in text


def test_bot_ignores_the_response_body_and_sends_the_token_header(bot):
    seen = {}

    class Resp:
        status = 200

        async def read(self):
            seen["read"] = True
            return b'{"reply": "ignored"}'

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class Session:
        def post(self, url, **kwargs):
            seen["url"], seen["kwargs"] = url, kwargs
            return Resp()

    status = asyncio.run(bot.post_to_webhook(Session(), "http://n8n:5678/webhook/p", "tok",
                                             {"content": "x"}))
    assert status == 200
    assert seen["kwargs"]["headers"] == {"X-Concho-Token": "tok"}
    assert seen["kwargs"]["json"] == {"content": "x"}
    # the bot never posts anything to Discord itself: n8n replies
    source = (h.AGENT / "bot" / "bot.py").read_text(encoding="utf-8")
    assert "channel.send" not in source and ".reply(" not in source


def test_bot_requirements_are_pinned():
    for line in (h.AGENT / "bot" / "requirements.txt").read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            assert "==" in line
