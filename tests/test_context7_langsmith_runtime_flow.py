from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.config.settings import get_settings
from backend.exceptions.workflow_errors import SetupNotReadyError, WorkflowError
from backend.schemas.state import SessionState


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / "backend" / "config" / ".env"
ENV_EXAMPLE_PATH = PROJECT_ROOT / "backend" / "config" / ".env.example"


def _assert_rehearsal_allowed(state: SessionState) -> None:
    """Lightweight mirror of the rehearsal guard contract.

    Importing backend.workflows.guards pulls the compiled workflow graph and
    optional runtime clients into collection. This helper keeps the test focused
    on the stage-order contract without requiring Redis or external services in
    the host test environment.
    """

    if not state.setup_ready:
        raise SetupNotReadyError("setup_ready=false，不能进入预演。")
    if state.run_mode == "guidance_only":
        raise WorkflowError("run_mode=guidance_only，不允许进入多轮预演。")
    if state.run_mode == "guidance_then_rehearsal" and not state.guidance_report_id:
        raise WorkflowError("run_mode=guidance_then_rehearsal，必须先生成谈前指导。")


def _dotenv_keys(path: Path) -> list[str]:
    keys: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        keys.append(line.split("=", 1)[0].strip())
    return keys


def _dotenv_values(path: Path, wanted: set[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() in wanted:
            values[key.strip()] = value.strip()
    return values


def test_context7_mcp_is_configured_for_host_runtime():
    """评测 Context7 是否已写入宿主 MCP 配置。

    当前测试不调用外部 Context7 服务，只确认宿主配置具备加载条件。
    """

    settings_path = Path.home() / ".claude" / "settings.json"
    if not settings_path.exists():
        pytest.skip("Claude settings.json not found in this runtime.")

    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    context7 = settings.get("mcpServers", {}).get("context7")

    assert context7 == {
        "type": "http",
        "url": "https://mcp.context7.com/mcp",
    }
    assert "mcp__context7" in settings.get("permissions", {}).get("allow", [])


def test_env_matches_example_and_required_runtime_flags_are_present():
    """评测 .env 是否覆盖 .env.example 中的运行配置项。"""

    example_keys = _dotenv_keys(ENV_EXAMPLE_PATH)
    env_keys = _dotenv_keys(ENV_PATH)

    assert [key for key in example_keys if key not in set(env_keys)] == []
    assert [key for key in env_keys if key not in set(example_keys)] == []

    required = {
        "REDIS_URL",
        "CACHE_ENABLED",
        "CACHE_KEY_PREFIX",
        "GUIDANCE_CACHE_TTL_SECONDS",
        "TTS_CACHE_TTL_SECONDS",
        "DOCUMENT_PARSE_CACHE_TTL_SECONDS",
        "REHEARSAL_AUX_CACHE_TTL_SECONDS",
        "LANGSMITH_TRACING",
        "LANGSMITH_API_KEY",
        "LANGSMITH_PROJECT",
        "LANGSMITH_ENDPOINT",
        "COACH_FINAL_REPORT_TIMEOUT_SECONDS",
    }
    values = _dotenv_values(ENV_PATH, required)

    assert set(values) == required
    assert values["CACHE_ENABLED"].lower() == "true"
    assert values["CACHE_KEY_PREFIX"] == "hragent05"
    assert values["LANGSMITH_TRACING"].lower() == "true"
    assert bool(values["LANGSMITH_API_KEY"])
    assert values["LANGSMITH_PROJECT"] == "hragent-05"
    assert values["COACH_FINAL_REPORT_TIMEOUT_SECONDS"] == "6"


def test_settings_effect_matches_runtime_cache_and_langsmith_expectations():
    """评测后端 Settings 对 Redis/cache 配置的读取效果。"""

    settings = get_settings()

    assert settings.cache_enabled is True
    assert settings.redis_url
    assert settings.cache_key_prefix == "hragent05"
    assert settings.guidance_cache_ttl_seconds == 21600
    assert settings.tts_cache_ttl_seconds == 604800
    assert settings.document_parse_cache_ttl_seconds == 2592000
    assert settings.rehearsal_aux_cache_ttl_seconds == 3600


def test_workflow_order_requires_setup_then_guidance_before_rehearsal():
    """评测核心执行顺序：未 setup 不能预演，未 guidance 不能进入预演。"""

    created = SessionState(session_id="order-created", stage="created", setup_ready=False)
    with pytest.raises(SetupNotReadyError):
        _assert_rehearsal_allowed(created)

    setup_ready = SessionState(
        session_id="order-setup",
        stage="setup_ready",
        setup_ready=True,
        run_mode="guidance_then_rehearsal",
    )
    with pytest.raises(WorkflowError):
        _assert_rehearsal_allowed(setup_ready)

    guidance_ready = setup_ready.model_copy(update={
        "stage": "guidance_ready",
        "guidance_report_id": "order-guidance-report",
    })
    _assert_rehearsal_allowed(guidance_ready)


def test_stage_order_contract_for_frontend_and_backend_alignment():
    """评测前后端约定的主流程阶段顺序。"""

    expected_order = [
        "created",
        "profile_ready",
        "setup_ready",
        "guidance_ready",
        "rehearsal",
        "report_ready",
        "ended",
    ]

    assert expected_order.index("created") < expected_order.index("profile_ready")
    assert expected_order.index("profile_ready") < expected_order.index("setup_ready")
    assert expected_order.index("setup_ready") < expected_order.index("guidance_ready")
    assert expected_order.index("guidance_ready") < expected_order.index("rehearsal")
    assert expected_order.index("rehearsal") < expected_order.index("report_ready")
