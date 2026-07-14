# HRagent Demo 日志可观测性 Coding Spec（拆分版）

> 本目录将 `../HRagent_Alloy_Loki_Grafana_Demo_Coding_Spec.md` 按实施阶段拆分，便于 Coding AI 分步执行。原始文档保持不变，仍可作为完整参考。

## 阅读顺序

1. [01-范围与架构](01-范围与架构.md)：边界、资源、架构和版本约束。
2. [02-实施前检查与业务侧改动](02-实施前检查与业务侧改动.md)：先确认现状、日志隐私，再进行最小业务 Compose 改动。
3. [03-可观测性 Compose](03-可观测性-Compose.md)：创建独立 Compose 项目及环境变量文件。
4. [04-Loki 与 Alloy](04-Loki-与-Alloy.md)：日志存储、采集、标签和 Alloy 校验。
5. [05-Grafana 配置与看板](05-Grafana-配置与看板.md)：数据源、Dashboard Provider 和 Dashboard JSON 要求。
6. [06-验证与测试](06-验证与测试.md)：静态检查、运行验证、隐私和资源检查。
7. [07-运行验收与回滚](07-运行验收与回滚.md)：日常命令、验收条件、回滚和最终交付格式。

## 执行规则

- 严格按上述顺序执行；未通过当前阶段的校验，不进入下一阶段。
- 只实现 Docker 容器日志采集、Loki 检索和 Grafana 可视化；不扩大为 Metrics、Tracing 或告警平台。
- 不改变 HRagent 的业务接口、数据库结构和业务流程。
- 不在任何配置、脚本、日志或交付内容中写入真实密码、Token、Cookie、API Key 或员工敏感正文。
- 遇到 Compose project name、服务名、镜像、Alloy/Loki 配置或 Docker Socket 与本文不一致时，停止并报告准确错误、影响和最小修复方案。

## 目标目录（实施后）

```text
observability/
├── .env.example
├── docker-compose.yml
├── README.md
├── alloy/config.alloy
├── loki/loki-config.yaml
└── grafana/
    ├── dashboards/hragent-logs.json
    └── provisioning/
        ├── dashboards/dashboards.yml
        └── datasources/loki.yml

scripts/verify_observability.sh
```

业务根目录的 `docker-compose.yml` 仅允许增加 Docker `json-file` 日志轮转配置。
