#!/usr/bin/env bash
# Import the Concho workflows and create their n8n credentials (roadmap P6.6).
#
#   scripts/import_workflows.sh [--env-file FILE] [--config project_config.json]
#                               [--build-dir DIR] [--no-restart] [--dry-run]
#
# What it does, in this order:
#   1. renders the prompts and the webhook path into the workflows (scripts/render_agent.py)
#      -> agent/build/ (git-ignored);
#   2. creates the four credentials of the workflows from the .env values (n8n import:credentials,
#      scripts/agent_credentials.py): concho-openai, concho-discord, concho-webhook-auth and
#      concho-postgres (chat memory). The secrets travel through stdin into the container and
#      exist there as a file only during the import;
#   3. imports the error workflow (id concho-error-handler) and the Concho workflow (id concho);
#   4. activates "Concho" and restarts n8n (a CLI activation needs a restart to register the
#      webhook).
#
# It only talks to the n8n container of agent/docker-compose.yml (project "concho"), never to
# another n8n instance. Re-running it replaces the same workflow ids and credentials.
# --dry-run renders the workflows and prints the n8n commands and the credentials with the
# secrets masked; it needs neither Docker nor a running stack.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/agent/.env"
BUILD_DIR="$ROOT/agent/build"
CONFIG=""
RESTART=1
DRY_RUN=0
PYTHON="${PYTHON:-python3}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file)   ENV_FILE="$2"; shift 2 ;;
    --config)     CONFIG="$2"; shift 2 ;;
    --build-dir)  BUILD_DIR="$2"; shift 2 ;;
    --no-restart) RESTART=0; shift ;;
    --dry-run)    DRY_RUN=1; shift ;;
    -h|--help)    sed -n '2,22p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1 (see --help)" >&2; exit 2 ;;
  esac
done

if [[ ! -f "$ENV_FILE" ]]; then
  echo "error: $ENV_FILE not found. Copy agent/.env.example to agent/.env and fill it in." >&2
  exit 1
fi

COMPOSE=(docker compose -f "$ROOT/agent/docker-compose.yml" --env-file "$ENV_FILE")
N8N_EXEC=("${COMPOSE[@]}" exec -T n8n)

render_args=(--env-file "$ENV_FILE" --out "$BUILD_DIR")
[[ -n "$CONFIG" ]] && render_args+=(--config "$CONFIG")
echo "==> render prompts and webhook path -> $BUILD_DIR"
"$PYTHON" "$ROOT/scripts/render_agent.py" "${render_args[@]}"

if [[ "$DRY_RUN" == 1 ]]; then
  echo "==> dry run: credentials (secrets masked)"
  "$PYTHON" "$ROOT/scripts/agent_credentials.py" --env-file "$ENV_FILE" --redact
  echo "==> dry run: commands that would run"
  echo "  n8n import:credentials --input=<credentials from stdin>"
  echo "  n8n import:workflow --input=$BUILD_DIR/error-handler.json"
  echo "  n8n import:workflow --input=$BUILD_DIR/concho.json"
  echo "  n8n update:workflow --id=concho --active=true"
  [[ "$RESTART" == 1 ]] && echo "  docker compose restart n8n"
  exit 0
fi

if ! "${N8N_EXEC[@]}" n8n --version >/dev/null 2>&1; then
  echo "error: the n8n container is not running. Start the stack first:" >&2
  echo "  docker compose -f agent/docker-compose.yml --env-file $ENV_FILE up -d --build" >&2
  exit 1
fi

# Copy a file or stdin into the container, run an n8n CLI import, always remove the file.
n8n_import() {  # <import:credentials|import:workflow>  <file or - for stdin>
  local command="$1" source="$2"
  "${N8N_EXEC[@]}" sh -c 'umask 077; cat > /tmp/concho-import.json
    n8n "$0" --input=/tmp/concho-import.json; status=$?; rm -f /tmp/concho-import.json; exit $status' \
    "$command" < "${source/#-//dev/stdin}"
}

echo "==> credentials (concho-openai, concho-discord, concho-webhook-auth, concho-postgres)"
"$PYTHON" "$ROOT/scripts/agent_credentials.py" --env-file "$ENV_FILE" | n8n_import import:credentials -

echo "==> workflows"
n8n_import import:workflow "$BUILD_DIR/error-handler.json"
n8n_import import:workflow "$BUILD_DIR/concho.json"

echo "==> activate Concho"
if ! "${N8N_EXEC[@]}" n8n update:workflow --id=concho --active=true; then
  echo "warning: could not activate from the CLI. Open the editor, open 'Concho' and switch" >&2
  echo "         it to active (n8n versions differ: update:workflow or publish:workflow)." >&2
fi

if [[ "$RESTART" == 1 ]]; then
  echo "==> restart n8n"
  "${COMPOSE[@]}" restart n8n
fi
echo "done. Webhook: POST http://127.0.0.1:\${N8N_PORT:-5678}/webhook/<CONCHO_WEBHOOK_PATH> with header X-Concho-Token"
