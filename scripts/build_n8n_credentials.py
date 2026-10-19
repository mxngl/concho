"""Build the n8n credentials file for ``n8n import:credentials`` from the environment (P6.6).

The workflows refer to credentials by fixed id (``agent/workflows/*.json`` never hold secrets):

=====================  ===============  ====================================  ==================
id                     n8n type         built from                            used by
=====================  ===============  ====================================  ==================
``concho-openai``      openAiApi        ``OPENAI_API_KEY``                    the chat models
``concho-discord``     discordBotApi    ``DISCORD_BOT_TOKEN``                 reply, error post
``concho-webhook-auth`` httpHeaderAuth  header ``X-Concho-Token`` =           the webhook
                                        ``CONCHO_WEBHOOK_TOKEN``
``concho-postgres``    postgres         ``POSTGRES_*`` (host ``postgres``)    chat memory (P6.4)
=====================  ===============  ====================================  ==================

The first three are the ones P6.6 asks for; the fourth is needed by the memory nodes. The
Postgres credential is skipped (with a note) when ``POSTGRES_PASSWORD`` is not set, e.g. on the
``npx n8n`` route without a database: the memory nodes then fail softly and Concho answers
without chat history.

The output holds secrets in plain text (n8n encrypts them with its own key on import): the
script writes it with mode 600, ``scripts/import_workflows.sh`` puts it in a temporary folder
and deletes it afterwards. Never commit or paste it.

    python scripts/build_n8n_credentials.py --out FILE
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

HEADER_NAME = "X-Concho-Token"
REQUIRED = {  # credential id -> (env variable, what it is)
    "concho-openai": ("OPENAI_API_KEY", "OpenAI API key"),
    "concho-discord": ("DISCORD_BOT_TOKEN", "Discord bot token"),
    "concho-webhook-auth": ("CONCHO_WEBHOOK_TOKEN", "webhook token"),
}


class CredentialError(Exception):
    """A variable the operator has to set."""


def _value(env: Mapping[str, str], name: str) -> str:
    return (env.get(name) or "").strip()


def build_credentials(
    env: Mapping[str, str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """``(credentials, notes)``; raises :class:`CredentialError` listing every missing variable."""
    env = os.environ if env is None else env
    missing = [f"{var} ({what})" for var, what in REQUIRED.values() if not _value(env, var)]
    if missing:
        raise CredentialError("missing in the environment (.env): " + "; ".join(missing))
    credentials: list[dict[str, Any]] = [
        {"id": "concho-openai", "name": "Concho OpenAI", "type": "openAiApi",
         "data": {"apiKey": _value(env, "OPENAI_API_KEY")}},
        {"id": "concho-discord", "name": "Concho Discord bot", "type": "discordBotApi",
         "data": {"botToken": _value(env, "DISCORD_BOT_TOKEN")}},
        {"id": "concho-webhook-auth", "name": "Concho webhook token", "type": "httpHeaderAuth",
         "data": {"name": HEADER_NAME, "value": _value(env, "CONCHO_WEBHOOK_TOKEN")}},
    ]
    notes: list[str] = []
    if _value(env, "POSTGRES_PASSWORD"):
        credentials.append({
            "id": "concho-postgres", "name": "Concho Postgres", "type": "postgres",
            "data": {"host": _value(env, "POSTGRES_HOST") or "postgres",
                     "port": int(_value(env, "POSTGRES_PORT") or 5432),
                     "database": _value(env, "POSTGRES_DB") or "concho",
                     "user": _value(env, "POSTGRES_USER") or "concho",
                     "password": _value(env, "POSTGRES_PASSWORD"),
                     "maxConnections": 10, "allowUnauthorizedCerts": False,
                     "ssl": "disable", "sshTunnel": False}})
    else:
        notes.append("POSTGRES_PASSWORD not set: credential concho-postgres skipped "
                     "(no chat memory)")
    return credentials, notes


def write_credentials(path: Path, credentials: list[dict[str, Any]]) -> None:
    """Write ``credentials`` readable by the owner only."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(credentials, handle, indent=2)
        handle.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True, metavar="FILE",
                        help="credentials file for 'n8n import:credentials' (mode 600)")
    args = parser.parse_args(argv)
    try:
        credentials, notes = build_credentials()
    except CredentialError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    write_credentials(args.out, credentials)
    for note in notes:
        print(f"note: {note}", file=sys.stderr)
    print("credentials: " + ", ".join(c["id"] for c in credentials), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
