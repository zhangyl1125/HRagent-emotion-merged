# HRagent-05 使用 Locust 进行 1 用户冒烟测试与 100 并发压测的可执行方案

## 1. 目标

为 HRagent-05 项目增加一套可直接运行的 Locust 压测文件，覆盖：

- 注册/登录后的认证会话；
- `/api/v1/health` 和 `/api/v1/auth/me` 基础接口；
- 可配置的业务 GET/POST 接口；
- 默认 1 用户冒烟测试场景，确认流程跑通后再显式执行 100 并发用户场景；
- 自动生成 Locust HTML 报告、CSV 数据和 Markdown 汇总报告；
- CI/CD 质量门禁：失败率、平均响应时间、P95 响应时间。

> HRagent-05 当前后端服务端口按 `8111` 设计，前端 HTTPS 端口按 `8443` 设计。压测后端接口时默认使用 `http://localhost:8111`。

---

## 2. 目录结构

建议在 HRagent-05 项目根目录新增：

```text
tests/
└── load/
    ├── hragent_locustfile.py
    ├── generate_locust_report.py
    ├── requirements-load.txt
    └── run_locust.sh

reports/
├── hragent_smoke_1u.html
├── hragent_smoke_1u_stats.csv
├── hragent_smoke_1u_stats_history.csv
├── hragent_smoke_1u_failures.csv
├── hragent_smoke_1u.json
└── hragent_load_test_report.md
```

---

## 3. 安装 Locust

```bash
python -m pip install -r locust-loadtest/tests/load/requirements-load.txt
locust -V
```

`locust-loadtest/tests/load/requirements-load.txt` 内容：

```text
locust>=2.31.0
```

---

## 4. 压测文件：`locust-loadtest/tests/load/hragent_locustfile.py`

```python

"""
HRagent-05 Locust load test file.

Usage:
  locust -f locust-loadtest/tests/load/hragent_locustfile.py \
    -H http://localhost:8111 \
    --headless -u 1 -r 1 -t 10s \
    --html reports/hragent_smoke_1u.html \
    --csv reports/hragent_smoke_1u \
    --csv-full-history \
    --json-file reports/hragent_smoke_1u.json

Environment variables:
  HRAGENT_EMAIL                     default: aah5sgh@bosch.com
  HRAGENT_PASSWORD                  required when auth is enabled
  HRAGENT_REGISTER_IF_MISSING       default: false
  HRAGENT_DISPLAY_NAME              default: Locust User
  HRAGENT_AUTH_ENABLED              default: true
  HRAGENT_VERIFY_TLS                default: true
  HRAGENT_READ_ENDPOINTS            comma-separated GET endpoints
  HRAGENT_POST_ENDPOINTS_JSON       optional JSON list for POST endpoints
  HRAGENT_MAX_FAIL_RATIO            default: 0.01
  HRAGENT_MAX_AVG_MS                default: 800
  HRAGENT_MAX_P95_MS                default: 2000
"""

from __future__ import annotations

import json
import logging
import os
import random
from typing import Any

from locust import HttpUser, between, events, task
from locust.exception import StopUser


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def parse_read_endpoints() -> list[str]:
    raw = os.getenv("HRAGENT_READ_ENDPOINTS", "/api/v1/health,/api/v1/auth/me")
    return [item.strip() for item in raw.split(",") if item.strip()]


def parse_post_endpoints() -> list[dict[str, Any]]:
    raw = os.getenv("HRAGENT_POST_ENDPOINTS_JSON", "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"HRAGENT_POST_ENDPOINTS_JSON is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise RuntimeError("HRAGENT_POST_ENDPOINTS_JSON must be a JSON list")
    return data


class HRagentUser(HttpUser):
    """
    模拟一个 HRagent 用户：
    1. on_start 阶段执行登录。
    2. 运行期间随机访问健康检查、当前用户信息和可配置业务接口。
    3. 可通过 HRAGENT_POST_ENDPOINTS_JSON 增加真实业务 POST 场景。
    """

    wait_time = between(1, 3)

    def on_start(self) -> None:
        self.auth_enabled = env_bool("HRAGENT_AUTH_ENABLED", True)
        self.verify_tls = env_bool("HRAGENT_VERIFY_TLS", True)
        self.email = os.getenv("HRAGENT_EMAIL", "aah5sgh@bosch.com").strip().lower()
        self.password = os.getenv("HRAGENT_PASSWORD", "")
        self.display_name = os.getenv("HRAGENT_DISPLAY_NAME", "Locust User")
        self.read_endpoints = parse_read_endpoints()
        self.post_endpoints = parse_post_endpoints()

        # 本地自签 HTTPS 证书压测时可设置 HRAGENT_VERIFY_TLS=false。
        try:
            self.client.verify = self.verify_tls
        except Exception:
            pass

        if self.auth_enabled:
            if not self.password:
                logging.error("HRAGENT_PASSWORD is required when HRAGENT_AUTH_ENABLED=true")
                raise StopUser()
            if env_bool("HRAGENT_REGISTER_IF_MISSING", False):
                self._register_once()
            self._login()

    def _register_once(self) -> None:
        payload = {
            "email": self.email,
            "password": self.password,
            "display_name": self.display_name,
        }
        with self.client.post(
            "/api/v1/auth/register",
            json=payload,
            name="POST /api/v1/auth/register",
            catch_response=True,
        ) as resp:
            # 已存在、已注册、白名单外等场景可能返回 400/409/200。
            # 压测注册不是主路径，因此这里只记录，不中断。
            if resp.status_code in {200, 201, 400, 409}:
                resp.success()
            else:
                resp.failure(f"unexpected register status={resp.status_code}, body={resp.text[:200]}")

    def _login(self) -> None:
        payload = {"email": self.email, "password": self.password}
        with self.client.post(
            "/api/v1/auth/login",
            json=payload,
            name="POST /api/v1/auth/login",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
                return
            resp.failure(f"login failed status={resp.status_code}, body={resp.text[:200]}")
            raise StopUser()

    @task(2)
    def read_scenario(self) -> None:
        endpoint = random.choice(self.read_endpoints)
        name = f"GET {endpoint}"
        with self.client.get(endpoint, name=name, catch_response=True) as resp:
            if resp.status_code in {200, 204}:
                resp.success()
            elif resp.status_code == 401:
                resp.failure("unauthorized: session cookie missing/expired or auth route not configured")
            elif resp.status_code == 404:
                resp.failure("endpoint not found: check HRAGENT_READ_ENDPOINTS")
            else:
                resp.failure(f"unexpected status={resp.status_code}, body={resp.text[:200]}")

    @task(1)
    def business_post_scenario(self) -> None:
        if not self.post_endpoints:
            # 没有配置真实业务 POST 时，用 /auth/me 保持轻量读压测。
            with self.client.get("/api/v1/auth/me", name="GET /api/v1/auth/me fallback", catch_response=True) as resp:
                if resp.status_code in {200, 204}:
                    resp.success()
                elif not self.auth_enabled and resp.status_code in {401, 404}:
                    resp.success()
                else:
                    resp.failure(f"unexpected fallback status={resp.status_code}")
            return

        scenario = random.choice(self.post_endpoints)
        path = scenario.get("path")
        payload = scenario.get("payload", {})
        name = scenario.get("name", f"POST {path}")

        if not path:
            raise RuntimeError("Each POST scenario must contain path")

        with self.client.post(path, json=payload, name=name, catch_response=True) as resp:
            if 200 <= resp.status_code < 300:
                resp.success()
            elif resp.status_code == 401:
                resp.failure("unauthorized: session cookie missing/expired")
            elif resp.status_code == 404:
                resp.failure("endpoint not found: check HRAGENT_POST_ENDPOINTS_JSON")
            else:
                resp.failure(f"unexpected status={resp.status_code}, body={resp.text[:300]}")


@events.quitting.add_listener
def on_quitting(environment, **kwargs) -> None:
    """
    CI/CD 质量门禁：
    - 失败率 > HRAGENT_MAX_FAIL_RATIO 判失败
    - 平均响应时间 > HRAGENT_MAX_AVG_MS 判失败
    - P95 > HRAGENT_MAX_P95_MS 判失败
    """
    stats = environment.stats.total
    max_fail_ratio = env_float("HRAGENT_MAX_FAIL_RATIO", 0.01)
    max_avg_ms = env_float("HRAGENT_MAX_AVG_MS", 800.0)
    max_p95_ms = env_float("HRAGENT_MAX_P95_MS", 2000.0)

    p95 = stats.get_response_time_percentile(0.95) or 0
    avg = stats.avg_response_time or 0
    fail_ratio = stats.fail_ratio or 0

    if fail_ratio > max_fail_ratio:
        logging.error("Load test failed: fail_ratio %.4f > %.4f", fail_ratio, max_fail_ratio)
        environment.process_exit_code = 1
    elif avg > max_avg_ms:
        logging.error("Load test failed: avg_response_time %.2f ms > %.2f ms", avg, max_avg_ms)
        environment.process_exit_code = 1
    elif p95 > max_p95_ms:
        logging.error("Load test failed: p95 %.2f ms > %.2f ms", p95, max_p95_ms)
        environment.process_exit_code = 1
    else:
        logging.info("Load test passed: fail_ratio=%.4f avg=%.2fms p95=%.2fms", fail_ratio, avg, p95)
        environment.process_exit_code = 0

```

---

## 5. 报告生成脚本：`locust-loadtest/tests/load/generate_locust_report.py`

```python

"""
Generate a Markdown load-test report from Locust CSV/JSON outputs.

Usage:
  python locust-loadtest/tests/load/generate_locust_report.py \
    --prefix reports/hragent_smoke_1u \
    --json reports/hragent_smoke_1u.json \
    --html reports/hragent_smoke_1u.html \
    --output reports/hragent_load_test_report.md
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def read_json(path: Path | None) -> Any:
    if not path or not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def find_aggregated(stats_rows: list[dict[str, str]]) -> dict[str, str]:
    for row in stats_rows:
        name = (row.get("Name") or row.get("name") or "").strip()
        if name.lower() in {"aggregated", "total"}:
            return row
    return stats_rows[-1] if stats_rows else {}


def get(row: dict[str, str], *names: str, default: str = "") -> str:
    for name in names:
        if name in row and row[name] != "":
            return row[name]
    return default


def to_float(value: str, default: float = 0.0) -> float:
    try:
        return float(str(value).replace("%", "").strip())
    except Exception:
        return default


def build_report(prefix: Path, json_path: Path | None, html_path: Path | None, output: Path) -> None:
    stats_path = Path(f"{prefix}_stats.csv")
    failures_path = Path(f"{prefix}_failures.csv")
    history_path = Path(f"{prefix}_stats_history.csv")

    stats_rows = read_csv(stats_path)
    failure_rows = read_csv(failures_path)
    history_rows = read_csv(history_path)
    json_data = read_json(json_path)

    agg = find_aggregated(stats_rows)

    request_count = get(agg, "Request Count", "request_count", default="0")
    failure_count = get(agg, "Failure Count", "failure_count", default="0")
    avg_ms = get(agg, "Average Response Time", "avg_response_time", default="0")
    min_ms = get(agg, "Min Response Time", "min_response_time", default="0")
    max_ms = get(agg, "Max Response Time", "max_response_time", default="0")
    median_ms = get(agg, "Median Response Time", "median_response_time", "50%", default="0")
    p95_ms = get(agg, "95%", "95", "response_time_percentile_0.95", default="0")
    p99_ms = get(agg, "99%", "99", "response_time_percentile_0.99", default="0")
    rps = get(agg, "Requests/s", "requests_per_second", default="0")

    req = to_float(request_count)
    fail = to_float(failure_count)
    fail_ratio = fail / req if req > 0 else 0.0
    verdict = "PASS" if fail_ratio <= 0.01 and to_float(p95_ms) <= 2000 else "REVIEW"

    top_rows = []
    for row in stats_rows:
        name = get(row, "Name", "name", default="")
        if not name or name.lower() in {"aggregated", "total"}:
            continue
        top_rows.append(row)
    top_rows = sorted(top_rows, key=lambda r: to_float(get(r, "95%", "Average Response Time", default="0")), reverse=True)[:10]

    lines = [
        "# HRagent-05 Locust 压测报告",
        "",
        f"- 生成时间：`{datetime.now().isoformat(timespec='seconds')}`",
        f"- 结论：**{verdict}**",
        f"- Locust HTML 报告：`{html_path}`" if html_path else "- Locust HTML 报告：未提供",
        "",
        "## 1. 总览指标",
        "",
        "| 指标 | 数值 |",
        "|---|---:|",
        f"| 总请求数 | {request_count} |",
        f"| 失败数 | {failure_count} |",
        f"| 失败率 | {fail_ratio:.2%} |",
        f"| RPS | {rps} |",
        f"| 平均响应时间 ms | {avg_ms} |",
        f"| 最小响应时间 ms | {min_ms} |",
        f"| 最大响应时间 ms | {max_ms} |",
        f"| 中位数响应时间 ms | {median_ms} |",
        f"| P95 响应时间 ms | {p95_ms} |",
        f"| P99 响应时间 ms | {p99_ms} |",
        "",
        "## 2. 最慢接口 Top 10",
        "",
        "| 接口 | 请求数 | 失败数 | 平均 ms | P95 ms | RPS |",
        "|---|---:|---:|---:|---:|---:|",
    ]

    if top_rows:
        for row in top_rows:
            lines.append(
                "| {name} | {req} | {fail} | {avg} | {p95} | {rps} |".format(
                    name=get(row, "Name", "name", default=""),
                    req=get(row, "Request Count", "request_count", default="0"),
                    fail=get(row, "Failure Count", "failure_count", default="0"),
                    avg=get(row, "Average Response Time", "avg_response_time", default="0"),
                    p95=get(row, "95%", "95", default="0"),
                    rps=get(row, "Requests/s", "requests_per_second", default="0"),
                )
            )
    else:
        lines.append("| 无数据 | 0 | 0 | 0 | 0 | 0 |")

    lines.extend([
        "",
        "## 3. 失败明细",
        "",
        "| Method | Name | Error | Occurrences |",
        "|---|---|---|---:|",
    ])

    if failure_rows:
        for row in failure_rows[:20]:
            lines.append(
                "| {method} | {name} | {error} | {occurrences} |".format(
                    method=get(row, "Method", "method", default=""),
                    name=get(row, "Name", "name", default=""),
                    error=get(row, "Error", "error", default="").replace("|", "\\|")[:300],
                    occurrences=get(row, "Occurrences", "occurrences", default="0"),
                )
            )
    else:
        lines.append("| - | - | 无失败记录 | 0 |")

    lines.extend([
        "",
        "## 4. 历史数据文件",
        "",
        f"- stats：`{stats_path}`",
        f"- failures：`{failures_path}`",
        f"- history：`{history_path}`，记录数 `{len(history_rows)}`",
        f"- json：`{json_path}`" if json_path else "- json：未提供",
        "",
        "## 5. 判断标准",
        "",
        "- 默认失败率 `<= 1%`。",
        "- 默认 P95 响应时间 `<= 2000ms`。",
        "- 登录接口因为包含 KDF，允许比普通读接口更慢；建议单独观察 `POST /api/v1/auth/login`。",
        "- 若出现大量 `401`，优先检查 `HRAGENT_PASSWORD`、Cookie、白名单和认证接口路径。",
        "- 若出现大量 `404`，优先检查 `HRAGENT_READ_ENDPOINTS` 或 `HRAGENT_POST_ENDPOINTS_JSON` 中的接口路径。",
        "",
        "## 6. 原始 JSON 摘要",
        "",
        "```json",
        json.dumps(json_data if json_data else {}, ensure_ascii=False, indent=2)[:4000],
        "```",
        "",
    ])

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", required=True, help="Locust CSV prefix, e.g. reports/hragent_smoke_1u")
    parser.add_argument("--json", default=None, help="Locust --json-file path")
    parser.add_argument("--html", default=None, help="Locust --html path")
    parser.add_argument("--output", required=True, help="Markdown report output path")
    args = parser.parse_args()
    build_report(
        prefix=Path(args.prefix),
        json_path=Path(args.json) if args.json else None,
        html_path=Path(args.html) if args.html else None,
        output=Path(args.output),
    )


if __name__ == "__main__":
    main()

```

---

## 6. 一键运行脚本：`locust-loadtest/tests/load/run_locust.sh`

```bash
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
: "${HRAGENT_REPORT_PREFIX:=${REPORTS_DIR}/hragent_smoke_1u}"

locust -f "${SCRIPT_DIR}/hragent_locustfile.py"   -H "${HRAGENT_BASE_URL}"   --headless   -u "${HRAGENT_USERS}"   -r "${HRAGENT_SPAWN_RATE}"   -t "${HRAGENT_RUN_TIME}"   --stop-timeout 30   --html "${HRAGENT_REPORT_PREFIX}.html"   --csv "${HRAGENT_REPORT_PREFIX}"   --csv-full-history   --json-file "${HRAGENT_REPORT_PREFIX}.json"

python "${SCRIPT_DIR}/generate_locust_report.py"   --prefix "${HRAGENT_REPORT_PREFIX}"   --json "${HRAGENT_REPORT_PREFIX}.json"   --html "${HRAGENT_REPORT_PREFIX}.html"   --output "${REPORTS_DIR}/hragent_load_test_report.md"

echo "HTML report: ${HRAGENT_REPORT_PREFIX}.html"
echo "Markdown report: ${REPORTS_DIR}/hragent_load_test_report.md"
```

保存后执行：

```bash
chmod +x locust-loadtest/tests/load/run_locust.sh
```

---

## 7. 最小可执行命令

### 7.1 仅压测健康检查和登录态

```bash
export HRAGENT_BASE_URL="http://localhost:8111"
export HRAGENT_EMAIL="aah5sgh@bosch.com"
export HRAGENT_PASSWORD="请替换为真实测试密码"
export HRAGENT_AUTH_ENABLED=true
export HRAGENT_READ_ENDPOINTS="/api/v1/health,/api/v1/auth/me"

bash locust-loadtest/tests/load/run_locust.sh
```

### 7.2 默认 1 用户、10 秒、每秒启动 1 个用户

```bash
HRAGENT_USERS=1 HRAGENT_SPAWN_RATE=1 HRAGENT_RUN_TIME=10s HRAGENT_REPORT_PREFIX=reports/hragent_smoke_1u bash locust-loadtest/tests/load/run_locust.sh
```

### 7.3 完整六步业务流程，1 用户跑通一次

该脚本用于先跑通完整业务链路，不用于正式压力测试。流程包含：登录、创建会话、员工搜索、上传文本资料、确认员工信息、确认沟通意图、确认 Persona、生成谈前指导、预演一轮、结束预演、生成复盘报告。

```bash
export HRAGENT_BASE_URL="http://localhost:8111"
export HRAGENT_EMAIL="aah5sgh@bosch.com"
export HRAGENT_PASSWORD="请替换为真实测试密码"
export HRAGENT_AUTH_ENABLED=true

bash locust-loadtest/tests/load/run_full_flow_1u.sh
```

完整流程模式会在 1 个用户完成一次链路后自动停止 Locust，并输出 `reports/hragent_full_flow_1u.html` 和 `reports/hragent_load_test_report.md`。

如果需要在 Locust Web UI 中观察完整流程：

```bash
export HRAGENT_BASE_URL="http://localhost:8111"
export HRAGENT_EMAIL="aah5sgh@bosch.com"
export HRAGENT_PASSWORD="请替换为真实测试密码"
export HRAGENT_AUTH_ENABLED=true

bash locust-loadtest/tests/load/run_full_flow_1u_web.sh
```

打开 `http://localhost:8099`，填写 `Users=1`、`Ramp up=1` 后启动。完整流程执行完会自动停止运行器。

### 7.4 本地 HTTPS 自签证书场景

如果使用 `https://localhost:8443` 且证书是自签名：

```bash
export HRAGENT_BASE_URL="https://localhost:8443"
export HRAGENT_VERIFY_TLS=false
bash locust-loadtest/tests/load/run_locust.sh
```

---

## 8. 增加真实业务接口压测

如果你已经确认 HRagent-05 的业务接口路径，可以通过环境变量加入：

### 8.1 GET 接口

```bash
export HRAGENT_READ_ENDPOINTS="/api/v1/health,/api/v1/auth/me,/api/v1/workflow/state,/api/v1/guidance/latest"
```

### 8.2 POST 接口

```bash
export HRAGENT_POST_ENDPOINTS_JSON='[
  {
    "name": "POST rehearsal message",
    "path": "/api/v1/rehearsal/message",
    "payload": {
      "session_id": "load-test-session",
      "speaker": "hrbp",
      "message": "我们今天主要讨论绩效反馈和下一步改进计划。"
    }
  }
]'
```

如果接口路径还没有确认，先不要压测写接口，避免向业务数据库写入大量测试数据。

---

## 9. 输出报告

运行完成后会生成：

```text
reports/hragent_smoke_1u.html              # Locust 官方 HTML 报告
reports/hragent_smoke_1u_stats.csv         # 接口统计
reports/hragent_smoke_1u_stats_history.csv # 历史曲线数据
reports/hragent_smoke_1u_failures.csv      # 失败明细
reports/hragent_smoke_1u.json              # JSON 汇总
reports/hragent_load_test_report.md       # 自定义 Markdown 汇总报告
```

Markdown 报告包含：总请求数、失败率、RPS、平均/最大/P95/P99 响应时间、最慢接口 Top 10、失败明细和 PASS/REVIEW 结论。

---

## 10. 质量门禁

默认规则写在 `hragent_locustfile.py` 的 `on_quitting` 中：

```yaml
HRAGENT_MAX_FAIL_RATIO: 0.01
HRAGENT_MAX_AVG_MS: 800
HRAGENT_MAX_P95_MS: 2000
```

可按环境调整：

```bash
export HRAGENT_MAX_FAIL_RATIO=0.01
export HRAGENT_MAX_AVG_MS=800
export HRAGENT_MAX_P95_MS=2000
```

建议判断标准：

| 场景 | 指标 |
|---|---|
| 普通读取接口 | P95 <= 800ms |
| 登录接口 | P95 <= 3000ms |
| 整体失败率 | <= 1% |
| 100 活跃用户 | 不出现连接池耗尽 |
| Redis session | 不出现大量 401 |
| 数据库 | 不出现 pool timeout |

---

## 11. 运行前检查

```bash
curl -fsS http://localhost:8111/api/v1/health
grep -E "AUTH_|DB_POOL|REDIS" .env || true
echo "$HRAGENT_EMAIL"
locust -V
```

---

## 12. Docker 运行方式

如果不想在本机安装 Locust，可以使用官方 Docker 镜像：

```bash
docker run --rm   --network host   -v "$PWD":/mnt/locust   -w /mnt/locust   -e HRAGENT_EMAIL="aah5sgh@bosch.com"   -e HRAGENT_PASSWORD="请替换为真实测试密码"   -e HRAGENT_AUTH_ENABLED=true   locustio/locust   -f locust-loadtest/tests/load/hragent_locustfile.py   -H http://localhost:8111   --headless -u 1 -r 1 -t 10s   --html reports/hragent_smoke_1u.html   --csv reports/hragent_smoke_1u   --csv-full-history   --json-file reports/hragent_smoke_1u.json
```

然后生成 Markdown 报告：

```bash
python locust-loadtest/tests/load/generate_locust_report.py   --prefix reports/hragent_smoke_1u   --json reports/hragent_smoke_1u.json   --html reports/hragent_smoke_1u.html   --output reports/hragent_load_test_report.md
```

Windows Docker 不一定支持 `--network host`，可把 `-H` 改成宿主机可访问地址：

```bash
-H http://host.docker.internal:8111
```

---

## 13. CI/CD 示例

```yaml
name: hragent-load-test

on:
  workflow_dispatch:

jobs:
  locust:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install load test dependencies
        run: python -m pip install -r locust-loadtest/tests/load/requirements-load.txt
      - name: Run Locust
        env:
          HRAGENT_EMAIL: ${{ secrets.HRAGENT_LOADTEST_EMAIL }}
          HRAGENT_PASSWORD: ${{ secrets.HRAGENT_LOADTEST_PASSWORD }}
          HRAGENT_AUTH_ENABLED: "true"
        run: |
          locust -f locust-loadtest/tests/load/hragent_locustfile.py             -H http://localhost:8111             --headless -u 1 -r 1 -t 10s             --html reports/hragent_smoke_1u.html             --csv reports/hragent_smoke_1u             --csv-full-history             --json-file reports/hragent_smoke_1u.json
      - name: Generate Markdown report
        run: |
          python locust-loadtest/tests/load/generate_locust_report.py             --prefix reports/hragent_smoke_1u             --json reports/hragent_smoke_1u.json             --html reports/hragent_smoke_1u.html             --output reports/hragent_load_test_report.md
      - name: Upload report
        uses: actions/upload-artifact@v4
        with:
          name: hragent-locust-report
          path: reports/
```

---

## 14. 常见问题

### 14.1 大量 401

优先检查测试账号、密码、白名单、Cookie 和认证接口路径。

```bash
echo "$HRAGENT_EMAIL"
```

不要把真实密码打印到日志。

### 14.2 大量 404

说明接口路径不匹配。先仅压测：

```bash
export HRAGENT_READ_ENDPOINTS="/api/v1/health,/api/v1/auth/me"
```

### 14.3 登录接口很慢

登录包含 `Argon2id` KDF，天然比普通接口慢。压测时应在 `on_start` 登录一次，后续复用 session cookie，不要让每个任务都频繁登录。

### 14.4 写接口污染数据

不要直接对真实业务 POST 接口压测。建议使用独立 load-test 数据库、测试 session_id 前缀，并在压测后清理测试数据。

---

## 15. Definition of Done

```yaml
locustfile:
  - locust-loadtest/tests/load/hragent_locustfile.py 已加入项目
  - on_start 可登录并复用 session
  - 支持 HRAGENT_READ_ENDPOINTS
  - 支持 HRAGENT_POST_ENDPOINTS_JSON
  - 支持 100 用户 headless 压测
report:
  - 生成 Locust HTML 报告
  - 生成 CSV 统计文件
  - 生成 JSON 汇总文件
  - 生成 Markdown 汇总报告
quality_gate:
  - fail_ratio > 1% 时退出码为 1
  - avg_response_time > 800ms 时退出码为 1
  - p95 > 2000ms 时退出码为 1
security:
  - 密码通过环境变量注入
  - 不把真实密码写入 locustfile
  - 不把真实账号密码提交到 Git
```

---

## 16. 推荐执行顺序

```text
Step 1: 将 locust-loadtest/tests/load/ 文件加入 HRagent-05 项目。
Step 2: 安装 Locust。
Step 3: 启动 HRagent-05 backend。
Step 4: 使用白名单账号注册并确认登录可用。
Step 5: 先执行 1 用户 10 秒 smoke test。
Step 6: 再执行 100 用户 5 分钟正式压测。
Step 7: 查看 HTML 报告。
Step 8: 生成 Markdown 报告。
Step 9: 根据 P95、失败率、慢接口 Top 10 调整后端连接池、Redis、KDF 并发和接口性能。
```

Smoke test：

```bash
HRAGENT_USERS=1 HRAGENT_SPAWN_RATE=1 HRAGENT_RUN_TIME=10s HRAGENT_REPORT_PREFIX=reports/hragent_smoke_1u bash locust-loadtest/tests/load/run_locust.sh
```

正式压测：

```bash
HRAGENT_USERS=100 HRAGENT_SPAWN_RATE=10 HRAGENT_RUN_TIME=5m HRAGENT_REPORT_PREFIX=reports/hragent_100u bash locust-loadtest/tests/load/run_locust.sh
```
