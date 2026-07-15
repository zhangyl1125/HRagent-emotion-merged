# HRagent-05 日志与 Token 用量监控

监控服务使用独立 Compose 项目 `hragent-observability`，不会加入或替换 HRagent-05 的业务服务。

## 启动

```bash
# 启动 HRagent-05
docker compose up -d postgres redis backend frontend

# 启动 Alloy、Loki、Grafana
docker compose --env-file observability/.env -f observability/docker-compose.yml up -d
```

Grafana 仅监听本机 `127.0.0.1:3000`。本机访问 `http://127.0.0.1:3000`；远程服务器请使用 SSH 隧道：

```bash
ssh -L 3000:127.0.0.1:3000 <user>@<host>
```

登录账号与密码由 `observability/.env` 管理，禁止提交或分享该文件。

## 使用

打开 `HRagent / HRagent Demo Logs` Dashboard：

- `Token Usage (5m)`：从后端 `llm_usage` 日志统计最近五分钟总 Token。
- `Log Rate by Service`、错误面板和 Live Logs：按 `backend`、`frontend`、`postgres`、`redis` 筛选日志。

Loki 只采集 `compose_project="hragent-05"` 的 Docker stdout/stderr；不使用业务用户、会话或文件名作为标签。

## 检查与停止

```bash
scripts/verify_observability.sh

docker compose --env-file observability/.env -f observability/docker-compose.yml ps
docker compose --env-file observability/.env -f observability/docker-compose.yml logs --tail=200 alloy loki grafana

# 停止监控并保留历史卷
docker compose --env-file observability/.env -f observability/docker-compose.yml down
```

不要执行 `down -v`，除非确认不再需要历史日志和 Grafana 数据。
