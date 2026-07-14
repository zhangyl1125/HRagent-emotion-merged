from __future__ import annotations

from pathlib import Path

import pytest

from backend.agents.employee_agent import EmployeeAgent
from backend.business_config.loader import BusinessConfigLoader
from backend.schemas.emotion import EmotionState
from backend.schemas.retrieval import RetrievedChunk
from backend.schemas.simulation import BigFivePersonality, MotivationState, VADVector
from backend.schemas.state import SessionState
from backend.services.emotion_transition_service import EmotionTransitionService


def _dynamic_state() -> SessionState:
    return SessionState(
        session_id="employee-dynamic",
        personality=BigFivePersonality(neuroticism=75),
        motivation=MotivationState(
            primary_motive_id="security",
            secondary_motive_ids=["recognition", "affiliation"],
            primary_score=-25,
            secondary_scores={"recognition": 10, "affiliation": 20},
        ),
        emotion_state=EmotionState(
            primary_motivation="commerce",
            secondary_motivation="power",
            primary_satisfaction=7,
            secondary_satisfaction=9,
            total_satisfaction=8,
            current_vad=VADVector(valence=-0.3, arousal=0.6, dominance=-0.2),
            current_anchor_id="anxious_defensive",
            reply_emotion_guidance="保持谨慎和防御。",
        ),
    )


def test_dynamic_prompt_uses_state_motivation_as_only_satisfaction_source():
    prompt = EmployeeAgent._build_reply_prompt(
        _dynamic_state(),
        "请说说你最担心什么。",
    )

    assert "主诉求：security，分数：-25.0" in prompt
    assert "当前三维 VAD 情绪" in prompt
    assert "anxious_defensive" in prompt
    assert "[当前员工核心诉求满足度]" not in prompt
    assert "主诉求：commerce" not in prompt
    assert "满足度：7.0/100" not in prompt


def test_dynamic_vad_prompt_excludes_legacy_motivation_fields():
    prompt = EmotionTransitionService()._build_prompt(
        _dynamic_state(),
        "请说说你的顾虑。",
    )

    assert '"current_vad"' in prompt
    assert "anxious_defensive" in prompt
    assert '"primary_motivation"' not in prompt
    assert '"secondary_motivation"' not in prompt
    assert '"primary_satisfaction"' not in prompt
    assert '"secondary_satisfaction"' not in prompt
    assert '"total_satisfaction"' not in prompt


def test_legacy_vad_prompt_keeps_legacy_motivation_fields():
    state = SessionState(
        session_id="employee-legacy-vad",
        emotion_state=EmotionState(
            primary_motivation="commerce",
            primary_satisfaction=7,
        ),
    )

    prompt = EmotionTransitionService()._build_prompt(state, "请继续。")

    assert '"primary_motivation": "commerce"' in prompt
    assert '"primary_satisfaction": 7.0' in prompt


def test_legacy_session_keeps_legacy_satisfaction_prompt():
    state = SessionState(
        session_id="employee-legacy",
        emotion_state=EmotionState(
            primary_motivation="commerce",
            secondary_motivation="power",
            primary_satisfaction=7,
            secondary_satisfaction=9,
            total_satisfaction=8,
        ),
    )

    prompt = EmployeeAgent._build_reply_prompt(state, "请继续。")

    assert "[当前员工核心诉求满足度]" in prompt
    assert "主诉求：commerce，满足度：7.0/100" in prompt


def test_employee_response_retrieval_config_uses_available_external_api_scopes():
    loader = BusinessConfigLoader(
        Path(__file__).resolve().parents[1] / "backend" / "business_config"
    )
    config = loader.query_config()
    employee = config["queries"]["employee_response"]

    assert employee["enabled"] is True
    assert employee["rerank_enabled"] is True
    assert employee["scopes"] == ["employee", "emotion", "performance"]


@pytest.mark.asyncio
async def test_employee_reply_retrieves_context_before_llm(monkeypatch):
    calls: list[str] = []
    captured: dict[str, object] = {}

    class FakeRetrieval:
        def retrieve(self, agent_name, context, top_k=None):
            calls.append("retrieval")
            captured["agent_name"] = agent_name
            captured["context"] = context
            captured["top_k"] = top_k
            return [
                RetrievedChunk(
                    chunk_id="employee-context",
                    source_id="emotion/demo.md",
                    title="员工沟通背景",
                    scope="emotion",
                    text="员工在高压反馈下可能先关注安全感和事实依据。",
                    score=0.9,
                )
            ]

    class FakeLLM:
        async def ainvoke_text(self, *, prompt, task_name):
            calls.append("llm")
            captured["prompt"] = prompt
            assert task_name == "employee"
            return "我想先确认一下具体依据。"

    monkeypatch.setattr(
        "backend.agents.employee_agent.LangChainLLMService",
        lambda: FakeLLM(),
    )

    result = await EmployeeAgent(retrieval=FakeRetrieval()).reply(
        _dynamic_state(),
        "请说说你的顾虑。",
    )

    assert result == "我想先确认一下具体依据。"
    assert calls == ["retrieval", "llm"]
    assert captured["agent_name"] == "employee_response"
    assert captured["top_k"] == 4
    assert captured["context"]["latest_manager_message"] == "请说说你的顾虑。"
    assert "intent" not in captured["context"]
    assert "员工在高压反馈下可能先关注安全感和事实依据。" in captured["prompt"]
    assert "不得以 HR、公司制度或政策专家口吻引用" in captured["prompt"]
