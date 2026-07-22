#!/usr/bin/env python3
"""Aggregate normalized AI usage JSONL without exposing prompt content."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

SENSITIVE_KEYS = {
    "authorization", "cookie", "password", "api_key", "secret",
    "access_token", "refresh_token", "email", "session_id", "user_id",
    "prompt", "messages", "content", "response", "completion",
}
ALLOWED_GROUP_FIELDS = {
    "provider", "model", "task", "feature", "route", "operation",
    "usage_source", "status", "user_ref", "tenant_ref",
}
TOKEN_FIELDS = (
    "input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens"
)


class InputError(ValueError):
    pass


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def decimal_value(value: Any, field: str, default: str = "0") -> Decimal:
    if value is None:
        value = default
    if isinstance(value, bool):
        raise InputError(f"{field} must be numeric")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise InputError(f"{field} must be numeric") from exc
    if not number.is_finite() or number < 0:
        raise InputError(f"{field} must be finite and non-negative")
    return number


def int_value(value: Any, field: str, default: int = 0) -> int:
    number = decimal_value(value, field, str(default))
    if number != number.to_integral_value():
        raise InputError(f"{field} must be an integer")
    return int(number)


def reject_sensitive_keys(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in SENSITIVE_KEYS:
                raise InputError(f"sensitive field is not allowed: {path}.{key}")
            reject_sensitive_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_sensitive_keys(child, f"{path}[{index}]")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise InputError(f"{path}:{line_number}: invalid JSON: {exc.msg}") from exc
            if not isinstance(value, dict):
                raise InputError(f"{path}:{line_number}: each line must be an object")
            reject_sensitive_keys(value)
            records.append(value)
    if not records:
        raise InputError("input contains no records")
    return records


def load_pricing(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InputError(f"cannot read pricing file: {exc}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("models"), dict):
        raise InputError("pricing must contain an object field named models")
    if not value.get("currency") or not value.get("effective_date"):
        raise InputError("pricing requires currency and effective_date")
    decimal_value(value.get("unit_tokens", 1_000_000), "unit_tokens")
    return value


def percentile(values: list[float], percent: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def blank_usage() -> dict[str, Any]:
    return {
        "usage_records": 0,
        "calls": 0,
        "retries": 0,
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
        "calculated_cost": Decimal("0"),
        "unpriced_usage_records": 0,
        "usage_sources": defaultdict(int),
        "statuses": defaultdict(int),
    }


def add_usage(target: dict[str, Any], record: dict[str, Any], cost: Decimal | None) -> None:
    target["usage_records"] += 1
    target["calls"] += int_value(record.get("calls"), "calls", 1)
    target["retries"] += int_value(record.get("retries"), "retries")
    token_total = 0
    for field in TOKEN_FIELDS:
        amount = int_value(record.get(field), field)
        target[field] += amount
        token_total += amount
    target["total_tokens"] += token_total
    target["usage_sources"][str(record.get("usage_source", "unavailable"))] += 1
    target["statuses"][str(record.get("status", "unknown"))] += 1
    if cost is None:
        target["unpriced_usage_records"] += 1
    else:
        target["calculated_cost"] += cost


def usage_cost(record: dict[str, Any], pricing: dict[str, Any] | None) -> Decimal | None:
    if pricing is None:
        return None
    provider = str(record.get("provider", "unknown"))
    model = str(record.get("model", "unknown"))
    rates = pricing["models"].get(f"{provider}/{model}")
    token_total = sum(int_value(record.get(field), field) for field in TOKEN_FIELDS)
    calls = int_value(record.get("calls"), "calls", 1)
    other_cost = decimal_value(record.get("other_cost"), "other_cost")
    if rates is None:
        return other_cost if token_total == 0 else None
    if not isinstance(rates, dict):
        raise InputError(f"pricing for {provider}/{model} must be an object")
    unit = decimal_value(pricing.get("unit_tokens", 1_000_000), "unit_tokens")
    if unit == 0:
        raise InputError("unit_tokens must be greater than zero")
    cost = other_cost + decimal_value(rates.get("per_request"), "per_request") * calls
    for field in TOKEN_FIELDS:
        rate_key = field.removesuffix("_tokens")
        amount = decimal_value(record.get(field), field)
        if amount > 0 and rate_key not in rates:
            return None
        cost += amount / unit * decimal_value(
            rates.get(rate_key), f"{provider}/{model}.{rate_key}"
        )
    return cost


def json_number(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.000000001")))


def finalize_usage(value: dict[str, Any], pricing_present: bool) -> dict[str, Any]:
    result = dict(value)
    result["calculated_cost"] = json_number(result["calculated_cost"])
    result["all_usage_priced"] = pricing_present and result["unpriced_usage_records"] == 0
    result["total_cost"] = (
        result["calculated_cost"] if result["all_usage_priced"] else None
    )
    result["usage_sources"] = dict(sorted(result["usage_sources"].items()))
    result["statuses"] = dict(sorted(result["statuses"].items()))
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Aggregate synthetic or pseudonymous AI usage JSONL."
    )
    parser.add_argument("events", type=Path)
    parser.add_argument("--pricing", type=Path)
    parser.add_argument(
        "--group-by", nargs="+", default=["provider", "model"],
        help="Usage-record fields used for grouping."
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        invalid_group_fields = sorted(set(args.group_by) - ALLOWED_GROUP_FIELDS)
        if invalid_group_fields:
            raise InputError(
                "unsupported group fields: " + ", ".join(invalid_group_fields)
            )
        records = load_jsonl(args.events)
        pricing = load_pricing(args.pricing)
        workflows: dict[str, dict[str, Any]] = {}
        workflow_latencies: list[float] = []
        totals = blank_usage()
        groups: dict[tuple[str, ...], dict[str, Any]] = {}

        for record in records:
            record_type = record.get("record_type")
            if record_type == "workflow":
                workflow_id = str(record.get("workflow_id", "")).strip()
                status = str(record.get("status", "")).strip()
                if not workflow_id or status not in {"completed", "failed"}:
                    raise InputError(
                        "workflow records require workflow_id and status=completed|failed"
                    )
                if workflow_id in workflows:
                    raise InputError(f"duplicate workflow record: {workflow_id}")
                workflows[workflow_id] = record
                workflow_latencies.append(
                    float(decimal_value(record.get("latency_ms"), "latency_ms"))
                )
            elif record_type == "usage":
                cost = usage_cost(record, pricing)
                add_usage(totals, record, cost)
                key = tuple(str(record.get(field, "unknown")) for field in args.group_by)
                if key not in groups:
                    groups[key] = blank_usage()
                add_usage(groups[key], record, cost)
            else:
                raise InputError("record_type must be workflow or usage")

        workflow_total = len(workflows)
        completed = sum(1 for item in workflows.values() if item["status"] == "completed")
        failed = workflow_total - completed
        final_totals = finalize_usage(totals, pricing is not None)
        final_totals.update({
            "workflows_started": workflow_total,
            "workflows_completed": completed,
            "workflows_failed": failed,
            "failure_rate": failed / workflow_total if workflow_total else None,
            "workflow_latency_p50_ms": percentile(workflow_latencies, 0.50),
            "workflow_latency_p95_ms": percentile(workflow_latencies, 0.95),
        })

        group_rows = []
        for key in sorted(groups):
            row = {field: key[index] for index, field in enumerate(args.group_by)}
            row.update(finalize_usage(groups[key], pricing is not None))
            group_rows.append(row)

        output = {
            "schema_version": 1,
            "pricing": None if pricing is None else {
                "currency": pricing["currency"],
                "effective_date": pricing["effective_date"],
                "unit_tokens": int(decimal_value(
                    pricing.get("unit_tokens", 1_000_000), "unit_tokens"
                )),
            },
            "group_by": args.group_by,
            "totals": final_totals,
            "groups": group_rows,
        }
        rendered = json.dumps(output, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
        else:
            sys.stdout.write(rendered)
        return 0
    except (InputError, OSError) as exc:
        fail(str(exc))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
