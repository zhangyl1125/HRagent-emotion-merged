from backend.agents.guidance_agent import GuidanceAgent
from backend.schemas.emotion import ConversationEmotionLog, EmotionState, EmployeeAttitude
from backend.schemas.intent import IntentConfig, IntentResult
from backend.schemas.simulation import BigFivePersonality, MotivationState, VADVector
from backend.schemas.state import SessionState


def _dynamic_state() -> SessionState:
    motivation = MotivationState(
        primary_motive_id="security",
        secondary_motive_ids=["recognition", "affiliation"],
        primary_score=38,
        secondary_scores={"recognition": 45, "affiliation": 52},
    )
    return SessionState(
        session_id="dynamic-guidance",
        setup_ready=True,
        personality=BigFivePersonality(
            openness=42,
            conscientiousness=72,
            extraversion=48,
            agreeableness=58,
            neuroticism=69,
        ),
        motivation=motivation,
        emotion_state=EmotionState(
            current_vad=VADVector(valence=-0.42, arousal=0.56, dominance=-0.31),
        ),
        emotion_log=[
            ConversationEmotionLog(
                turn_index=1,
                hrbp_text="我们先对齐事实。",
                employee_attitude_before=EmployeeAttitude.GUARDED_HESITANT,
                employee_attitude_after=EmployeeAttitude.DEFENSIVE_RESISTANT,
                intensity=66,
                transition_reason="压力上升",
                vad_before=VADVector(valence=-0.12, arousal=0.21, dominance=-0.05),
                vad_after=VADVector(valence=-0.42, arousal=0.56, dominance=-0.31),
                motivation_before=motivation,
                motivation_after=motivation.model_copy(update={"primary_score": 38}),
            )
        ],
        intent=IntentResult(
            intent_id="improvement",
            config=IntentConfig(
                id="improvement",
                name="改进型反馈",
                business_goal="对齐绩效差距并形成改进行动。",
                expected_outcome="员工理解事实与下一步行动。",
            ),
        ),
    )


def test_guidance_prompt_includes_dynamic_personality_motivation_and_vad_log():
    prompt = GuidanceAgent._build_prompt(_dynamic_state(), [])

    assert '"primary_motive_id": "security"' in prompt
    assert '"current_vad"' in prompt
    assert '"vad_before"' in prompt
    assert '"vad_after"' in prompt
    assert '"updated_at"' not in prompt
    assert "不得作为事实定性或心理诊断" in prompt


def test_guidance_fallback_uses_motive_and_vad_without_personality_diagnosis():
    report = GuidanceAgent._fallback_report(_dynamic_state(), [])

    assert any("稳定与确定性" in item for item in report.risk_preview)
    assert any("Big Five" in item for item in report.risk_preview)
    assert any("VAD" in item for item in report.risk_preview)
    assert any("稳定与确定性" in item for item in report.safer_phrases)
    assert any("不把人格参数当作绩效事实" in item for item in report.response_strategies)
