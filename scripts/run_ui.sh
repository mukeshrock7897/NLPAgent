#!/usr/bin/env bash
set -euo pipefail

PORT="${NLPAGENT_WEB_PORT:-8502}"
HOST="${NLPAGENT_WEB_HOST:-127.0.0.1}"

echo "Starting NLPAGENT Web on http://${HOST}:${PORT}"
uvicorn web.app:app --host "${HOST}" --port "${PORT}" --reload
