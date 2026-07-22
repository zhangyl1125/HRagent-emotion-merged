"""Pure Stage 01 quality gates shared by Locust and unit tests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from threading import Lock
from typing import Any

BASELINE_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


@dataclass(frozen=True)
class FullFlowSnapshot:
    started: int
    guidance_completed: int
    report_completed: int
    completed: int
    failed: int


class FullFlowMetrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self._started = 0
            self._guidance_completed = 0
            self._report_completed = 0
            self._completed = 0
            self._failed = 0

    def increment(self, field: str) -> None:
        attribute = f"_{field}"
        if attribute not in {
            "_started",
            "_guidance_completed",
            "_report_completed",
            "_completed",
            "_failed",
        }:
            raise ValueError(f"Unknown full-flow metric: {field}")
        with self._lock:
            setattr(self, attribute, getattr(self, attribute) + 1)

    def snapshot(self) -> FullFlowSnapshot:
        with self._lock:
            return FullFlowSnapshot(
                started=self._started,
                guidance_completed=self._guidance_completed,
                report_completed=self._report_completed,
                completed=self._completed,
                failed=self._failed,
            )


FULL_FLOW_METRICS = FullFlowMetrics()


def validate_baseline_label(value: str) -> str | None:
    if not value:
        return None
    if BASELINE_LABEL_PATTERN.fullmatch(value):
        return None
    return "HRAGENT_BASELINE_LABEL must contain 1-64 ASCII letters, digits, '.', '_' or '-'"


def guidance_done_error(payload: dict[str, Any] | None) -> str | None:
    if payload is None:
        return "ended without done event"
    if payload.get("complete") is not True:
        return "done event did not contain complete=true"
    return None


def report_done_error(payload: dict[str, Any] | None) -> str | None:
    if payload is None:
        return "ended without done event"
    if payload.get("error"):
        return "done event contained an error"
    report = payload.get("report")
    if not isinstance(report, dict) or not report:
        return "done event did not contain a complete report"
    return None


def quality_gate_errors(
    *,
    num_requests: int,
    fail_ratio: float,
    avg_response_time: float,
    p95_response_time: float,
    min_requests: int,
    max_fail_ratio: float,
    max_avg_ms: float,
    max_p95_ms: float,
    flow_mode: str,
    full_flow: FullFlowSnapshot,
) -> list[str]:
    errors: list[str] = []
    if num_requests < min_requests:
        errors.append(f"requests {num_requests} < minimum {min_requests}")
    if fail_ratio > max_fail_ratio:
        errors.append(f"fail_ratio {fail_ratio:.4f} > {max_fail_ratio:.4f}")
    if avg_response_time > max_avg_ms:
        errors.append(f"avg_response_time {avg_response_time:.2f}ms > {max_avg_ms:.2f}ms")
    if p95_response_time > max_p95_ms:
        errors.append(f"p95 {p95_response_time:.2f}ms > {max_p95_ms:.2f}ms")
    if flow_mode == "full":
        if full_flow.started < 1:
            errors.append("no full flow started")
        if full_flow.failed:
            errors.append(f"full-flow failures {full_flow.failed} > 0")
        if full_flow.completed != full_flow.started:
            errors.append(
                f"full-flow completed {full_flow.completed} != started {full_flow.started}"
            )
        if full_flow.guidance_completed != full_flow.started:
            errors.append(
                "guidance completions "
                f"{full_flow.guidance_completed} != started {full_flow.started}"
            )
        if full_flow.report_completed != full_flow.started:
            errors.append(
                f"report completions {full_flow.report_completed} != started {full_flow.started}"
            )
    return errors
