# HRagent Alloy + Loki + Grafana

启动：

```bash
docker compose --env-file observability/.env -f observability/docker-compose.yml up -d
```

Grafana 仅监听 `127.0.0.1:3000`。通过 SSH 隧道访问远程主机：`ssh -L 3000:127.0.0.1:3000 <user>@<host>`。

停止监控（保留日志和 Dashboard 卷）：

```bash
docker compose --env-file observability/.env -f observability/docker-compose.yml down
```
