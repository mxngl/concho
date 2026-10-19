"""Build the n8n credentials of the Concho workflows from the environment (roadmap P6.6).

The workflows refer to credentials by fixed id (``concho-openai``, ``concho-discord``,
``concho-webhook-auth``, ``concho-postgres``). Credentials are never part of a workflow export,
so ``scripts/import_workflows.sh`` creates them with ``n8n import:credentials``. The ids and
names come from the workflow files themselves (so they cannot drift), the secrets from the env:

    OPENAI_API_KEY               -> openAiApi       (concho-openai)
    DISCORD_BOT_TOKEN            -> discordBotApi   (concho-discord)
    CONCHO_WEBHOOK_TOKEN         -> httpHeaderAuth  (concho-webhook-auth, header X-Concho-Token)
    POSTGRES_USER/_PASSWORD/_DB  -> postgres        (concho-postgres, host ``postgres``)

    python scripts/n8n_credentials.py          # JSON array for ``n8n import:credentials`` (stdout)
    python scripts/n8n_credentials.py --list   # ids and names only, no secrets

The JSON contains secrets: the import script pipes it straight into the container and never
writes it to a file. Values are read from the process environment (the import script sources
``agent/.env`` first).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = REPO_ROOT / "agent" / "workflows"
WORKFLOW_FILES = ("concho.json", "error-handler.json")
WEBHOOK_HEADER = "X-Concho-Token"
DISCORD_PLACEHOLDER = "not-set"  # keeps the import working for an eval-only n8n


class CredentialError(Exception):
    pass


def referenced_credentials(workflows_dir: Path = WORKFLOWS_DIR) -> dict[str, dict[str, str]]:
    """``{id: {"id", "name", "type"}}`` of every credential the workflow files use."""
    found: dict[str, dict[str, str]] = {}
    for fname in WORKFLOW_FILES:
        wf = json.loads((workflows_dir / fname).read_text(encoding="utf-8"))
        for node in wf["nodes"]:
            for ctype, ref in node.get("credentials", {}).items():
                prev = found.setdefault(ref["id"], {"id": ref["id"], "name": ref["name"],
                                                    "type": ctype})
                if (prev["name"], prev["type"]) != (ref["name"], ctype):
                    raise CredentialError(f"credential {ref['id']} is used with different "
                                          f"names/types ({prev['name']}/{prev['type']} vs "
                                          f"{ref['name']}/{ctype})")
    return found


def _need(env: Mapping[str, str], *names: str) -> list[str]:
    return [env.get(n, "").strip() for n in names]


def credential_data(ctype: str, env: Mapping[str, str]) -> dict[str, Any]:
    if ctype == "openAiApi":
        (key,) = _need(env, "OPENAI_API_KEY")
        if not key:
            raise CredentialError("OPENAI_API_KEY is empty")
        return {"apiKey": key, "organizationId": "", "url": "https://api.openai.com/v1"}
    if ctype == "discordBotApi":
        (token,) = _need(env, "DISCORD_BOT_TOKEN")
        return {"botToken": token or DISCORD_PLACEHOLDER}
    if ctype == "httpHeaderAuth":
        (token,) = _need(env, "CONCHO_WEBHOOK_TOKEN")
        if not token:
            raise CredentialError("CONCHO_WEBHOOK_TOKEN is empty")
        return {"name": WEBHOOK_HEADER, "value": token}
    if ctype == "postgres":
        user, password, db = _need(env, "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")
        if not password:
            raise CredentialError("POSTGRES_PASSWORD is empty")
        return {"host": "postgres", "port": 5432, "database": db or "concho",
                "user": user or "concho", "password": password, "ssl": "disable",
                "maxConnections": 100, "allowUnauthorizedCerts": False, "sshTunnel": False}
    raise CredentialError(f"no env mapping for credential type {ctype!r}: add it here")


def build(env: Mapping[str, str] | None = None,
          workflows_dir: Path = WORKFLOWS_DIR) -> list[dict[str, Any]]:
    env = os.environ if env is None else env
    out = []
    for ref in sorted(referenced_credentials(workflows_dir).values(), key=lambda r: r["id"]):
        out.append({"id": ref["id"], "name": ref["name"], "type": ref["type"],
                    "data": credential_data(ref["type"], env)})
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--list", action="store_true", help="print ids, names and types only")
    args = parser.parse_args(argv)
    try:
        if args.list:
            for ref in sorted(referenced_credentials().values(), key=lambda r: r["id"]):
                print(f"{ref['id']}  {ref['type']}  {ref['name']}")
            return 0
        json.dump(build(), sys.stdout)
        sys.stdout.write("\n")
    except CredentialError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not os.environ.get("DISCORD_BOT_TOKEN", "").strip():
        print(f"warning: DISCORD_BOT_TOKEN is empty; the Discord credential gets the "
              f"placeholder {DISCORD_PLACEHOLDER!r} (Discord replies will fail)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
