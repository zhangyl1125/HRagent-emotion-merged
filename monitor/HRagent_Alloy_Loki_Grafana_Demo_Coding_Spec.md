# HRagent Demo 日志可观测性落地 Coding Spec

> **结论：可行，可以实施。**
>
> 本文档是给 Coding AI 的最终执行说明。请严格按本文档改造当前 HRagent 项目，不扩大技术范围，不修改业务接口和业务逻辑。

---

## 1. 项目现状与可行性判断

已检查当前代码仓库，现有主运行栈为：

- FastAPI 后端；
- React/Vite 构建后的 Nginx 前端；
- PostgreSQL + pgvector；
- Redis；
- Docker Compose 单机部署；
- 当前主 Compose 共 4 个业务容器；
- 后端、Nginx、PostgreSQL、Redis 的运行日志均可通过容器 `stdout/stderr` 获取。

因此，无需先重构业务代码，即可使用以下技术栈完成 Demo 环境的集中日志采集、检索和可视化：

- **Grafana Alloy**：发现 Docker 容器并采集容器日志；
- **Grafana Loki**：单机保存、索引和查询日志；
- **Grafana**：查询日志并展示日志面板。

实施后容器数量为：

- 4 个现有业务容器；
- 3 个可观测性容器；
- 合计 7 个容器。

若将本地 MinerU 服务一并启用，容器数将增加，并显著提高 CPU、内存或 GPU 压力；此时不应继续按本 Demo 资源预算估算。

### 1.1 资源判断

截图中的资源预算可以作为**可观测性栈的增量预算**，不能视为整台主机的总资源预算：

| 组件 | CPU 限额建议 | 内存限额建议 | 主要磁盘用途 |
|---|---:|---:|---|
| Alloy | 0.30 核 | 256 MiB | 读取位置、队列与少量状态 |
| Loki | 1.00 核 | 1.5 GiB | 日志块、索引、压缩与保留 |
| Grafana | 0.50 核 | 512 MiB | Dashboard、SQLite、插件与会话 |
| 合计预留 | 约 2 核 | 约 3 GiB | 建议从 20 GiB 可用空间起步 |

整台 Demo 主机建议至少具备：

- **4 vCPU**；
- **8 GiB RAM**；
- **40 GiB 以上可用磁盘**；
- 其中为 Alloy/Loki/Grafana 单独预留约 2 vCPU、3 GiB RAM、20 GiB 磁盘空间。

若当前主机低于 4 vCPU / 8 GiB，或磁盘剩余空间低于 30 GiB，应先扩容或降低业务与日志负载，再实施。

### 1.2 本方案覆盖范围

本次只实现：

1. Docker 容器日志集中采集；
2. Loki 7 天日志保留；
3. Grafana 日志搜索与基础面板；
4. 通过日志文本实现基础故障观察；
5. Docker 本地日志轮转；
6. 最小化安全暴露和隐私风险。

本次**不实施**：

- Prometheus；
- Tempo；
- Alertmanager；
- OpenTelemetry Collector；
- 全量主机 CPU、内存、磁盘、网络指标；
- 分布式链路追踪；
- 高可用 Loki；
- 对象存储；
- Kubernetes；
- Grafana 公网直接暴露；
- 对业务 API、数据库结构或业务行为的改造。

注意：Alloy + Loki + Grafana 是日志可观测性方案，不等于完整的 Metrics + Logs + Traces 可观测平台。

---

## 2. 最终目标架构

```text
┌───────────────────────────────────────────────────────────────┐
│ HRagent 业务 Compose：project name = hragent-05              │
│                                                               │
│ frontend(Nginx) ─┐                                            │
│ backend(FastAPI) ├─ stdout/stderr → Docker json-file logs      │
│ postgres         ┤                                            │
│ redis            ┘                                            │
└───────────────────────────────┬───────────────────────────────┘
                                │ Docker Socket
                                ▼
┌───────────────────────────────────────────────────────────────┐
│ 独立可观测性 Compose：project name = hragent-observability    │
│                                                               │
│ Alloy ──HTTP Push──▶ Loki ──LogQL Query──▶ Grafana            │
│                       │                    │                    │
│                       ▼                    ▼                    │
│                  loki_data            grafana_data             │
└───────────────────────────────────────────────────────────────┘
```

必须将可观测性栈放在独立 Compose 项目中，原因如下：

- 可以独立启动、停止和升级；
- 停止监控不会影响 HRagent 业务容器；
- 回滚更简单；
- 避免把监控服务与业务服务生命周期强耦合。

---

## 3. 版本和目录约束

### 3.1 固定镜像版本

默认固定为：

```text
grafana/alloy:v1.17.0
grafana/loki:3.7.3
grafana/grafana:13.0.0
```

不得使用 `latest`。

如实际拉取镜像失败，只允许替换为同一大版本内、官方仓库中真实存在的稳定补丁版本，并在交付报告中说明替换原因和实际版本。

### 3.2 新增目录

在仓库根目录新增：

```text
observability/
├── .env.example
├── docker-compose.yml
├── README.md
├── alloy/
│   └── config.alloy
├── loki/
│   └── loki-config.yaml
└── grafana/
    ├── dashboards/
    │   └── hragent-logs.json
    └── provisioning/
        ├── dashboards/
        │   └── dashboards.yml
        └── datasources/
            └── loki.yml

scripts/
└── verify_observability.sh
```

不得覆盖现有业务 Compose 文件；只允许对根目录已有 `docker-compose.yml` 增加日志轮转配置。

---

## 4. 修改现有业务 Compose：强制 Docker 日志轮转

Loki 的 7 天保留不会替代 Docker 自身 `json-file` 日志文件轮转。若不设置轮转，Docker 原生日志仍可能无限增长并占满主机磁盘。

在根目录现有 `docker-compose.yml` 顶层增加：

```yaml
x-default-logging: &default-logging
  driver: json-file
  options:
    max-size: "20m"
    max-file: "3"
```

然后给以下每个现有业务服务增加：

```yaml
logging: *default-logging
```

必须覆盖：

- `postgres`；
- `redis`；
- `backend`；
- `frontend`。

若未来把 MinerU 加入主 Compose，也必须使用同一日志轮转策略。

完成修改后执行：

```bash
docker compose -f docker-compose.yml config
```

命令必须成功，不允许破坏现有 Compose 结构。

---

## 5. 新增 `observability/.env.example`

创建以下内容：

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

实施时复制：

```bash
cp observability/.env.example observability/.env
```

生成随机密码：

```bash
openssl rand -hex 24
```

将输出写入 `GRAFANA_ADMIN_PASSWORD`。

要求：

- `observability/.env` 不得提交到 Git；
- 确认项目 `.gitignore` 已覆盖 `.env` 或 `*.env`；
- 不得在 Compose、README、脚本、Dashboard JSON 中硬编码真实密码。

---

## 6. 新增 `observability/docker-compose.yml`

使用以下内容：

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
    command:
      - run
      - --server.http.listen-addr=0.0.0.0:12345
      - --storage.path=/var/lib/alloy/data
      - /etc/alloy/config.alloy
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
    security_opt:
      - no-new-privileges:true
    logging: *default-logging
    networks:
      - observability

  loki:
    image: ${LOKI_IMAGE:-grafana/loki:3.7.3}
    container_name: hragent-loki
    command:
      - -config.file=/etc/loki/loki-config.yaml
    volumes:
      - ./loki/loki-config.yaml:/etc/loki/loki-config.yaml:ro
      - loki_data:/loki
    expose:
      - "3100"
    healthcheck:
      test:
        - CMD-SHELL
        - wget -qO- http://127.0.0.1:3100/ready >/dev/null 2>&1 || exit 1
      interval: 10s
      timeout: 5s
      retries: 12
      start_period: 20s
    restart: unless-stopped
    cpus: 1.00
    mem_limit: 1536m
    mem_reservation: 768m
    pids_limit: 256
    security_opt:
      - no-new-privileges:true
    logging: *default-logging
    networks:
      - observability

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
    ports:
      - "127.0.0.1:${GRAFANA_PORT:-3000}:3000"
    depends_on:
      loki:
        condition: service_healthy
    healthcheck:
      test:
        - CMD-SHELL
        - wget -qO- http://127.0.0.1:3000/api/health >/dev/null 2>&1 || exit 1
      interval: 10s
      timeout: 5s
      retries: 12
      start_period: 30s
    restart: unless-stopped
    cpus: 0.50
    mem_limit: 512m
    mem_reservation: 256m
    pids_limit: 256
    security_opt:
      - no-new-privileges:true
    logging: *default-logging
    networks:
      - observability

networks:
  observability:
    name: hragent-observability

volumes:
  alloy_data:
    name: hragent_alloy_data
  loki_data:
    name: hragent_loki_data
  grafana_data:
    name: hragent_grafana_data
```

### 6.1 Compose 实现要求

1. 不要给 Loki 暴露主机端口；
2. 不要给 Alloy 暴露主机端口；
3. Grafana 默认只绑定 `127.0.0.1`；
4. 不要加入 `privileged: true`；
5. Docker Socket 只允许 Alloy 挂载；
6. Docker Socket 即使以 `:ro` 挂载，仍属于高权限宿主机接口，必须将 Alloy 镜像和配置视为可信代码；
7. 远程访问 Grafana 应通过 SSH 隧道或公司反向代理，不得直接绑定 `0.0.0.0`；
8. 若基础镜像不包含 `wget`，允许把 healthcheck 改为镜像中已存在的等价命令，但必须保留健康检查；
9. 不要使用 `network_mode: host`。

远程访问示例：

```bash
ssh -L 3000:127.0.0.1:3000 <user>@<server>
```

本机浏览器访问：

```text
http://127.0.0.1:3000
```

---

## 7. 新增 Loki 配置

创建 `observability/loki/loki-config.yaml`：

```yaml
auth_enabled: false

server:
  http_listen_port: 3100
  grpc_listen_port: 9096
  log_level: warn
  grpc_server_max_concurrent_streams: 1000

common:
  instance_addr: 127.0.0.1
  path_prefix: /loki
  storage:
    filesystem:
      chunks_directory: /loki/chunks
      rules_directory: /loki/rules
  replication_factor: 1
  ring:
    kvstore:
      store: inmemory

query_range:
  results_cache:
    cache:
      embedded_cache:
        enabled: true
        max_size_mb: 64

limits_config:
  allow_structured_metadata: true
  volume_enabled: true
  retention_period: 168h
  max_query_lookback: 168h
  reject_old_samples: true
  reject_old_samples_max_age: 168h
  ingestion_rate_mb: 4
  ingestion_burst_size_mb: 8
  max_entries_limit_per_query: 5000
  max_query_parallelism: 4

schema_config:
  configs:
    - from: "2024-01-01"
      store: tsdb
      object_store: filesystem
      schema: v13
      index:
        prefix: index_
        period: 24h

compactor:
  working_directory: /loki/retention
  compaction_interval: 10m
  retention_enabled: true
  retention_delete_delay: 2h
  retention_delete_worker_count: 20
  delete_request_store: filesystem

analytics:
  reporting_enabled: false
```

### 7.1 Loki 配置约束

- 使用 single-binary；
- 使用本地 filesystem 存储；
- 使用 TSDB schema v13；
- 索引周期必须为 24 小时；
- 全局保留周期必须为 168 小时；
- 必须启用 compactor retention；
- 不设置多副本；
- 不引入 MinIO、S3 或其他对象存储；
- 不启用多租户认证；
- Loki 不直接暴露至宿主机或公网。

重要：Loki 的时间保留不会根据“磁盘快满了”自动提前删除数据。因此仍需检查主机磁盘空间，并在实际日志量明显高于预期时缩短保留期或扩容磁盘。

---

## 8. 新增 Alloy 配置

创建 `observability/alloy/config.alloy`：

```alloy
logging {
  level  = "info"
  format = "logfmt"
}

discovery.docker "hragent" {
  host             = "unix:///var/run/docker.sock"
  refresh_interval = "10s"
}

discovery.relabel "hragent" {
  targets = discovery.docker.hragent.targets

  rule {
    source_labels = ["__meta_docker_container_label_com_docker_compose_project"]
    regex         = sys.env("HRAGENT_COMPOSE_PROJECT")
    action        = "keep"
  }

  rule {
    source_labels = ["__meta_docker_container_label_com_docker_compose_project"]
    target_label  = "compose_project"
  }

  rule {
    source_labels = ["__meta_docker_container_label_com_docker_compose_service"]
    target_label  = "service"
  }

  rule {
    source_labels = ["__meta_docker_container_name"]
    regex         = "/(.*)"
    target_label  = "container"
  }

  rule {
    target_label = "environment"
    replacement  = sys.env("HRAGENT_ENVIRONMENT")
  }

  rule {
    target_label = "host"
    replacement  = sys.env("HRAGENT_HOST")
  }
}

loki.source.docker "hragent" {
  host             = "unix:///var/run/docker.sock"
  targets          = discovery.relabel.hragent.output
  refresh_interval = "10s"
  labels           = { source = "docker" }
  forward_to       = [loki.process.hragent.receiver]
}

loki.process "hragent" {
  stage.decolorize {}

  stage.regex {
    expression = "(?i)(?:^|\\|[[:space:]]*)(?P<level>debug|info|warning|warn|error|critical|exception|fatal|log)(?:[[:space:]]*\\||:)"
  }

  stage.labels {
    values = {
      level = "",
    }
  }

  forward_to = [loki.write.local.receiver]
}

loki.write "local" {
  endpoint {
    url = "http://loki:3100/loki/api/v1/push"
  }
}
```

### 8.1 Alloy 标签要求

只保留下列低基数标签：

- `compose_project`；
- `service`；
- `container`；
- `environment`；
- `host`；
- `source`；
- `level`。

不得把以下字段变成 Loki 标签：

- `request_id`；
- `session_id`；
- `user_id`；
- `employee_id`；
- `document_id`；
- `filename`；
- URL；
- 错误消息全文；
- 任意高基数业务字段。

高基数字段必须保留在日志正文或 JSON 字段中，通过内容过滤检索。

### 8.2 Alloy 配置校验

在提交代码前必须运行：

```bash
docker run --rm \
  -e HRAGENT_COMPOSE_PROJECT=hragent-05 \
  -e HRAGENT_ENVIRONMENT=demo \
  -e HRAGENT_HOST=hragent-demo-01 \
  -v "$PWD/observability/alloy/config.alloy:/etc/alloy/config.alloy:ro" \
  grafana/alloy:v1.17.0 \
  validate /etc/alloy/config.alloy
```

并运行格式检查：

```bash
docker run --rm \
  -v "$PWD/observability/alloy/config.alloy:/etc/alloy/config.alloy:ro" \
  grafana/alloy:v1.17.0 \
  fmt --test /etc/alloy/config.alloy
```

如官方镜像 CLI 参数有补丁版本差异，应依据固定镜像的 `alloy help` 调整命令，但不得跳过配置验证。

---

## 9. Grafana 自动配置

### 9.1 Loki 数据源

创建 `observability/grafana/provisioning/datasources/loki.yml`：

```yaml
apiVersion: 1

prune: true

datasources:
  - name: Loki
    uid: loki
    type: loki
    access: proxy
    url: http://loki:3100
    isDefault: true
    editable: false
    jsonData:
      maxLines: 2000
```

### 9.2 Dashboard Provider

创建 `observability/grafana/provisioning/dashboards/dashboards.yml`：

```yaml
apiVersion: 1

providers:
  - name: HRagent
    orgId: 1
    folder: HRagent
    type: file
    disableDeletion: false
    editable: true
    updateIntervalSeconds: 30
    options:
      path: /var/lib/grafana/dashboards
```

### 9.3 Dashboard JSON 要求

创建有效的 Grafana Dashboard JSON：

```text
observability/grafana/dashboards/hragent-logs.json
```

固定元数据：

```text
UID: hragent-demo-logs
Title: HRagent Demo Logs
Default time range: Last 1 hour
Refresh: 10s
Timezone: browser
```

必须包含以下变量：

#### `service`

- 类型：Query；
- 数据源：Loki；
- 查询：

```logql
label_values({compose_project="hragent-05"}, service)
```

- 启用 Include All；
- All value 使用 `.*`。

#### `search`

- 类型：Text box；
- 默认值为空字符串。

必须包含以下面板：

### Panel 1：Log Rate by Service

类型：Time series

```logql
sum by (service) (
  rate({compose_project="hragent-05"}[5m])
)
```

### Panel 2：Errors in Last 5 Minutes

类型：Stat

```logql
sum(
  count_over_time(
    {compose_project="hragent-05"}
    |~ "(?i)(error|exception|critical|traceback|failed)"
    [5m]
  )
)
```

### Panel 3：Error Rate by Service

类型：Time series

```logql
sum by (service) (
  rate(
    {compose_project="hragent-05"}
    |~ "(?i)(error|exception|critical|traceback|failed)"
    [5m]
  )
)
```

### Panel 4：Backend Business Failures

类型：Logs

```logql
{compose_project="hragent-05", service="backend"}
|~ "(?i)(documents\\.text\\.failed|guidance.*failed|rehearsal.*failed|redis.*failed)"
```

### Panel 5：Live Logs

类型：Logs

```logql
{compose_project="hragent-05", service=~"$service"}
|= "$search"
```

面板要求：

- Logs 面板显示时间、标签和日志正文；
- 默认按时间倒序；
- 不依赖第三方 Grafana 插件；
- 不使用需要额外数据源的 Transformation；
- Dashboard 必须能在一个全新 `grafana_data` 卷上自动 provision；
- JSON 必须是合法 JSON，不得只写伪代码。

---

## 10. 后端日志隐私和安全整改

当前日志可以直接采集，因此第一阶段不要求大规模重写日志框架。但 HRagent 涉及员工、文档、面试或人力资源数据，以下整改属于完成条件，而不是可选项。

### 10.1 禁止记录的内容

不得写入任何日志：

- 员工完整姓名、邮箱、手机号、工号；
- 用户对话全文；
- 上传文档正文；
- 简历正文；
- 面试回答全文；
- 提示词全文；
- 模型请求正文和模型响应全文；
- `Authorization`；
- Cookie；
- API Key；
- Client Secret；
- Password；
- 数据库连接密码；
- 原始 Access Token / Refresh Token；
- 请求体和响应体原文。

### 10.2 必须整改的字段

检索现有代码中的日志调用，重点检查：

```text
session_id
filename
document_id
employee_id
email
token
api_key
secret
password
Authorization
Cookie
request body
response body
```

现有日志中若输出原始 `session_id`，应改为不可逆短引用，例如：

```python
from hashlib import sha256


def safe_ref(value: str | None) -> str | None:
    if not value:
        return None
    return sha256(value.encode("utf-8")).hexdigest()[:12]
```

输出：

```python
logger.info("documents.text.start | session_ref=%s", safe_ref(session_id))
```

现有日志中若输出上传文件名，不得输出完整文件名，只允许输出：

- 文件扩展名；
- 文件大小；
- 经过白名单清洗的文档类型。

示例：

```python
from pathlib import Path

suffix = Path(filename or "").suffix.lower()[:10]
logger.info("documents.text.start | extension=%s", suffix)
```

不得把散列后的 `session_ref` 变成 Loki 标签。

### 10.3 异常日志

允许保留异常类型和堆栈，以便排障，但必须：

- 不拼接请求正文；
- 不拼接响应正文；
- 不打印环境变量；
- 不打印第三方接口完整返回；
- 对异常消息中的明显凭证进行脱敏；
- 面向客户端的错误响应继续使用通用错误消息，不能把堆栈返回给前端。

### 10.4 日志标准化：推荐的 P1 改造

在 P0 日志采集打通后，推荐立即实施以下标准化，但不得因此阻塞最小可用版本：

1. 新增 `backend/core/logging_config.py`；
2. 使用 `logging.config.dictConfig` 集中配置日志；
3. 修改 `backend/utils/logger.py`，只返回 `logging.getLogger(name)`，不再为每个 logger 重复添加 handler；
4. 增加 Request ID 中间件；
5. 使用 `ContextVar` 向日志注入 `request_id`；
6. 响应头返回 `X-Request-ID`；
7. 日志输出为单行 JSON；
8. 不记录 query string 和 request body。

建议 JSON 字段：

```text
timestamp
level
logger
message
environment
service
request_id
event
duration_ms
status_code
```

`request_id` 只作为 JSON 字段，不得作为 Loki 标签。

---

## 11. 新增验证脚本

创建 `scripts/verify_observability.sh`，脚本必须：

1. 使用 `set -Eeuo pipefail`；
2. 检查 `docker` 和 `docker compose`；
3. 检查 `observability/.env` 存在；
4. 校验业务 Compose；
5. 校验可观测性 Compose；
6. 检查 Loki `/ready`；
7. 检查 Grafana `/api/health`；
8. 检查三个监控容器均为 running/healthy；
9. 输出 Loki label 查询是否包含 `service`；
10. 查询最近 5 分钟 HRagent 日志数量；
11. 返回非零状态码表示失败；
12. 不在输出中打印 Grafana 密码。

参考实现框架：

```bash
#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OBS_COMPOSE="$ROOT_DIR/observability/docker-compose.yml"
OBS_ENV="$ROOT_DIR/observability/.env"

command -v docker >/dev/null 2>&1 || {
  echo "ERROR: docker is not installed" >&2
  exit 1
}

docker compose version >/dev/null

[[ -f "$OBS_ENV" ]] || {
  echo "ERROR: $OBS_ENV does not exist" >&2
  exit 1
}

docker compose -f "$ROOT_DIR/docker-compose.yml" config >/dev/null
docker compose --env-file "$OBS_ENV" -f "$OBS_COMPOSE" config >/dev/null

for container in hragent-alloy hragent-loki hragent-grafana; do
  state="$(docker inspect -f '{{.State.Status}}' "$container" 2>/dev/null || true)"
  [[ "$state" == "running" ]] || {
    echo "ERROR: $container is not running" >&2
    exit 1
  }
done

curl -fsS http://127.0.0.1:3000/api/health >/dev/null

docker exec hragent-loki \
  wget -qO- http://127.0.0.1:3100/ready >/dev/null

end_ns="$(date +%s%N)"
start_ns="$((end_ns - 300000000000))"

query_result="$(
  docker exec hragent-loki wget -qO- \
    "http://127.0.0.1:3100/loki/api/v1/query_range?query=%7Bcompose_project%3D%22hragent-05%22%7D&start=${start_ns}&end=${end_ns}&limit=20" \
    || true
)"

[[ "$query_result" == *'"status":"success"'* ]] || {
  echo "ERROR: Loki query did not succeed" >&2
  exit 1
}

echo "OK: observability stack is healthy"
```

Coding AI 必须根据实际镜像内可用工具修正脚本，不能直接假设 `wget`、`curl`、`jq` 一定存在。宿主机验证可使用 `curl`；容器内验证优先使用镜像已包含的命令。

---

## 12. 启动、验证和停止命令

### 12.1 启动业务系统

沿用项目现有启动方式：

```bash
docker compose up -d
```

### 12.2 启动可观测性栈

```bash
docker compose \
  --env-file observability/.env \
  -f observability/docker-compose.yml \
  up -d
```

### 12.3 查看状态

```bash
docker compose \
  --env-file observability/.env \
  -f observability/docker-compose.yml \
  ps
```

```bash
docker stats --no-stream \
  hragent-alloy \
  hragent-loki \
  hragent-grafana
```

### 12.4 查看监控服务日志

```bash
docker compose \
  --env-file observability/.env \
  -f observability/docker-compose.yml \
  logs --tail=200 alloy loki grafana
```

### 12.5 停止可观测性栈

```bash
docker compose \
  --env-file observability/.env \
  -f observability/docker-compose.yml \
  down
```

停止时默认保留数据卷。

除非明确需要删除全部历史日志和 Dashboard 数据，否则禁止执行：

```bash
docker compose \
  --env-file observability/.env \
  -f observability/docker-compose.yml \
  down -v
```

---

## 13. 测试要求

### 13.1 静态检查

必须全部通过：

```bash
docker compose -f docker-compose.yml config
```

```bash
docker compose \
  --env-file observability/.env \
  -f observability/docker-compose.yml \
  config
```

```bash
python -m json.tool \
  observability/grafana/dashboards/hragent-logs.json \
  >/dev/null
```

Alloy `validate` 和 `fmt --test` 必须成功。

### 13.2 运行测试

1. 启动当前 HRagent；
2. 启动可观测性栈；
3. 调用一个确定存在的 HRagent 健康检查接口；
4. 访问至少一个后端 API，产生后端访问日志；
5. 刷新前端，产生 Nginx 日志；
6. 确认 PostgreSQL 和 Redis 服务日志可查询；
7. 60 秒内在 Grafana Explore 中查询到四类服务日志。

基础查询：

```logql
{compose_project="hragent-05"}
```

分别验证：

```logql
{compose_project="hragent-05", service="backend"}
```

```logql
{compose_project="hragent-05", service="frontend"}
```

```logql
{compose_project="hragent-05", service="postgres"}
```

```logql
{compose_project="hragent-05", service="redis"}
```

### 13.3 隐私检查

至少抽查最近 200 条后端日志，确认不存在：

- Authorization Header；
- Cookie；
- API Key；
- 密码；
- 员工完整邮箱；
- 对话全文；
- 上传文档正文；
- 完整文件名；
- 原始 session ID。

可使用以下关键字扫描代码和日志，但不能只依赖自动扫描：

```bash
rg -n -i \
  'authorization|cookie|api[_-]?key|secret|password|session_id|filename|request\.body|response\.body' \
  backend
```

### 13.4 资源检查

在稳定运行 10 分钟后执行：

```bash
docker stats --no-stream \
  hragent-alloy \
  hragent-loki \
  hragent-grafana
```

通过标准：

- 无容器重启循环；
- 无 OOMKilled；
- Alloy 未持续接近 256 MiB；
- Loki 未持续接近 1.5 GiB；
- Grafana 未持续接近 512 MiB；
- Loki 无持续写入失败；
- Alloy 无持续 `429`、连接失败或丢弃日志；
- 主机磁盘剩余空间充足。

磁盘检查：

```bash
docker system df -v
```

```bash
docker volume inspect hragent_loki_data
```

必要时根据卷挂载点执行：

```bash
du -sh <loki-volume-mountpoint>
```

### 13.5 保留策略检查

立即测试阶段必须确认：

- Loki 正确加载 `retention_period: 168h`；
- Compactor 已启动；
- 无 retention 配置错误；
- 索引周期为 24h。

真正的 7 天删除行为需要在运行超过 7 天后再次验证。不能仅凭配置文件存在就声称历史日志已按期删除。

---

## 14. 验收标准

只有同时满足以下条件，任务才算完成：

- [ ] 原有 HRagent 业务功能无回归；
- [ ] 原有 API schema 无变化；
- [ ] 根 Compose 配置校验通过；
- [ ] 业务容器全部启用 Docker 日志轮转；
- [ ] 可观测性 Compose 配置校验通过；
- [ ] Alloy 配置 `validate` 通过；
- [ ] Alloy 配置 `fmt --test` 通过；
- [ ] Alloy、Loki、Grafana 均运行且健康；
- [ ] Alloy 只采集 `hragent-05` Compose 项目；
- [ ] Grafana 数据源自动 provision；
- [ ] Dashboard 在全新 Grafana 数据卷上自动 provision；
- [ ] Dashboard 五个面板可执行查询；
- [ ] 后端、前端、PostgreSQL、Redis 日志均可检索；
- [ ] Loki 配置为 7 天保留；
- [ ] Loki 和 Alloy 不对宿主机暴露端口；
- [ ] Grafana 只绑定 `127.0.0.1`；
- [ ] Grafana 禁止匿名访问和公开注册；
- [ ] 代码和日志中未发现明文密码、Token、API Key；
- [ ] 日志中未记录 HR 敏感正文或原始 session ID；
- [ ] 监控容器未 OOM、未重启循环；
- [ ] 提供完整变更文件列表；
- [ ] 提供全部验证命令及真实输出摘要；
- [ ] 提供回滚命令。

---

## 15. 回滚方案

若上线后出现问题，按以下顺序回滚：

### 15.1 停止可观测性服务

```bash
docker compose \
  --env-file observability/.env \
  -f observability/docker-compose.yml \
  down
```

这一步不能影响业务 Compose。

### 15.2 恢复业务 Compose 修改

若 Docker 日志轮转配置导致兼容性问题，只回滚根 `docker-compose.yml` 中新增的：

```yaml
x-default-logging
logging: *default-logging
```

然后执行：

```bash
docker compose -f docker-compose.yml config
docker compose up -d
```

### 15.3 保留数据

默认保留：

- `hragent_alloy_data`；
- `hragent_loki_data`；
- `hragent_grafana_data`。

只有在明确确认不再需要历史日志后，才允许删除卷。

---

## 16. Coding AI 执行顺序

Coding AI 必须按以下顺序工作，不得跳步：

1. 阅读根目录 `docker-compose.yml`；
2. 确认 Compose project name 和服务名；
3. 搜索现有日志实现和敏感字段；
4. 给业务服务增加 Docker 日志轮转；
5. 创建 `observability/` 目录和全部配置；
6. 创建 Grafana Dashboard JSON；
7. 创建验证脚本；
8. 执行 Compose 静态校验；
9. 执行 Alloy 配置校验和格式校验；
10. 启动业务服务；
11. 启动可观测性服务；
12. 验证 Loki、Grafana、Alloy；
13. 验证四类业务日志；
14. 做隐私抽查；
15. 做资源检查；
16. 输出变更报告。

遇到以下情况必须停止并明确报告，不得猜测：

- 实际 Compose project name 不是 `hragent-05`；
- 实际服务名与本文不一致；
- 固定镜像不存在；
- Docker Compose 不支持本文件中的资源限制字段；
- Alloy 配置校验失败；
- Loki 启动后配置解析失败；
- Dashboard JSON 无法 provision；
- 主机资源低于最低建议且出现明显内存或磁盘风险；
- 发现日志包含大量 HR 敏感数据；
- Docker Socket 不允许挂载。

发生上述情况时，先给出准确错误、影响和最小修复方案，不得绕过验证直接宣布完成。

---

## 17. Coding AI 最终交付格式

最终回复必须包含以下内容：

```markdown
## 实施结果
- 状态：成功 / 部分成功 / 失败
- 实际镜像版本：
- 实际 Compose project name：
- 实际采集服务：

## 变更文件
- 路径：变更说明

## 配置校验
- 命令：
- 结果：

## 运行验证
- Alloy：
- Loki：
- Grafana：
- backend 日志：
- frontend 日志：
- postgres 日志：
- redis 日志：

## 隐私检查
- 检查范围：
- 发现的问题：
- 已整改内容：
- 仍存在的风险：

## 资源使用
- Alloy：CPU / 内存
- Loki：CPU / 内存
- Grafana：CPU / 内存
- Loki 卷占用：

## 未完成项
- 无 / 明确列出

## 启动命令
...

## 停止命令
...

## 回滚命令
...
```

不得只回复“已完成”；必须提供真实命令执行结果摘要。

---

## 18. 官方文档参考

以下为实现和校验时使用的官方资料：

- Grafana Alloy Docker log source：
  - https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.docker/
- Grafana Alloy Docker monitoring example：
  - https://grafana.com/docs/alloy/latest/monitor/monitor-docker-containers/
- Grafana Alloy CLI：
  - https://grafana.com/docs/alloy/latest/reference/cli/validate/
  - https://grafana.com/docs/alloy/latest/reference/cli/fmt/
- Grafana Loki Docker installation：
  - https://grafana.com/docs/loki/latest/setup/install/docker/
- Grafana Loki filesystem storage：
  - https://grafana.com/docs/loki/latest/operations/storage/filesystem/
- Grafana Loki retention：
  - https://grafana.com/docs/loki/latest/operations/storage/retention/
- Grafana provisioning：
  - https://grafana.com/docs/grafana/latest/administration/provisioning/
- Grafana Docker installation：
  - https://grafana.com/docs/grafana/latest/setup-grafana/installation/docker/
- Docker json-file logging driver：
  - https://docs.docker.com/engine/logging/drivers/json-file/
- Docker Compose services resource fields：
  - https://docs.docker.com/reference/compose-file/services/

---

## 19. 最终决策

**批准采用 Alloy + Loki + Grafana。**

适用前提：

- 单机 Demo；
- 当前约 4 个业务容器，实施后共约 7 个容器；
- 日志保留 7 天；
- 日志量处于轻量到中等规模；
- 主机具备足够的 CPU、内存和磁盘；
- 不启用高负载本地 MinerU/GPU 推理，或为其另行配置资源；
- 接受本方案只覆盖日志、不覆盖完整指标和链路追踪。

在这些前提下，该技术栈与当前 HRagent 架构兼容，实施成本低，回滚边界清晰，适合作为 Demo 环境的日志可观测性方案。
