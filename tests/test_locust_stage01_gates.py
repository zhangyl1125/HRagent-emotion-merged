from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative_path: str):
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


gates = load_module(
    "hragent_stage01_quality_gates",
    "locust-loadtest/tests/load/stage01_quality_gates.py",
)
baseline = load_module(
    "hragent_token_baseline",
    "locust-loadtest/tests/load/generate_token_baseline.py",
)


def snapshot(**overrides):
    values = {
        "started": 1,
        "guidance_completed": 1,
        "report_completed": 1,
        "completed": 1,
        "failed": 0,
    }
    values.update(overrides)
    return gates.FullFlowSnapshot(**values)


def gate_errors(**overrides):
    values = {
        "num_requests": 25,
        "fail_ratio": 0.0,
        "avg_response_time": 100.0,
        "p95_response_time": 200.0,
        "min_requests": 1,
        "max_fail_ratio": 0.01,
        "max_avg_ms": 800.0,
        "max_p95_ms": 2000.0,
        "flow_mode": "full",
        "full_flow": snapshot(),
    }
    values.update(overrides)
    return gates.quality_gate_errors(**values)


def test_zero_requests_and_minimum_request_gate_fail():
    assert "requests 0 < minimum 1" in gate_errors(
        num_requests=0,
        flow_mode="basic",
        full_flow=snapshot(started=0, guidance_completed=0, report_completed=0, completed=0),
    )
    assert "requests 4 < minimum 5" in gate_errors(
        num_requests=4,
        min_requests=5,
        flow_mode="basic",
    )


@pytest.mark.parametrize(
    ("flow", "expected"),
    [
        (snapshot(started=0, guidance_completed=0, report_completed=0, completed=0), "no full flow started"),
        (snapshot(failed=1), "full-flow failures 1 > 0"),
        (snapshot(completed=0), "full-flow completed 0 != started 1"),
        (snapshot(guidance_completed=0), "guidance completions 0 != started 1"),
        (snapshot(report_completed=0), "report completions 0 != started 1"),
    ],
)
def test_incomplete_full_flow_gate_fails(flow, expected):
    assert expected in gate_errors(full_flow=flow)


def test_complete_full_flow_gate_passes():
    assert gate_errors() == []


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (None, "ended without done event"),
        ({}, "done event did not contain complete=true"),
        ({"complete": False}, "done event did not contain complete=true"),
        ({"complete": True}, None),
    ],
)
def test_guidance_done_validation(payload, expected):
    assert gates.guidance_done_error(payload) == expected


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (None, "ended without done event"),
        ({"error": "failed"}, "done event contained an error"),
        ({}, "done event did not contain a complete report"),
        ({"report": {}}, "done event did not contain a complete report"),
        ({"report": {"summary": "synthetic"}}, None),
    ],
)
def test_report_done_validation(payload, expected):
    assert gates.report_done_error(payload) == expected


def test_invalid_label_is_rejected():
    assert gates.validate_baseline_label("stage01-baseline") is None
    assert gates.validate_baseline_label("contains space") is not None


def test_shared_full_flow_metrics_is_available():
    gates.FULL_FLOW_METRICS.reset()
    assert gates.FULL_FLOW_METRICS.snapshot() == gates.FullFlowSnapshot(0, 0, 0, 0, 0)


def test_full_flow_metrics_reset_and_increment():
    metrics = gates.FullFlowMetrics()
    metrics.increment("started")
    metrics.increment("guidance_completed")
    assert metrics.snapshot() == gates.FullFlowSnapshot(1, 1, 0, 0, 0)
    metrics.reset()
    assert metrics.snapshot() == gates.FullFlowSnapshot(0, 0, 0, 0, 0)


def test_baseline_evidence_is_aggregate_and_preserves_unavailable_usage():
    started = datetime(2026, 7, 21, 1, 0, tzinfo=timezone.utc)
    ended = datetime(2026, 7, 21, 2, 0, tzinfo=timezone.utc)
    evidence = baseline.build_evidence(
        label="stage01-baseline",
        started_at=started,
        ended_at=ended,
        flow_count=1,
        rows=[
            {
                "task_name": "guidance",
                "provider": "external",
                "model": "synthetic-model",
                "usage_source": "provider",
                "status": "success",
                "calls": 1,
                "input_tokens": 100,
                "output_tokens": 20,
                "input_unavailable_calls": 0,
                "output_unavailable_calls": 0,
                "retries": 0,
                "average_duration_ms": 10,
            },
            {
                "task_name": "employee",
                "provider": "external",
                "model": "synthetic-model",
                "usage_source": "unavailable",
                "status": "error",
                "calls": 1,
                "input_tokens": None,
                "output_tokens": None,
                "input_unavailable_calls": 1,
                "output_unavailable_calls": 1,
                "retries": 0,
                "average_duration_ms": None,
            },
        ],
    )
    assert evidence["known_totals"] == {
        "input_tokens": 100,
        "output_tokens": 20,
        "calls": 2,
    }
    assert evidence["unavailable_usage"] == {
        "input_token_calls": 1,
        "output_token_calls": 1,
    }
    serialized = str(evidence).lower()
    assert "email" not in serialized
    assert "business_session_id" not in serialized
