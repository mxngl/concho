"""P6.6: the deployment bundle, checked statically (no Docker daemon, no n8n, no Discord).

``docker compose config`` runs when the Docker CLI is installed (it needs no daemon). The bot's
logic is tested with stand-in message objects; the import script runs against stand-ins for
``docker`` and ``n8n`` that record what they were asked to do.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from types import SimpleNamespace

import agent_helpers as h
import pytest
import yaml

COMPOSE = h.AGENT / "docker-compose.yml"
IMPORT_SH = h.REPO_ROOT / "scripts" / "import_workflows.sh"
sys.path.insert(0, str(h.REPO_ROOT / "scripts"))
sys.path.insert(0, str(h.AGENT / "bot"))
import agent_credentials as ac  # noqa: E402
import bot  # noqa: E402

REQUIRED = {  # variables without which compose must refuse to start
    "POSTGRES_USER", "POSTGRES_PASSWORD", "N8N_VERSION", "N8N_ENCRYPTION_KEY", "CONCHO_API_TOKEN",
    "DISCORD_BOT_TOKEN", "DISCORD_CHANNEL_ID_ASK", "CONCHO_WEBHOOK_PATH", "CONCHO_WEBHOOK_TOKEN",
    "CONCHO_TEAM_REPO",
}
DUMMY_ENV = {
    "POSTGRES_USER": "concho", "POSTGRES_PASSWORD": "pw-for-tests", "N8N_VERSION": "1.0.0",
    "N8N_ENCRYPTION_KEY": "key-for-tests", "CONCHO_API_TOKEN": "api-token-for-tests",
    "DISCORD_BOT_TOKEN": "discord-token-for-tests", "DISCORD_CHANNEL_ID_ASK": "111,222",
    "CONCHO_WEBHOOK_PATH": "a" * 30, "CONCHO_WEBHOOK_TOKEN": "hook-token-for-tests",
    "CONCHO_TEAM_REPO": "/tmp", "OPENAI_API_KEY": "sk-for-tests",
    "CONCHO_PROJECT_NAME": "Demo Project", "CONCHO_LOCATION": "Somewhere",
    "CONCHO_COMPLETION_DATE": "June 1, 2030", "CONCHO_TEAM": "Demo Team",
}


@pytest.fixture(scope="module")
def compose():
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def write_env(path, values=DUMMY_ENV):
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
    return path


# ------------------------------------------------------------------ compose


def test_services(compose):
    assert set(compose["services"]) == {"postgres", "memory-maintenance", "n8n", "discord-bot",
                                        "data-api"}


def test_only_n8n_publishes_a_port_and_only_on_localhost(compose):
    for name, svc in compose["services"].items():
        assert "network_mode" not in svc
        if name != "n8n":
            assert "ports" not in svc, f"{name} must not publish a port"
    (port,) = compose["services"]["n8n"]["ports"]
    assert port.startswith("127.0.0.1:")


def test_data_api_and_postgres_are_on_the_internal_network_only(compose):
    assert compose["networks"]["backend"]["internal"] is True
    for name in ("postgres", "memory-maintenance", "data-api"):
        assert compose["services"][name]["networks"] == ["backend"]
    assert compose["services"]["discord-bot"]["networks"] == ["default"]
    assert set(compose["services"]["n8n"]["networks"]) == {"default", "backend"}


def test_data_api_is_the_concho_api_server_on_the_team_repo(compose):
    svc = compose["services"]["data-api"]
    dockerfile = (h.AGENT / "api" / "Dockerfile").read_text(encoding="utf-8")
    assert '"concho-api", "serve"' in dockerfile and 'pip install ".[api]"' in dockerfile
    assert any(v.endswith(":/team:ro") for v in svc["volumes"]), "team repo is mounted read-only"
    assert "--enable-sql" not in dockerfile and "CONCHO_API_ENABLE_SQL" not in str(svc)
    # n8n reaches it by service name
    n8n_env = compose["services"]["n8n"]["environment"]
    assert "http://data-api:8000" in n8n_env["CONCHO_API_URL"]


def test_n8n_gets_everything_the_workflows_read(compose):
    env = compose["services"]["n8n"]["environment"]
    used = set()
    for name in ("concho.json", "error-handler.json"):
        for s in h.strings(h.load(name)):
            used.update(re.findall(r"\$env\.([A-Z][A-Z0-9_]*)", s))
    assert used <= set(env), f"not passed to the n8n container: {sorted(used - set(env))}"
    assert env["N8N_BLOCK_ENV_ACCESS_IN_NODE"] == "false"
    assert env["DB_TYPE"] == "postgresdb"


def test_bot_posts_to_the_webhook_of_n8n(compose):
    env = compose["services"]["discord-bot"]["environment"]
    assert env["CONCHO_WEBHOOK_URL"].startswith("http://n8n:5678/webhook/${CONCHO_WEBHOOK_PATH")
    wf = h.load("concho.json")
    webhook = h.by_name(wf)["Webhook"]
    assert webhook["parameters"]["httpMethod"] == "POST"


def test_secrets_are_required_and_nothing_is_hard_coded():
    text = COMPOSE.read_text(encoding="utf-8")
    for var in REQUIRED:
        assert "${" + var + ":?" in text, f"{var} must be required (no empty default)"
    assert not re.search(r"(PASSWORD|TOKEN|KEY): (?!\$\{)\S", text)
    assert not re.search(r"\b\d{17,20}\b", text)  # no Discord ids


def test_every_compose_variable_is_in_env_example():
    text = COMPOSE.read_text(encoding="utf-8")
    used = set(re.findall(r"\$\{([A-Z][A-Z0-9_]*)", text))
    documented = h.env_vars_in_example()
    assert used <= documented, f"not in agent/.env.example: {sorted(used - documented)}"


def test_every_env_example_variable_is_used_somewhere():
    sources = []
    for path in [COMPOSE, *h.AGENT.rglob("*.json"), *h.AGENT.glob("bot/*.py"),
                 *(h.REPO_ROOT / "scripts").glob("*.py"), IMPORT_SH]:
        sources.append(path.read_text(encoding="utf-8"))
    blob = "\n".join(sources)
    unused = {v for v in h.env_vars_in_example() if v not in blob}
    assert not unused, f"in .env.example but read by nothing: {sorted(unused)}"


def test_env_example_secrets_are_empty():
    for line in h.ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            if re.search(r"TOKEN|KEY|PASSWORD|SECRET|PATH$", key):
                assert value.strip() == "", f"{key} must be empty in .env.example"


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker CLI not installed")
def test_docker_compose_config_validates(tmp_path):
    env = write_env(tmp_path / "test.env")
    probe = subprocess.run(["docker", "compose", "version"], capture_output=True, text=True)
    if probe.returncode != 0:
        pytest.skip("docker compose plugin not installed")
    proc = subprocess.run(["docker", "compose", "-f", str(COMPOSE), "--env-file", str(env),
                           "config", "--format", "json"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    cfg = json.loads(proc.stdout)
    assert cfg["services"]["discord-bot"]["environment"]["CONCHO_WEBHOOK_URL"] == (
        "http://n8n:5678/webhook/" + "a" * 30)
    assert cfg["services"]["data-api"]["volumes"][0]["read_only"] is True
    # without the required values compose must refuse
    bare = subprocess.run(["docker", "compose", "-f", str(COMPOSE), "--env-file",
                           str(write_env(tmp_path / "bare.env", {})), "config"],
                          capture_output=True, text=True)
    assert bare.returncode != 0 and "set POSTGRES_USER" in bare.stderr


def test_memory_maintenance_command_uses_the_sql_file(compose):
    svc = compose["services"]["memory-maintenance"]
    assert "./memory.sql:/memory.sql:ro" in svc["volumes"]
    script = svc["command"][-1]
    assert "-f /memory.sql" in script and "concho_purge_chat_history" in script
    assert "sleep 86400" in script


# ------------------------------------------------------------------ credentials


def test_credentials_match_the_workflows_and_hold_the_env_values():
    creds = {c["id"]: c for c in ac.build_credentials(DUMMY_ENV)}
    referenced: dict[str, dict] = {}
    for name in ("concho.json", "error-handler.json"):
        for n in h.load(name)["nodes"]:
            for kind, cred in n.get("credentials", {}).items():
                referenced[cred["id"]] = {"name": cred["name"], "kind": kind}
    assert set(referenced) == set(creds) == {"concho-openai", "concho-discord",
                                             "concho-webhook-auth", "concho-postgres"}
    for cid, ref in referenced.items():
        assert creds[cid]["name"] == ref["name"]
        assert creds[cid]["type"] == {"httpHeaderAuth": "httpHeaderAuth", "openAiApi": "openAiApi",
                                      "discordBotApi": "discordBotApi",
                                      "postgres": "postgres"}[ref["kind"]]
    assert creds["concho-openai"]["data"]["apiKey"] == "sk-for-tests"
    assert creds["concho-discord"]["data"]["botToken"] == "discord-token-for-tests"
    assert creds["concho-webhook-auth"]["data"] == {"name": "X-Concho-Token",
                                                    "value": "hook-token-for-tests"}
    assert creds["concho-postgres"]["data"]["host"] == "postgres"
    assert creds["concho-postgres"]["data"]["password"] == "pw-for-tests"


def test_credentials_need_their_variables():
    with pytest.raises(ac.CredentialError, match="OPENAI_API_KEY"):
        ac.build_credentials({k: v for k, v in DUMMY_ENV.items() if k != "OPENAI_API_KEY"})


def test_dotenv_parser(tmp_path):
    from agent_env import load_env, parse_env_text

    text = ('# c\nA=1\nB="two words" # c\nC=three # inline\nexport D=\'4\'\nE=\nF=a#b\n'
            'G=has $dollar\n')
    assert parse_env_text(text) == {"A": "1", "B": "two words", "C": "three", "D": "4", "E": "",
                                    "F": "a#b", "G": "has $dollar"}
    f = tmp_path / "x.env"
    f.write_text("A=file\nB=file\n", encoding="utf-8")
    assert load_env(f, {"A": "process"}) == {"A": "process", "B": "file"}


# ------------------------------------------------------------------ bot


def msg(content="how much is the roof?", *, channel_id=111, parent_id=None, bot_author=False,
        author_id=42, attachments=()):
    channel = SimpleNamespace(id=channel_id, parent_id=parent_id)
    author = SimpleNamespace(id=author_id, name="max", display_name="Max", bot=bot_author)
    return SimpleNamespace(content=content, channel=channel, author=author, id=999,
                           guild=SimpleNamespace(id=7), attachments=list(attachments))


def test_bot_builds_the_payload_the_normalizer_reads():
    payload = bot.build_payload(msg())
    assert payload == {"content": "how much is the roof?", "author_id": "42",
                       "author_name": "Max", "channel_id": "111", "guild_id": "7",
                       "message_id": "999", "source": "discord", "attachments": []}
    # every key is one that "Normalize input" reads
    wf = h.load("concho.json")
    expr = json.dumps(h.by_name(wf)["Normalize input"]["parameters"])
    for key in payload:
        assert f"body.{key}" in expr or key in ("content",), key
    assert "body.content" in expr


def test_bot_thread_message_carries_thread_id_and_parent_channel():
    payload = bot.build_payload(msg(channel_id=555, parent_id=111))
    assert payload["channel_id"] == "111" and payload["thread_id"] == "555"
    assert "thread_id" not in bot.build_payload(msg())


def test_bot_ids_stay_strings_beyond_2_pow_53():
    big = 1_234_567_890_123_456_789
    payload = bot.build_payload(msg(channel_id=big, author_id=big))
    assert payload["channel_id"] == str(big) and payload["author_id"] == str(big)
    json.dumps(payload)


def test_bot_filters_messages():
    allowed = bot.parse_channel_ids("111, 222,")
    assert allowed == {"111", "222"}
    assert bot.should_handle(msg(), allowed, 1)
    assert bot.should_handle(msg(channel_id=555, parent_id=222), allowed, 1)  # thread
    assert not bot.should_handle(msg(channel_id=333), allowed, 1)  # other channel
    assert not bot.should_handle(msg(bot_author=True), allowed, 1)
    assert not bot.should_handle(msg(author_id=1), allowed, 1)  # itself
    assert not bot.should_handle(msg("   "), allowed, 1)


def test_bot_settings_need_all_variables():
    env = {"DISCORD_BOT_TOKEN": "t", "DISCORD_CHANNEL_ID_ASK": "1", "CONCHO_WEBHOOK_URL": "u",
           "CONCHO_WEBHOOK_TOKEN": "w"}
    assert bot.settings(env)["channels"] == {"1"}
    del env["CONCHO_WEBHOOK_TOKEN"]
    with pytest.raises(SystemExit, match="CONCHO_WEBHOOK_TOKEN"):
        bot.settings(env)


def test_bot_posts_with_the_token_and_ignores_the_body():
    calls = []

    class Response:
        status = 200

        async def read(self):
            return b"not looked at"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class Session:
        def post(self, url, json, headers):
            calls.append((url, json, headers))
            return Response()

    status = asyncio.run(bot.post_to_webhook(Session(), "http://n8n/x", "tok", {"content": "q"}))
    assert status == 200
    assert calls == [("http://n8n/x", {"content": "q"}, {"X-Concho-Token": "tok"})]
    source = (h.AGENT / "bot" / "bot.py").read_text(encoding="utf-8")
    assert ".json()" not in source and ".text()" not in source  # the body is never parsed


def test_bot_has_no_reply_path():
    source = (h.AGENT / "bot" / "bot.py").read_text(encoding="utf-8")
    assert "channel.send" not in source and ".reply(" not in source


# ------------------------------------------------------------------ import script


def fake_bin(tmp_path):
    """``docker`` and ``n8n`` stand-ins: docker runs the command after ``exec -T n8n`` locally,
    n8n logs its arguments and keeps a copy of the --input file."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "calls.log"
    docker = bindir / "docker"
    docker.write_text(f"""#!/usr/bin/env bash
echo "docker $*" >> {log}
args=("$@")
for i in "${{!args[@]}}"; do
  if [[ "${{args[$i]}}" == exec ]]; then
    rest=("${{args[@]:$((i+3))}}")   # skip: exec -T n8n
    exec "${{rest[@]}}"
  fi
done
exit 0
""", encoding="utf-8")
    n8n = bindir / "n8n"
    n8n.write_text(f"""#!/usr/bin/env bash
echo "n8n $*" >> {log}
for a in "$@"; do
  case "$a" in --input=*) n=$(ls "{tmp_path}" | grep -c '^imported-')
                          cp "${{a#--input=}}" "{tmp_path}/imported-$n-$1"
                          echo "input-exists $(ls -l ${{a#--input=}} | cut -c1-10)" >> {log};; esac
done
exit 0
""", encoding="utf-8")
    for p in (docker, n8n):
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return bindir, log


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_import_script_dry_run(tmp_path):
    env_file = write_env(tmp_path / "t.env")
    out = tmp_path / "build"
    proc = subprocess.run(["bash", str(IMPORT_SH), "--env-file", str(env_file), "--build-dir",
                           str(out), "--dry-run"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert {p.name for p in out.glob("*.json")} == {"concho.json", "error-handler.json"}
    for secret in ("sk-for-tests", "pw-for-tests", "hook-token-for-tests",
                   "discord-token-for-tests"):
        assert secret not in proc.stdout, "secrets must be masked in the dry run"
    assert "concho-postgres" in proc.stdout


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_import_script_imports_credentials_then_workflows(tmp_path):
    bindir, log = fake_bin(tmp_path)
    env_file = write_env(tmp_path / "t.env")
    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}
    proc = subprocess.run(["bash", str(IMPORT_SH), "--env-file", str(env_file), "--build-dir",
                           str(tmp_path / "build")], capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    calls = log.read_text(encoding="utf-8").splitlines()
    n8n_calls = [c for c in calls if c.startswith("n8n ")]
    assert [" ".join(c.split()[:2]) for c in n8n_calls] == [
        "n8n --version", "n8n import:credentials", "n8n import:workflow",
        "n8n import:workflow", "n8n update:workflow"]
    assert "--id=concho --active=true" in n8n_calls[-1]
    assert any("restart n8n" in c for c in calls)
    # the credentials arrived through stdin with the secrets, in a file readable by the owner only
    imported = [json.loads(p.read_text()) for p in
                sorted(tmp_path.glob("imported-*"), key=lambda p: int(p.name.split("-")[1]))]
    creds, error_handler, concho = imported
    assert {c["id"] for c in creds} == {"concho-openai", "concho-discord",
                                        "concho-webhook-auth", "concho-postgres"}
    assert next(c for c in creds if c["id"] == "concho-openai")["data"]["apiKey"] == "sk-for-tests"
    assert "input-exists -rw-------" in calls
    # the workflows are the rendered ones (webhook path set, prompts filled in)
    assert error_handler["id"] == "concho-error-handler"
    assert concho["id"] == "concho"
    assert "a" * 30 in json.dumps(concho) and "@@PROMPT" not in json.dumps(concho)
    # nothing secret on any command line
    assert not any(s in " ".join(calls) for s in ("sk-for-tests", "pw-for-tests"))


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_import_script_fails_without_an_env_file(tmp_path):
    proc = subprocess.run(["bash", str(IMPORT_SH), "--env-file", str(tmp_path / "missing.env")],
                          capture_output=True, text=True)
    assert proc.returncode == 1 and "agent/.env.example" in proc.stderr
