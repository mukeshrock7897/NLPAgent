#!/usr/bin/env bash
set -euo pipefail

HOST="${NLPAGENT_MCP_HOST:-127.0.0.1}"
PORT="${NLPAGENT_MCP_PORT:-8000}"

# Prevent 'address already in use' on mac
PID="$(lsof -ti tcp:${PORT} || true)"
if [ -n "${PID}" ]; then
  echo "Port ${PORT} already in use by PID ${PID}. Stop it first (or kill)."
  echo "Tip: kill -9 ${PID}"
  exit 1
fi

echo "Starting NLPAGENT MCP server on http://${HOST}:${PORT}/mcp"
python server/server.py
