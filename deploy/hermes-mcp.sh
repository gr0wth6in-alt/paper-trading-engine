#!/usr/bin/env bash
# Launch the paper-trading MCP server for Hermes over stdio.
# Reads PAPER_AGENT_TOKEN (and optional PAPER_ENGINE_URL) from a root-owned env file that
# the Hermes user can read (mode 0640, group = Hermes user's group). stdout is reserved for
# the MCP protocol, so this script prints nothing on success.
set -euo pipefail

ENV_FILE="${PAPER_AGENT_ENV_FILE:-/etc/paper-engine/agent.env}"
APP_DIR="${PAPER_APP_DIR:-/opt/paper-trading-engine}"

if [[ ! -r "$ENV_FILE" ]]; then
  echo "hermes-mcp: cannot read $ENV_FILE (see DEPLOYMENT.md section 11)" >&2
  exit 1
fi
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a
export PAPER_ENGINE_URL="${PAPER_ENGINE_URL:-http://127.0.0.1:8000}"
cd "$APP_DIR"
exec "$APP_DIR/.venv/bin/python" -m paper_engine.mcp_server "$@"
