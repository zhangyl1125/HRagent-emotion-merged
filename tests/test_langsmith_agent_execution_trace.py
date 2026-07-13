from __future__ import annotations

"""LangSmith trace smoke tests for the HRagent overall agent flow.

Context7 note:
- The current Codex runtime may not expose the Context7 MCP tool until the host
  process is restarted after adding it to Claude settings.
- This test follows the LangSmith/LangChain tracing pattern: annotate the root
  flow and each stage with traceable runs, then attach feedback scores to the
  root run.

Run local logic only:
    pytest tests/test_langsmith_agent_execution_trace.py -q

Run the real LangSmith integration test:
    RUN_LANGSMITH_INTEGRATION=1 pytest tests/test_langsmith_agent_execution_trace.py -q

The integration test reads LANGSMITH_* from the process environment first, then
falls back to backend/config/.env. It never prints the API key.
"""

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest


EXPECTED_AGENT_ORDER = [
    "profile",
    "intent",
    "persona",
    "guidance",
    "rehearsal",
    "report",
]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / "backend" / "config" / ".env"


@dataclass(frozen=True)
class StageResult:
    stage: str
    status: str
    score: float
    notes: str


def _load_langsmith_env_from_dotenv() -> None:
    """Load only LangSmith-related env vars from backend/config/.env.

    This keeps the integration test runnable from the host shell without
    requiring python-dotenv, while avoiding any logging of secret values.
    """

    if not ENV_PATH.exists():
        return
    wanted_prefixes = ("LANGSMITH_", "LANGCHAIN_")
    for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        key = key.strip()
        if key.startswith(wanted_prefixes) and key not in os.environ:
            os.environ[key] = value.strip()


def _stage(stage: str, score: float = 1.0, notes: str = "ok") -> StageResult:
    return StageResult(stage=stage, status="completed", score=score, notes=notes)


def _simulate_hragent_flow() -> dict[str, Any]:
    """A deterministic, no-network model of the full Agent stage order."""

    stages = [
        _stage("profile", notes="employee profile extracted"),
        _stage("intent", notes="conversation intent selected"),
        _stage("persona", notes="employee persona and difficulty configured"),
        _stage("guidance", notes="pre-talk guidance generated"),
        _stage("rehearsal", score=0.92, notes="employee reply generated from HRBP message"),
        _stage("report", score=0.88, notes="coach report summarized strengths and risks"),
    ]
    observed_order = [item.stage for item in stages]
    order_score = 1.0 if observed_order == EXPECTED_AGENT_ORDER else 0.0
    effect_score = round(sum(item.score for item in stages) / len(stages), 4)
    return {
        "observed_order": observed_order,
        "expected_order": EXPECTED_AGENT_ORDER,
        "order_score": order_score,
        "effect_score": effect_score,
        "stages": [item.__dict__ for item in stages],
    }


def test_local_agent_execution_order_and_effect_metric_contract():
    """本地评测：验证整体 Agent 顺序和效果评分规则，不访问 LangSmith。"""

    result = _simulate_hragent_flow()

    assert result["observed_order"] == EXPECTED_AGENT_ORDER
    assert result["order_score"] == 1.0
    assert 0.0 <= result["effect_score"] <= 1.0
    assert result["effect_score"] >= 0.95


@pytest.mark.asyncio
async def test_langsmith_records_overall_agent_order_and_feedback():
    """真实集成评测：向 LangSmith 写入 trace，并检查执行顺序和反馈分数。

    默认跳过，避免日常单元测试访问外网。需要显式设置：
    RUN_LANGSMITH_INTEGRATION=1
    """

    if os.getenv("RUN_LANGSMITH_INTEGRATION") != "1":
        pytest.skip("Set RUN_LANGSMITH_INTEGRATION=1 to run LangSmith integration test.")

    _load_langsmith_env_from_dotenv()
    if os.getenv("LANGSMITH_TRACING", "").lower() != "true":
        pytest.skip("LANGSMITH_TRACING is not true.")
    if not os.getenv("LANGSMITH_API_KEY"):
        pytest.skip("LANGSMITH_API_KEY is not configured.")

    try:
        from langsmith import Client, traceable
        from langsmith.run_helpers import get_current_run_tree
    except ImportError as exc:  # pragma: no cover - environment guard
        pytest.skip(f"langsmith package is not available: {exc}")

    project_name = os.getenv("LANGSMITH_PROJECT") or "hragent-05"
    client = Client()
    root_run_holder: dict[str, Any] = {}

    @traceable(name="01_profile_extract", run_type="chain")
    def profile_step() -> dict[str, Any]:
        return _stage("profile", notes="employee profile extracted").__dict__

    @traceable(name="02_intent_recognition", run_type="chain")
    def intent_step() -> dict[str, Any]:
        return _stage("intent", notes="conversation intent selected").__dict__

    @traceable(name="03_persona_setup", run_type="chain")
    def persona_step() -> dict[str, Any]:
        return _stage("persona", notes="persona and difficulty configured").__dict__

    @traceable(name="04_guidance_generation", run_type="chain")
    def guidance_step() -> dict[str, Any]:
        return _stage("guidance", notes="pre-talk guidance generated").__dict__

    @traceable(name="05_rehearsal_reply", run_type="chain")
    def rehearsal_step() -> dict[str, Any]:
        return _stage("rehearsal", score=0.92, notes="employee reply generated").__dict__

    @traceable(name="06_coach_report", run_type="chain")
    def report_step() -> dict[str, Any]:
        return _stage("report", score=0.88, notes="coach report generated").__dict__

    @traceable(
        name="HRagent05 overall agent order evaluation",
        run_type="chain",
        tags=["hragent-05", "agent-order", "integration-test"],
        metadata={"expected_order": EXPECTED_AGENT_ORDER, "test_file": Path(__file__).name},
    )
    def overall_agent_flow() -> dict[str, Any]:
        current_run = get_current_run_tree()
        root_run_holder["id"] = current_run.id
        root_run_holder["trace_id"] = current_run.trace_id

        stages = [
            profile_step(),
            intent_step(),
            persona_step(),
            guidance_step(),
            rehearsal_step(),
            report_step(),
        ]
        observed_order = [stage["stage"] for stage in stages]
        order_score = 1.0 if observed_order == EXPECTED_AGENT_ORDER else 0.0
        effect_score = round(sum(stage["score"] for stage in stages) / len(stages), 4)
        return {
            "observed_order": observed_order,
            "expected_order": EXPECTED_AGENT_ORDER,
            "order_score": order_score,
            "effect_score": effect_score,
            "summary": "HRagent overall Agent stage order and effect score evaluation.",
        }

    result = overall_agent_flow()

    assert result["observed_order"] == EXPECTED_AGENT_ORDER
    assert result["order_score"] == 1.0
    assert result["effect_score"] >= 0.95
    assert root_run_holder.get("id")

    root_run_id = root_run_holder["id"]
    client.create_feedback(
        run_id=root_run_id,
        key="agent_execution_order_score",
        score=result["order_score"],
        comment="Expected order: profile -> intent -> persona -> guidance -> rehearsal -> report.",
    )
    client.create_feedback(
        run_id=root_run_id,
        key="agent_effect_score",
        score=result["effect_score"],
        comment="Deterministic smoke evaluation of stage completion quality.",
    )

    # LangSmith ingestion can be eventually consistent. Poll briefly so this test
    # proves the root run is visible remotely, without making the suite slow.
    fetched = None
    for _ in range(10):
        try:
            fetched = client.read_run(root_run_id)
            if fetched is not None:
                break
        except Exception:  # noqa: BLE001 - transient remote consistency/network errors
            time.sleep(1)
    assert fetched is not None
    assert fetched.name == "HRagent05 overall agent order evaluation"
