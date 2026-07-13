#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
REPORTS_DIR="${PROJECT_ROOT}/reports"
mkdir -p "${REPORTS_DIR}"

: "${HRAGENT_BASE_URL:=http://localhost:8111}"
: "${HRAGENT_USERS:=1}"
: "${HRAGENT_SPAWN_RATE:=1}"
: "${HRAGENT_RUN_TIME:=10s}"
: "${HRAGENT_FLOW_MODE:=basic}"
: "${HRAGENT_REPORT_PREFIX:=${REPORTS_DIR}/hragent_smoke_1u}"

export HRAGENT_FLOW_MODE

locust -f "${SCRIPT_DIR}/hragent_locustfile.py"   -H "${HRAGENT_BASE_URL}"   --headless   -u "${HRAGENT_USERS}"   -r "${HRAGENT_SPAWN_RATE}"   -t "${HRAGENT_RUN_TIME}"   --stop-timeout 30   --html "${HRAGENT_REPORT_PREFIX}.html"   --csv "${HRAGENT_REPORT_PREFIX}"   --csv-full-history   --json-file "${HRAGENT_REPORT_PREFIX}.json"

python "${SCRIPT_DIR}/generate_locust_report.py"   --prefix "${HRAGENT_REPORT_PREFIX}"   --json "${HRAGENT_REPORT_PREFIX}.json"   --html "${HRAGENT_REPORT_PREFIX}.html"   --output "${REPORTS_DIR}/hragent_load_test_report.md"

echo "HTML report: ${HRAGENT_REPORT_PREFIX}.html"
echo "Markdown report: ${REPORTS_DIR}/hragent_load_test_report.md"
