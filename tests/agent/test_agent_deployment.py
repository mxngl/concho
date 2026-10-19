"""P6.6: the deployment bundle, checked statically (no Docker daemon, n8n or Discord here).

``docker compose config`` runs when the docker CLI is available; the import script runs against
a stub ``docker`` so its order of steps and its handling of secrets are tested.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys

import agent_helpers as h
import pytest
import yaml

SCRIPTS = h.REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import build_n8n_credentials as creds  # noqa: E402

COMPOSE = h.AGENT / "docker-compose.yml"
IMPORT = SCRIPTS / "import_workflows.sh"
BASH = shutil.which("bash")
DUMMY_ENV = {
    "POSTGRES_PASSWORD": "pg-secret-value", "CONCHO_API_TOKEN": "api-secret-value",
    "CONCHO_DATA_REPO": "/tmp", "N8N_ENCRYPTION_KEY": "enc-secret-value",
    "DISCORD_BOT_TOKEN": "discord-secret-value", "CONCHO_WEBHOOK_PATH": "w" * 30,
    "CONCHO_WEBHOOK_TOKEN": "hook-secret-value", "OPENAI_API_KEY": "openai-secret-value",
}


@pytest.fixture(scope="module")
def compose():
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ compose file


def test_the_four_services_exist(compose):
    assert set(compose["services"]) == {"postgres", "data-api", "n8n", "bot"}
    assert set(compose["volumes"]) == {"pgdata", "apidata", "n8n_data"}


def test_nothing_but_the_n8n_editor_is_published_and_only_on_loopback(compose):
    services = compose["services"]
    for name in ("postgres", "data-api", "bot"):
        assert "ports" not in services[name], f"{name} must not publish a port"
    assert services["data-api"]["expose"] == ["8000"]
    (port,) = services["n8n"]["ports"]
    assert port.startswith("127.0.0.1:")
    text = COMPOSE.read_text(encoding="utf-8")
    assert not re.search(r"^\s*-\s*\"?0\.0\.0\.0:", text, re.MULTILINE)


def test_compose_holds_no_secret_values(compose):
    text = COMPOSE.read_text(encoding="utf-8")
    for line in text.splitlines():
        if re.search(r"(PASSWORD|TOKEN|KEY|SECRET)\s*:", line) \
                and not line.lstrip().startswith("#"):
            value = line.split(":", 1)[1].strip()
            assert value.startswith("${"), f"secret not taken from the env: {line.strip()}"
    from check_forbidden import check_text  # noqa: PLC0415
    assert not check_text(text, "agent/docker-compose.yml")


def test_required_secrets_fail_loudly_when_unset(compose):
    text = COMPOSE.read_text(encoding="utf-8")
    for var in ("POSTGRES_PASSWORD", "CONCHO_API_TOKEN", "N8N_ENCRYPTION_KEY", "DISCORD_BOT_TOKEN",
                "CONCHO_WEBHOOK_PATH", "CONCHO_WEBHOOK_TOKEN", "CONCHO_DATA_REPO"):
        assert f"${{{var}:?" in text, f"{var} must be required"


def test_every_variable_compose_reads_is_in_env_example(compose):
    text = COMPOSE.read_text(encoding="utf-8")
    used = set(re.findall(r"\$\{([A-Z][A-Z0-9_]*)", text))
    assert used and used <= h.env_vars_in_example(), sorted(used - h.env_vars_in_example())


def test_n8n_gets_the_settings_the_workflows_read(compose):
    env = compose["services"]["n8n"]["environment"]
    assert env["N8N_BLOCK_ENV_ACCESS_IN_NODE"] == "false"
    assert env["CONCHO_API_URL"] == "http://data-api:8000"
    assert env["DB_TYPE"] == "postgresdb" and env["DB_POSTGRESDB_HOST"] == "postgres"
    wf_vars = set()
    for name in ("concho.json", "error-handler.json"):
        for s in h.strings(h.load(name)):
            wf_vars.update(re.findall(r"\$env\.([A-Z][A-Z0-9_]*)", s))
    assert wf_vars <= set(env), f"workflow reads variables n8n does not get: {wf_vars - set(env)}"
    assert re.fullmatch(r"n8nio/n8n:\$\{N8N_VERSION:-\d+\.\d+\.\d+\}",
                        compose["services"]["n8n"]["image"])
    assert "2.43.8" in (h.AGENT / ".env.example").read_text(encoding="utf-8")


def test_data_api_reads_the_team_repo_read_only_and_keeps_its_db_in_a_volume(compose):
    volumes = compose["services"]["data-api"]["volumes"]
    assert any(v.endswith(":/data:ro") and "CONCHO_DATA_REPO" in v for v in volumes)
    assert "apidata:/db" in volumes
    dockerfile = (h.AGENT / "Dockerfile.api").read_text(encoding="utf-8")
    assert "concho-api" in dockerfile and "--db" in dockerfile and "/db/concho.db" in dockerfile
    assert "USER concho" in dockerfile and "HEALTHCHECK" in dockerfile
    assert compose["services"]["n8n"]["depends_on"]["data-api"]["condition"] == "service_healthy"


def test_postgres_is_a_version_n8n_supports(compose):
    """n8n 2.43.8 warns that Postgres 16 is outside its supported range; memory.sql was
    re-checked on 17. An existing version-16 pgdata volume does not start on 17: the docs say
    to remove it."""
    assert compose["services"]["postgres"]["image"] == "postgres:17-alpine"
    deployment = (h.REPO_ROOT / "docs" / "agent-deployment.md").read_text(encoding="utf-8")
    assert "postgres:17-alpine" in deployment and "docker compose" in deployment
    assert "down -v" in deployment


def test_postgres_creates_the_memory_table_on_first_start(compose):
    volumes = compose["services"]["postgres"]["volumes"]
    assert "./memory.sql:/docker-entrypoint-initdb.d/10-memory.sql:ro" in volumes
    assert (h.AGENT / "memory.sql").is_file()


def test_the_bot_only_talks_to_the_webhook(compose):
    env = compose["services"]["bot"]["environment"]
    assert env["CONCHO_WEBHOOK_URL"].startswith("http://n8n:5678/webhook/${CONCHO_WEBHOOK_PATH")
    # the short URL, no workflow id and no node name in it (needs webhookId in concho.json)
    assert re.fullmatch(r"http://n8n:5678/webhook/\$\{CONCHO_WEBHOOK_PATH[^}]*\}",
                        env["CONCHO_WEBHOOK_URL"])
    assert set(env) == {"DISCORD_BOT_TOKEN", "DISCORD_GUILD_ID", "DISCORD_CHANNEL_ID_ASK",
                        "CONCHO_WEBHOOK_URL", "CONCHO_WEBHOOK_TOKEN"}
    assert "USER concho" in (h.AGENT / "bot" / "Dockerfile").read_text(encoding="utf-8")


def test_dockerignore_keeps_secrets_and_data_out_of_the_build_context():
    lines = (h.REPO_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    for entry in (".env", ".fixtures", "**/*.xlsx", ".git"):
        assert entry in lines


@pytest.mark.skipif(not shutil.which("docker"), reason="docker CLI not installed")
def test_docker_compose_config_validates(tmp_path):
    env_file = tmp_path / "test.env"
    env_file.write_text("".join(f"{k}={v}\n" for k, v in DUMMY_ENV.items()), encoding="utf-8")
    proc = subprocess.run(
        ["docker", "compose", "--env-file", str(env_file), "-f", str(COMPOSE), "config"],
        capture_output=True, text=True)
    if proc.returncode != 0 and "docker" in proc.stderr.lower() and "daemon" in proc.stderr.lower():
        pytest.skip("docker compose is not usable here")
    assert proc.returncode == 0, proc.stderr
    assert "http://n8n:5678/webhook/" + DUMMY_ENV["CONCHO_WEBHOOK_PATH"] in proc.stdout
    missing = subprocess.run(["docker", "compose", "--env-file", os.devnull, "-f", str(COMPOSE),
                              "config"], capture_output=True, text=True)
    assert missing.returncode != 0 and "POSTGRES_PASSWORD" in missing.stderr


# ------------------------------------------------------------------ credentials


def test_credentials_cover_every_credential_the_workflows_refer_to():
    built, _ = creds.build_credentials(DUMMY_ENV)
    by_id = {c["id"]: c for c in built}
    referenced = {}
    for name in ("concho.json", "error-handler.json"):
        for node in h.load(name)["nodes"]:
            for kind, ref in node.get("credentials", {}).items():
                referenced[ref["id"]] = (kind, ref["name"])
    assert set(referenced) == set(by_id) == {"concho-openai", "concho-discord",
                                             "concho-webhook-auth", "concho-postgres"}
    for cred_id, (kind, cred_name) in referenced.items():
        assert by_id[cred_id]["type"] == kind and by_id[cred_id]["name"] == cred_name


def test_credential_values_come_from_the_env():
    built, notes = creds.build_credentials(DUMMY_ENV)
    by_id = {c["id"]: c["data"] for c in built}
    assert by_id["concho-openai"] == {"apiKey": "openai-secret-value"}
    assert by_id["concho-discord"] == {"botToken": "discord-secret-value"}
    assert by_id["concho-webhook-auth"] == {"name": "X-Concho-Token", "value": "hook-secret-value"}
    assert by_id["concho-postgres"]["host"] == "postgres"
    assert by_id["concho-postgres"]["password"] == "pg-secret-value" and notes == []
    assert by_id["concho-postgres"]["database"] == "concho"


def test_missing_variables_are_all_listed_and_postgres_is_optional():
    with pytest.raises(creds.CredentialError) as err:
        creds.build_credentials({"OPENAI_API_KEY": "x"})
    assert "DISCORD_BOT_TOKEN" in str(err.value) and "CONCHO_WEBHOOK_TOKEN" in str(err.value)
    env = {k: v for k, v in DUMMY_ENV.items() if k != "POSTGRES_PASSWORD"}
    built, notes = creds.build_credentials(env)
    assert [c["id"] for c in built] == ["concho-openai", "concho-discord", "concho-webhook-auth"]
    assert "skipped" in notes[0]


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_the_credentials_file_is_private_and_the_cli_reports_errors(tmp_path, monkeypatch, capsys):
    for key, value in DUMMY_ENV.items():
        monkeypatch.setenv(key, value)
    out = tmp_path / "credentials.json"
    assert creds.main(["--out", str(out)]) == 0
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    assert len(json.loads(out.read_text(encoding="utf-8"))) == 4
    assert "openai-secret-value" not in capsys.readouterr().err
    monkeypatch.delenv("OPENAI_API_KEY")
    assert creds.main(["--out", str(tmp_path / "x.json")]) == 1
    assert "OPENAI_API_KEY" in capsys.readouterr().err


# ------------------------------------------------------------------ import script


STUB = """#!/usr/bin/env bash
# stub docker: log the arguments and keep what was streamed into the container
echo "$*" >> "$STUB_LOG"
case "$*" in
  *"sh -c"*) n=$(ls "$STUB_DIR" | wc -l); cat > "$STUB_DIR/stdin-$n.json" ;;
esac
exit 0
"""


@pytest.mark.skipif(BASH is None or os.name == "nt", reason="needs bash and a POSIX shell")
def test_import_script_syntax():
    assert subprocess.run([BASH, "-n", str(IMPORT)]).returncode == 0
    assert os.access(IMPORT, os.X_OK)


@pytest.mark.skipif(BASH is None or os.name == "nt", reason="needs bash and a POSIX shell")
def test_import_script_order_and_secret_handling(tmp_path):
    bin_dir, captured = tmp_path / "bin", tmp_path / "captured"
    bin_dir.mkdir()
    captured.mkdir()
    stub = bin_dir / "docker"
    stub.write_text(STUB, encoding="utf-8")
    stub.chmod(0o755)
    log = tmp_path / "log.txt"
    env_file = tmp_path / "test.env"
    config = h.REPO_ROOT / "template" / "project_config.json"
    env_file.write_text("".join(f"{k}={v}\n" for k, v in DUMMY_ENV.items())
                        + f"CONCHO_PROJECT_CONFIG={config}\n", encoding="utf-8")
    env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "STUB_LOG": str(log),
           "STUB_DIR": str(captured), "ENV_FILE": str(env_file),
           "BUILD_DIR": str(tmp_path / "build"), "PYTHON": sys.executable,
           "HOME": str(tmp_path), "TMPDIR": str(tmp_path)}
    proc = subprocess.run([BASH, str(IMPORT)], cwd=h.REPO_ROOT, env=env, capture_output=True,
                          text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    calls = log.read_text(encoding="utf-8").splitlines()
    joined = "\n".join(calls)
    # order: credentials, error workflow, Concho workflow, publish, restart
    steps = ["import:credentials", "import:workflow --input=/tmp/concho-import.json",
             "publish:workflow --id=concho-main", "restart n8n"]
    positions = [joined.index(s) for s in steps]
    assert positions == sorted(positions)
    assert joined.count("import:workflow") == 2 and "update:workflow" not in joined
    # secrets are streamed on stdin, never on the command line or left in the temp folder
    for secret in DUMMY_ENV.values():
        if "secret" in secret:
            assert secret not in joined
    streamed = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(captured.glob("stdin-*"))]
    assert [len(streamed[0]), streamed[1]["id"], streamed[2]["id"]] == [
        4, "concho-error-handler", "concho-main"]
    assert {c["id"] for c in streamed[0]} >= {"concho-openai", "concho-discord",
                                              "concho-webhook-auth"}
    leftovers = [p for p in tmp_path.glob("tmp.*")]
    assert leftovers == [], "temporary folder with credentials must be deleted"
    rendered = (tmp_path / "build" / "concho.json").read_text(encoding="utf-8")
    assert "@@PROMPT" not in rendered and "REPLACE_WITH_RANDOM_WEBHOOK_PATH" not in rendered
    assert DUMMY_ENV["CONCHO_WEBHOOK_PATH"] in rendered


@pytest.mark.skipif(BASH is None or os.name == "nt", reason="needs bash and a POSIX shell")
def test_import_script_stops_when_a_secret_is_missing(tmp_path):
    env_file = tmp_path / "test.env"
    env_file.write_text("CONCHO_WEBHOOK_PATH=" + "w" * 30 + "\n", encoding="utf-8")
    env = {"PATH": os.environ["PATH"], "ENV_FILE": str(env_file), "BUILD_DIR": str(tmp_path / "b"),
           "PYTHON": sys.executable, "HOME": str(tmp_path), "TMPDIR": str(tmp_path),
           "CONCHO_PROJECT_CONFIG": str(h.REPO_ROOT / "template" / "project_config.json")}
    proc = subprocess.run([BASH, str(IMPORT)], cwd=h.REPO_ROOT, env=env, capture_output=True,
                          text=True)
    assert proc.returncode != 0 and "OPENAI_API_KEY" in proc.stderr


def test_the_workflow_ids_are_fixed_so_a_second_import_updates_instead_of_duplicating():
    assert h.load("concho.json")["id"] == "concho-main"
    assert h.load("error-handler.json")["id"] == "concho-error-handler"
    assert h.load("concho.json")["settings"]["errorWorkflow"] == "concho-error-handler"
