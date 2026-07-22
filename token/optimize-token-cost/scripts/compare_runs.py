#!/usr/bin/env python3
"""Compare two aggregate_usage.py summaries and enforce explicit gates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


class InputError(ValueError):
    pass


def load_summary(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InputError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise InputError(f"{path} is not a supported aggregate summary")
    if not isinstance(value.get("totals"), dict):
        raise InputError(f"{path} does not contain totals")
    return value


def number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InputError(f"{field} must be numeric")
    return float(value)


def reduction(before: float, after: float) -> float | None:
    if before <= 0:
        return None
    return (before - after) / before * 100.0


def append_gate(
    gates: list[dict[str, Any]], name: str, passed: bool, actual: Any, expected: str
) -> None:
    gates.append({
        "name": name,
        "passed": passed,
        "actual": actual,
        "expected": expected,
    })


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare baseline and candidate Token-cost summaries."
    )
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--min-baseline-workflows", type=int, default=1)
    parser.add_argument("--min-candidate-workflows", type=int, default=1)
    parser.add_argument("--min-token-reduction-pct", type=float)
    parser.add_argument("--min-cost-reduction-pct", type=float)
    parser.add_argument("--max-failure-rate-pct", type=float, default=100.0)
    parser.add_argument("--max-p95-regression-pct", type=float)
    parser.add_argument("--max-retry-rate-pct", type=float)
    parser.add_argument("--require-all-priced", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        thresholds = {
            "min_baseline_workflows": args.min_baseline_workflows,
            "min_candidate_workflows": args.min_candidate_workflows,
            "max_failure_rate_pct": args.max_failure_rate_pct,
            "min_token_reduction_pct": args.min_token_reduction_pct,
            "min_cost_reduction_pct": args.min_cost_reduction_pct,
            "max_p95_regression_pct": args.max_p95_regression_pct,
            "max_retry_rate_pct": args.max_retry_rate_pct,
        }
        for name, value in thresholds.items():
            if value is not None and value < 0:
                raise InputError(f"{name} must be non-negative")
        baseline = load_summary(args.baseline)
        candidate = load_summary(args.candidate)
        before = baseline["totals"]
        after = candidate["totals"]
        gates: list[dict[str, Any]] = []

        before_completed = number(
            before.get("workflows_completed"), "baseline.workflows_completed"
        )
        after_completed = number(
            after.get("workflows_completed"), "candidate.workflows_completed"
        )
        append_gate(
            gates, "baseline_nonzero",
            before_completed >= args.min_baseline_workflows,
            before_completed, f">= {args.min_baseline_workflows}"
        )
        append_gate(
            gates, "candidate_nonzero",
            after_completed >= args.min_candidate_workflows,
            after_completed, f">= {args.min_candidate_workflows}"
        )

        failure_rate_pct = number(
            after.get("failure_rate") or 0, "candidate.failure_rate"
        ) * 100
        append_gate(
            gates, "candidate_failure_rate",
            failure_rate_pct <= args.max_failure_rate_pct,
            failure_rate_pct, f"<= {args.max_failure_rate_pct}%"
        )

        token_reduction = reduction(
            number(before.get("total_tokens"), "baseline.total_tokens"),
            number(after.get("total_tokens"), "candidate.total_tokens"),
        )
        if args.min_token_reduction_pct is not None:
            append_gate(
                gates, "token_reduction",
                token_reduction is not None
                and token_reduction >= args.min_token_reduction_pct,
                token_reduction, f">= {args.min_token_reduction_pct}%"
            )

        before_cost = before.get("total_cost")
        after_cost = after.get("total_cost")
        cost_reduction = None
        if before_cost is not None and after_cost is not None:
            cost_reduction = reduction(
                number(before_cost, "baseline.total_cost"),
                number(after_cost, "candidate.total_cost"),
            )
        if args.min_cost_reduction_pct is not None:
            same_pricing = baseline.get("pricing") == candidate.get("pricing")
            append_gate(
                gates, "pricing_version_match", same_pricing,
                {"baseline": baseline.get("pricing"), "candidate": candidate.get("pricing")},
                "identical pricing metadata"
            )
            append_gate(
                gates, "cost_reduction",
                same_pricing and cost_reduction is not None
                and cost_reduction >= args.min_cost_reduction_pct,
                cost_reduction, f">= {args.min_cost_reduction_pct}%"
            )

        if args.require_all_priced:
            append_gate(
                gates, "baseline_all_priced",
                bool(before.get("all_usage_priced")),
                before.get("all_usage_priced"), "true"
            )
            append_gate(
                gates, "candidate_all_priced",
                bool(after.get("all_usage_priced")),
                after.get("all_usage_priced"), "true"
            )

        p95_before = before.get("workflow_latency_p95_ms")
        p95_after = after.get("workflow_latency_p95_ms")
        p95_regression = None
        if p95_before is not None and p95_after is not None:
            p95_regression = -reduction(
                number(p95_before, "baseline.workflow_latency_p95_ms"),
                number(p95_after, "candidate.workflow_latency_p95_ms"),
            )
        if args.max_p95_regression_pct is not None:
            append_gate(
                gates, "p95_regression",
                p95_regression is not None
                and p95_regression <= args.max_p95_regression_pct,
                p95_regression, f"<= {args.max_p95_regression_pct}%"
            )

        calls = number(after.get("calls"), "candidate.calls")
        retries = number(after.get("retries"), "candidate.retries")
        retry_rate_pct = retries / calls * 100 if calls > 0 else (0.0 if retries == 0 else None)
        if args.max_retry_rate_pct is not None:
            append_gate(
                gates, "retry_rate",
                retry_rate_pct is not None
                and retry_rate_pct <= args.max_retry_rate_pct,
                retry_rate_pct, f"<= {args.max_retry_rate_pct}%"
            )

        passed = all(gate["passed"] for gate in gates)
        output = {
            "schema_version": 1,
            "passed": passed,
            "metrics": {
                "token_reduction_pct": token_reduction,
                "cost_reduction_pct": cost_reduction,
                "p95_regression_pct": p95_regression,
                "candidate_failure_rate_pct": failure_rate_pct,
                "candidate_retry_rate_pct": retry_rate_pct,
            },
            "gates": gates,
        }
        rendered = json.dumps(output, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
        else:
            sys.stdout.write(rendered)
        return 0 if passed else 2
    except (InputError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
