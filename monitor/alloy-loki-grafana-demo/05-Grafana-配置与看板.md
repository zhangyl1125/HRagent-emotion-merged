# 05：Grafana 配置与看板

## Loki 数据源

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

## Dashboard Provider

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

## Dashboard JSON

创建合法 JSON 文件 `observability/grafana/dashboards/hragent-logs.json`；不得使用伪代码。它必须在全新 `grafana_data` 卷自动 provision，且不依赖第三方插件或额外数据源 Transformation。

固定元数据：

| 属性 | 值 |
|---|---|
| UID | `hragent-demo-logs` |
| Title | `HRagent Demo Logs` |
| 默认时间范围 | Last 1 hour |
| Refresh | 10s |
| Timezone | browser |

变量：

- `service`：Query 类型，Loki 数据源，查询 `label_values({compose_project="hragent-05"}, service)`，开启 Include All，All value 为 `.*`。
- `search`：Text box，默认空字符串。

必须包含以下 5 个面板：

| 面板 | 类型 | LogQL |
|---|---|---|
| Log Rate by Service | Time series | `sum by (service) ( rate({compose_project="hragent-05"}[5m]) )` |
| Errors in Last 5 Minutes | Stat | `sum( count_over_time( {compose_project="hragent-05"} \|~ "(?i)(error\|exception\|critical\|traceback\|failed)" [5m] ) )` |
| Error Rate by Service | Time series | `sum by (service) ( rate( {compose_project="hragent-05"} \|~ "(?i)(error\|exception\|critical\|traceback\|failed)" [5m] ) )` |
| Backend Business Failures | Logs | `{compose_project="hragent-05", service="backend"} \|~ "(?i)(documents\\.text\\.failed\|guidance.*failed\|rehearsal.*failed\|redis.*failed)"` |
| Live Logs | Logs | `{compose_project="hragent-05", service=~"$service"} \|= "$search"` |

两类 Logs 面板均要显示时间、标签和日志正文，默认按时间倒序。

JSON 校验命令：

```bash
python -m json.tool observability/grafana/dashboards/hragent-logs.json >/dev/null
```
