#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export HRAGENT_BASE_URL="${HRAGENT_BASE_URL:-http://localhost:8111}"
export HRAGENT_FLOW_MODE="full"

locust -f "${SCRIPT_DIR}/hragent_locustfile.py" \
  -H "${HRAGENT_BASE_URL}" \
  --web-host "${HRAGENT_WEB_HOST:-0.0.0.0}" \
  --web-port "${HRAGENT_WEB_PORT:-8099}"
