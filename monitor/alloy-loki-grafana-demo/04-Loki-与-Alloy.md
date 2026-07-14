# 04：Loki 与 Alloy

## `observability/loki/loki-config.yaml`

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
    kvstore: {store: inmemory}
query_range:
  results_cache:
    cache:
      embedded_cache: {enabled: true, max_size_mb: 64}
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
      index: {prefix: index_, period: 24h}
compactor:
  working_directory: /loki/retention
  compaction_interval: 10m
  retention_enabled: true
  retention_delete_delay: 2h
  retention_delete_worker_count: 20
  delete_request_store: filesystem
analytics: {reporting_enabled: false}
```

必须保持：single-binary、本地 filesystem、TSDB v13、24 小时索引、168 小时全局保留、Compactor retention、单副本、无对象存储/多租户认证，且 Loki 不对宿主机或公网暴露。保留期不依据磁盘余量提前清理；磁盘压力增大时只能缩短保留期或扩容。

## `observability/alloy/config.alloy`

```alloy
logging { level = "info" format = "logfmt" }

discovery.docker "hragent" {
  host = "unix:///var/run/docker.sock"
  refresh_interval = "10s"
}

discovery.relabel "hragent" {
  targets = discovery.docker.hragent.targets
  rule {
    source_labels = ["__meta_docker_container_label_com_docker_compose_project"]
    regex = sys.env("HRAGENT_COMPOSE_PROJECT")
    action = "keep"
  }
  rule { source_labels = ["__meta_docker_container_label_com_docker_compose_project"] target_label = "compose_project" }
  rule { source_labels = ["__meta_docker_container_label_com_docker_compose_service"] target_label = "service" }
  rule { source_labels = ["__meta_docker_container_name"] regex = "/(.*)" target_label = "container" }
  rule { target_label = "environment" replacement = sys.env("HRAGENT_ENVIRONMENT") }
  rule { target_label = "host" replacement = sys.env("HRAGENT_HOST") }
}

loki.source.docker "hragent" {
  host = "unix:///var/run/docker.sock"
  targets = discovery.relabel.hragent.output
  refresh_interval = "10s"
  labels = {source = "docker"}
  forward_to = [loki.process.hragent.receiver]
}

loki.process "hragent" {
  stage.decolorize {}
  stage.regex {
    expression = "(?i)(?:^|\\|[[:space:]]*)(?P<level>debug|info|warning|warn|error|critical|exception|fatal|log)(?:[[:space:]]*\\||:)"
  }
  stage.labels { values = {level = ""} }
  forward_to = [loki.write.local.receiver]
}

loki.write "local" {
  endpoint { url = "http://loki:3100/loki/api/v1/push" }
}
```

仅允许低基数标签：`compose_project`、`service`、`container`、`environment`、`host`、`source`、`level`。禁止将 request/session/user/employee/document ID、文件名、URL、错误全文或任何高基数业务字段设为标签；它们只能在日志正文或 JSON 字段中检索。

## Alloy 必做校验

```bash
docker run --rm -e HRAGENT_COMPOSE_PROJECT=hragent-05 -e HRAGENT_ENVIRONMENT=demo -e HRAGENT_HOST=hragent-demo-01 -v "$PWD/observability/alloy/config.alloy:/etc/alloy/config.alloy:ro" grafana/alloy:v1.17.0 validate /etc/alloy/config.alloy

docker run --rm -v "$PWD/observability/alloy/config.alloy:/etc/alloy/config.alloy:ro" grafana/alloy:v1.17.0 fmt --test /etc/alloy/config.alloy
```

若固定镜像 CLI 参数存在补丁差异，先用 `alloy help` 确认等价命令；不得跳过验证。
