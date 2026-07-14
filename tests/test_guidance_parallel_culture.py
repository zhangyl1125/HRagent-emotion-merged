import asyncio
import threading

import pytest

import backend.agents.guidance_agent as guidance_agent_module
from backend.agents.guidance_agent import GUIDANCE_SECTION_KEYS, GuidanceAgent
from backend.business_config.loader import BusinessConfigLoader
from backend.schemas.intent import IntentConfig, IntentResult
from backend.schemas.profile import EmployeeProfile
from backend.schemas.retrieval import RetrievedChunk
from backend.schemas.state import SessionState
from backend.services.guidance_service import GuidanceService
from backend.services.langchain_llm_service import LangChainLLMService


class ActiveCultureLoader:
    def company_values(self):
        return {
            "version": "culture-v1",
            "enabled": True,
            "values": [
                {
                    "id": "respect",
                    "name": "尊重与信任",
                    "definition": "先倾听，再基于事实回应。",
                    "desired_behaviors": [],
                    "anti_patterns": [],
                    "manager_applications": [],
                    "source_refs": ["culture/values.md"],
                }
            ],
        }

    def company_values_enabled(self):
        return True

    def company_value_terms(self):
        return "尊重与信任"

    def culture_version(self):
        return "culture-v1"


def _state() -> SessionState:
    return SessionState(
        session_id="guidance-parallel",
        setup_ready=True,
        employee_profile=EmployeeProfile(
            employee_alias="员工A",
            source_profile_text="补充资料中的历史反馈。",
        ),
        intent=IntentResult(
            intent_id="improvement",
            config=IntentConfig(
                id="improvement",
                name="改进型反馈",
                business_goal="对齐事实与行动。",
                expected_outcome="形成下一步行动。",
            ),
        ),
    )


def _chunk(chunk_id: str, scope: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        source_id=f"{scope}/{chunk_id}.md",
        title=chunk_id,
        scope=scope,
        text=f"{scope} guidance",
        score=0.8,
    )


@pytest.mark.asyncio
async def test_guidance_agent_generates_all_five_sections_concurrently(monkeypatch):
    agent = GuidanceAgent()
    started: list[str] = []
    all_started = asyncio.Event()

    async def fake_generate_section(state, chunks, key):
        started.append(key)
        if len(started) == len(GUIDANCE_SECTION_KEYS):
            all_started.set()
        await asyncio.wait_for(all_started.wait(), timeout=1)
        return f"{key}-content"

    monkeypatch.setattr(agent, "generate_section", fake_generate_section)

    sections = await agent.generate_sections(_state(), [])

    assert set(started) == set(GUIDANCE_SECTION_KEYS)
    assert list(sections) == list(GUIDANCE_SECTION_KEYS)


@pytest.mark.asyncio
async def test_guidance_stream_section_uses_streaming_llm(monkeypatch):
    calls = []

    async def fake_astream_text(self, **kwargs):
        calls.append(kwargs)
        yield "第一段"
        yield "继续生成"

    monkeypatch.setattr(LangChainLLMService, "astream_text", fake_astream_text)

    deltas = [
        delta
        async for delta in GuidanceAgent().stream_section(_state(), [], "purpose")
    ]

    assert deltas == ["第一段", "继续生成"]
    assert calls and calls[0]["task_name"] == "guidance"


def test_guidance_retrieves_general_and_culture_context_in_parallel():
    calls: list[tuple[str, dict]] = []
    barrier = threading.Barrier(2)

    class Retrieval:
        def retrieve(self, name, context, top_k=None):
            calls.append((name, context))
            barrier.wait(timeout=2)
            return [_chunk(name, "culture" if name == "guidance_culture" else "general")]

    service = object.__new__(GuidanceService)
    service.config_loader = ActiveCultureLoader()
    service.retrieval = Retrieval()

    _, chunks = service._prepare_state(_state())

    assert {name for name, _ in calls} == {"guidance", "guidance_culture"}
    assert {chunk.scope for chunk in chunks} == {"general", "culture"}
    assert all(context["supplemental_info"] == "补充资料中的历史反馈。" for _, context in calls)
    assert all(context["company_value_terms"] == "尊重与信任" for _, context in calls)


def test_guidance_prompt_merges_values_and_culture_without_legacy_setup(monkeypatch):
    monkeypatch.setattr(
        guidance_agent_module,
        "get_config_loader",
        lambda: ActiveCultureLoader(),
    )

    prompt = GuidanceAgent._build_section_prompt(
        _state(),
        [_chunk("general-1", "general"), _chunk("culture-1", "culture")],
        "response_strategies",
    )

    assert "补充资料中的历史反馈" in prompt
    assert "尊重与信任" in prompt
    assert "culture/culture-1.md" in prompt
    assert "不是评分标准" in prompt
    assert '"persona":' not in prompt
    assert '"difficulty":' not in prompt


def test_guidance_plain_text_cleanup_removes_markdown_markers():
    text = GuidanceAgent.clean_section_text(
        "### 沟通目标\n\n- **先对齐事实**，再确认下一步。\n\n`不要承诺`"
    )

    assert text == "沟通目标\n\n先对齐事实，再确认下一步。\n\n不要承诺"


def test_company_values_loader_normalizes_and_is_safe_when_disabled(tmp_path):
    (tmp_path / "company_values.yaml").write_text(
        """
version: culture-v1
enabled: false
values:
  - id: respect
    name: 尊重与信任
    definition: 先倾听，再基于事实回应。
    desired_behaviors:
      - " 先倾听 "
""".strip(),
        encoding="utf-8",
    )
    loader = BusinessConfigLoader(config_dir=tmp_path)

    values = loader.company_values()
    values["values"][0]["name"] = "调用方修改"

    assert loader.company_values_enabled() is False
    assert loader.company_value_terms() == ""
    assert loader.culture_version() is None
    assert loader.company_values()["values"][0]["name"] == "尊重与信任"
    assert loader.company_values()["values"][0]["desired_behaviors"] == ["先倾听"]
