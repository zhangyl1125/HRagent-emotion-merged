
"""
Generate a Markdown load-test report from Locust CSV/JSON outputs.

Usage:
  python locust-loadtest/tests/load/generate_locust_report.py \
    --prefix reports/hragent_100u \
    --json reports/hragent_100u.json \
    --html reports/hragent_100u.html \
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
    parser.add_argument("--prefix", required=True, help="Locust CSV prefix, e.g. reports/hragent_100u")
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
