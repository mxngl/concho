"""The n8n credentials the Concho workflows refer to, as JSON for ``n8n import:credentials``
(roadmap P6.6). Values come from the env / ``.env``; nothing is stored in the repo.

    python scripts/agent_credentials.py --env-file agent/.env | n8n import:credentials --input=...

``scripts/import_workflows.sh`` pipes the output into the n8n container (the file exists there
for the duration of the import only). The ids and names are the ones in
``agent/workflows/*.json``; a test compares them.

- `concho-openai` / "Concho OpenAI" (openAiApi): OPENAI_API_KEY
- `concho-discord` / "Concho Discord bot" (discordBotApi): DISCORD_BOT_TOKEN
- `concho-webhook-auth` / "Concho webhook token" (httpHeaderAuth, header X-Concho-Token):
  CONCHO_WEBHOOK_TOKEN
- `concho-postgres` / "Concho Postgres" (postgres): POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB

The fourth credential (Postgres) is needed by the chat-memory nodes of P6.4.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent_env import load_env  # noqa: E402

WEBHOOK_HEADER = "X-Concho-Token"
POSTGRES_HOST = "postgres"  # the compose service name
SECRET_FIELDS = {"apiKey", "botToken", "value", "password"}


class CredentialError(Exception):
    """A required variable is missing."""


def _need(env: Mapping[str, str], *names: str) -> list[str]:
    missing = [n for n in names if not (env.get(n) or "").strip()]
    if missing:
        raise CredentialError("missing in the env / .env: " + ", ".join(missing))
    return [env[n].strip() for n in names]


def build_credentials(env: Mapping[str, str]) -> list[dict]:
    """The four credentials with their secrets filled in (a list for ``import:credentials``)."""
    (openai,) = _need(env, "OPENAI_API_KEY")
    (discord,) = _need(env, "DISCORD_BOT_TOKEN")
    (webhook,) = _need(env, "CONCHO_WEBHOOK_TOKEN")
    user, password = _need(env, "POSTGRES_USER", "POSTGRES_PASSWORD")
    database = (env.get("POSTGRES_DB") or "").strip() or "n8n"
    return [
        {"id": "concho-openai", "name": "Concho OpenAI", "type": "openAiApi",
         "data": {"apiKey": openai}},
        {"id": "concho-discord", "name": "Concho Discord bot", "type": "discordBotApi",
         "data": {"botToken": discord}},
        {"id": "concho-webhook-auth", "name": "Concho webhook token",
         "type": "httpHeaderAuth", "data": {"name": WEBHOOK_HEADER, "value": webhook}},
        {"id": "concho-postgres", "name": "Concho Postgres", "type": "postgres",
         "data": {"host": POSTGRES_HOST, "port": 5432, "database": database, "user": user,
                  "password": password, "ssl": "disable", "maxConnections": 10,
                  "allowUnauthorizedCerts": False, "sshTunnel": False}},
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--env-file", type=Path, metavar="FILE",
                        help="the .env file (the process environment wins)")
    parser.add_argument("--redact", action="store_true",
                        help="print the structure with the secrets replaced (for --dry-run)")
    args = parser.parse_args(argv)
    try:
        creds = build_credentials(load_env(args.env_file))
    except (CredentialError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.redact:
        for c in creds:
            c["data"] = {k: "***" if k in SECRET_FIELDS else v for k, v in c["data"].items()}
    print(json.dumps(creds, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
