#!/usr/bin/env bash
# Import the Concho workflows into the n8n of the compose bundle (roadmap P6.6).
#
#   scripts/import_workflows.sh --config path/to/team-repo/project_config.json
#   scripts/import_workflows.sh --dry-run          # show the steps, change nothing
#
# Steps
#   1. read agent/.env (override with --env-file)
#   2. render prompts + webhook path into agent/build (scripts/render_agent.py)
#   3. start Postgres, the data API and n8n (docker compose up -d --wait)
#   4. create the credentials in n8n from the env (scripts/n8n_credentials.py):
#        concho-openai, concho-discord, concho-webhook-auth (+ concho-postgres for the memory)
#   5. n8n import:workflow for the error workflow and the Concho workflow, activate, restart n8n
#
# Touches only the n8n of this compose project. It never talks to another n8n and never reads
# or changes a live workflow. Credential JSON goes through a pipe into the container, never to
# a file. Needs docker compose and python3.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT/agent/docker-compose.yml"
ENV_FILE="$ROOT/agent/.env"
BUILD_DIR="$ROOT/agent/build"
CONFIG=""
DRY_RUN=0
ACTIVATE=1

usage() { sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    --config) CONFIG="${2:?--config needs a file}"; shift 2 ;;
    --env-file) ENV_FILE="${2:?--env-file needs a file}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --no-activate) ACTIVATE=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

run() {  # print the command; run it unless --dry-run
  echo "+ $*"
  if [ "$DRY_RUN" -eq 0 ]; then "$@"; fi
}

[ -f "$ENV_FILE" ] || { echo "error: $ENV_FILE not found: cp agent/.env.example agent/.env and fill it in" >&2; exit 1; }
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

missing=()
for v in CONCHO_WEBHOOK_PATH CONCHO_WEBHOOK_TOKEN CONCHO_API_TOKEN CONCHO_TEAM_REPO \
         OPENAI_API_KEY POSTGRES_PASSWORD N8N_ENCRYPTION_KEY; do
  [ -n "${!v:-}" ] || missing+=("$v")
done
if [ "${#missing[@]}" -gt 0 ]; then
  echo "error: empty in $ENV_FILE: ${missing[*]}" >&2
  exit 1
fi

COMPOSE=(docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE")
RENDER=(python3 "$ROOT/scripts/render_agent.py" --out "$BUILD_DIR")
[ -z "$CONFIG" ] || RENDER+=(--config "$CONFIG")

echo "== 1/4 render prompts and webhook path -> $BUILD_DIR"
run "${RENDER[@]}"

echo "== 2/4 start postgres, data-api and n8n"
run "${COMPOSE[@]}" up -d --build --wait postgres data-api n8n

echo "== 3/4 credentials (from the env; values not printed)"
python3 "$ROOT/scripts/n8n_credentials.py" --list
if [ "$DRY_RUN" -eq 0 ]; then
  python3 "$ROOT/scripts/n8n_credentials.py" \
    | "${COMPOSE[@]}" exec -T n8n sh -c 'cat > /tmp/concho-credentials.json && n8n import:credentials --input=/tmp/concho-credentials.json; rc=$?; rm -f /tmp/concho-credentials.json; exit $rc'
else
  echo "+ (python3 scripts/n8n_credentials.py | docker compose exec -T n8n ... n8n import:credentials)"
fi

echo "== 4/4 workflows"
run "${COMPOSE[@]}" exec -T n8n n8n import:workflow --input=/import/error-handler.json
run "${COMPOSE[@]}" exec -T n8n n8n import:workflow --input=/import/concho.json
if [ "$ACTIVATE" -eq 1 ]; then
  # activates every workflow of this (private) n8n; takes effect after the restart
  if ! run "${COMPOSE[@]}" exec -T n8n n8n update:workflow --all --active=true; then
    echo "warning: could not activate from the CLI: open n8n and activate 'Concho' in the UI" >&2
  fi
  run "${COMPOSE[@]}" restart n8n
fi

cat <<MSG

Done. n8n: http://127.0.0.1:5678 (first start asks for an owner account).
Webhook (from this machine): http://127.0.0.1:5678/webhook/<CONCHO_WEBHOOK_PATH>
Discord bot: docker compose -f agent/docker-compose.yml --env-file agent/.env --profile discord up -d
Smoke test and eval: docs/agent.md ("Run it locally").
MSG
