from pathlib import Path

import pytest

from backend.agents.employee_agent import EmployeeAgent
from backend.business_config.loader import BusinessConfigLoader
from backend.schemas.difficulty import DifficultyConfig
from backend.schemas.emotion import EmployeeAttitude, EmotionSignal, EmotionState
from backend.schemas.persona import PersonaConfig
from backend.schemas.simulation import BigFivePersonality, MotivationState, VADVector
from backend.schemas.state import SessionState
from backend.services.emotion_transition_service import EmotionTransitionService
from backend.services.setup_service import SetupService
from backend.workflows.nodes import RehearsalNodes


def _dynamic_state() -> SessionState:
    return SessionState(
        session_id="dynamic-session",
        setup_ready=True,
        run_mode="rehearsal_report",
        persona=PersonaConfig(id="legacy-persona", name="证据追问型"),
        difficulty=DifficultyConfig(id="high", name="高压", description="持续追问事实"),
        personality=BigFivePersonality(
            openness=70,
            conscientiousness=85,
            extraversion=35,
            agreeableness=45,
            neuroticism=75,
        ),
        motivation=MotivationState(
            primary_motive_id="security",
            secondary_motive_ids=["recognition", "affiliation"],
        ),
        emotion_state=EmotionState(
            current_attitude=EmployeeAttitude.GUARDED_HESITANT,
            current_vad=VADVector(valence=-0.2, arousal=0.3, dominance=-0.1),
            current_anchor_id="anxious_defensive",
            reply_emotion_guidance="谨慎、防御，但保持职场边界。",
        ),
    )


def test_legacy_session_json_gets_dynamic_defaults_without_losing_old_fields():
    state = SessionState.model_validate(
        {
            "session_id": "legacy-session",
            "emotion_state": {
                "current_attitude": "defensive_resistant",
                "intensity": 48,
                "primary_satisfaction": 12,
            },
        }
    )

    assert state.personality is None
    assert state.motivation is None
    assert state.emotion_state.current_attitude == EmployeeAttitude.DEFENSIVE_RESISTANT
    assert state.emotion_state.intensity == 48
    assert state.emotion_state.current_vad == VADVector()
    assert state.emotion_log == []


def test_setup_options_keep_legacy_persona_and_add_dynamic_options():
    service = SetupService.__new__(SetupService)
    service.loader = BusinessConfigLoader(
        Path(__file__).resolve().parents[1] / "backend" / "business_config"
    )

    options = service.list_options()

    assert options["personas"]
    assert options["difficulties"]
    assert options["motives"]
    assert options["emotion_anchors"]
    assert set(options["default_big_five"]) == {
        "openness",
        "conscientiousness",
        "extraversion",
        "agreeableness",
        "neuroticism",
    }


def test_employee_prompt_contains_legacy_and_dynamic_simulation_context():
    prompt = EmployeeAgent._build_reply_prompt(_dynamic_state(), "请说说你最担心什么。")

    assert "证据追问型" in prompt
    assert "持续追问事实" in prompt
    assert "大五人格分数" in prompt
    assert "主诉求：security" in prompt
    assert "当前三维 VAD 情绪" in prompt
    assert "anxious_defensive" in prompt
    assert "诉求满足度和 VAD 是两套独立状态" in prompt


def test_initial_vad_uses_big_five_personality():
    service = EmotionTransitionService()
    sensitive = service.initial_state(
        None,
        BigFivePersonality(
            openness=50,
            conscientiousness=20,
            extraversion=20,
            agreeableness=20,
            neuroticism=100,
        ),
    )
    composed = service.initial_state(
        None,
        BigFivePersonality(
            openness=50,
            conscientiousness=100,
            extraversion=50,
            agreeableness=100,
            neuroticism=0,
        ),
    )

    assert sensitive.current_vad.valence < composed.current_vad.valence
    assert sensitive.current_vad.arousal > composed.current_vad.arousal
    assert sensitive.current_vad.dominance < composed.current_vad.dominance


@pytest.mark.asyncio
async def test_dynamic_rehearsal_records_audio_vad_and_motivation_trajectory():
    state = _dynamic_state()
    nodes = RehearsalNodes.__new__(RehearsalNodes)

    class FakeEmployeeAgent:
        async def reply(self, next_state: SessionState, manager_message: str) -> str:
            assert next_state.motivation.total_satisfaction == 60
            assert next_state.emotion_state.current_anchor_id == "hopeful_negotiating"
            return "如果标准和支持能写清楚，我愿意继续谈。"

    class FakeMotivationScoring:
        async def update_after_manager_message(
            self,
            next_state: SessionState,
            manager_message: str,
        ) -> SessionState:
            next_state.motivation = MotivationState(
                primary_motive_id="security",
                secondary_motive_ids=["recognition", "affiliation"],
                primary_score=60,
                secondary_scores={"recognition": 60, "affiliation": 60},
            )
            next_state.warnings.append("motivation fallback")
            return next_state

    class FakeEmotionTransition:
        async def update_after_manager_message(
            self,
            next_state: SessionState,
            manager_message: str,
            *,
            audio_emotion: str | None = None,
        ) -> SessionState:
            assert audio_emotion == "calm"
            next_state.emotion_state = next_state.emotion_state.model_copy(
                update={
                    "previous_attitude": next_state.emotion_state.current_attitude,
                    "current_attitude": EmployeeAttitude.REFLECTIVE_SOFTENING,
                    "current_vad": VADVector(valence=0.2, arousal=-0.1, dominance=0.2),
                    "current_anchor_id": "hopeful_negotiating",
                    "transition_reason": "support_and_clarity",
                }
            )
            next_state.warnings.append("emotion fallback")
            return next_state

    async def fake_analyze_emotion(**kwargs) -> EmotionSignal:
        return EmotionSignal(audio_emotion=kwargs["audio_emotion"], empathy=0.8)

    nodes.employee_agent = FakeEmployeeAgent()
    nodes.motivation_scoring = FakeMotivationScoring()
    nodes.emotion_transition = FakeEmotionTransition()
    nodes.analyze_emotion = fake_analyze_emotion

    updated = await nodes.employee_reply_node(
        state,
        "我理解你的担心，也会把标准和支持写清楚。",
        input_mode="voice",
        audio_emotion="calm",
    )

    trajectory = updated.emotion_log[-1]
    assert trajectory.input_mode == "voice"
    assert trajectory.audio_emotion == "calm"
    assert trajectory.vad_before == VADVector(valence=-0.2, arousal=0.3, dominance=-0.1)
    assert trajectory.vad_after == VADVector(valence=0.2, arousal=-0.1, dominance=0.2)
    assert trajectory.motivation_before.total_satisfaction == 50
    assert trajectory.motivation_after.total_satisfaction == 60
    assert {"motivation fallback", "emotion fallback"} <= set(updated.warnings)
