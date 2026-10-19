#!/usr/bin/env bash
# Import the Concho workflows and credentials into n8n (roadmap P6.6).
#
#   bash scripts/import_workflows.sh            # n8n runs in the docker compose bundle
#   bash scripts/import_workflows.sh --local    # n8n runs on this machine (npx n8n)
#
# What it does, in order:
#   1. render the prompts and the webhook path into agent/build/   (scripts/render_agent.py)
#   2. create the credentials concho-openai, concho-discord, concho-webhook-auth (and
#      concho-postgres for the chat memory) from the environment  (build_n8n_credentials.py)
#      and `n8n import:credentials` them; the file with the secrets is a temp file (mode 600)
#      that is deleted on exit
#   3. `n8n import:workflow` the error workflow, then the Concho workflow
#   4. publish (activate) the Concho workflow and restart n8n so the webhook is registered
#
# Settings come from ./.env (or $ENV_FILE) and the environment; see agent/.env.example.
# Needs: bash, python 3.11+, and docker compose (default) or n8n via `npx` (--local).
# Never touches an existing workflow with another id: the ids are concho-main and
# concho-error-handler, so running it again updates these two and nothing else.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
MODE=docker
for arg in "$@"; do
  case "$arg" in
    --local) MODE=local ;;
    -h|--help) sed -n '2,19p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

ENV_FILE="${ENV_FILE:-.env}"
COMPOSE_FILE="agent/docker-compose.yml"
BUILD_DIR="${BUILD_DIR:-agent/build}"
N8N_CMD="${N8N_CMD:-npx n8n}"   # --local: how to start the n8n CLI
PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
  for candidate in python3 python py; do
    if command -v "$candidate" >/dev/null 2>&1; then PYTHON="$candidate"; break; fi
  done
fi
[ -n "$PYTHON" ] || { echo "error: python 3.11+ not found (set PYTHON=...)" >&2; exit 1; }

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
else
  echo "note: $ENV_FILE not found, using the environment only (cp agent/.env.example .env)" >&2
fi

compose() { docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
chmod 700 "$TMP"

# n8n_cli <subcommand> <file on this machine> [more args]: runs the n8n CLI on that file.
n8n_cli() {
  local sub="$1" file="$2"; shift 2
  if [ "$MODE" = local ]; then
    # shellcheck disable=SC2086
    $N8N_CMD "$sub" --input="$file" "$@"
  else
    # the file is streamed into the container (no bind mount, no leftover with secrets)
    compose exec -T n8n sh -c \
      "cat > /tmp/concho-import.json && n8n $sub --input=/tmp/concho-import.json $*; rc=\$?; rm -f /tmp/concho-import.json; exit \$rc" \
      < "$file"
  fi
}

n8n_run() {   # n8n_run <args...>: a CLI command without an input file
  if [ "$MODE" = local ]; then
    # shellcheck disable=SC2086
    $N8N_CMD "$@"
  else
    compose exec -T n8n n8n "$@"
  fi
}

echo "== 1/4 render prompts and webhook path -> $BUILD_DIR"
render_args=(--out "$BUILD_DIR")
if [ -n "${CONCHO_PROJECT_CONFIG:-}" ]; then render_args+=(--config "$CONCHO_PROJECT_CONFIG"); fi
"$PYTHON" scripts/render_agent.py "${render_args[@]}"

echo "== 2/4 credentials"
"$PYTHON" scripts/build_n8n_credentials.py --out "$TMP/credentials.json"
n8n_cli import:credentials "$TMP/credentials.json"
rm -f "$TMP/credentials.json"

echo "== 3/4 workflows"
n8n_cli import:workflow "$BUILD_DIR/error-handler.json"
n8n_cli import:workflow "$BUILD_DIR/concho.json"

echo "== 4/4 publish the Concho workflow"
published=0
if n8n_run publish:workflow --id=concho-main; then
  published=1
elif n8n_run update:workflow --id=concho-main --active=true; then
  published=1   # n8n 1.x
fi
if [ "$published" = 1 ]; then
  if [ "$MODE" = docker ]; then
    compose restart n8n
    echo "n8n restarted. Webhook: http://localhost:${N8N_PORT:-5678}/webhook/<CONCHO_WEBHOOK_PATH>"
  else
    echo "Restart your local n8n so the webhook is registered."
  fi
else
  echo "warning: could not activate the workflow from the CLI: open the n8n editor," \
       "check the credentials on the nodes and switch the workflow \"Concho\" to Active." >&2
fi
echo "done."
