#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OBS_COMPOSE="$ROOT_DIR/observability/docker-compose.yml"
OBS_ENV="$ROOT_DIR/observability/.env"
command -v docker >/dev/null 2>&1 || { echo "ERROR: docker is not installed" >&2; exit 1; }
docker compose version >/dev/null
[[ -f "$OBS_ENV" ]] || { echo "ERROR: observability/.env does not exist" >&2; exit 1; }
docker compose -f "$ROOT_DIR/docker-compose.yml" config >/dev/null
docker compose --env-file "$OBS_ENV" -f "$OBS_COMPOSE" config >/dev/null
for container in hragent-alloy hragent-loki hragent-grafana; do
  state="$(docker inspect -f '{{.State.Status}}' "$container" 2>/dev/null || true)"
  [[ "$state" == "running" ]] || { echo "ERROR: $container is not running" >&2; exit 1; }
done
curl -fsS http://127.0.0.1:3000/api/health >/dev/null
docker exec hragent-grafana wget -qO- http://loki:3100/ready >/dev/null
end_ns="$(date +%s%N)"; start_ns="$((end_ns - 300000000000))"
query_result="$(docker exec hragent-grafana wget -qO- "http://loki:3100/loki/api/v1/query_range?query=%7Bcompose_project%3D%22hragent-05%22%7D&start=${start_ns}&end=${end_ns}&limit=20" || true)"
[[ "$query_result" == *'"status":"success"'* ]] || { echo "ERROR: Loki query did not succeed" >&2; exit 1; }
echo "OK: observability stack is healthy"
