# 03：可观测性 Compose

在仓库根目录创建 `observability/`，不得覆盖现有业务 Compose 文件。以下是 `observability/.env.example`：

```dotenv
# Grafana
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=replace_with_a_strong_random_password
GRAFANA_PORT=3000

# 只采集该 Docker Compose 项目的日志
HRAGENT_COMPOSE_PROJECT=hragent-05
HRAGENT_ENVIRONMENT=demo
HRAGENT_HOST=hragent-demo-01

# 固定镜像版本
ALLOY_IMAGE=grafana/alloy:v1.17.0
LOKI_IMAGE=grafana/loki:3.7.3
GRAFANA_IMAGE=grafana/grafana:13.0.0
```

实施时执行 `cp observability/.env.example observability/.env`，再用 `openssl rand -hex 24` 生成并写入 Grafana 密码。`.env` 不提交；确认 `.gitignore` 已覆盖 `.env` 或 `*.env`。任何文件均不得硬编码真实密码。

## `observability/docker-compose.yml`

```yaml
name: hragent-observability

x-default-logging: &default-logging
  driver: json-file
  options:
    max-size: "20m"
    max-file: "3"

services:
  alloy:
    image: ${ALLOY_IMAGE:-grafana/alloy:v1.17.0}
    container_name: hragent-alloy
    command: [run, --server.http.listen-addr=0.0.0.0:12345, --storage.path=/var/lib/alloy/data, /etc/alloy/config.alloy]
    environment:
      HRAGENT_COMPOSE_PROJECT: ${HRAGENT_COMPOSE_PROJECT:-hragent-05}
      HRAGENT_ENVIRONMENT: ${HRAGENT_ENVIRONMENT:-demo}
      HRAGENT_HOST: ${HRAGENT_HOST:-hragent-demo-01}
    volumes:
      - ./alloy/config.alloy:/etc/alloy/config.alloy:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - alloy_data:/var/lib/alloy/data
    depends_on:
      loki:
        condition: service_healthy
    restart: unless-stopped
    cpus: 0.30
    mem_limit: 256m
    mem_reservation: 128m
    pids_limit: 128
    security_opt: [no-new-privileges:true]
    logging: *default-logging
    networks: [observability]

  loki:
    image: ${LOKI_IMAGE:-grafana/loki:3.7.3}
    container_name: hragent-loki
    command: [-config.file=/etc/loki/loki-config.yaml]
    volumes:
      - ./loki/loki-config.yaml:/etc/loki/loki-config.yaml:ro
      - loki_data:/loki
    expose: ["3100"]
    healthcheck:
      test: [CMD-SHELL, wget -qO- http://127.0.0.1:3100/ready >/dev/null 2>&1 || exit 1]
      interval: 10s
      timeout: 5s
      retries: 12
      start_period: 20s
    restart: unless-stopped
    cpus: 1.00
    mem_limit: 1536m
    mem_reservation: 768m
    pids_limit: 256
    security_opt: [no-new-privileges:true]
    logging: *default-logging
    networks: [observability]

  grafana:
    image: ${GRAFANA_IMAGE:-grafana/grafana:13.0.0}
    container_name: hragent-grafana
    environment:
      GF_SECURITY_ADMIN_USER: ${GRAFANA_ADMIN_USER:-admin}
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:?GRAFANA_ADMIN_PASSWORD must be set}
      GF_USERS_ALLOW_SIGN_UP: "false"
      GF_AUTH_ANONYMOUS_ENABLED: "false"
      GF_ANALYTICS_REPORTING_ENABLED: "false"
      GF_ANALYTICS_CHECK_FOR_UPDATES: "false"
      GF_SECURITY_COOKIE_SECURE: "false"
      GF_SECURITY_COOKIE_SAMESITE: strict
      GF_SERVER_ROOT_URL: http://localhost:${GRAFANA_PORT:-3000}
    volumes:
      - grafana_data:/var/lib/grafana
      - ./grafana/provisioning:/etc/grafana/provisioning:ro
      - ./grafana/dashboards:/var/lib/grafana/dashboards:ro
    ports: ["127.0.0.1:${GRAFANA_PORT:-3000}:3000"]
    depends_on:
      loki:
        condition: service_healthy
    healthcheck:
      test: [CMD-SHELL, wget -qO- http://127.0.0.1:3000/api/health >/dev/null 2>&1 || exit 1]
      interval: 10s
      timeout: 5s
      retries: 12
      start_period: 30s
    restart: unless-stopped
    cpus: 0.50
    mem_limit: 512m
    mem_reservation: 256m
    pids_limit: 256
    security_opt: [no-new-privileges:true]
    logging: *default-logging
    networks: [observability]

networks:
  observability:
    name: hragent-observability

volumes:
  alloy_data: {name: hragent_alloy_data}
  loki_data: {name: hragent_loki_data}
  grafana_data: {name: hragent_grafana_data}
```

## 强制约束

- 不给 Loki 或 Alloy 暴露主机端口，不使用 `network_mode: host`、`privileged: true`。
- Grafana 只绑定 `127.0.0.1`；远程访问用 SSH 隧道：`ssh -L 3000:127.0.0.1:3000 <user>@<server>`。
- Docker Socket 只可由 Alloy 以只读方式挂载；它依然是高权限接口，Alloy 镜像和配置必须视为可信代码。
- 基础镜像没有 `wget` 时，健康检查可改为镜像内等价命令，但不可删除健康检查。
