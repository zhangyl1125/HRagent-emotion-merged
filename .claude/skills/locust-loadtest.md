---
name: locust-loadtest
description: Locust-based load testing framework for web services. Use when setting up performance tests, running smoke tests (1 user) or stress tests (100+ concurrent users), or integrating load tests into CI/CD pipelines.
triggers:
  - 压测
  - 负载测试
  - load test
  - Locust
  - 性能测试
  - 并发测试
  - 冒烟测试
scope: Web service performance testing
---

# Locust 压测框架

来源：HRagent-05 [locust-loadtest/](../../locust-loadtest/) 目录

## 目录结构

```
locust-loadtest/
├── tests/
│   └── load/
│       ├── hragent_locustfile.py       # Locust 测试脚本
│       ├── generate_locust_report.py    # 报告生成脚本
│       └── requirements-load.txt       # 依赖：locust>=2.31.0
reports/
├── hragent_smoke_1u.html               # 1 用户冒烟 HTML 报告
├── hragent_smoke_1u_stats.csv          # 请求统计 CSV
├── hragent_smoke_1u_stats_history.csv  # 时序统计 CSV
├── hragent_smoke_1u_failures.csv       # 失败记录 CSV
├── hragent_smoke_1u.json               # JSON 原始数据
└── hragent_load_test_report.md         # Markdown 汇总报告
```

## 安装

```bash
pip install -r locust-loadtest/tests/load/requirements-load.txt
locust -V
```

## 两阶段策略

### 阶段 1：冒烟测试（1 用户）

```bash
locust -f locust-loadtest/tests/load/hragent_locustfile.py \
  --headless \
  --users 1 \
  --spawn-rate 1 \
  --run-time 60s \
  --host http://localhost:8111 \
  --html reports/hragent_smoke_1u.html \
  --csv reports/hragent_smoke_1u \
  --json reports/hragent_smoke_1u.json
```

**目的**：确认所有接口可访问、认证流程正常、无 500 错误。

### 阶段 2：并发压测

```bash
locust -f locust-loadtest/tests/load/hragent_locustfile.py \
  --headless \
  --users 100 \
  --spawn-rate 10 \
  --run-time 300s \
  --host http://localhost:8111
```

## Locustfile 编写规范

### 认证会话管理

```python
from locust import HttpUser, task, between

class HRAgentUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        """每个虚拟用户启动时注册/登录，获取认证 cookie。"""
        self.client.post("/api/v1/auth/register", json={...})
        self.client.post("/api/v1/auth/login", json={...})

    @task(3)  # 权重 3
    def health_check(self):
        self.client.get("/api/v1/health")

    @task(2)  # 权重 2
    def auth_me(self):
        self.client.get("/api/v1/auth/me")

    @task(1)  # 权重 1（较重接口降低频率）
    def guidance(self):
        self.client.post("/api/v1/guidance/...", json={...})
```

### 任务权重

- `@task(3)` — 高频：health check、状态查询
- `@task(2)` — 中频：数据读取、列表查询
- `@task(1)` — 低频：重计算接口（guidance、report 生成）

## CI/CD 质量门禁

| 指标 | 冒烟测试 | 压测 |
|---|---|---|
| 失败率 | 0% | < 1% |
| 平均响应时间 | < 500ms | < 2000ms |
| P95 响应时间 | < 1000ms | < 5000ms |

## 前置条件

1. 目标服务已启动并可通过 `--host` 访问。
2. 测试账号已在白名单中（或 `auth_whitelist_enabled=false`）。
3. 数据库和 Redis 已初始化。
4. 如涉及 LLM 调用，注意 API 额度和成本。

## 报告解读

- **HTML 报告**：总览 RPS、响应时间分布、失败率曲线
- **failures.csv**：记录每次失败的请求路径、状态码、响应体
- **stats_history.csv**：按秒级粒度记录，用于定位性能劣化时间点
